# Engineering Standards and Static Quality Tooling

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | B04 |
| Parent package | B04 (no delivery slice) |
| Objective | Language standards and static quality tooling |
| Operating track | Solo bootstrap |
| Package status | Partial |
| Accountable owner role | Platform |
| Change risk | R2 shared build and quality policy |
| Applicable gates | QG01-QG06, QG09-QG14 |
| Machine-readable policy | [Engineering standards policy](engineering-standards.toml) |
| Provisional dependency record | [Engineering tool dependencies](engineering-tool-dependencies.toml) |
| Evidence | [B04 partial evidence](../governance/evidence/examples/b04-r2-partial/manifest.toml) |

This contract implements the blueprint's B04 language, sanitizer, warnings,
numerical, generated-code, API-stability, property/state-machine, coverage, and
mutation-baseline requirements. It refines the language guides under
[`docs/coding_standards`](../coding_standards/README.md); it does not repeat or
weaken them.

## Scope and delivery boundary

B04 makes current engineering standards executable for the repository's admitted
Python targets. It adds the `alpha-governance-engineering-standards` checker and a
sandboxed Bazel property/state-machine test target. The checker binds exact tool
versions to the uv lock, validates warnings-as-errors configuration, rejects an
unowned or expired suppression, prevents generated source outside an admitted
root, and blocks C, C++, or Rust source until an owned native target and sanitizer
profile are admitted.

B02 and B03 remain provisional dependencies. Their Bazel graph, exact Python
toolchain, clean-machine shell, sandbox, and rollback are preserved. The
[pre-B01 refresh](../roadmap/pre-b01-toolchain-refresh.md) remains historical
compatibility evidence; B04 does not repeat it or claim that existing tools have
undergone final B07 admission.

No economic, data, schema, research, model, strategy, risk, execution, runtime, or
deployment behavior is introduced. Fast affected-target selection and authoritative
merged-result policy remain B05-owned.

The initial repository-internal checker intentionally keeps contract parsing and
repository cross-checks in one policy module because they share one closed set of
B04 invariants and have one consumer lifecycle. This exceeds the preferred
400-line source-file guideline; split it only when another admitted language or
generated-source root creates an independently testable policy boundary, so an
early abstraction cannot let the two validation paths drift.

## Language admission and warnings policy

Python 3.12.14 is the only admitted language runtime. Ruff 0.16.5 owns formatting
and linting, mypy 2.3.1 runs strict type checking, Bandit 1.9.4 performs current
security static analysis, and pytest 9.1.1 treats warnings as errors. Findings are
blocking; a tool may not be globally silenced to make a change pass.

Rust and C/C++ remain dormant because the repository contains no justified native
source target. This is a fail-closed state, not a claim that native code needs no
sanitizer. Before native source enters a governed root, the owning change must:

1. justify the language and target under ADR 0002;
2. pin the compiler, standard library, linker, formatter, static analyzer, and
   sanitizer inputs in the B02 graph and B03 environment;
3. add a provisional B07-compatible dependency record;
4. run AddressSanitizer plus UndefinedBehaviorSanitizer for relevant C/C++ changes
   and a separate ThreadSanitizer build for shared-memory concurrency;
5. run Miri or an applicable sanitizer/fuzzer for unsafe or low-level Rust; and
6. retain sanitizer, conformance, numerical, failure, and rollback evidence.

Python does not claim a native memory sanitizer. A Python extension inherits the
owning native target's sanitizer requirements and must additionally satisfy the
binding lifetime, GIL, exception, and differential-test rules.

## Suppressions

Every `noqa`, `nosec`, `type: ignore`, coverage exclusion, formatter disable, or
equivalent suppression in an admitted source root must be line-scoped where the
tool allows it and end with metadata in this exact order:

```text
[owner=<governed_role>; rationale=<concrete reason>; expires=YYYY-MM-DD]
```

