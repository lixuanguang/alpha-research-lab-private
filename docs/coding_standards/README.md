# Engineering guide

This is the repository's single engineering guide. It applies to Python source,
tests, scripts, configuration-owned snippets, and the native stubs under
`tools/typing/stubs`. It governs new code and code materially changed by a
patch; it does not require unrelated legacy code to be rewritten in that patch.
The OOP target also covers existing owned Python implementation, with remaining
work recorded under [Python scope and migration](#python-scope-and-migration).
Repository configuration and the owning target contract take precedence when
they are more specific.

Follow the [development workflow](../governance/workflow.md) for changes and the
[architecture guide](../architecture/README.md) for dependency direction.

The current implemented source targets standard GIL-enabled CPython 3.14.7, with
native dependency stubs under `tools/typing/stubs`. No C, C++, or Rust implementation target is present
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
function-registration mechanism. The checker does not yet enforce the
orchestrator-only function rule or assess class cohesion; those are review
requirements pending the [OOP migration](../roadmap/future-mr10-to-mr21.md#python-ownership-and-enforcement).
A passing check does not establish OOP compliance. Line-scoped tool suppressions
are separate and must carry the owner, rationale, and expiry metadata described
below.

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

Follow the [functional ownership and entrypoint rules](../architecture/platform-design.md#functional-apis-and-application-entrypoints).
The current source map lives in architecture; each future roadmap capability
names its intended owner. Import and command enforcement applies to the current
functional layout.

Give each module one cohesive responsibility and each consumer the smallest
useful interface. Names must reveal domain purpose; use one term for one
concept, include units where the type does not carry them, and avoid filler
names such as `data`, `manager`, `helper`, and `utils`. Predicates should read
as facts or questions, operations should use verbs, and collection names should
be plural.

Each method or orchestrator function must have a clear contract and one level
of abstraction. Keep transformations and calculations pure where practical,
isolate I/O and other side effects behind explicit boundaries, and extract a
block only when it has its own name, invariant, reuse, or test value. Do not split cohesive logic to
meet a line count, introduce Boolean mode flags whose meaning is unclear, or
create forwarding layers that only repeat arguments or error translation.

Owned Python implementation MUST use cohesive classes for reusable behavior.
Domain objects own their invariants and related operations; service and adapter
objects own explicit capabilities. A class may own one meaningful operation or
represent a validated value or schema. Method count alone does not justify
merging or splitting classes. Share implementation when responsibilities and
contracts coincide, while preserving distinct domain types and error semantics.
Prefer composition and shallow inheritance; public inheritance requires
substitutable behavior.

Private parsing, arithmetic, validation, predicate and callback helpers MUST be
methods of their cohesive owner. Use instance methods for object state or bound
dependencies, class methods for construction tied to the concrete class, and
static methods for class-owned operations that need neither. Stateless methods
may remain pure; do not introduce mutable state solely to use a class. Moving
unrelated functions into a static-method collection does not establish meaningful
ownership. Supply callbacks as methods or callable objects, preserving their
required signatures and behavior.

Constructors establish valid objects. Put fallible I/O and complex parsing in a
named factory method or boundary service. Bind stable collaborators in a typed
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

### Stable names and test-support layout

Maintained directories, modules, files, classes, functions, and test names MUST
use stable domain, capability, or behavior names. Newly authored runtime and
test scenario labels MUST follow the same rule. These names MUST NOT be based on
MR identifiers, review-package labels, or milestone IDs. Organize static fixture
data, subprocess support, and integration scenarios by purpose and domain; see
the [tests guide](../../tests/README.md) for the test-tree contract. This naming
rule is a review requirement; no automated enforcement is currently provided.

Roadmaps and acceptance records MAY refer to MR, review-package, and milestone
IDs when those identifiers are the subject of the record. Preserve historical
provenance and content-addressed evidence, including its original names and
references; do not rewrite it to satisfy the current naming rule.

### Orchestrator pipelines and libraries

Bare module-level functions, including asynchronous functions, MUST be workflow
orchestrators. All other implementation modules MUST expose reusable behavior
through cohesive domain, service or adapter classes and their methods, alongside
value types and protocols. They MUST NOT introduce forwarding wrappers.
A function that merely constructs a library object and forwards its arguments
to a method is a wrapper, even when it is described as a convenience API or
compatibility helper. A subclass whose only purpose is choosing existing
constructor arguments or wiring other library objects is also a composition
wrapper; it needs its own substantive contract to belong in a library.

Orchestrator pipelines own workflow composition: selecting run configuration,
constructing and reusing collaborators, sequencing operations, coordinating I/O,
handling workflow failures, and routing results. An orchestrator function MUST
serve that coordination responsibility; its name or placement in a pipeline
module alone is insufficient. It MUST NOT duplicate domain logic or add another
name for an otherwise identical call.

Library modules own parsing, validation, transformations, calculations, codecs,
and explicit adapter contracts. They MUST receive required inputs and
collaborators explicitly and MUST NOT depend on orchestrator pipelines or
choose a pipeline's run configuration. Library methods may call other objects'
methods to implement their own cohesive contract; such collaboration does not
make them workflow orchestrators. Classes bind reusable configuration where
needed and enforce their invariants. Bounded I/O operations such as verified file
reading or atomic publication may be library methods. Curated package exports
may expose the actual library types and orchestrator functions without adding
forwarding callables.

For example, a dataset pipeline creates a `BinancePayloadDecoder(instruments)`,
passes it to `TardisDecoder(payload_decoder=..., source_id=...)`, and reuses
`decode_line` for each input. The two classes own venue parsing and provider
framing respectively; their construction belongs to the pipeline. The data
library MUST NOT add a `decode_tardis_line` forwarding function or a subclass
whose only purpose is that wiring. Apply this boundary when adding or materially
changing implementation code, including development tooling. Implementation
plans MUST identify the concrete consumer and responsibility of each new
abstraction, and explicitly retain, change or retire relevant existing
abstractions before adding consumers that depend on them. The
[functional source map](../architecture/platform-design.md#current-and-planned-repository-shape)
applies this rule to the next implementation slices.

### Python scope and migration

The OOP target covers maintained runtime source, reusable development tooling,
scripts, tests and implementation snippets. Organize tests and fixtures as
methods on cohesive test classes while retaining framework discovery, fixture
scope and isolation. Reusable test doubles and callbacks follow the same
ownership rule. Internal helper behavior belongs in methods; nesting a function
or lambda is not a substitute for giving that behavior a class owner. Script and
command entry functions are permitted when they actually orchestrate a workflow.

Native-library stubs describe upstream interfaces, including upstream free
functions; they MUST retain those signatures. Calls into those libraries belong
behind owned adapter classes. Historical fixtures and recorded examples retain
their original meaning and are not evidence of current OOP compliance.

Existing non-orchestrator functions remain migration work, not a permanent
exception or evidence that migration is complete. New and materially changed
implementation MUST follow this rule. Migrate each affected API with its callers,
exports, tests and documentation; retain current API descriptions until the code
changes. The [roadmap](../roadmap/future-mr10-to-mr21.md#python-ownership-and-enforcement) owns the remaining
implementation and enforcement work. This policy update changes no runtime API
or checker behavior by itself.

### Generalized code and configuration-driven activation

Implementation code MUST express reusable behavior across the assets and
strategies its contracts support. Names, signatures and purpose MUST describe
economic or technical roles: use `instrument`, `quote_currency` and
`target_quantity`, rather than `btc_pair`, `usdt_balance` or a pair-specific
calculation name. Shared code MUST NOT hardcode the selected research pair,
strategy, source binding or run parameters in defaults, branches or paths.
Strategy modules own their particular formulas; provider and venue adapters own
their actual protocol and market mechanics. Those meaningful specializations
remain explicit. Generalization does not require speculative abstractions or
claim support for unimplemented products, data sources or operating modes.

Versioned configuration files MUST distinguish available definitions from active
selections scoped to a workflow. Separate instrument/universe definitions, data
jobs, strategy definitions, strategy instances and deployment/authorization
configuration. These relationships may be many-to-many: a strategy can use several
sources/instruments, several strategies can share a dataset, and a collection job
can cover a wider universe than its current research consumers. A single global
mutable `active_asset` or `active_pipeline` MUST NOT control unrelated jobs.
Add monitoring, execution and other bindings with their implemented consumers. Listing an asset
in a reference catalog or installing a strategy MUST NOT activate it. Use one
appropriate serialization format at a boundary; this rule does not require
parallel JSON, YAML and TOML loaders.

Orchestrator pipelines MUST load and resolve that configuration, select the
active jobs or instances and construct the collaborators required by the requested
workflow. Configuration libraries may parse, validate and resolve records; they
MUST NOT run pipelines. Other libraries receive explicit validated inputs and
MUST NOT discover active assets or strategies through global configuration or
environment reads. Configuration selects implemented behavior and supplies
parameters; strategy formulas remain in strategy code.

Validate schema versions, references, units, parameter invariants and capability
compatibility before starting the workflow. Unknown or unsupported selections
MUST fail explicitly. Retain an immutable resolved run manifest containing the
actual universe, non-secret parameters, policies and referenced implementation,
schema, reference and data versions. A mutable config name is insufficient.
Collection, research selection and trading authorization MUST remain distinct;
research configuration cannot grant executable account access. Isolate
mutable state and results by strategy instance; a shared implementation or input
does not imply shared cash, positions or pending decisions.

For an asset already covered by implemented capabilities, onboarding SHOULD
require only configuration/reference data and focused validation. A new strategy
SHOULD require its strategy implementation, configuration and relevant tests,
without edits to shared orchestration or asset-specific branches in libraries.
Extend the owning library, pipeline or monitoring boundary only when a required
capability is missing. Implementation plans MUST place configuration selection
with its first working consumer and include a bounded onboarding example that
proves the shared path is reusable; do not defer general names and explicit inputs
until a later platform rewrite.

Exploratory research notebooks MAY tailor names, calculations and scenarios to
specific strategies or assets. When promoting behavior into the maintained
package, remove incidental case assumptions, expose explicit inputs and move
activation and parameters into configuration. Formal notebook results then call
the promoted implementation. The
[planned configuration design](../architecture/platform-design.md#configuration-and-active-workflows)
and [research workflow](../roadmap/research-program.md#notebook-research-and-package-promotion)
apply these boundaries.

### Capability milestones and extension evidence

Implementation plans MUST organize MRs around runnable capability milestones
with supported configurations, dependencies, an executable acceptance workflow
and documented limitations. MR counts describe review boundaries, not completion.
Basic data correctness, reproducibility, applicable telemetry and recovery MUST
ship with the behavior they protect; advanced analysis may follow later.
Historical EDA and deterministic backtesting MUST NOT depend on an unused live
feed, trained-model platform or particular storage product.

Historical, replay and live paths MUST use compatible canonical contracts while
preserving their distinct source/receipt/availability semantics. Promote the same
versioned decision and feature logic between research and runtime. Evidence must
distinguish deterministic fixture parity from supported source, market mechanics
and operational use. The support boundary is per product, capability and mode;
a new configuration entry alone cannot establish lifecycle or execution support.

Exercise multi-instrument selection and independent strategy-instance state at
their first consumers. Use a bounded different-family fixture at the relevant
neutral interface to expose unit or lifecycle assumptions, with explicit rejection
where behavior is unsupported. Before multiple strategies share an executable
or paper account, implement independent instance/account risk, reservation and
aggregation/allocation rules, attributable orders/fills/costs and restart isolation.
Strategy logic cannot own hard limits or kill authority. The
[milestone plan](../roadmap/README.md) maps these obligations to MRs.

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
and project groups must occur in that order. `applications`, `configuration`,
`financial_units`, `market_data`, `reference_data`, `research`, `runtime`,
`serialization`, `telemetry` and `alpha_research_governance` are project imports.
Runtime cross-owner imports use the owner's explicit `__init__.py` API. The
engineering checker rejects retired `alpha_research` imports, forbidden dependency
directions, private implementation access and extra command entrypoints. Apply the same headings,
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

Strict Pydantic boundary models remain permitted for cold administrative
configuration and are retained by the C01, C02 and C03 foundation APIs. They do
not authorize a validation framework in economic or trading-domain code without
a boundary-specific need. Latency-sensitive market-data and event records, plus
quote, order-intent and execution records, MUST use frozen `msgspec.Struct`
values with cached strict typed codecs for serialization and deserialization.
This candidate uses the serialization boundary for exact financial values and
bounded canonical Binance event records. Later quote, order-intent, execution,
configuration and report records will use the same boundary when their planned
consumers are introduced; this does not require a blanket foundation rewrite.

`msgspec` annotations are not checked by direct constructors. Its records MUST
therefore retain explicit constructor and custom invariant checks so invalid,
malformed, non-finite, wrong-unit or unsafely modified values fail. Records stay
immutable, and serialized numeric values use exact Decimal strings,
scale-documented integer units, or canonical integer numerator/denominator pairs
for exact rational values under the [financial contract](../architecture/financial-units.md#planned-research-and-accounting-arithmetic);
binary floats MUST NOT replace exact arithmetic.
Preserve the established strict immutable contracts for instrument identity,
venue calendars and financial units, including their distinct validation and
copy behavior. Prove any measured allocation or serialization choice with
focused negative and round-trip tests.

Validate untrusted data once at each trust boundary, then rely on documented
invariants internally. Validate again when callers can supply unsafe copied or
constructed instances. On trusted event paths, reuse the cached codecs and
avoid redundant per-event validation, dictionary creation or JSON round-trips.
Do not replace `Decimal` or `Fraction` arithmetic with binary floats for
line-count or speed reasons.

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
for currency or identifiers. Exact ratios and proportional attribution use
`Fraction` where division is not closed over the declared decimal grid; retain
dimensions and explicit serialization. Exact financial reconciliation uses no
tolerance. Approximate analytical comparisons use a tolerance justified by
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
and end-to-end behavior when those costs matter. For latency-sensitive codecs,
measure serialization, deserialization, allocation and end-to-end replay with
the cached implementation. External vendor benchmarks are not local latency
evidence, and performance measurements do not establish live readiness.
Sequential path-dependent simulation must remain sequential. Parallel execution,
caching, custom allocators and latency-specific tuning require correctness
evidence, a bounded failure policy and measured need.

## Documentation

Every module, class, method and orchestrator function must have a meaningful
Google-style summary. Existing functions pending migration remain subject to
the same documentation checks. A private helper method or test may use a useful
one-line summary because it exposes no public structured contract. Public
functions and methods MUST include whichever of `Args:`, `Returns:`, `Yields:`,
and `Raises:` sections a meaningful contract or review requires; they MAY omit
sections when the summary is sufficient. The sections are not required solely
because a signature has parameters, a return annotation, a yield, or a raise.
The checker treats a function as public unless its name or containing owner
begins with `_`, except that `__init__` remains public; test functions named
`test_*` under `tests/` are summary-only.

When one of those Google sections is present, it must be nonempty. A present
`Args:` section must use declared parameter names (excluding implicit `self`
and `cls`) and describe each declared parameter; an optional section does not
replace review of the underlying contract. Review must determine whether prose
explains intent, units, time semantics, mutability, side effects, propagated
failures, and non-obvious rationale.
Overload signatures inherit the concrete implementation's documentation; write
the structured contract once on that implementation. Use imperative summary
lines and top-level Google headings. Implementations of inherited protocol
contracts may refer to the unchanged owning contract rather than reproduce its
structured sections, while retaining any local units, time, error, or side-effect
semantics. Comments explain why, invariants, units, external constraints, or numerical reasoning;
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

The unit-test tree mirrors the `src` ownership boundary: component tests use
their owning package directory, shared data tests live under `tests/unit/data/`,
provider-specific data tests live under the matching
`tests/unit/data/providers/<provider>/` directory, and venue-specific tests live
under the matching
`tests/unit/data/venues/<venue>/` directory. Documentation and active commands
use these current paths; preserved historical evidence may retain the path used
by its original run.

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
