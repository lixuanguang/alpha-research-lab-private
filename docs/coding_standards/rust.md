# Rust Coding Standards

## Scope and baseline

This guide applies to Rust source, tests, examples, benchmarks, build scripts, and
Cargo configuration. It supplements the shared [coding standards](README.md) and
the official Rust API Guidelines.

Use the edition and minimum supported Rust version declared by the workspace.
For a new workspace, select an edition and toolchain supported by the deployment
environment, dependencies, and repository build system, then pin them explicitly.
Do not infer `stable` from the developer machine or change the edition or minimum
supported version in an unrelated patch.

## Required tooling

The repository's root build/test interface and target graph are authoritative.
When the owning target exposes a Cargo workspace for local iteration, a normal
Rust change MUST run the configured equivalents of:

```text
cargo fmt --all --check
cargo clippy --workspace --all-targets <feature-flags> -- -D warnings
cargo test --workspace <feature-flags>
cargo doc --workspace <feature-flags> --no-deps
```

Run examples, doctests, feature-specific builds, benchmarks, Miri, fuzzers,
sanitizers, `cargo audit`, or `cargo deny` when configured or relevant to the risk.
The `<feature-flags>` placeholder is illustrative. Check the supported feature
matrix; use `--all-features` only when that is a valid configuration and do not
assume it represents every supported build.

Do not add a crate merely to avoid a few clear lines of standard-library code.
New dependencies MUST have a current need, compatible license, acceptable
maintenance/security posture, and intentionally selected features. Commit
`Cargo.lock` for binaries/applications when Cargo owns resolution, and follow the
repository build graph's lock/import policy when another system owns resolution.

- The compiler, target triple, standard library, linker, sysroot, code generators,
  Cargo configuration, and target CPU/features MUST be pinned build inputs.
- `build.rs`, procedural macros, and generators MUST be deterministic for declared
  inputs and MUST NOT fetch from the network or depend on undeclared host tools,
  directories, environment variables, timestamps, or locale.
- Do not enable host CPU features implicitly for portable artifacts. Model CPU
  variants as explicit platform targets and test dispatch on supported hosts.
- A deployable artifact records source, target, toolchain, dependency, schema,
  platform, feature-set, panic-mode, and symbol/debug-artifact provenance.

## Formatting, modules, and imports

- `rustfmt` owns whitespace and wrapping. Do not hand-format against it.
- Use `rustfmt.toml` only for stable options supported by the pinned toolchain.
- Modules SHOULD reflect cohesive domain concepts, not implementation categories
  such as `helpers` or `utils`.
- For new hierarchies, prefer `foo.rs` with child modules under `foo/` rather than
  the older `foo/mod.rs` layout; follow the local layout in established code.
- Imports belong at module scope unless a narrow local import improves trait-method
  clarity or macro scope.
- Group imports according to `rustfmt`; do not use glob imports outside preludes,
  tests, or an enum variant scope where the imported set is intentionally small.
- Re-export only a deliberate public API. Do not flatten unrelated internals into
  a large prelude.
- Keep visibility as narrow as possible: private, then `pub(super)`/`pub(crate)`,
  and `pub` only for supported external API.

## Naming

Follow Rust's standard naming conventions:

| Construct | Convention | Example |
| --- | --- | --- |
| Crate or module | `lower_snake_case` | `portfolio_risk` |
| Function or method | `lower_snake_case` | `calculate_exposure` |
| Local variable or field | `lower_snake_case` | `decision_time` |
| Struct, enum, trait, or type alias | `UpperCamelCase` | `MarketEvent` |
| Enum variant | `UpperCamelCase` | `OrderState::Rejected` |
| Constant or static | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT` |
| Lifetime | short lowercase | `'a`, `'request` |
| Type parameter | concise `UpperCamelCase` | `T`, `Value` |
| Feature | `lower-kebab-case` | `simd-pricing` |

Additional rules:

- Constructors use `new`; conversions use the standard `From`, `TryFrom`, `AsRef`,
  and related traits when their semantics match.
- Avoid redundant `get_` prefixes. Use `field()`, `field_mut()`, and `set_field()`
  when accessors are needed.
- Iterator methods SHOULD follow standard vocabulary such as `iter`, `iter_mut`,
  and `into_iter`.
- Predicates SHOULD start with `is_`, `has_`, `can_`, or another natural question.
- Acronyms are cased as words: `HttpClient`, `instrument_id`, and `parse_csv`.
- Unsafe functions MUST make the hazardous action evident and document caller
  obligations; an `unsafe_` prefix alone is not adequate documentation.

## Types and API design

- Use the type system to make invalid states unrepresentable where practical.
- Prefer domain newtypes over passing interchangeable primitive IDs, units,
  currencies, or timestamps.
- Use enums for closed state variants and state transitions instead of Boolean or
  string tags.
- Prefer owned values in stored state and borrowed views in call parameters when
  the lifetime is simple and useful.
- Accept flexible borrowed forms through `&str`, slices, `AsRef`, or iterators when
  doing so improves the API without obscuring types. Do not add generics solely to
  save a trivial caller conversion.
- Return `impl Trait` when callers need behavior but not the concrete type. Use
  trait objects for genuine runtime polymorphism and generics for useful static
  polymorphism.
- Keep trait contracts small and cohesive. Implement a standard trait rather than
  inventing an equivalent project trait.
- Derive standard traits such as `Debug`, `Clone`, `Copy`, `Eq`, `Ord`, `Hash`, and
  serialization only when their semantics are correct. Do not derive `Copy` for a
  type whose duplication should remain visible.
- Public `#[non_exhaustive]`, `repr`, discriminants, and serialized representations
  are compatibility decisions and MUST be deliberate.
