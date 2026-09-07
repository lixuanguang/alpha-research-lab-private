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
| Dependency admission | [Dependency admission contract](dependency-admission.md) and the frozen `uv.lock` |
| Evidence | [B04 partial evidence](../governance/evidence/examples/b04-r2-partial/manifest.toml) |

This contract implements the blueprint's B04 language, sanitizer, warnings,
numerical, generated-code, API-stability, property/state-machine, coverage, and
mutation-baseline requirements. It refines the language guides under
[`docs/coding_standards`](../coding_standards/README.md); it does not repeat or
weaken them.

## Scope and delivery boundary

B04 makes current engineering standards executable for the repository's admitted
Python targets. It adds the `alpha-governance-engineering-standards` checker and
property/state-machine coverage. The checker binds exact tool
versions to the uv lock, validates warnings-as-errors configuration, rejects an
unowned or expired suppression, prevents generated source outside an admitted
root, enforces the Python standards contract, and blocks C, C++, or Rust
source until an owned native target and sanitizer profile are admitted.

The former B02/B03 Bazel and Nix paths are historical records. The active source
and test contract uses the pinned Python/uv environment and `make check`. The
completed pre-B01 toolchain refresh is retained in Git history (`ba121d4`, formerly
`docs/roadmap/pre-b01-toolchain-refresh.md`). Current pins and admission decisions
belong to the lock and [dependency-admission contract](dependency-admission.md).
B04 does not claim final B07 admission.

No economic, data, schema, research, model, strategy, risk, execution, runtime, or
deployment behavior is introduced. Source validation, retained secret scanning,
and installed wheel smoke are owned by B05's current check path.

The repository-internal checker separates Python source rules from policy parsing
and repository cross-checks. Import headings, source typing and documentation
have an independently testable boundary while retaining the existing command and lifecycle. Keep
unrelated contract parsing together until another admitted language or
generated-source root creates a similarly independent boundary; an early
abstraction must not let validation paths drift.

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
   sanitizer inputs in the repository lock and owning admission record;
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

Use cohesive classes for meaningful concepts, related behavior, state ownership,
or invariants. Module-level functions and ordinary test functions are permitted
without registration. Class design remains a semantic review responsibility;
the scanner does not require a class disposition for each function.

Ruff `D` uses the Google convention and `ANN401` rejects dynamically typed
annotations. `make lint` and `make typecheck`, pre-commit and hosted CI share
these controls. Source and inferred-typing diagnostics must pass directly.
Diagnostics cannot be admitted through a debt baseline or a reduced checking scope.
The function-exception register, its expiry and definition-fingerprint checks,
and the `PYC001` class-disposition rule were retired in cleanup step 1. There is
no source-rule waiver mechanism, including for inherited documentation contracts.

The scanner validates summaries and structured sections, including each public
parameter. It checks `Raises:` for explicit raises in a function's own body;
reviewers must also document relevant failures propagated by collaborators.
Private helpers and `test_` functions under `tests/` may use summary-only docs.
It inspects source-level type syntax, including quoted annotations and generic
bounds; mypy remains responsible for inferred types and signature correctness.

The required Ruff selection and global mypy flags are enforced by the repository
validator. Removing them, restricting their scope or adding configuration
overrides fails the engineering-standards check.

### Protected clarity checks

Cleanup preserves the following executable boundaries. No custom clarity rule
has been replaced on the assumption that a similarly named Ruff or mypy rule is
equivalent.

| Requirement | Enforcement and retained regression coverage |
| --- | --- |
| Complete function typing and strict inferred types | Configured strict mypy across `src`, `tests`, `tools/governance/src`, and `tools/typing/stubs`, including all four `disallow_any_*` settings; `test_python_typing.py` checks scope and failure propagation, and `test_engineering_standards.py` rejects configuration bypasses. |
| No explicit `Any` | Source scanner plus Ruff `ANN401` and mypy; `test_python_source_standards.py` covers aliases, qualified names, quoted annotations, type comments, generic bounds, nested occurrences, and ordinary text that must remain accepted. |
| Import headings and organization | Source scanner plus Ruff `I`; `test_python_source_standards.py` retains accepted and rejected grouping, spacing, future-import, relative-import, and `TYPE_CHECKING` cases. |
| Explanatory Google-style documentation | Source scanner plus Ruff `D`; `test_python_source_standards.py` retains summaries for modules, classes and private functions, public parameter descriptions, `Returns:`, `Yields:` and `Raises:`, and the narrower test/private summary-only contract. Semantic review checks the prose. |
| Every owned Python source remains checked | `test_python_standards.py` covers repository discovery and direct diagnostics without an exception file, including newly created source and owned stubs. Ordinary functions still receive all applicable clarity checks. |

The test paths above are under `tests/engineering/`. The checked scope and strict
configuration are unchanged; retiring function registration does not authorize
blanket exclusions or undocumented APIs.

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

B04 admits no generated source root. Existing SQL and Protobuf files under the
retired build fixture area were historical test fixtures rather than generated
production source. A future generated source root requires an owning generator target and a
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
`make check` is the required repository entry point; focused standards commands
remain optional during development.

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
artifact. Rollout adds the checker and property coverage to the existing root,
hook, hosted, and uv validation surfaces without implementing a separate scheduler.
Rollback removes the checker, policy, and B04 evidence together while preserving
the retained clarity rules and frozen lock.

Current monitoring is a nonzero checker/test exit with retained repository-local
evidence. There is no service, dashboard, page, alert route, on-call action,
production runbook, kill path, post-deploy window, or operator migration. The
runbook is: inspect the named finding, restore the last passing policy/lock/source
combination, rerun the complete check, and do not weaken or extend a suppression.

## Governance references

The [development workflow](../governance/workflow.md) owns daily evidence. B04
defines engineering standards only and grants no deployment, activation,
credential, market or capital authority.
