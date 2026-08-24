# C and C++ Coding Standards

## Scope and baseline

This guide applies to C and C++ source, headers, tests, build definitions, and
foreign-function boundaries. It supplements the shared [coding standards](README.md).

Use the language version declared by the nearest build configuration. For a new
component with no established baseline, prefer C17 or later for C and C++20 or
later for C++, subject to supported compilers and deployment targets. Do not change
the language version as part of an unrelated patch.

C and C++ are different languages. Do not write a lowest-common-denominator hybrid
or compile the same implementation as both languages. Shared boundaries MUST use
an explicitly C-compatible ABI.

## Required tooling and build policy

The repository's build system is authoritative. A normal change MUST run the
applicable equivalents of:

```bash
clang-format --dry-run --Werror <changed-files>
clang-tidy <changed-files> -- <compile-flags>
cmake --build <build-directory>
ctest --test-dir <build-directory> --output-on-failure
```

Use the compilation database produced by the build; do not invent include paths or
defines for static analysis. New code MUST compile without warnings under the
repository warning policy. New components SHOULD enable at least `-Wall`, `-Wextra`,
and `-Wpedantic` (or the supported compiler equivalents), and CI SHOULD treat
project-code warnings as errors.

Run sanitizer builds for changes involving memory, parsing, concurrency, unsafe
FFI, or non-trivial indexing:

- AddressSanitizer and UndefinedBehaviorSanitizer for memory/undefined behavior.
- ThreadSanitizer in a separate compatible build for shared-memory concurrency.

Do not edit generated sources or vendored third-party code to satisfy local style.
Regenerate or isolate warnings at the dependency boundary.

## Files, formatting, and headers

- Use `clang-format` with the repository configuration. Do not manually fight the
  formatter.
- Headers use `.h`; C++ implementations use `.cpp`; C implementations use `.c`
  unless the local build defines another convention.
- Every header MUST be self-contained and compile when included first.
- Use `#pragma once` when supported by repository policy; otherwise use a unique
  project-prefixed include guard.
- Include only what a file directly uses. Do not rely on transitive includes.
- Include order is the matching header, C/C++ standard library, third party, then
  project headers, with groups separated by one blank line.
- Prefer forward declarations in C++ only when they preserve a clean ownership/API
  boundary. Do not forward-declare standard-library types.
- Keep declarations in headers and non-template implementation in source files.
- Definitions in headers MUST be `inline`, templates, or otherwise safe under the
  one-definition rule.
- Never place `using namespace` in a header. Avoid it at source-file scope; narrow
  aliases inside a function or implementation namespace are acceptable.

## Naming

### C++

| Construct | Convention | Example |
| --- | --- | --- |
| Namespace | `lower_snake_case` | `alpha::execution` |
| Class, struct, enum, type alias, concept | `UpperCamelCase` | `OrderRequest` |
| Function or method | `lower_snake_case` | `calculate_notional` |
| Local variable or parameter | `lower_snake_case` | `fill_price` |
| Private data member | `lower_snake_case_` | `order_id_` |
| Compile-time constant | `kUpperCamelCase` | `kMaxRetryCount` |
| Enumerator | `UpperCamelCase` | `OrderState::PartiallyFilled` |
| Template parameter | `UpperCamelCase` | `Allocator`, `Value` |
| Macro | `PROJECT_UPPER_SNAKE_CASE` | `ALPHA_LIKELY` |

### C

| Construct | Convention | Example |
| --- | --- | --- |
| Function | `<project>_<module>_<verb>` | `alpha_book_update` |
| Struct, union, or enum tag | `<project>_<domain_noun>` | `alpha_order` |
| Local variable or parameter | `lower_snake_case` | `order_count` |
| Public constant or enumerator | `PROJECT_UPPER_SNAKE_CASE` | `ALPHA_ORDER_OPEN` |
| Macro | `PROJECT_UPPER_SNAKE_CASE` | `ALPHA_ARRAY_LENGTH` |