- Mark results or types `#[must_use]` when silently discarding them is likely a bug.

## Ownership, borrowing, and allocation

- Prefer borrowing to cloning. Do not add `clone()` only to satisfy the borrow
  checker without first understanding the intended ownership.
- Clone explicitly when an independent owned value is required; keep the cloned
  scope and data size visible.
- Prefer stack/value storage and standard containers. Box only for recursive types,
  trait objects, stable indirection, or measured size needs.
- Use `Rc` only for single-threaded shared ownership and `Arc` only for necessary
  thread-safe shared ownership. Shared ownership is not a substitute for a clear
  lifetime design.
- Interior mutability (`Cell`, `RefCell`, `Mutex`, `RwLock`, atomics) requires a
  documented ownership/synchronization reason.
- Avoid self-referential structures and pinning unless the API genuinely requires
  stable addresses; encapsulate them behind a safe interface.
- Reuse buffers in hot paths only after measurement and without exposing stale
  data or weakening correctness.

## Errors and panics

- Fallible operations return `Result<T, E>`; optional values use `Option<T>`. Do
  not encode errors as magic values, empty collections, or log-only behavior.
- Library errors MUST be structured and actionable. They SHOULD expose stable
  variants/categories without leaking dependency-specific internals into the
  public API.
- Application boundaries MAY use contextual dynamic errors. Libraries SHOULD use
  typed errors when callers need to inspect or recover.
- Add context when crossing file, network, parsing, task, or domain boundaries and
  preserve the underlying source.
- Use `?` for propagation when no local recovery or translation is needed.
- Do not use `unwrap()` in production code. `expect()` is permitted only when a
  local invariant proves impossibility and its message states that invariant.
- Panics are for programmer defects or violated internal invariants, not malformed
  input, ordinary I/O failure, or expected domain outcomes.
- Tests MAY use `unwrap`/`expect` where failure itself makes the test diagnostic,
  but clear assertions and messages are preferred.
- Do not ignore a `Result` with `let _ =` unless best-effort semantics are part of
  the contract and the lost failure is deliberately accounted for.

## Unsafe Rust and FFI

- Safe Rust is the default. `unsafe` is allowed only when required for FFI, a
  proven performance need, or an abstraction impossible to express safely.
- Every `unsafe` block MUST be minimal and immediately preceded by a `// SAFETY:`
  comment that explains why all safety preconditions hold.
- An `unsafe fn` MUST have a `# Safety` documentation section listing every caller
  obligation.
- Encapsulate unsafe implementation behind a small safe API whose invariants are
  tested. Deny or warn on unsafe operations inside unsafe functions according to
  workspace policy.
- Review pointer validity, alignment, initialization, aliasing, provenance,
  lifetime, layout, unwinding, and thread-safety assumptions explicitly.
- FFI types MUST have a defined representation such as `#[repr(C)]` where needed.
  Never expose Rust references, trait objects, `String`, `Vec`, or Rust enum layout
  directly through a C ABI.
- No panic may unwind across an FFI boundary. Translate failures to the boundary's
  explicit result convention.
- FFI ownership and allocation/deallocation side MUST be documented and paired.
- Prefer opaque handles for complex Rust state. Create, borrow/retain where
  applicable, and destroy operations MUST define thread safety and invalid-handle
  behavior.
- Error codes crossing an ABI MUST be stable and machine-readable. Diagnostic
  strings and returned buffers need explicit encoding, allocator, capacity,
  lifetime, and release rules.
- Callbacks MUST document calling thread, reentrancy, lifetime, cancellation, and
  whether they may re-enter Rust or the foreign runtime.
- Python bindings MUST document GIL behavior and MUST NOT call Python APIs while
  the GIL is released. No panic may unwind across the binding boundary; external
  failures return structured Rust errors that translate into stable Python
  exception categories.
- Unsafe and low-level code SHOULD run under Miri, sanitizers, and/or fuzzing as
  applicable.

## Async and concurrency

- Use asynchronous code for concurrent I/O, not as a default abstraction.
- Do not perform blocking I/O or long CPU work on an async executor thread. Use an
  appropriate blocking pool or separate worker.
