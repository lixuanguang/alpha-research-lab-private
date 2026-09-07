# Engineering guide

This is the repository's single engineering guide. It applies to Python source,
tests, scripts, configuration-owned snippets, and the native stubs under
`tools/typing/stubs`. It governs new code and code materially changed by a
patch; it does not require unrelated legacy code to be rewritten. Repository
configuration and the owning target contract take precedence when they are more
specific.

Follow the [development workflow](../governance/workflow.md) for changes and the
[architecture guide](../architecture/README.md) for dependency direction.

The current implemented source is Python 3.12, with native dependency stubs
under `tools/typing/stubs`. No C, C++, or Rust implementation target is present
today; the native-boundary paragraph records the reusable contract for bindings.

Use **MUST** and **MUST NOT** for requirements, **SHOULD** and **SHOULD NOT** for
the normal choice that needs a concrete reason to change, and **MAY** for an
intentional local choice. Resolve conflicts in this order: safety, security,
legal and data-integrity requirements; the accepted change specification and
public contracts; nearest repository instructions; this guide; then local
style.

## Commands and enforcement

Run commands from the repository root in the pinned uv environment. The current
entry points are:

| Command | Current purpose |
| --- | --- |
| `make format-check` / `make format` | Check or apply Ruff formatting to `src`, `tests`, governance tooling, and owned stubs |
| `make lint` | Ruff lint and import checks over the same Python scope |
| `make typecheck` | Strict mypy over the same scope, followed by native `stubtest` |
| `make engineering-standards-check` | Local import, explicit-`Any`, docstring, suppression, and tool-configuration checks |
| `make security` | Bandit over runtime and governance source |
| `make check` | Complete source checks and installed-wheel smoke validation |

For local iteration, use `uv run --frozen ruff check <paths>`,
`uv run --frozen ruff format --check <paths>`,
`uv run --frozen mypy --strict <paths>`, and
`uv run --frozen --no-editable pytest -q <test-paths>`. The last command is a
focused test invocation; the default pytest configuration excludes
`integration` and `performance` cases, which must be selected explicitly when
affected. A successful command that ran no relevant tests is not validation.
Report skips and deselections separately from passes.

`ruff` owns formatting and linting, strict `mypy` owns inferred typing, and the
engineering checker covers project rules that those tools do not fully express.
Run the complete configured static scope when changing global enforcement.
Focused checks do not replace the complete `make check` lane required before
merge. Use the repository workflow for implementation and acceptance; automated
success does not replace domain review or grant release or activation authority.

The checker scans every `.py` and `.pyi` file recursively under exactly:
`src`, `tests`, `tools/governance/src`, and `tools/typing/stubs`, including files
that Git does not track. A missing root, unreadable source, malformed
configuration, or finding fails closed. It has no source-rule waiver or
function-registration mechanism: functions do not need owner, expiry, or
fingerprint records. Line-scoped tool suppressions are separate and must carry
the owner, rationale, and expiry metadata described below.

The configured tools currently require:

- strict mypy with `disallow_any_explicit`, `disallow_any_unimported`,
  `disallow_any_decorated`, and `disallow_any_expr`;
- the Pydantic mypy plugin with `init_typed`, `init_forbid_extra`, and
  `warn_required_dynamic_aliases`;
- Ruff rules including import sorting (`I`), Google documentation (`D`), and
  dynamic typing (`ANN401`), with the Google pydocstyle convention; and
- pytest warnings treated as errors.

Do not add global excludes, per-file ignores, module overrides, or other
configuration that narrows this scope. A line-scoped tool suppression must end
with this exact metadata, in this order:

```text
[owner=<identifier>; rationale=<concrete reason>; expires=YYYY-MM-DD]
```

The owner is a lowercase source annotation, the rationale must be at least 12
characters after trimming, and expiry may be no more than 180 days after
validation. Missing, malformed, expired, or overlong metadata fails the
checker. Use the smallest possible suppression and fix the underlying issue
when practical.