Avoid inventing public names ending in `_t`; POSIX reserves many such identifiers.
Public C symbols MUST carry a project/module prefix. Identifiers beginning with an
underscore followed by an uppercase letter, or containing double underscores, are
reserved and MUST NOT be declared.

For both languages, names involving sizes and indexing SHOULD distinguish
`count`, `capacity`, `index`, and byte size. Add units when the type does not encode
them, such as `timeout_ms` or `buffer_size_bytes`.

## C++ type and interface design

- Use value semantics by default. A type MUST establish and preserve its invariants.
- Use `class` for encapsulated invariant-bearing types and `struct` for transparent
  aggregates with public data.
- Prefer composition over inheritance. Public inheritance requires a substitutable
  interface and normally a public virtual destructor.
- Use `override` on every override and exactly one of `virtual`, `override`, or
  `final` on a declaration.
- Mark single-argument constructors `explicit` unless implicit conversion is the
  deliberate documented contract.
- Mark important non-discardable results `[[nodiscard]]`.
- Use `enum class`, not unscoped enums, for new C++ code.
- Prefer `std::span`, `std::string_view`, iterators, or ranges for non-owning input
  views. Their referenced storage MUST outlive the view.
- Use `const` to express non-mutation. Do not use `const_cast` to bypass an API.
- Use `auto` when the type is evident, unnameable, or avoids repetition. Spell out
  types when ownership, signedness, precision, or conversion would be obscured.
- Avoid implicit narrowing and signed/unsigned mixing. Use checked conversions at
  external and numerical boundaries.
- Prefer standard-library facilities over custom containers, algorithms, smart
  pointers, or synchronization primitives.

## Ownership and lifetime

### C++

- Ownership MUST be visible in the type. Prefer values and RAII.
- Use `std::unique_ptr` for exclusive heap ownership and `std::shared_ptr` only for
  necessary shared lifetime. Use `std::weak_ptr` to break genuine ownership cycles.
- A raw pointer or reference is non-owning unless a documented C/FFI API states
  otherwise. Do not return a pointer/reference to expired or movable storage.
- Do not call `new`, `delete`, `malloc`, or `free` directly in ordinary C++ business
  code. Encapsulated low-level allocators are the exception and require tests.
- Follow the rule of zero. If a type owns a low-level resource and must define a
  destructor, copy, or move operation, review all five special members.
- Destructors MUST NOT throw.
- Avoid global mutable state and initialization-order dependencies. Function-local
  immutable initialization is preferred when global lifetime is unavoidable.

### C

- Every allocating/initializing function MUST document the matching release or
  cleanup operation and ownership transfer.
- Initialize objects before use and leave output parameters unchanged or in a
  documented safe state on failure.
- A resource-owning object SHOULD have one cleanup function that is safe after
  partial initialization.
- Pass buffer pointer and length together. Validate length arithmetic before
  allocation, copying, indexing, or pointer addition.
- Prefer a caller-owned result or an opaque handle to exposing mutable internal
  representation.
- Do not return pointers to automatic storage. Document borrowed-pointer lifetime.

## Error handling

### C++

- Use exceptions for exceptional failures when the component enables them. Throw
  typed domain or standard exceptions, and add context at boundaries.
- Expected alternatives SHOULD use a value type such as `std::optional`, a project
  result type, or `std::expected` when available under the language/toolchain policy.
- Do not use exceptions as normal loop or branch control flow.
- Catch by `const` reference. Catch only what can be handled or translated; a
  catch-all is limited to a thread/process boundary that produces a defined failure.
- State exception-safety guarantees for mutating public operations. Prefer strong
  guarantee through commit-after-success; at minimum, preserve invariants.
- Code built with exceptions disabled MUST use one consistent explicit result
  policy. Do not terminate on recoverable external input.

### C

- Fallible operations MUST return an explicit status code or result object. Reserve
  one well-defined value for success.
- Output parameters follow inputs and MUST be validated before use.
- Preserve the original failure detail through a documented error object or
  boundary logging; do not depend on `errno` after another call can overwrite it.
- Use one cleanup path when it makes acquisition/release correctness clearer.
  `goto cleanup` is acceptable in C for this purpose only.
