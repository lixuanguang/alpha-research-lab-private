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
root, enforces the staged Python standards contract, and blocks C, C++, or Rust
source until an owned native target and sanitizer profile are admitted.

B02 and B03 remain provisional dependencies. Their Bazel graph, exact Python
toolchain, clean-machine shell, sandbox, and rollback are preserved. The completed
pre-B01 toolchain refresh is retained in Git history (`ba121d4`, formerly
`docs/roadmap/pre-b01-toolchain-refresh.md`). Current pins and admission decisions
belong to the lock and [dependency-admission contract](dependency-admission.md).
B04 does not repeat that refresh or claim final B07 admission.

No economic, data, schema, research, model, strategy, risk, execution, runtime, or
deployment behavior is introduced. Fast affected-target selection and authoritative
merged-result policy remain B05-owned.

The initial repository-internal checker kept contract parsing and repository
cross-checks in one policy module because they shared one closed set of B04
invariants and one consumer lifecycle. The Python standards migration introduces
an independently testable Python-standard boundary for import headings, source
typing, documentation, and class dispositions. Those checks may use a focused
component while retaining the existing command and lifecycle. Keep unrelated
contract parsing together until another admitted language or generated-source
root creates a similarly independent boundary; an early abstraction must not let
validation paths drift.

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

## Python standards enforcement contract

The `alpha-governance-engineering-standards` command enforces the following
Python rules alongside the configured Ruff and mypy checks:

- Every nonempty import category has its exact comment heading and blank-line
  separation. `__future__` imports stay in their own group immediately after the
  module docstring. `alpha_research` and `alpha_research_governance` are both
  first-party; relative and `TYPE_CHECKING` imports follow the same rules.
- Owned source and tests contain no explicit `Any`, including aliases, qualified
  references, container members, type aliases, and quoted annotations. Strict
  mypy is required across `src`, `tests`, governance tooling and owned native
  stubs. Explicit, unfollowed-import, decorated-signature and expression-level
  dynamic types are prohibited throughout that scope. Library and framework
  boundaries must provide a precise consumed contract and validate raw results.
- Every module, class, and named function, including private helpers, has a
  Google-style summary. Public APIs include every applicable `Args:`,
  `Returns:`/`Yields:`, and `Raises:` section. Reviewers check that the prose is
  meaningful; metadata checks cannot prove a prose justification.
- High-level domain, policy, validation, loading, and orchestration operations
  prefer cohesive classes. Low-level, framework, and compatibility functions
  require an explicit rationale.

Ruff `D` uses the Google convention and `ANN401` rejects dynamically typed
annotations. `make lint` and `make typecheck`, pre-commit and hosted CI share
these controls. The completed migration's source and inferred-typing inventories
have been retired; diagnostics cannot be admitted through a baseline.

Exact exceptions are separate in
[`docs/architecture/python-standards-exceptions.toml`](python-standards-exceptions.toml).
They are limited to low-level, framework, or compatibility functions and
inherited-doc contracts. Each exception records an owner, rationale, expiry, and
source fingerprint. Expired or unknown-owner entries, unsupported categories,
fingerprint mismatches, and stale exceptions fail the command. Exceptions cannot
waive the explicit-`Any`, import-heading, or syntax rules. The metadata check
cannot establish whether a rationale is substantively justified; that remains a
review responsibility.

Exception records use the exact fields `path`, `symbol`, `rule`, `detail`, `kind`,
`owner_role`, `rationale`, `expires`, and `source_sha256`. Use a native TOML date
for `expires`, with at most 180 days remaining at validation time, and at least
12 rationale characters after trimming surrounding whitespace. The fingerprint
is SHA-256 of the definition's `ast.dump(node, include_attributes=False)` UTF-8 bytes under the
pinned Python interpreter. Whitespace and line relocation do not change it;
definition changes do. Duplicate qualified definitions cannot receive an
ambiguous exception. `PYC001` permits `low_level`, `framework`, or `compatibility`;
`PYD001`/`PYD002` permit only `inherited_contract`. Each record discharges exactly
one finding; duplicate, moved or multiplied findings are rejected.

The scanner validates summaries and structured sections, including each public
parameter. It checks `Raises:` for explicit raises in a function's own body;
reviewers must also document relevant failures propagated by collaborators.
Private helpers and `test_` functions under `tests/` may use summary-only docs.
It inspects source-level type syntax, including quoted annotations and generic
bounds; mypy remains responsible for inferred types and signature correctness.

The final Ruff selection and global mypy flags are enforced by the repository
validator. Removing them, restricting their scope or adding configuration
overrides fails the engineering-standards check.

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

## Classification and evidence

B04 is R2 because it changes a shared build and quality contract with a
compatibility-window reversal. Gate definitions live in the
[quality-gate catalog](operations.md#quality-gate-catalog); exact state and finding
closure conditions live in
[engineering-standards.toml](engineering-standards.toml). Current state and finding
IDs are rendered in the [program status](../governance/program-status.md).

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

## Governance references

The [development workflow](../governance/workflow.md) owns daily evidence. B04
defines engineering standards only and grants no deployment, activation,
credential, market or capital authority.
