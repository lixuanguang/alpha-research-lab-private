# Coding Standards

## Purpose

These standards define how humans and coding agents design, implement, review,
and validate code in this repository. They are written as executable guidance:
an implementation should be reviewable against individual rules without relying
on unstated conventions.

They implement, and are subordinate to, the root
[Institutional Multi-Asset Quant Monorepo Blueprint](../../Institutional_Multi_Asset_Quant_Monorepo_Blueprint.pdf).
The blueprint's invariants, R0-R4 change classes, QG01-QG15 gates, independent
approvals, and non-waivable controls cannot be weakened by local style guidance.

The standards apply to new code and to code materially changed by a patch. They
do not require unrelated legacy code to be rewritten. When a touched area cannot
meet a rule, keep the exception narrow and document the reason and follow-up.

Standards apply at the build-target boundary. The repository is organized by
economic or platform responsibility first and implementation language second;
co-located Python, Rust, and C/C++ targets may implement or expose one domain
contract without sharing a release cadence or runtime.

## Language guides

- [Python](python.md)
- [C and C++](c_cpp.md)
- [Rust](rust.md)

This file contains rules shared by all languages. A language guide may make a
shared rule stricter, but may not silently weaken it.

## Requirement language and precedence

The words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are
normative:

- **MUST** or **MUST NOT**: required unless an approved, documented exception
  applies.
- **SHOULD** or **SHOULD NOT**: the default; a deviation needs a concrete reason.
- **MAY**: optional and chosen according to the local design.

When instructions conflict, use this order:

1. Safety, security, legal, and data-integrity requirements.
2. The accepted specification and public contracts for the change.
3. The nearest directory-level contributor or agent instructions.
4. The language-specific guide in this directory.
5. This shared guide.
6. Existing local style in the touched module.

Do not use local style as justification for reproducing a correctness or security
defect. Surface irreconcilable conflicts instead of guessing.

## Required workflow for coding agents

Before editing, an agent MUST:

1. Read the request, the nearest repository instructions, and the relevant
   language guide completely.
2. Inspect the affected code, tests, public interfaces, build configuration, and
   current working-tree changes.
3. State any assumption that materially affects behavior. Resolve facts from the
   repository rather than inventing APIs, schemas, dependencies, or commands.
4. Identify affected build targets, owners, reverse dependencies, generated code,
   schemas, serialized formats, and FFI/ABI consumers.
5. Assign or confirm the R0-R4 risk class, applicable QG01-QG15 gates, required
   independent reviewers, rollout mode, and evidence retention.
6. Confirm the MR is Ready: linked roadmap item, scope/non-goals, impact analysis,
   thresholds, migration, rollout, rollback, monitoring, runbook, dependencies,
   and reviewer availability.
7. Choose the smallest coherent change that satisfies the request. Prefer one
   logical behavior change and keep non-generated changes near or below 400 lines
   where practical; otherwise provide the required split or migration rationale.

While editing, an agent MUST:

1. Preserve unrelated user changes and avoid broad formatting or refactoring.
2. Follow established package boundaries, build-target visibility, ownership,
   and dependency direction.
3. Update tests and documentation when behavior or a public contract changes.
4. Keep generated files out of hand-written patches unless the project explicitly
   tracks them; use the owning generator instead.
5. Update conformance, compatibility, migration, and rollback evidence when a
   schema, serialized representation, or language boundary changes.
6. Keep deployment separate from activation; a merged change or deployed artifact
   MUST NOT expand a capital or risk envelope.
7. Stop and report a conflict when safe behavior depends on unavailable domain
   knowledge or authorization.

Before declaring completion, an agent MUST:

1. Review the diff for scope, secrets, debugging code, dead code, and accidental
   generated artifacts.
2. Run the narrowest affected build targets through the repository's documented
   root interface, plus the configured formatter, linter, and type/static checks.
3. Run reverse-dependency or broader tests when the change affects shared
   contracts, build rules, toolchains, serialization, persistence, concurrency,
   numerical logic, or security boundaries.