- Every spawned task MUST have an owner, shutdown behavior, and a policy for
  observing failure. Avoid detached tasks.
- Propagate cancellation and make cancellation safety explicit around partial
  writes, transactions, and state changes.
- Never hold a synchronous lock guard across `.await`. Keep async lock critical
  sections small and do not call unknown code while locked.
- Prefer channels or ownership transfer over `Arc<Mutex<_>>` shared state.
- A type MUST not receive unsafe `Send` or `Sync` implementations without a
  documented proof of its synchronization and lifetime invariants.
- Atomic operations require an explanation of ordering. Prefer stronger ordering
  until a measured need and a reviewed proof justify weakening it.
- Use monotonic time for durations/timeouts and wall-clock time only for domain
  timestamps.

## Performance and numerical code

- Establish a correct simple implementation before optimizing and preserve it as
  a reference in tests when practical.
- Benchmark representative workloads; do not infer performance from code shape.
- Avoid unnecessary allocation in hot loops, but do not trade correctness or clear
  ownership for speculative micro-optimization.
- Iterator chains are encouraged when clear. Use an explicit loop when it makes
  state, short-circuiting, or error handling easier to understand.
- Choose numeric types from domain range, signedness, precision, serialization, and
  interoperability requirements.
- Use checked arithmetic where input can exceed the valid range. Saturating or
  wrapping arithmetic MUST reflect the explicit domain contract, not convenience.
- Floating-point code MUST define handling for `NaN`, infinity, signed zero, and
  tolerance-based comparisons.
- Floating-point contraction, reassociation, fast-math, flush-to-zero, and SIMD
  choices are semantic decisions. They require numerical conformance tests and
  MUST NOT enter financial, risk, or accounting code through an unrelated
  optimization change.
- Randomized work MUST accept or construct from an explicit reproducible seed when
  results need to be repeatable.

### Latency-sensitive targets

- A latency claim requires a representative benchmark on controlled hardware with
  recorded CPU, NUMA, power, compiler, artifact, feature-set, and background-load
  configuration. Shared CI timing is diagnostic only.
- Hot paths MUST NOT perform unbounded allocation, blocking I/O, DNS, process
  creation, synchronous logging, or metrics export. Use bounded queues or
  preallocated telemetry with an explicit overflow policy.
- Observability backpressure MUST NOT delay market data, risk checks, order
  handling, or a kill switch. Dropped observations remain measurable.
- Lock-free code, custom allocators, busy polling, pinning, huge pages, and unsafe
  SIMD require measurements, documented invariants, failure behavior, and a safe
  reference implementation or conformance oracle where practical.
- Performance improvements MUST preserve shared golden results or declare and
  justify numerical differences.

## Documentation

- Public items MUST have rustdoc explaining purpose, invariants, units, errors,
  panics, and side effects when relevant.
- Public modules SHOULD begin with `//!` documentation describing their role and
  boundary.
- Examples in rustdoc SHOULD be executable doctests. Mark examples `no_run` only
  when execution genuinely requires an external resource, and explain that need.
- Use standard sections where applicable: `# Errors`, `# Panics`, `# Safety`, and
  `# Examples`.
- Documentation MUST not promise complexity, allocation, ordering, or compatibility
  guarantees the implementation and tests do not support.

## Testing

- Put focused unit tests near private implementation and integration tests in
  `tests/` for public behavior and crate boundaries.
- Name tests after behavior and condition, for example
  `rejects_order_when_available_balance_is_insufficient`.
- Test valid behavior, boundary values, structured error variants, and state
  invariants.
- Use property tests for parsers, round trips, state machines, arithmetic invariants,
  and broad input spaces when beneficial.
- Use fuzzing for untrusted parsers, binary formats, and unsafe boundaries.
- Foreign consumers and alternate-language implementations MUST run shared
  contract, golden, and differential tests across the supported ABI/schema matrix.
- Concurrency tests SHOULD use controlled synchronization rather than sleeps and
  timing assumptions. Model checking tools are encouraged for subtle protocols.
- Tests MUST be deterministic and independent of ordering, timezone, locale,
  network, and user environment unless explicitly integration-scoped.
- Examples and documentation tests are part of the supported API and MUST pass.

## Rust review checklist

- `fmt`, warning-denying `clippy`, tests, and docs pass for affected targets/features.
- Ownership is intentional; clones, boxes, reference counting, and interior
  mutability are justified.
- Errors are structured and contextual; normal external failures cannot panic.
- Every unsafe operation has a complete safety argument and safe encapsulation.
- Async tasks, locks, cancellation, and shutdown have explicit ownership.
- Public APIs and serialized/FFI representations account for compatibility.
- Toolchain, target CPU/features, dependencies, panic mode, and generated inputs
  are declared rather than inherited from the host.
- Latency-sensitive telemetry is bounded and non-blocking, and performance evidence
  comes from controlled hardware.