The owner must exist in the A03 ownership register, the rationale must contain at
least 12 characters, and expiry must be no more than 180 days from validation.
Expired, unknown-owner, missing-field, malformed, or overlong suppressions fail the
checker. Renewal is a reviewed change that re-establishes the need; expiry is not
an invitation to remove a safety check without fixing its cause.

## Numerical standards

There is no repository-wide floating-point epsilon. Each floating comparison
records an absolute tolerance, a relative tolerance, and a scale/algorithm
rationale at the owning contract or test. Exact currency and identifiers use
integer or decimal representations. `NaN` and infinity fail by default unless a
separately documented boundary contract defines and tests another outcome.

Numerical tests cover meaningful limiting cases, empty inputs, zero denominators,
overflow/underflow, signed zero, conditioning, equivalent representations, and
perturbations as applicable. Reassociation, contraction, flush-to-zero, SIMD, and
fast-math are semantic changes requiring separate numerical and compatibility
review; performance evidence cannot waive them.

## Generated code

B04 admits no generated source root. Existing SQL and Protobuf files under
`tests/build/fixtures` remain B02 test fixtures rather than generated production
source. A future generated source root requires an owning generator target and a
policy update. Each generated file then identifies:

- the generator and exact generator version;
- every declared input through an input SHA-256 identity;
- the deterministic generation command and owning build target; and
- the reproducibility, diff-separation, compatibility, and rollback procedure.

Manual edits to generated source are prohibited. Generator output must reproduce
from declared inputs in the sandbox, and a generated rewrite cannot hide an
unrelated semantic change.

## API stability

`alpha_research` remains a compatibility surface for existing callers. A breaking
change needs a versioned migration, deprecation window, compatibility test, and
retained rollback. `alpha_research_governance` is repository-internal, but a change
must still update all graph-selected consumers in the same change and retain the
previous compatible revision as rollback. Importability alone does not create a
new supported API.

Schema, serialized, ABI, and FFI compatibility remain owned by their later domain
packages. B04 defines the review rule but creates no schema or language boundary.

## Property, state-machine, coverage, and mutation baselines

Hypothesis 6.167.1 is pinned for Python property and rule-based state-machine tests.
B04 tests use 50 deterministic examples, no persistent example database, and a
bounded 12-step lifecycle sequence. Failing examples are retained in normal test
output/evidence; future domain packages own domain-specific regression fixtures.

The 2026-09-02 completed B04 branch-coverage baseline is 81 percent across the
`alpha_research` and `alpha_research_governance` packages. Coverage is a discovery
baseline, not a score to satisfy with weak tests. B04 also records twelve of twelve
representative policy mutations rejected. The mutations cover status and risk
downgrade, successor drift, global epsilon, non-finite continuation, weak property
limits, incomplete mutation evidence, false native admission, missing C/C++
sanitizers, and missing findings. A later general mutation engine requires its own
provisional dependency record and must not replace semantic review.

## Interfaces and deterministic failure behavior

Run the canonical repository-local check with:

```sh
uv run --frozen alpha-governance-engineering-standards
```

The command exits `0` only when the policy, exact locks, dependency record, current
source, suppressions, language admission, configuration, and synthetic evidence
agree. It exits `1` for invalid repository state and `2` for invalid command use.
`make engineering-standards-check` is the root compatibility entry point. The B04
Bazel test is part of the existing sandboxed build-platform suite.

Unknown fields, missing roots, malformed TOML, invalid dates, stale tool versions,
unlocked dependencies, absent warnings-as-errors, generated source, dormant native
source, unsafe suppressions, evidence drift, and digest mismatch all fail closed.

## A04 classification and quality gates

B04 is R2 because it changes a shared build and quality contract with a compatibility
window. It has no capital, production-serving, privileged-control, economic, model,
or trading effect. It is computationally material because the policy and property
tests run across shared source/build interfaces. QG07-QG08 and QG15 are not
applicable: no cost, capacity, risk control, deployment, promotion, or activation
surface exists.