4. For a deployable target, verify that its artifact identity and provenance do
   not depend on undeclared host state or secret values.
5. Report what changed, what was validated, and any check that could not run.
6. Confirm mandatory gates, approvals, evidence links, release identity,
   monitoring, post-deploy checks, and expiry/removal dates required by the change
   class. A merged MR is not automatically a production release.

Passing automated checks is necessary but does not replace reasoning about
correctness, information leakage, numerical behavior, or failure modes.

## Core design principles

### Correctness and clarity first

- Code MUST be correct for valid inputs and fail explicitly for invalid states.
- Prefer clear, unsurprising control flow over compact or clever code.
- Make units, time semantics, ownership, mutability, and optionality explicit.
- Do not silently discard errors, truncate values, weaken validation, or choose a
  favorable fallback.
- Deterministic work MUST have controlled clocks, seeds, ordering, and inputs.

### DRY: one authoritative representation

- A business rule, schema, constant, or algorithm SHOULD have one authoritative
  implementation.
- When two languages must implement the same contract, either bind one
  authoritative implementation or require versioned golden and differential
  tests. Source similarity alone is not proof of equivalent behavior.
- Extract duplication when the repeated code represents the same concept and is
  likely to change together.
- Do not force superficially similar behavior into a shared abstraction when its
  invariants or reasons to change differ.
- Tests MAY repeat small setup fragments when extraction would hide the scenario.
- Do not duplicate source constants in comments or documentation when they can
  drift; explain meaning and constraints instead.

### SOLID design

- **Single responsibility:** a module, type, or function SHOULD have one cohesive
  reason to change.
- **Open/closed:** add behavior through stable composition points when variants
  are expected; do not add an abstraction for a hypothetical variant.
- **Liskov substitution:** implementations MUST preserve the documented inputs,
  outputs, invariants, and failure semantics of their interface.
- **Interface segregation:** consumers SHOULD depend on the smallest useful
  contract, not a broad interface with irrelevant methods.
- **Dependency inversion:** domain logic SHOULD depend on domain-facing contracts;
  infrastructure code implements those contracts at the boundary.

Use composition by default. Use inheritance only for a genuine substitutable
relationship with a stable contract.

### KISS and YAGNI

- Implement the simplest design that meets the current verified requirements.
- Do not add extension points, configuration flags, dependencies, caches,
  concurrency, or distributed components without a current use case.
- Remove obsolete branches and compatibility shims when their supported lifetime
  ends.
- Optimize only after establishing a correctness baseline and measuring a
  relevant bottleneck.

### Cohesion and coupling

- Keep domain logic independent from storage, network, CLI, and UI frameworks.
- Side effects SHOULD be isolated at boundaries; calculations SHOULD be pure when
  practical.
- Dependencies MUST point toward stable policy, not from domain code toward a
  concrete vendor or transport.
- Avoid circular dependencies, service locators, hidden global state, and modules
  whose only purpose is to re-export unrelated objects.
- Public interfaces SHOULD accept domain concepts rather than loose bags of
  primitives.
- Research targets MAY depend on production-capable domain libraries. Production
  targets MUST NOT depend on notebooks, ad hoc experiments, or research-only
  approximations.

## Monorepo targets, builds, and artifacts

- A build target is the unit of dependency, ownership, testing, artifact creation,
  and deployment. A directory is not automatically a public dependency surface.
- Each target MUST declare its direct dependencies, visibility, owner, supported
  runtime platform, and generated inputs according to repository tooling.
- Builds MUST use pinned interpreters, compilers, standard libraries, package
  dependencies, and code generators. Developer-machine installations and ambient
  environment variables MUST NOT be undeclared inputs.
- The target repository MUST provide one documented root interface backed by the
  pinned hermetic Bazel graph introduced in B02. The current uv/Make interface is
  transitional bootstrap tooling. Language-native tools MAY remain available for
  fast local iteration, but they do not override Bazel ownership, dependency,
  affected-target, merged-result, provenance, or artifact checks.
- Generated source MUST identify its generator and inputs. Do not mix a large
  generated rewrite with an unrelated semantic change.