- Assertions are for internal invariants, never validation of untrusted input.

## Preprocessor, macros, and conditional compilation

- Prefer typed constants, inline functions, templates, and `constexpr` over macros.
- A function-like macro MUST parenthesize every parameter use and the complete
  expansion, evaluate arguments exactly once, or document why that is impossible.
- Never hide control flow, resource ownership, or declarations behind a surprising
  macro.
- Conditional compilation belongs in small platform/feature adapters. Core domain
  algorithms SHOULD not be fragmented by compiler flags.
- Every supported conditional branch MUST compile in CI or have a documented test
  procedure.

## Numerical and low-level safety

- Use fixed-width integer types at serialization, protocol, and FFI boundaries.
  Elsewhere, use the type that represents the domain and check conversions.
- Use `size_t` for object sizes and container indices, while handling differences
  from signed domain values explicitly.
- Check integer overflow before allocation-size multiplication and addition.
- Do not use uninitialized storage, out-of-bounds pointer arithmetic, type-punning
  through incompatible pointers, or reads of inactive union members.
- C++ code SHOULD use `std::bit_cast` for supported bit reinterpretation. C code
  SHOULD use `memcpy` where required to avoid aliasing violations.
- Floating-point comparisons MUST use scale-appropriate tolerances. Explicitly
  handle `NaN`, infinity, signed zero, and non-associativity where relevant.
- Do not use `memcpy`, `memset`, or byte serialization on non-trivially-copyable C++
  types.
- Binary formats MUST define byte order, size, alignment, version, and validation.
- Sensitive buffers SHOULD be minimized and cleared with an operation the compiler
  cannot optimize away when the threat model requires it.

## Concurrency

- Prefer immutable data, task isolation, and message passing to shared mutable state.
- Every shared mutable object MUST have a documented synchronization policy.
- Use RAII locks in C++ and one structured acquire/release path in C.
- Keep critical sections small. Do not perform blocking I/O, invoke unknown
  callbacks, or await external work while holding a lock.
- Establish and document lock order when multiple locks can be acquired.
- Use atomics only with a documented memory-order argument. Default sequential
  consistency is preferred until a measured need and proof justify weaker ordering.
- A thread MUST have an owner and explicit join/stop lifetime; detached threads are
  prohibited unless managed by a process-lifetime subsystem.
- Test cancellation, shutdown, partial startup, and contention behavior.

## C interoperability

- Expose C++ through a narrow `extern "C"` API using C-compatible types and calling
  conventions.
- Never allow an exception to cross a C ABI boundary. Translate it to an explicit
  status and preserve safe diagnostic context.
- Do not expose C++ standard-library containers, references, overloaded functions,
  templates, or class layouts in a C ABI.
- ABI-visible structs MUST define ownership, alignment, versioning, and compatible
  extension behavior.
- Validate all pointers, lengths, enum values, and handles received across FFI.

## Documentation and testing

- Public headers MUST document ownership, nullability, units, thread safety,
  lifetime, errors, and invalidation rules.
- Complex templates, lock-free code, numerical algorithms, and low-level memory
  operations MUST document invariants and cite their source/design.
- Unit tests MUST cover boundary sizes, empty input, invalid values, ownership
  transfer, cleanup after partial failure, and error propagation.
- Parsers and binary interfaces SHOULD have fuzz tests and a retained regression
  corpus.
- C++ value types SHOULD test copy/move behavior when custom special members exist.
- Concurrency tests MUST avoid timing-only assertions; use synchronization to make
  the intended interleaving deterministic where possible.
- Tests MUST run under applicable sanitizers in CI or a documented validation job.

## C/C++ review checklist

- Headers are self-contained and the build is warning-free.
- Ownership, borrowing, nullability, sizes, units, and cleanup are explicit.
- No undefined behavior, unchecked narrowing, unsafe length arithmetic, or ABI
  exception leak is present.
- RAII/rule-of-zero is used in C++; C cleanup is correct after partial failure.
- Concurrency has a clear lifetime, synchronization, and lock-order policy.
- Formatter, static analysis, tests, and applicable sanitizers pass.