| Gate | Repository-local evidence |
| --- | --- |
| QG01 | Exact format/lint/type/security tools, warnings-as-errors, suppression policy, and generated-source separation |
| QG02 | Exact uv/Bazel inputs, sandboxed property target, and provisional dependency digest |
| QG03 | Success, boundary, invalid-input, malformed-policy, CLI, failure, and lifecycle tests |
| QG04 | Property/state-machine tests, numerical policy, coverage statement, and twelve-of-twelve mutation baseline |
| QG05-QG06 | Explicit no-schema/data/PIT/research/model impact and preserved governance lineage |
| QG09 | Existing package, root, hook, hosted, uv, and Bazel interfaces remain compatible |
| QG10 | Ten thousand suppression checks complete within the one-second local budget; no target-host latency claim |
| QG11 | Missing, unknown, expired, unowned, unlocked, or unadmitted state stops validation |
| QG12 | Bandit, bounded suppressions, immutable dependency digest, and B07 admission finding |
| QG13 | Standards, interfaces, baselines, migration, rollback, signals, findings, and successor are documented |
| QG14 | A failed checker is the repository-local signal; no deployed monitor or SLO is claimed |

Institutional acceptance requires a Platform Code Owner and an independent domain,
data, or model reviewer. Those roles are unavailable on the solo-bootstrap track.

## Dependency, migration, rollout, rollback, monitoring, and runbook

Hypothesis is test-only and brings sortedcontainers 2.4.0 as a pure-Python
transitive dependency. Its published platform wheels include upstream native
extension artifacts; B04 does not build or admit a repository-native target. The
provisional record binds its PyPI source digest, MPL-2.0 license, supported
platforms, native-artifact fact, transitive dependency, maintenance review, and
rollback. B07 retains qualified binary/source provenance, license, vulnerability,
exploitability, and final admission authority.

The change is additive: it creates no data/state/schema migration and no deployable
artifact. Rollout adds the checker and property target to the existing root, hook,
hosted, uv, and Bazel validation surfaces without implementing B05 affected-target
or merged-result policy. Rollback removes the property target, dependency pins,
checker, policy, and B04 evidence together while preserving the prior B03 graph
and frozen-uv path.

Current monitoring is a nonzero checker/test exit with retained repository-local
evidence. There is no service, dashboard, page, alert route, on-call action,
production runbook, kill path, post-deploy window, or operator migration. The
runbook is: inspect the named finding, restore the last passing policy/lock/source
combination, rerun the complete check, and do not weaken or extend a suppression.

## Open findings

| Finding | Owner | Unavailable evidence | Closure condition |
| --- | --- | --- | --- |
| B04-F01 | Domain Architecture | Independent domain review and commit-bound Platform Code Owner approval | Named reviewers resolve findings and approve the exact standards, checker, dependency record, baselines, and evidence at the reviewed commit |
| B04-F02 | Platform/CI | Protected merged-result Linux execution and retained representative-defect, property/state-machine, coverage, and mutation evidence | Protected CI runs the exact reviewed merged result on x86_64 Linux and retains the passing checks plus all twelve blocking mutations |
| B04-F03 | Security | Qualified Hypothesis/sortedcontainers source, license, vulnerability, exploitability, maintenance, and transitive admission | B07 admits or replaces both dependencies without weakening determinism, property/state-machine coverage, Bazel execution, or rollback |

These findings are neither waivers nor approvals. B04 remains `partial` until all
three close.

## Explicit non-goals and successor

B04 does not:

- admit a C, C++, or Rust target or install its formatter, compiler, analyzer,
  sanitizer, Miri, or fuzzer;
- implement a domain numeric type, tolerance, state machine, model, schema, or
  generated client;
- implement B05 affected/reverse-dependency selection, merged-result authority,
  flake policy, secret scanning, schema compatibility, or evidence events;
- implement B06 remote cache/execution, B07 final dependency admission, or B08
  SBOM, provenance, signing, publication, or consumer verification; or
- deploy, activate, access an external market, create credentials, expose capital,
  or expand a venue, account, instrument, limit, or risk envelope.

The next selector is `B05`.
