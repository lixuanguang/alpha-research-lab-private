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
do not require unrelated legacy code to be rewritten. Repository-wide automated
checks still apply to their complete configured scope. When a touched area cannot
meet a rule, use its owning policy's exception process where one exists; a prose
rationale alone does not waive a blocking check.

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

The machine-enforced B04 policy is the
[language and static quality standards contract](../architecture/engineering-standards.md).
Python is currently the only admitted implementation language. C/C++ and Rust
rules remain design requirements for future admitted targets, not evidence that a
native toolchain or target is installed.

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

Follow the [development workflow](../governance/workflow.md) for implementation,
validation and acceptance. Before editing, read the request, nearest repository
instructions, relevant language guide and owning capability contract. Inspect
affected code, tests, public interfaces, build targets, owners, reverse
dependencies, generated inputs, and working-tree changes. Resolve facts from the
repository and state assumptions that materially affect behavior.

Use the [development and release workflow](../governance/workflow.md) for the
requested operation and the [operations runbook](../governance/operations.md)
for a real deployment or activation. Prefer one logical change; record a split
plan when a change is too broad to review safely.

Preserve unrelated changes and dependency boundaries. Use owning generators for
generated files. Update behavior documentation, tests, compatibility, migration,
and rollback evidence with the affected contract. For a refactor, identify the
supported imports, signatures, CLI behavior, errors, serialized results and
numerical contracts before moving code; preserve them unless the change explicitly
includes a contract migration. Update callers, build ownership, packaging, imports
and CI selection together when modules move. Reverse service and caller changes
together if compatibility fails. Report unresolved conflicts that depend on
unavailable domain knowledge or authorization.

Before completion, review the diff for scope, secrets, debug/dead code, and
accidental artifacts. Run the narrowest affected targets through the root
interface and applicable formatting, lint, type/static checks. Broaden validation
for shared contracts, build/toolchain, serialization, persistence, concurrency,
numerics, or security changes. Changes to global static enforcement require the
complete configured static scope. Use the development workflow's complete lane
before merge; affected checks do not establish a full-lane pass. Verify deployable
provenance excludes undeclared host state and secrets. Report checks run, checks
unavailable, and outstanding gates; automated success does not replace domain
review or grant release or activation authority.

## Core design principles

- Code MUST satisfy valid-input contracts and fail explicitly on invalid states.
  Make units, time, ownership, mutability, and optionality explicit; do not discard
  errors, truncate values, weaken validation, or choose favorable fallbacks.
- Keep one authoritative implementation of each rule. Independent language
  implementations require shared versioned goldens and differential tests.
- Extract genuinely shared behavior; avoid abstractions for superficial similarity
  or hypothetical variants. Small repeated test setup is acceptable when clearer.
- Give modules one cohesive responsibility and consumers the smallest useful
  interface. Prefer composition; inheritance requires substitutable inputs,
  outputs, invariants, and failure behavior.
- Keep calculations pure where practical and isolate storage/network/CLI/UI side
  effects behind domain contracts. Avoid cycles, service locators, hidden globals,
  and unrelated re-export modules.
- Implement current requirements. Add dependencies, configuration, caches,
  concurrency, and optimization only for demonstrated needs; measure bottlenecks
  against a correctness baseline. Remove obsolete paths when support ends.
- Follow the [architecture dependency rules](../architecture/principles.md#dependency-direction).
  Production code cannot depend on notebooks or research-only approximations.
- Control clocks, seeds, input identity, and ordering for deterministic work.

## Repository targets, builds, and artifacts

A repository target owns dependency, visibility, platform, generated inputs,
testing, and artifact boundaries; directory proximity does not make an API
public. Follow the package boundaries and dependency direction and run the
pinned uv environment through `make check`. The former hermetic-build
contract is historical; it does not add an active build backend or validation
requirement. Generated source identifies its generator and inputs; keep generated
rewrites separate from unrelated semantic changes.

Each deployable has its own immutable source/target/toolchain/dependency/schema/
platform/build-mode identity. Build once and promote by digest under the
[artifact contract](../architecture/artifact-supply-chain.md) and
[operations runbook](../governance/operations.md).
Version environment configuration separately. Source access, data entitlements,
credentials, promotion, deployment, and capital permissions remain distinct;
activation requires independent authorization.

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
- A formatter, linter, type, coverage, or security suppression MUST end with
  `[owner=<governed_role>; rationale=<specific_reason>; expires=YYYY-MM-DD]`, use
  that exact field order, and expire no more than 180 days after validation. A
  global suppression is not a substitute for fixing or isolating a finding.
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
- Refactors MUST retain behavioral coverage, including repeated calls, failure
  recovery, malformed inputs, deterministic results, exact errors where contractual,
  and existing goldens. Preserve property-test cases and settings unless the
  contract change justifies an explicit revision. Do not replace behavioral tests
  with class-existence checks or bypass the entry point under test. If test
  organization changes, compare collection before and after and account for every
  removed or renamed case.