## Design and interfaces

Give each module one cohesive responsibility and each consumer the smallest
useful interface. Names must reveal domain purpose; use one term for one
concept, include units where the type does not carry them, and avoid filler
names such as `data`, `manager`, `helper`, and `utils`. Predicates should read
as facts or questions, operations should use verbs, and collection names should
be plural.

Each function must have a clear contract and one level of abstraction. Keep
transformations and calculations pure where practical, isolate I/O and other
side effects behind explicit boundaries, and extract a block only when it has
its own name, invariant, reuse, or test value. Do not split cohesive logic to
meet a line count, introduce Boolean mode flags whose meaning is unclear, or
create forwarding layers that only repeat arguments or error translation.

Use a cohesive class when it represents a meaningful concept, groups related
behavior, owns state, or establishes an invariant. A stateless validator can
justify a class when its operations form one coherent responsibility. Use a
module-level function when it expresses a stateless, low-level, parser,
arithmetic, predicate, callback, or test operation clearly. Functions need no
registration, owner, expiry, or source-fingerprint record, and there is no
class-to-function ratio or blanket class requirement. Prefer composition and
shallow inheritance; public inheritance requires substitutable behavior.

Constructors establish valid objects. Put fallible I/O and complex parsing in a
named factory or boundary service. Bind stable collaborators in a typed
constructor and keep findings and intermediate results local to each invocation.
A reusable service must not retain a prior invocation's findings after success
or failure unless an explicit cache lifetime and invalidation contract exists.
Properties should be inexpensive and unsurprising. Do not use miscellaneous
`Manager`, `Helper`, or `Utils` classes.

Public interface changes account for callers, supported imports, signatures,
CLI behavior, errors, serialized results, documentation, migration, and
rollback. A build target owns dependency, visibility, platform, generated
inputs, testing, and artifact boundaries; directory proximity does not make an
API public. Declare direct dependencies in the owning metadata and lock, and do
not rely on a mutable environment, path mutation, transitive imports, or an
editable install at runtime.

## Python source rules

Use the pinned interpreter and let `ruff format` decide whitespace and wrapping.
Use four-space indentation, UTF-8 source, and direct imports. Import-time work
must be bounded and free of network access, bulk loading, process creation,
external registration, and other operational side effects. Wildcard imports
are prohibited. Absolute imports are the default; a relative import is allowed
inside a cohesive private subpackage when it improves stability.

Every nonempty import category must use its exact heading and a blank line
between groups:

```python
# standard library imports
# third party library imports
# project library imports
```

`__future__` imports form their own group immediately after the module
docstring, with a blank line before and after it. Standard-library, third-party,
and project groups must occur in that order. `alpha_research` and
`alpha_research_governance` are project imports. Apply the same headings,
ordering, and separation to relative imports, imports inside `TYPE_CHECKING`,
and nested import blocks. Do not add a heading for an empty category.

Use `lower_snake_case` for packages, modules, functions, methods, variables,
and parameters; `UpperCamelCase` for classes, protocols, and exceptions;
`UPPER_SNAKE_CASE` for module constants; and a leading underscore for private
implementation details. Boolean names should begin with `is`, `has`, `can`, or
`should`. Exceptions end in `Error` unless they intentionally mirror a
built-in. Avoid shadowing built-ins and name dimensional values with units such
as `timeout_ms` or `notional_usd`.

All functions and methods, including private helpers and tests, must have typed
parameters and explicit return types, including `-> None`. Type class
attributes and module variables. Use precise domain records, enums, `Literal`,
`NewType`, and protocols where they express the contract; use `Protocol` for a
behavioral structural boundary and an abstract base class only when nominal
runtime behavior is required.