- A monorepo does not imply one version or release. Each deployable target produces
  an immutable artifact with source, target, toolchain, dependency, schema,
  platform, and build-mode provenance.
- The same deployable target is built once and promoted by artifact digest across
  applicable environments. Environment-specific configuration is validated and
  versioned separately; secret values never enter source or artifact identity.
- Every deployable release also carries signed provenance, an SPDX-compatible
  SBOM, schema/model/data/config/limit identities, evidence and approvals. It may
  be activated only through an independently authorized envelope.
- Source visibility does not grant runtime authority. Market-data entitlements,
  deployment rights, credentials, and capital permissions remain separate.

## Cross-language contracts

- Organize code by owning domain and keep language-specific implementations below
  that boundary. Do not create global language silos that duplicate economic
  rules without explicit ownership.
- Cross-process interfaces MUST use versioned schemas with compatibility tests.
  Schema changes account for old and new readers, migration, rollback, and every
  affected consumer selected from the dependency graph.
- In-process Rust/C++ integration MUST use a narrow C ABI or a reviewed
  interoperability layer. Ownership, allocator, lifetime, alignment, error,
  unwinding, threading, and version rules MUST be explicit.
- Language-native collections, exceptions, references, trait objects, class
  layouts, and other unstable representations MUST NOT cross an undocumented ABI.
- Python/native bindings SHOULD expose coarse or batch-oriented operations.
  Measure boundary conversion and call overhead before assuming native code is
  faster.
- Independent language implementations of one contract MUST share fixtures and
  pass differential or conformance tests within documented numerical tolerances.

## Functions, modules, and public interfaces

- Each function MUST have a clear contract and a single level of abstraction.
- Prefer small functions, but do not split cohesive logic solely to meet a line
  count. Extract when a block has its own name, invariant, reuse, or test value.
- Avoid Boolean parameters whose meaning is unclear at the call site. Prefer a
  named option, enum, or separate operation.
- Validate untrusted input at the boundary. Internal code MAY rely on validated
  domain types and documented invariants.
- Public API changes MUST account for callers, compatibility, migration, and
  documentation.
- Return values and errors MUST distinguish materially different outcomes. Do not
  use sentinel values that overlap valid data.
- Make state transitions explicit and reject invalid transitions.

## Naming

Language-specific casing is defined in each guide. In every language:

- Names MUST reveal purpose in the domain and use established vocabulary.
- Use one term for one concept. Do not alternate between synonyms such as
  `asset`, `instrument`, and `security` unless they are distinct types.
- Include units or representation where ambiguity is dangerous, for example
  `timeout_ms`, `price_minor_units`, or `timestamp_utc`.
- Avoid unexplained abbreviations, type-encoding prefixes, and filler names such
  as `data`, `info`, `manager`, `helper`, or `utils` when a precise name exists.
- Single-letter names are limited to conventional tiny scopes such as indices,
  coordinates, or mathematical notation whose meaning is documented nearby.
- A collection name SHOULD be plural; a predicate SHOULD read as a fact or
  question; an operation SHOULD use a verb.
- Do not encode an implementation detail in a public name unless it is part of
  the contract.

## Comments and documentation

- Comments explain why, invariants, units, external constraints, numerical
  reasoning, or non-obvious trade-offs. They MUST NOT merely narrate the syntax.
- Public APIs MUST document behavior, parameters, results, errors, side effects,
  and any non-obvious units or time semantics.
- A TODO MUST include a concrete condition or issue reference. Do not leave vague
  promises such as `TODO: improve`.
- Update documentation in the same change as the behavior it describes.
- Examples MUST compile or run when the language tooling supports checked
  examples.

## Error handling and observability

- Use the language's explicit error mechanism; do not ignore return status or
  catch errors without handling, translating, or re-raising them.
- Expected domain failures and programmer defects MUST remain distinguishable.
- Add context at system boundaries while preserving the original cause.
- Error messages SHOULD identify the failed operation and relevant safe
  identifiers, but MUST NOT expose secrets or sensitive payloads.
