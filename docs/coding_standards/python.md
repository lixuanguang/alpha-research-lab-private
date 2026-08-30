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

The repository's root build/test interface and target graph are authoritative.
For local iteration, run the configured equivalents below against affected Python
targets and their reverse dependencies. The placeholders are illustrative, not
literal repository paths:

```text
ruff check <affected-paths>
ruff format --check <affected-paths>
mypy --strict <affected-packages>
pytest <affected-tests>
bandit -q -c <config> -r <affected-source>  # when configured
```

During iteration, scoped commands are encouraged. Before completion, run every
applicable repository check affected by the change. Run `pre-commit run --all-files`
when hook behavior or multiple file types are involved.

Do not silence a tool globally to fix a local violation. A suppression MUST be as
narrow as possible and include a reason when that reason is not self-evident.

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
- Import groups are standard library, third party, then local application code.
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

- All public functions, methods, class attributes, and module-level variables MUST
  be typed. Private functions SHOULD be fully typed; strict `mypy` is the default.
- Annotate return types explicitly, including `-> None`.
- Use syntax supported by the pinned minimum interpreter. Prefer built-in generics
  such as `list[str]`, union syntax such as `X | None`, and protocols from `typing`
  when that minimum version supports them; do not silently raise the runtime floor.
- Prefer precise domain types, enums, `Literal`, `NewType`, dataclasses, or validated
  models over unstructured dictionaries and tuples.
- Use `Protocol` for behavioral structural contracts. Use abstract base classes
  only when shared runtime behavior or nominal registration is required.
- `Any` is allowed only at an untyped boundary. Contain it, validate/narrow it
  immediately, and do not let it propagate into domain logic.
- Do not use `cast` to make an unsafe value appear valid. A cast requires an
  invariant the type checker cannot express and that the code actually establishes.
- Use `TypeGuard` or explicit validation for reusable narrowing logic.
- Prefer immutable/frozen value objects for identifiers, specifications, money,
  timestamps, and configuration.
- Use `default_factory` for mutable dataclass/model defaults. Never share a mutable
  default argument.
- Distinguish absent, empty, zero, and unknown values. Do not make a parameter
  optional merely for caller convenience when absence is invalid.
- Generated schema types and binding stubs are boundary representations. Translate
  them into domain types rather than allowing generated or native-library details
  to spread through research and portfolio logic.

## Functions and control flow

- Prefer pure functions for transformations and calculations.
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

- Use a class when state and behavior share invariants. Prefer a function or
  module for stateless behavior.
- Favor composition over inheritance and keep inheritance trees shallow.
- Constructors establish valid objects. Fallible I/O or complex parsing belongs
  in a named factory or boundary service.
- Do not create `Manager`, `Helper`, or `Utils` classes as miscellaneous containers.
- Properties MUST be inexpensive and unsurprising. I/O, blocking work, and
  material computation belong in methods.
- Dataclasses are appropriate for transparent data carriers. Do not add behavior
  to a dataclass that lets callers bypass its invariants.
- Pydantic or equivalent validation belongs at configuration/serialization
  boundaries; domain code SHOULD not depend on a validation framework without a
  boundary-specific need.
- The current bootstrap governance, configuration, registry, and serialization
  records use strict immutable Pydantic boundary models under
  [ADR 0008](../architecture/decisions/0008-pydantic-boundary-models.md). This does
  not authorize validation-framework dependencies in economic or trading-domain
  models.

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

- Public modules, classes, functions, and methods MUST have useful docstrings unless
  the contract is entirely obvious and already documented by an inherited protocol.
- Use an imperative one-line summary. Add sections for parameters, returns, raises,
  examples, units, and side effects when they add information.
- A docstring MUST describe semantics rather than repeat annotations.
- Non-obvious algorithms SHOULD cite a stable paper, specification, or issue and
  document deviations from it.
- Comments for type/lint suppression MUST use the tool's error code and be scoped
  to the affected line.

## Testing

- Use `pytest` and plain `assert` unless project configuration specifies otherwise.
- Name test files `test_<unit>.py` and tests `test_<behavior>_<condition>`.
- Organize tests as arrange, act, assert; comments are optional when the phases are
  already clear.
- Use fixtures for meaningful shared setup or lifecycle management, not to hide
  the values central to a test.
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
- Exceptions preserve causes and resources are managed by narrow context managers.
- Native bindings have explicit ownership, GIL, error, and conformance evidence.
- Tests cover behavior, boundaries, and regression/failure paths.