Owned Python source must not use explicit `Any`. The rule covers imports from
`typing` and `typing_extensions`, aliases and qualified references, annotations
and generic bounds, assignments, type comments, quoted annotations, container
members, and nested scopes. Ordinary text, docstrings, and values inside
`Literal` remain ordinary values. Receive untyped boundary data as `object`,
validate and narrow it immediately, and construct a precise owned type. Do not
use `cast` to make an unsafe value appear valid; use a validator or `TypeGuard`
when reusable narrowing is needed.

Use immutable or frozen value objects for identifiers, specifications, money,
timestamps, and configuration where their contract permits. Use
`default_factory` for mutable model defaults and never use a mutable default
argument. Distinguish absent, empty, zero, and unknown. Keep generated schema
types and native binding stubs at the boundary by translating them into domain
types.

## Classes, records, errors, and resources

Strict Pydantic boundary models are the default for new validation-rich
configuration and serialized records. They do not authorize a validation
framework in economic or trading-domain code without a boundary-specific need.
Preserve the established strict immutable contracts for instrument identity,
venue calendars, and financial units, including their distinct validation and
copy behavior. If a different record implementation is considered for measured
allocation or serialization costs, retain constructor checks, custom
invariants, exceptions, serialization, and mutability behavior, and prove the
choice with focused negative and round-trip tests.

Validate untrusted data once at each trust boundary, then rely on documented
invariants internally. Validate again when callers can supply unsafe copied or
constructed instances. Do not replace `Decimal` or `Fraction` arithmetic with
binary floats for line-count or speed reasons.

Raise the most specific built-in or domain exception. Messages identify the
operation and safe context without secrets. Translate at a boundary with
`raise DomainError(...) from error`; catch only failures the block can handle.
Broad `except Exception` is limited to a process or task boundary that records
the failure and produces a defined outcome. Do not ignore exceptions or use
them as routine branching. Context managers own files, locks, transactions,
temporary resources, and suppression scope, and cleanup must be safe after
partial initialization and repeated failure.

Use concurrency only for an inherent or measured need. Every task has an owner
that awaits, cancels, or deliberately supervises it. Propagate cancellation,
avoid shared mutable state where possible, do not hold synchronous locks across
`await`, and put timeouts at external boundaries using monotonic time for
elapsed duration.

## Security and diagnostics

Never commit or log secrets, private keys, credentials or sensitive dataset
samples. Treat paths, URLs, serialized objects, queries and process arguments
as untrusted input. Use parameterized queries and structured process arguments;
do not interpolate unchecked input into commands. Use established cryptographic
libraries, least privilege, and the smallest practical sensitive-data lifetime.
Dependency changes need a justified purpose, compatible license, exact lock and
the retained source/integrity checks.

Destructive or externally visible actions need explicit scope and duplicate
protection where applicable, with meaningful failure tests. Retry only transient
failures with bounded attempts, backoff and idempotent behavior. Diagnostics should
identify safe source, artifact, configuration and domain context without repeating
the same failure at every layer. Assertions express internal invariants; external
data still needs runtime validation. See the
[operations runbook](../governance/operations.md) for access and incident handling.

## Boundaries, time, and numerical behavior

State units, currency, timezone, precision, missing-value behavior, and boundary
inclusivity in every domain or data boundary. Use timezone-aware timestamps and
normalize platform event time to UTC. Preserve source event, receipt,
ingestion, knowledge, and reference-valid times, sequence or revision, clock
quality, and convention metadata when they affect decisions. Point-in-time
decisions must enforce `ts_knowledge <= decision_time`.

Use `Decimal` constructed from strings or integer minor units for exact monetary
arithmetic, according to the domain contract. Do not use binary floating point
for currency or identifiers. Numerical comparisons use a tolerance justified by
the scale and algorithm. Handle empty input, zero denominators,
overflow/underflow, non-finite values, shape and dtype mismatches, duplicate
keys, missing data, and unstable ordering deliberately.

For arrays and dataframes, document shape, index, columns, dtype, units, and
missing-value expectations. Do not mutate caller-owned arrays or frames unless
the contract says so. Randomized code accepts an explicit generator or seed;
tests use fixed seeds. Historical and simulated code uses only information
available at decision time, and future-perturbation tests should detect leakage.
Preserve deterministic ordering wherever it affects hashes, decisions, results,
or serialized output.