- Retry only failures known to be transient, with bounded attempts, backoff, and
  idempotent behavior.
- Logs MUST be structured where supported and use stable event names. Avoid log
  spam inside hot loops and do not log the same failure at every layer.
- Operational telemetry SHOULD identify the source revision, artifact digest,
  target, configuration version, environment, and safe domain identifiers needed
  for reconciliation.
- Telemetry from a latency-sensitive path MUST be bounded and non-blocking. A slow
  collector MUST NOT delay market data, risk enforcement, order handling, or a
  kill switch; dropped telemetry MUST itself be observable.
- Assertions express internal invariants; they are not a substitute for validating
  user, file, network, or market data.

## Security and data safety

- No secret, credential, token, private key, or sensitive dataset sample may be
  committed or logged.
- Treat file paths, URLs, queries, serialized objects, and external process
  arguments as untrusted input.
- Use parameterized queries and structured process APIs. Never construct commands
  or queries through unchecked string interpolation.
- Apply least privilege and minimize the lifetime and scope of sensitive data.
- Keep source access, data entitlements, artifact promotion, deployment authority,
  and trading credentials as distinct permissions.
- Use established cryptographic libraries and algorithms; never design custom
  cryptography.
- Destructive and externally visible operations MUST have explicit scope,
  idempotency or duplicate protection where applicable, and tests for failure
  behavior.
- Dependency additions MUST be justified, maintained, license-compatible, and
  pinned or locked according to repository policy.

## Numerical, time, and data-intensive code

- State units, currency, timezone, precision, missing-value behavior, and boundary
  inclusivity in the contract.
- Use UTC internally unless a domain convention explicitly requires another
  timezone. Do not use naive timestamps for real events.
- Do not use binary floating point for exact currency or identifiers. Choose
  decimal or integer minor units according to the domain contract.
- Numerical comparisons MUST use a tolerance justified by scale and algorithm;
  do not apply an arbitrary global epsilon.
- Check empty inputs, zero denominators, overflow/underflow, non-finite values,
  shape mismatches, and unstable ordering where relevant.
- Historical or simulated decisions MUST use only information available at the
  decision time. Tests SHOULD perturb future data to detect leakage.
- Preserve deterministic ordering when order affects hashes, results, or output.

## Testing standards

- Every defect fix MUST include a regression test that fails without the fix.
- New behavior MUST cover the success path, meaningful boundaries, and expected
  failures at the lowest practical test level.
- Tests MUST be deterministic, isolated, and independent of execution order.
- Unit tests SHOULD avoid real clocks, random global state, networks, and external
  services. Inject or fake those boundaries.
- Prefer testing observable behavior and contracts over private implementation
  details.
- Use integration tests for component boundaries and a small number of end-to-end
  tests for critical paths. Do not replace focused tests with a large end-to-end
  suite.
- CI SHOULD select affected targets and reverse dependencies from the build graph.
  Foundational schema, toolchain, and build-rule changes require broader validation.
- Cross-language implementations and bindings MUST run shared contract, golden,
  and differential tests; each side passing isolated unit tests is insufficient.
- Property, fuzz, or generative tests SHOULD cover parsers, serializers, numeric
  invariants, state machines, and other broad input spaces.
- A test MUST fail for the reason it claims to verify; avoid weak assertions and
  broad exception matches.

## Review checklist

Before approval, verify that:

- The change implements the requested contract and no unrelated behavior.
- Names, types, units, and ownership make invalid use difficult.
- DRY/SOLID abstractions reflect real shared behavior, not speculation.
- Boundary validation and all failure paths are explicit and safe.
- Security, concurrency, numerical, and time semantics were considered.
- Tests would detect a realistic regression and are deterministic.
- Public documentation and examples match the implementation.
- Build-target dependencies, visibility, owners, schema compatibility, and
  artifact provenance are correct for the change.
- Cross-language behavior is authoritative or covered by conformance evidence;
  ABI ownership and failure rules are explicit.
- Formatting, lint, static/type checks, tests, and build checks pass.
- No secrets, debug statements, commented-out code, or accidental artifacts remain.
