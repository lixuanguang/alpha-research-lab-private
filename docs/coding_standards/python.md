# Python Coding Standards

## Scope and baseline

This guide applies to Python source, tests, scripts, and configuration-owned Python
snippets. Use the interpreter and language level pinned by the owning build target
and root toolchain configuration. Do not infer a version from the developer's
machine or float to the latest interpreter in an unrelated change.

Code MUST follow:

- [PEP 8](https://peps.python.org/pep-0008/) for source style and naming.
- [PEP 257](https://peps.python.org/pep-0257/) for docstrings.
- [PEP 20](https://peps.python.org/pep-0020/) for clarity and explicitness.
- The shared [coding standards](README.md).

Repository configuration and automated tooling take precedence when they make a
style choice more specific. Do not hand-format code against `ruff format`.

## Required tooling

Run commands from the repository root using the pinned environment.
[Makefile](../../Makefile), [pyproject.toml](../../pyproject.toml), and the owning
Bazel targets define the executable scope; `mypy --strict` alone does not express
the repository's additional dynamic-type restrictions.

| Command | Scope and purpose |
| --- | --- |
| `make lint`, `make format-check` | Configured Ruff checks across source, tests, governance tooling and owned native stubs |
| `make typecheck` | Complete configured strict mypy scope, followed by native stubtest |
| `make engineering-standards-check` | Source rules, exact design exceptions and static-tool configuration |
| `make security` | Configured Bandit checks for runtime and governance source |
| `make check` | Authoritative complete lane with the default Bazel backend; see the [development workflow](../governance/workflow.md) |

For local iteration, use `uv run --frozen ruff check <affected-paths>`,
`uv run --frozen ruff format --check <affected-paths>` and
`uv run --frozen mypy --strict <affected-paths>` with actual repository paths.
Run focused tests with `uv run --frozen --no-editable pytest -q <test-paths>` and
their owning targets with `bazel test --config=ci <target-labels>`. Resolve targets
and relevant reverse dependencies from the checked-in build graph.

The default pytest configuration excludes `integration` and `performance` cases.
When affected, select them explicitly with `-m integration` or `-m performance`
and the relevant test paths. Verify that pytest and Bazel actually execute the
expected cases; an entry point that exits successfully without running tests is
not validation. Report skips and deselections separately from passes.

Before completion, run every applicable repository check affected by the change.
Changes to global lint or typing enforcement require the complete configured
static scope. Run `uv run --frozen pre-commit run --all-files` when hook behavior
or multiple file types are involved. Focused checks and hooks do not replace the
complete lane required before merge.

Do not silence a tool globally to fix a local violation. A suppression MUST be as
narrow as possible and use the exact B04 suffix
`[owner=<governed_role>; rationale=<specific_reason>; expires=YYYY-MM-DD]`; expiry
may be no more than 180 days after validation. Pytest warnings are errors.

## Formatting and source layout

- Use four spaces per indentation level and no tabs.
- Let `ruff format` decide line wrapping and whitespace.
- Store source as UTF-8. Use non-ASCII text only when it improves the domain text,
  data, or user-facing output.
- Put one import per line except imports from the same module as formatted by the
  tool.
- Imports MUST appear at module scope unless a local import is required to break a
  proven cycle, avoid an optional dependency, or defer a measured cost.
- Modules MUST NOT rely on an unrelated package having imported a transitive
  submodule first. Import every direct dependency explicitly.
- Import-time work MUST be bounded and free of operational side effects: do not
  perform network access, bulk data loading, process creation, registration with
  external systems, or other operational actions merely by importing a module.
- Every nonempty import category MUST use its exact heading comment:
  `# standard library imports`, `# third party library imports`, or
  `# project library imports`. Separate every nonempty group with a blank line.
  Keep `__future__` imports immediately after the module docstring in their own
  group, before the headed groups. Treat `alpha_research` and
  `alpha_research_governance` as first-party project imports. Apply the same
  headings, ordering, and blank-line rules to relative imports and to imports
  guarded by `TYPE_CHECKING`; do not add headings for empty categories.
- Use absolute imports across packages. Relative imports MAY be used within a
  cohesive private subpackage when they improve stability.
- Never use wildcard imports.
- Modules SHOULD expose a focused public surface. Do not use `__all__` to disguise
  an unfocused module.

## Packages and environments

- A Python package is owned and depended on through its build target; being
  importable from the monorepo does not make it a supported public API.
- Declare direct Python and native dependencies in build metadata and the owning
  lock or resolution input. Do not depend on packages present incidentally in a
  mutable shared environment.
- Deployable Python environments MUST be reproducible and immutable. Their
  identity includes the interpreter, dependency lock, native libraries, schemas,
  and owning source/build targets.
- Production targets MUST NOT import notebooks, experiment entrypoints, or
  research-only convenience packages. Move promoted logic into an owned library.
- Avoid a repository-wide package that automatically imports every internal
  module. Explicit imports and narrow package surfaces reduce startup cost,
  dependency ambiguity, and accidental coupling.
- Build and test modules as normal packages. Do not make path mutation,
  `PYTHONPATH`, the working directory, or editable installs an undeclared runtime
  requirement.

## Naming

| Construct | Convention | Example |
| --- | --- | --- |
| Package or module | `lower_snake_case` | `portfolio_risk` |
| Function or method | `lower_snake_case` | `calculate_exposure` |
| Local variable or parameter | `lower_snake_case` | `decision_time` |
| Class, protocol, or exception | `UpperCamelCase` | `MarketDataError` |
| Module constant | `UPPER_SNAKE_CASE` | `MAX_RETRY_ATTEMPTS` |
| Type variable | short `UpperCamelCase` | `T`, `ValueT` |
| Private implementation detail | one leading underscore | `_parse_record` |
| Boolean | fact/question with `is`, `has`, `can`, or `should` | `is_stale` |

Additional rules:

- Exceptions MUST end in `Error` unless they intentionally mirror a built-in.
- Async functions SHOULD use the same verb-based naming as synchronous functions;
  do not add an `_async` suffix unless both variants must coexist and ambiguity
  remains at call sites.
- Do not use double-leading-underscore names to simulate privacy. Reserve name
  mangling for preventing subclass collisions in a deliberately subclassable API.
- Avoid shadowing built-ins such as `id`, `type`, `list`, `filter`, and `input`.
- Name dimensional values with units when the type cannot express them, such as
  `latency_ms` or `notional_usd`.

## Types and data modeling

- All functions and methods, including private helpers and tests, MUST have typed
  parameters and explicit return types under the configured strict mypy checks.
  Class attributes and module-level variables MUST be typed.
- Annotate return types explicitly, including `-> None`.
- Use syntax supported by the pinned minimum interpreter. Prefer built-in generics
  such as `list[str]`, union syntax such as `X | None`, and protocols from `typing`
  when that minimum version supports them; do not silently raise the runtime floor.
- Prefer precise domain types, enums, `Literal`, `NewType`, or validated
  structured records over unstructured dictionaries and tuples. Choose a record
  framework using the [model-selection rules](#classes-and-object-design).
- Use `Protocol` for behavioral structural contracts. Use abstract base classes
  only when shared runtime behavior or nominal registration is required.
- Owned source and tests MUST NOT use explicit `Any`, including aliases,
  qualified references, container members, type aliases, or quoted annotations.
  This is a source-level rule and applies to `src`, `tests`, and governance
  tooling. Parse untyped boundary data as `object`, validate and narrow it
  immediately, and construct a precise owned type.
- Keep strict `mypy` across `src`, `tests`, governance tooling and the owned
  native stubs under `tools/typing/stubs`. The pinned Pydantic plugin requires
  `init_typed`, `init_forbid_extra` and `warn_required_dynamic_aliases`.
  `disallow_any_explicit`, `disallow_any_unimported`, `disallow_any_decorated`
  and `disallow_any_expr` apply throughout the complete scope, including tests.
  Preserve custom constructor entry points and runtime negative tests.
- Resolve inferred dynamic types at their library, parsing, callback or framework
  boundary. Bind a precise consumed contract, receive untrusted results as
  `object`, then validate before using them. There is no migration inventory
  that permits remaining diagnostics, and tests must not be excluded to make
  the checks pass.
- `make typecheck` and pre-commit run the same checks, including native stubtest.
  Follow the [boundary typing contract](../../tools/typing/README.md) when
  changing a stub, native dependency, parser or serialized model contract.
- Do not use `cast` to make an unsafe value appear valid. A cast requires an
  invariant the type checker cannot express and that the code actually establishes.
- Use `TypeGuard` or explicit validation for reusable narrowing logic.
- Prefer immutable/frozen value objects for identifiers, specifications, money,
  timestamps, and configuration.
- Use `default_factory` for mutable model defaults. Never share a mutable
  default argument.
- Distinguish absent, empty, zero, and unknown values. Do not make a parameter
  optional merely for caller convenience when absence is invalid.
- Generated schema types and binding stubs are boundary representations. Translate
  them into domain types rather than allowing generated or native-library details
  to spread through research and portfolio logic.

## Functions and control flow

- Keep transformations and calculations pure where possible, whether expressed
  as methods or justified low-level functions.
- Do not mutate an input unless mutation is the explicit contract and is evident
  from the name or type.
- Never use a mutable object as a default parameter.
- Prefer early validation and guard clauses to deeply nested branches.
- Use comprehensions only when they remain readable and side-effect free. Use a
  loop when transformation, filtering, and error handling combine.
- Do not use assignment expressions when they make the condition harder to read.
- Replace long `if`/`elif` type dispatch with polymorphism, a registry, or
  `match` only when variants form a real stable set.
- Use keyword-only parameters for options whose order is not meaningful or whose
  values are easy to confuse.
- Avoid Boolean mode flags; use an enum or separate named operation.
- A generator SHOULD be used for streaming or potentially large sequences. Make
  single-use behavior clear in the return type and documentation.

## Classes and object design

- Prefer a cohesive class for high-level domain, policy, validation, loading,
  and orchestration operations, with typed collaborators and explicit state
  ownership. Use a class when state and behavior share invariants.
- A low-level parser, arithmetic kernel, predicate, required framework or CLI
  callback, or supported compatibility wrapper MAY remain a module-level
  function only with an explicit low-level, framework, or compatibility
  rationale recorded for the function in the
  [design exception register](../architecture/python-standards-exceptions.toml).
  Follow the [exception contract](../architecture/engineering-standards.md#python-standards-enforcement-contract)
  for exact rule, symbol, owner, expiry and fingerprint fields. Reassess the
  rationale when a definition changes, update only its affected records, and
  remove records whose findings no longer exist. Do not bulk-renew fingerprints
  or expiry dates merely to pass a check. Do not enforce this preference with a
  class-to-function ratio or a blanket class requirement.
- New internal callers SHOULD use the owning service. Retain public adapters
  needed by supported imports and CLI contracts, document that boundary, and
  remove temporary wrappers once their remaining callers have migrated.
- Favor composition over inheritance and keep inheritance trees shallow.
- Constructors establish valid objects. Fallible I/O or complex parsing belongs
  in a named factory or boundary service.
- Bind stable repository, policy, path and collaborator dependencies in the
  owning service's typed constructor. Keep findings and intermediate results local
  to each invocation. Reusing a service after success or failure MUST NOT retain
  prior findings or partial results; any intentional cache needs an explicit
  lifetime and invalidation contract.
- Do not create `Manager`, `Helper`, or `Utils` classes as miscellaneous containers.
- Properties MUST be inexpensive and unsurprising. I/O, blocking work, and
  material computation belong in methods.
- Use strict Pydantic `BaseModel` records by default for new or migrated
  structured data, especially validation-rich configuration and governance
  boundaries. Do not introduce standard-library dataclasses or
  `pydantic.dataclasses`; frozen records are preferred.
- Evaluate [`msgspec.Struct`](https://msgspec.dev/structs) when allocation or
  serialization costs affect a workload. Prefer it over Pydantic when it supports
  the required features and representative end-to-end benchmarks improve with
  the same schema, exceptions, serialization, and mutability contract.
- Use msgspec only for its supported schemas and features. A `msgspec.Struct`
  constructor and attribute assignment do not validate field types, so direct
  construction and mutation are trusted, prevalidated operations. Retain
  Pydantic when callers require constructor-time checks.
- At an untrusted boundary, use [`msgspec.json.decode`](https://msgspec.dev/api#msgspec.json.decode)
  with `type=..., strict=True` or [`msgspec.convert`](https://msgspec.dev/api#msgspec.convert)
  with raw built-in data, `type=..., strict=True`; these APIs define the typed
  conversion boundary. Set `forbid_unknown_fields=True` for closed schemas and
  `frozen=True` for value records. Validate defaults, custom invariants, and
  cross-field constraints there, preserving the existing exceptions,
  serialization, and mutability behavior.
- Do not assume msgspec `strict` has the same meaning as Pydantic strict mode or
  that converting an existing `Struct` revalidates it. Add focused negative and
  round-trip tests for the selected boundary. Do not require validation
  scaffolding on every function when the owning boundary establishes the contract.
- Keep workflow services as ordinary classes with explicit typed constructors
  and collaborators. Performing I/O does not make a service a data model.
- Pydantic or equivalent validation belongs at configuration/serialization
  boundaries; domain code SHOULD not depend on a validation framework without a
  boundary-specific need.
- The current bootstrap governance, configuration, registry, and serialization
  records use strict immutable Pydantic boundary models under
  [ADR 0008](../architecture/decisions/0008-pydantic-boundary-models.md). This does
  not authorize validation-framework dependencies in economic or trading-domain
  models. The C01 instrument-identity exception is narrowly authorized by
  [ADR 0010](../architecture/decisions/0010-pydantic-instrument-identity-models.md),
  and the C02 venue/calendar boundary uses the same strict immutable pattern under
  [ADR 0011](../architecture/decisions/0011-versioned-venue-calendar-adapter.md).
  C03 financial units use the same framework with validated replacement under
  [ADR 0013](../architecture/decisions/0013-explicit-financial-units-and-conventions.md).

## Errors and resource management

- Raise the most specific built-in or domain exception available.
- Exception messages MUST describe the failed operation and safe context. Do not
  include credentials, full sensitive payloads, or secret-bearing URLs.
- Preserve causes when translating errors: `raise DomainError(...) from error`.
- Catch only exceptions the block can handle. A broad `except Exception` is
  allowed only at a process/task boundary that records the failure and produces a
  defined outcome. Bare `except` is prohibited outside deliberate interpreter
  shutdown handling.
- Do not use exceptions for routine branching when the outcome is naturally a
  value or an explicit optional result.
- Never ignore an exception with `pass`. If best-effort behavior is required,
  document it and emit appropriate evidence or telemetry.
- Use context managers for files, locks, transactions, temporary resources, and
  suppressions. Keep their scope narrow.
- Cleanup MUST be safe under partial initialization and repeated failure.

## Concurrency and asynchronous code

- Use concurrency only for a measured or inherent I/O/parallelism need.
- Do not call blocking I/O directly from an event loop. Use an async implementation
  or an explicitly managed executor.
- Every spawned task MUST have an owner that awaits it, cancels it, or deliberately
  supervises its lifetime.
- Propagate cancellation; do not translate it into an ordinary retryable failure.
- Protect shared mutable state or, preferably, avoid it through message passing or
  immutability.
- Do not hold a synchronous lock across `await`.
- Timeouts belong at external boundaries and SHOULD use monotonic time for elapsed
  duration.

## Data, time, and numerical code

- Use timezone-aware timestamps and normalize platform event time to UTC. Preserve
  the distinction among source event time, platform receipt time, ingestion time,
  knowledge time, and reference-data valid time, along with source sequence or
  revision, clock quality, and timezone/convention metadata. Historical decisions
  MUST enforce `ts_knowledge <= decision_time`.
- Use `Decimal` or integer minor units for exact monetary arithmetic according to
  the domain contract; construct decimals from strings, not binary floats.
- Declare array/dataframe shape, index, column, dtype, units, and missing-value
  expectations at module boundaries.
- Prefer vectorization only when it preserves readability and semantics. Measure
  before replacing clear code with a complex vectorized expression.
- Do not mutate caller-owned dataframes or arrays unless explicitly documented.
- Handle `NaN`, infinity, empty windows, duplicate keys, and unstable sorting
  deliberately.
- Randomized code MUST accept an explicit generator/seed and tests MUST use fixed
  deterministic seeds.
- Point-in-time research code MUST never fit, normalize, select, or impute using
  future observations. Add future-perturbation tests for time-dependent features.

## Numerical acceleration

- Treat Numba as a complementary JIT layer for the pinned CPython runtime. Choose
  a suitable numeric kernel after measuring it. A proven `@njit` implementation
  is a first option before a C++ or Rust extension; unsupported algorithms,
  proven tail-latency requirements, or ABI requirements can justify native code
  immediately. Ordinary Python remains responsible for I/O, models, validation,
  and orchestration. See the [Numba five-minute guide](https://numba.readthedocs.io/en/stable/user/5minguide.html).
- NumPy, Polars, and Arrow vectorized operations already execute native code.
  Compare a Numba kernel with a clear Python reference and the appropriate
  vectorized operation. A benchmark MUST include cold start, each dtype
  specialization, warm execution, end-to-end conversion, and memory behavior;
  report measured speedups for representative workloads. See the [Numba
  performance guidance](https://numba.readthedocs.io/en/stable/user/performance-tips.html).
- Use `@njit` in nopython mode and keep object mode out of governed kernels.
  Extract primitive arrays and scalars from Pydantic or msgspec models in the
  Python wrapper, then state dtype, shape, layout, units, and scalar types at the
  kernel boundary. Small module-level kernels are allowed under the existing
  low-level function rationale when they have no hidden I/O or mutable globals.
- Prefer sequential loops for path-dependent simulations. Do not parallelize
  time dependence. Use parallel execution only for independent workloads, with
  explicit thread, random-number, and reduction controls; bound thread pools to
  avoid oversubscription. Numba `prange` requires independent iterations apart
  from supported reductions. See the
  [Numba parallel guide](https://numba.readthedocs.io/en/stable/user/parallel.html).
- Compare kernel outputs with a clear reference using identical inputs and random
  seeds, preserving time ordering and documenting numerical tolerances. Exercise
  independent parallel workloads under the same comparison contract.
- Check array lengths and index preconditions before entering a kernel. Test
  boundary behavior with bounds checking enabled where supported, fixed-width
  integer overflow, `NaN` and infinity, empty inputs, and justified numerical
  tolerances. Never silently convert `Decimal` to float. Keep `fastmath=False`
  and `parallel=False` by default; each exception requires correctness tests and
  a measured reason. Numba's [Python semantic notes](https://numba.readthedocs.io/en/stable/reference/pysemantics.html)
  document bounds-checking and fixed-width integer behavior.
- Use `cache=True` only with a managed cache and a startup plan that records
  source, compiler, platform, and specialization identity and invalidation. Do
  not rely on imported-code changes invalidating cached code or on mutable globals
  being observed; pass changing values as parameters. See Numba's
  [caching limitations](https://numba.readthedocs.io/en/stable/developer/caching.html).
  When latency matters, prewarm required signatures during controlled startup
  and include first-call compilation in the startup budget.
- Numba, msgspec, and any native dependency MUST pass the [existing dependency
  admission](../architecture/dependency-admission.md), lock, runtime, and
  native-compatibility checks before introduction.
  Check Numba's [version support information](https://numba.readthedocs.io/en/stable/user/installing.html#version-support-information)
  against the pinned CPython, NumPy, llvmlite, and LLVM environment. This
  guidance does not install or imply admission of any dependency.

## Native extensions and cross-language behavior

- Python bindings are adapters around an owned Rust or C++ target, not a second
  implementation by default. Keep economic logic on one authoritative side of
  the boundary where practical.
- Define ownership and lifetime for every borrowed buffer, capsule, memory view,
  callback, and native handle. A Python object MUST NOT outlive native storage it
  views, and native code MUST NOT retain borrowed Python references without the
  required ownership operation.
- Document GIL assumptions. Release it only while native code cannot call Python
  APIs and while every borrowed Python-owned buffer or handle has a valid lifetime
  and concurrency guarantee; reacquire it before calling Python.
- Native exceptions, panics, and error codes MUST be translated into stable Python
  exception categories without unwinding across the ABI.
- Prefer vectorized or batch APIs over per-row or per-event boundary calls. Measure
  serialization, copying, conversion, and GIL overhead with representative data.
- A Python fallback and native implementation of the same contract MUST run shared
  golden and differential tests within a justified tolerance.

## Documentation

- Every module, class, and named function, including methods and private helpers,
  MUST have a concise Google-style summary. Simple private helpers and tests MAY
  use a useful one-line summary. Public APIs MUST include every applicable
  `Args:`, `Returns:` or `Yields:`, and `Raises:` section; document units, time
  semantics, state changes, I/O, and failure conditions where they affect use.
  An inherited protocol contract is an exception only when recorded in the
  [design exception register](../architecture/python-standards-exceptions.toml)
  with its source fingerprint.
- Use an imperative one-line summary and Google section headings. A summary MUST
  describe semantics rather than repeat annotations. Reviewers remain responsible
  for the meaning and completeness of prose; metadata checks cannot prove that
  justification. Document relevant failures propagated by collaborators as well
  as exceptions raised directly by the function.
- Non-obvious algorithms SHOULD cite a stable paper, specification, or issue and
  document deviations from it.
- Comments for type/lint suppression MUST use the tool's error code, be scoped to
  the affected line, and carry the required owner/rationale/expiry suffix.

Ruff `D` with the Google convention and `ANN401` are required across the complete
Python scope, including tests and owned native stubs. The engineering-standards
checker additionally enforces useful contract sections, import headings and
reviewed function ownership. Its exact exception register retains ownership,
rationale, expiry and source fingerprints; no legacy source-debt allowance remains.

## Testing

- Use `pytest` and plain `assert` unless project configuration specifies otherwise.
- Name test files `test_<unit>.py` and tests `test_<behavior>_<condition>`.
- Organize tests as arrange, act, assert; comments are optional when the phases are
  already clear.
- Use fixtures for meaningful shared setup or lifecycle management, not to hide
  the values central to a test.
- Follow the shared [behavioral coverage rules](README.md#testing-standards) when
  reorganizing tests or moving workflows into classes. Type fixes MUST preserve
  malformed inputs and reach the original runtime rejection path. Serialization
  refactors MUST preserve the selected serializer, JSON options and golden output
  unless a separately documented contract change requires otherwise.
- Use parametrization for the same behavior across input/output cases. Split tests
  whose failure explanations or setup differ.
- Assert specific exception types and meaningful message fragments with
  `pytest.raises`.
- Mock at owned boundaries, not deep inside third-party implementation details.
  Prefer small fakes for stable domain protocols.
- Tests for native bindings MUST cover ownership, buffer lifetime, dtype/shape,
  exception translation, empty inputs, non-contiguous inputs where supported, and
  repeated initialization/shutdown.
- Use `tmp_path`, injected clocks, and local deterministic fixtures rather than
  real user directories, wall clocks, networks, or credentials.
- Floating-point assertions MUST use justified absolute/relative tolerances.
- Coverage identifies untested code but is not a target to satisfy with weak tests.

## Python review checklist

- The code is `ruff`-formatted and lint-clean without unjustified suppressions.
- Strict type checking passes and untyped boundary data is narrowed immediately.
- Imports are direct and side-effect free; package dependencies are declared in
  the owning build target and reproducible environment.
- Public names and docstrings follow PEP 8/257 and domain vocabulary.
- No mutable defaults, naive timestamps, uncontrolled randomness, or hidden I/O
  remain.
- Structured-record choices retain boundary validation and mutability contracts;
  msgspec use has representative end-to-end benchmark evidence.
- Numeric acceleration has cold/warm, dtype, conversion, memory, and correctness
  evidence, with dependency admission and cache identity handled explicitly.
- Exceptions preserve causes and resources are managed by narrow context managers.
- Native bindings have explicit ownership, GIL, error, and conformance evidence.
- Tests cover behavior, boundaries, and regression/failure paths.