Optimize only after a correct reference exists and representative workloads are
measured. An optimized array or numerical implementation must preserve the
reference contract; benchmark cold start, warm execution, conversion, memory,
and end-to-end behavior when those costs matter. Sequential path-dependent
simulation must remain sequential. Parallel execution, caching, custom
allocators, and latency-specific tuning require correctness evidence, a bounded
failure policy, and measured need.

## Documentation

Every module, class, and named function, including private helpers and ordinary
test functions, must have a meaningful Google-style summary. A private helper
or test may use a useful one-line summary because it exposes no public
structured contract. A public function or method must document every parameter
(excluding implicit `self` and `cls`) with `Args:` entries, and must include an
applicable nonempty `Returns:`, `Yields:`, or `Raises:` section. The checker
treats a function as public unless its name or containing owner begins with
`_`, except that `__init__` remains public; test functions named `test_*` under
`tests/` are summary-only.

The checker requires `Returns:` when a function returns a value or has a
non-`None` return annotation, `Yields:` when it yields, and `Raises:` when its
body raises. It checks the sections and parameter names syntactically; review
must still determine whether prose explains intent, units, time semantics,
mutability, side effects, propagated failures, and non-obvious rationale.
Use imperative summary lines and top-level Google headings. Implementations of
inherited protocol contracts follow these same source requirements. Comments
explain why, invariants, units, external constraints, or numerical reasoning;
they do not narrate syntax. Non-obvious algorithms should cite a stable source
or issue and document deviations.

## Native binding boundaries

Native bindings, if introduced, are adapters around an owned implementation and
must keep one authoritative contract. Keep the boundary narrow and
C-compatible. Native collection layouts, language exceptions, panics,
references, trait objects, templates, and allocators must not cross an
undocumented ABI. Define ownership, allocator, lifetime, alignment, size,
encoding, versioning, nullability, thread, reentrancy, cancellation, and error
behavior for every handle, buffer, callback, and returned diagnostic. Translate
native failures to stable Python or ABI error categories without unwinding
across the boundary. Bindings should batch work and measure conversion,
copying, interpreter-lock, and call overhead.

Hot paths must not perform unbounded allocation, blocking I/O, DNS, process
creation, synchronous logging, or unbounded telemetry. A latency claim requires
a representative controlled benchmark with hardware, compiler, artifact, and
background-load identity. Performance evidence never replaces conformance,
recovery, or risk-control tests.

## Behavioral tests

Tests verify observable behavior and contracts at the lowest practical level.
Every defect fix includes a regression test that fails without the fix. New or
changed behavior covers success, meaningful boundaries, malformed or invalid
inputs, and expected failures. Tests are deterministic, isolated, independent
of execution order, and explicit about exception types, error details, units,
time semantics, and numerical tolerances.

Use fakes or injected clocks, seeds, files, and protocols at stable boundaries;
avoid real networks, credentials, user directories, global random state, and
wall clocks in unit tests. Use integration tests for component boundaries and a
small number of end-to-end tests for critical paths. Property or fuzz tests are
appropriate for parsers, serializers, state machines, broad numeric domains,
and untrusted binary inputs.

Refactors retain behavior for repeated calls, failure recovery, malformed data,
deterministic results, serialization options, exact contractual errors, and
existing numerical goldens. Type fixes must still reach the runtime rejection
path under malformed input. Cross-language implementations and bindings use
shared schemas, fixtures, goldens, and differential or conformance tests within
declared tolerances. Do not replace behavioral tests with class-existence tests,
private implementation assertions, or a large end-to-end suite.

Before handoff, review the diff for scope, secrets, dead code, generated files,
and accidental artifacts. Report the checks run, the tests actually executed,
skips or deselections, unavailable checks, and material remaining gates.
