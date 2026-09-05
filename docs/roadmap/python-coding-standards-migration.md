# Python coding standards audit and migration plan

Audit date: 2026-09-05. Baseline revision:
`d3a40ca98d71208426c8501d8d4a1aaaa049768d`.
Status: steps 1–2 implemented on 2026-09-05; steps 3–7 remain planned. The findings
below describe the original audited revision, before step-1 enforcement.

The requested target is segregated, commented import groups; stringent typing
without `Any`; useful Google-style docstrings; and a preference for classes over
standalone functions, with small low-level operations remaining functions.
The last requirement reflects the user's clarification.

The main work is strengthening enforcement and reorganizing governance workflows.
Existing import sorting and signature annotations are already consistent. Public
source APIs generally have summary docstrings, and the domain packages already
contain useful classes. A wholesale rewrite would obscure those strengths.

## Findings

These priorities describe standards and maintainability gaps against the requested
target, not production incidents. Confidence is high for the measured gaps;
proposed class boundaries remain design recommendations. These baseline findings
define the completion criteria for the migration.

### P2 — The current policy and checks permit the requested violations

The [Python guide, line 122](../coding_standards/python.md#types-and-data-modeling)
permits boundary `Any`; its [object-design rule, line 157](../coding_standards/python.md#classes-and-object-design)
prefers functions or modules for stateless behavior. Its documentation rules do
not require the Google convention or import category comments.
[Ruff configuration, line 52](../../pyproject.toml#L52) selects no documentation
or annotation rules. [Mypy configuration, line 55](../../pyproject.toml#L55)
enables strict mode, which does not enable all of its `Any` restrictions.
The [source scanner, line 658](../../tools/governance/src/alpha_research_governance/engineering_standards/policy.py#L658)
checks suppression metadata, generated source and dormant languages, without
checking the four requested standards.

Consequently a change can pass current CI while adding the requested violations.
Update the policy and executable checks together. This is partly a new standards
migration, rather than solely a failure to follow the existing written policy.
Risk dimension: reliability and maintainability; invariant: CI must enforce the
standard it claims to check.

### P2 — Two test modules explicitly erase types with Any

There are 12 AST references to `Any`, excluding imports: ten in
[financial-unit tests](../../tests/unit/test_financial_units.py#L64), and two in
[developer-environment checks](../../tests/build/developer_environment_test.py#L48).
The `dynamic(value: Any) -> Any` helper removes checking for every consumer;
`fixture() -> Any` propagates an unchecked JSON shape through assertions.
[An operation parameter, line 242](../../tests/unit/test_financial_units.py#L242)
can be typed as `Callable[[], object]`. Invalid-value parameters can start as
`object`. [Nested lock access, line 134](../../tests/build/developer_environment_test.py#L134)
needs validated mapping shapes before indexing and calling `.get()`.

Preserve the purpose of deliberately invalid-input tests while removing their
general escape hatch. Use typed fixture records, explicit callable contracts,
and runtime narrowing. Do not replace `Any` with `cast`, `Never`, ellipsis
callables or generic `object` containers that merely move the loss of checking.
Risk dimension: test reliability; invariant: tests must retain meaningful static
contracts while still exercising invalid runtime input.

### P2 — Strict mypy passing does not establish freedom from implicit Any

No explicit `Any` appears in tracked runtime or governance Python source.
However, [the calendar adapter, line 11](../../src/alpha_research/venue_calendar/adapter.py#L11)
has three `import-untyped` suppressions, and
[the QuantLib adapter, line 15](../../src/alpha_research/financial_units/conventions.py#L15)
has one. Runtime checks and the calendar protocol already contain some of this
uncertainty; these suppressions are intentional under the current policy.
Pydantic inheritance, validation callbacks, JSON/TOML parsing and dynamic
attribute access add further inferred dynamic types.

An experiment enabling `disallow_any_explicit`, `disallow_any_unimported` and
`disallow_any_decorated` reports **173 diagnostics in 27 files**. Some diagnostics
called `explicit-any` occur on inherited Pydantic classes, despite no literal
`Any` in their source. Separately, `disallow_any_expr` reports **350 diagnostics
in 33 runtime/governance files**. These counts overlap and are not counts of
independent defects or evidence of incorrect numerical results.

Introduce accurate boundary contracts and evaluate the pinned Pydantic mypy
plugin before enabling every flag globally. Owned logic should receive validated
types; library-facing uncertainty must be identified and retired deliberately.
Risk dimension: data integrity and maintainability; invariant: unchecked library
or parsed values must not silently define owned application contracts.

### P2 — Documentation is mostly summaries, without structured contracts

Only one of the 1,245 class/function/method definitions has a recognized Google
section: [OperatingRules.require_local_completion, line 79](../../tools/governance/src/alpha_research_governance/operating_model.py#L79)
has `Raises:`. None has an `Args:` or `Returns:` section. This is a structural
measurement, not a claim that every one-line docstring is inadequate.

For example, [ExchangeCalendarsAdapter.build_snapshot, line 238](../../src/alpha_research/venue_calendar/adapter.py#L238)
accepts a date range, source version and several override collections, but its
summary does not document their parameter contracts or failure conditions.
[QuantLibConventions.year_fraction, line 79](../../src/alpha_research/financial_units/conventions.py#L79)
already explains numerical tolerances well; it needs structured arguments,
results and exceptions while retaining that explanation.

There are also 250 undocumented module-level functions and 25 undocumented
classes in runtime/governance source, predominantly private helpers and models.
Tests have 409 undocumented module-level functions. Add concise summaries for
simple helpers/tests and full Google sections where semantics warrant them.
Risk dimension: API reliability; invariant: callers and reviewers can determine
units, date coverage, side effects, validation and errors without reading bodies.

### P2 — High-level governance behavior has weak ownership boundaries

Runtime/governance source contains 380 module-level functions. The count alone
does not make them violations: many are parsers, predicates or entry points.
The strongest candidates have shared dependencies and multi-step workflows:

- [The control-map loader, line 582](../../tools/governance/src/alpha_research_governance/security_controls/registry.py#L582)
  spans 394 lines, combining parsing, policy checks, references and evidence.
- [The program registry](../../tools/governance/src/alpha_research_governance/program_governance/registry.py#L884)
  is 1,231 lines with 30 module-level functions, combining roadmap/schema
  parsing, ownership, dependency graphs and observations.
- [Bundle verification, line 613](../../tools/governance/src/alpha_research_governance/artifact_supply_chain/bundle.py#L613)
  spans 250 lines of file, digest, provenance and signature checks.
- [The affected CI runner, line 381](../../tools/governance/src/alpha_research_governance/ci_policy/runner.py#L381)
  and [remote runner, line 68](../../tools/governance/src/alpha_research_governance/remote_execution/runner.py#L68)
  repeatedly pass repository, policy, environment and execution context.

Move workflows behind cohesive services with explicit dependencies and small
methods. Keep validation findings local to each invocation so repeated calls do
not accumulate stale state. A giant class containing the same long methods
would not resolve the issue. Risk dimension: reliability and maintainability;
invariant: workflow dependencies and state have one clear owner.

### P3 — Every import-bearing file lacks the requested category comments

All **123 tracked files with module-level imports** lack the requested headings.
Examples are [the calendar adapter](../../src/alpha_research/venue_calendar/adapter.py#L5)
and [CI selection](../../tools/governance/src/alpha_research_governance/ci_policy/selection.py#L5).
Existing Ruff import sorting passes, and there are no wildcard imports. The gap
is the heading requirement, rather than wholesale failure to segregate imports.
The proposed heading configuration produces 124 import-block diagnostics across
these 123 files, because one file has more than one checked block. Add headings
through the pinned formatter/linter configuration to avoid recurring manual work.

## Baseline and scope

The inventory covers all 125 Git-tracked `.py` files: 30,423 physical lines.
There are no tracked `.pyi` files. Generated/build outputs, dependencies and
untracked duplicates are excluded. During the audit, three unrelated untracked
` 2` copies appeared; they were preserved. Initial directory-wide tools saw 126
Python files, so the reported checks were rerun on the explicit tracked list.

| Measure | Runtime `src` | Governance tooling | Tests |
| --- | ---: | ---: | ---: |
| Files | 30 | 64 | 31 |
| Files with imports / requested headings | 29 / 0 | 63 / 0 | 31 / 0 |
| Module-level functions | 32 | 348 | 426 |
| Module-level functions with docstrings | 8 | 122 | 17 |
| Classes / classes with docstrings | 72 / 72 | 117 / 92 | 5 / 2 |
| Methods / methods with docstrings | 119 / 91 | 73 / 60 | 8 / 0 |
| Nested functions / with docstrings | 2 / 0 | 6 / 0 | 37 / 0 |
| Explicit `Any` references, excluding imports | 0 | 0 | 12 |
| `cast(...)` calls, inventory only | 1 | 100 | 17 |

All 125 modules have docstrings. All 1,051 named function/method definitions have
parameter and return annotations, excluding implicit `self`/`cls` parameters;
this does not measure local-variable or class-attribute annotation completeness.
The 118 casts are review candidates, not automatically unsafe: several follow
explicit validation. Docstring coverage was counted with Python 3.12 AST;
Google sections were detected by section-header matching and representative
manual inspection. Privacy/inheritance exceptions require manual judgment.

Review focus: Python standards and architecture. Market/reference-data guidance
was used for calendar and symbology compatibility concerns; those runtime
contracts warrant tier-2 regression evidence when refactored. This report is a
non-behavioral planning artifact, not a full numerical, security or trading audit.

## Target standard and enforcement

### Imports

Use blank lines between nonempty categories and the exact requested comments.
Keep `__future__` imports immediately after the module docstring in their own
group. Treat both owned Python packages as project imports. Specify the same
behavior for relative and `TYPE_CHECKING` blocks; do not add empty categories.

Active settings in `pyproject.toml` after step 2, using the pinned Ruff 0.16.5:

```toml
[tool.ruff.lint.isort]
known-first-party = ["alpha_research", "alpha_research_governance"]

[tool.ruff.lint.isort.import-heading]
standard-library = "standard library imports"
third-party = "third party library imports"
first-party = "project library imports"
local-folder = "project library imports"
```

The headings survived an import-fix/format/recheck cycle in a temporary sample.
The first sample needed the usual blank line after its module docstring; after
formatting, both checks passed. This experiment changed no repository source.

### Types

- Prohibit explicit `Any` throughout owned code and tests, including aliases,
  qualified references and container members. Add `ANN401` as a fast signal,
  plus an AST/import-aware prohibition to catch uses beyond function signatures.
- Keep current strict mypy across `src`, `tests` and governance tooling. Plain
  `mypy` uses configured packages; the root/pre-commit command explicitly includes
  tests. Preserve that full scope when changing invocation or configuration.
- Parse raw values as `object`, narrow them immediately and construct precise
  records. Use `TypedDict` for validated static shapes, existing immutable models
  for runtime schemas, `Protocol` for behavior and `Callable` for callbacks.
  Remember that JSON and TOML have different value domains, including TOML dates.
- Enable the additional mypy flags in audited slices. Investigate Pydantic's
  existing `pydantic.mypy` plugin with `init_typed` and `init_forbid_extra`, and
  explicit `ValidationInfo` context types. These are candidate remedies requiring
  verification against custom constructors and validation behavior.
- Provide narrow, accurate stubs or adapters for the consumed native-library
  surface. Include any new stub package in mypy paths, build/package inputs and
  dependency metadata. Prove stub/runtime agreement with conformance tests.
- Keep `disallow_any_expr` as a measured, shrinking diagnostic inventory until
  owned scopes pass. No blanket `ignore_errors`, exclusion of tests, or casts
  that pretend invalid data is valid. Any residual framework limitation must be
  explicitly unresolved, rather than described as complete compliance.

For negative tests, preserve the exact entry point being tested. An `object`
input can use a raw validation API when that is the intended contract. A test of
a typed method's runtime rejection may need a narrowly documented expected
`arg-type` violation using the existing suppression metadata policy; do not
broaden the production signature or route the test around that method.

### Docstrings

Add `D` and `ANN401` to the existing Ruff selection, with
`[tool.ruff.lint.pydocstyle] convention = "google"`, as the affected inventory
is resolved. Require summaries for classes, functions and methods, including
nontrivial private helpers. Use `Args:`, `Returns:`/`Yields:` and `Raises:` when
applicable; class docs describe invariants and meaningful attributes. Explain
units, time semantics, state changes and I/O where relevant. Simple tests and
tiny obvious helpers can have a useful one-line Google-compatible summary.

Ruff's installed `D417` only checks argument completeness when an argument
section already exists. It does not force a missing `Args:` section into a
summary-only docstring, and public-doc rules omit many private helpers. Extend
the existing standards checker for required presence/sections on owned APIs;
review semantic accuracy manually. Use scoped exceptions for inherited protocol
contracts and trivial framework methods rather than dummy prose or empty sections.

### Classes

Prefer a cohesive class for domain operations, policy evaluation, loading,
validation and orchestration. Give it the repository, policy or collaborator it
actually uses; keep constructors free of fallible I/O. Favor composition and
typed dependencies. Avoid utility classes that only group unrelated static methods.

Retain standalone functions for small parsers, arithmetic kernels, predicates,
required CLI/framework callbacks and temporary compatibility wrappers. Record a
disposition for each existing function: owning class, low-level rationale, or
framework/compatibility requirement. Group tests into contract-oriented pytest
classes where useful, with no custom constructor; keep required fixture and
entry-point functions. Compare collection before/after and update node-ID users.
Do not enforce this preference using an arbitrary class-to-function ratio.

Keep `SymbologyCatalog`, `ExchangeCalendarsAdapter`, `QuantLibConventions` and
existing immutable value models; improve their contracts without replacing them
merely to increase class counts.

## Migration sequence

The founder owns implementation under the current operating policy. These are
engineering slices, not additional organizational approval stages. Prefer roughly
400 changed non-generated lines per review, splitting by package or responsibility.
Keep each slice passing; this plan does not activate unfinished rules globally.

| Step | Work and dependencies | Completion evidence |
| --- | --- | --- |
| 1. Establish the executable contract — implemented | Updated the Python guide; extended the existing checker, pre-commit hook and Bazel inputs/tests. Froze 3,079 original-revision obligations. | 55 focused tests cover new/moved/multiplied debt, missing Google sections, aliased `Any`, imports and invalid exception metadata. See the step-1 validation record below. |
| 2. Normalize imports — implemented | Activated the heading settings and applied import-only fixes in runtime, tooling and test batches. Retired all 243 import obligations. | Ruff import/format checks pass; complete AST comparison confirms unchanged import targets, aliases, relative levels and execution order. See the step-2 validation record below. |
| 3. Remove explicit Any in tests | Replace the two modules' escape hatches with fixture types, callable types and narrowing. Document their helpers at the same time. Depends on step 1. | Zero source-level `Any`; strict mypy and focused financial-unit/developer-environment tests pass; deliberately invalid inputs still reach the intended rejection path. |
| 4. Strengthen library and parsing boundaries | Pilot Pydantic typing on a small governance model, then audit shared bases, JSON/TOML readers and native adapters. Depends on step 3 for negative-test compatibility. | Enforced mypy scopes pass additional flags; every remaining diagnostic has a concrete cause and retirement task. Stub conformance, validation and existing native goldens pass. |
| 5. Document existing contracts | Start with exported domain APIs, shared model validation and high-level governance operations; then private helpers, test classes and fixtures. Depends on step 1; combine docs for moved functions with step 6. | Required Google sections are checked; public contracts describe actual units/errors/side effects; residual exceptions are exact and justified. |
| 6. Refactor workflows into classes | Pilot change-risk classification, then loaders and CI services using the queue below. Depends on steps 2–4 for the owning package. | Existing callers and CLI behavior remain compatible; methods have typed dependencies and docs; behavior and repeated-call tests pass. |
| 7. Finish adoption and make checks unconditional | Migrate callers, audit remaining functions, reduce temporary wrappers, and eliminate the standards debt inventory. Depends on steps 3–6. | All completion criteria below pass, root/local/Bazel/hosted checks agree, and any supported compatibility facade is explicitly documented. |

For gradual enforcement, use exact rule plus module/qualified-symbol identities,
not a global numerical allowance or blanket module ignore. Reject additions and
expired exceptions; prune resolved entries. Function relocation must preserve its
tracked obligation. Keep source-level `Any` prohibition distinct from mypy's
inherited-library diagnostics. Follow existing owner/rationale/expiry policy for
actual suppressions; unresolved migration tasks are not permanent exemptions.

### Step 1 implementation

The existing `make engineering-standards-check` command now invokes a class-based
source scanner and exact debt reconciler. It scans `.py` and `.pyi` files under
the existing source roots, including files not yet added to Git, without relying
on Git or network access at check time. Both new checker modules and their tests
satisfy the new rules without migration allowances.

The [debt inventory](../architecture/python-standards-debt.json) was generated
only from the baseline revision recorded above, using the completed scanner.
At step-1 completion it contained 3,079 obligations across 123 files, attributed
to the `platform` owner role and the relevant migration step:

| Rule | Obligation | Count | Retirement step |
| --- | --- | ---: | ---: |
| PYI001 | Import grouping, headings and spacing | 243 | 2 |
| PYT001 | Explicit `Any`, including two import bindings | 14 | 3 |
| PYD001 | Missing definition summary | 781 | 5 |
| PYD002 | Missing Google section or individual parameter description | 1,235 | 5 |
| PYC001 | Module-level function requiring a class or reviewed disposition | 806 | 6 |

These are scanner obligations, not independent bugs. A definition can carry
several obligations; module-level function counts include pytest/framework
functions that may receive a justified exception in step 6. The source-level
typing inventory does not claim to remove inferred third-party `Any`.

The JSON checksum is pinned in the checker. New findings, additional occurrences
of an existing finding, moved symbols, and unpruned resolved entries fail.
Normal migration removes the resolved entries and updates the checksum in the
same reviewed change; it must not regenerate allowances from the current tree.
The separate [exception policy](../architecture/python-standards-exceptions.toml)
starts empty and validates exact source identity, owner, rationale, category and
expiry. Imports, explicit `Any`, and syntax errors cannot receive exceptions.

The scanner checks syntax and structure. Review still establishes documentation
accuracy and whether a proposed low-level/framework/inherited-contract exception
is warranted. It does not infer propagated exceptions from arbitrary callees or
replace mypy's analysis of library boundaries. Existing strict mypy and Ruff
import sorting remain active; mass import, typing and docstring edits belong to
the later migration steps.

### Step 2 implementation

The root Ruff configuration now supplies the agreed headings for standard-library,
third-party, absolute project and relative project imports, with both owned
packages explicitly classified as first-party. Ruff inserted 243 heading comments
in 123 files: 29 runtime modules, 63 governance modules and 31 test modules. The
four checker/test modules introduced in step 1 already met the import standard.
The fixes changed no import targets, aliases, relative levels or execution order;
complete Python ASTs were identical before and after normalization.

All 243 `PYI001` entries were removed from the existing debt inventory, and its
checksum pin was updated in the same change. No allowances were regenerated or
added. The remaining 2,836 obligations across 87 files are unchanged: 14 explicit
typing, 781 definition-summary, 1,235 structured-documentation and 806 function
disposition obligations. Rule attribution and the original baseline revision
remain available for the later migration steps.

### Class migration queue

Paths below are relative to `tools/governance/src/alpha_research_governance` unless
prefixed with `src/`. Names are proposed responsibilities, not mandatory new files.

| Order / current area | Proposed responsibility | Compatibility and behavior to preserve |
| --- | --- | --- |
| 1. `change_risk/classification.py`, then `approvals.py` | `ChangeRiskClassifier(policy)` and a separate approval evaluator; small classification pilot first. | Highest-dimension rule, downgrade rejection, gate ordering, founder/team rules; `classify_change` delegates temporarily. |
| 2. `program_governance/registry.py`, `status.py` | `ProgramRepository` for loading with explicit root/ownership context; distinct roadmap parsing, observation reading and status rendering responsibilities. | Schema versions 1–4, dependency purposes/cycles, finding mapping, deterministic status text and existing exported loaders. |
| 3. `security_controls/registry.py`, `inventory/registry.py` | Separate `SecurityControlMapLoader` and `InventoryLoader`; pure field/ID parsing stays small. | Error categories, complete references, source identity, ownership and deterministic findings. |
| 4. `repository_topology/registry.py`, `engineering_standards/policy.py`, `dependency_admission/policy.py`, `ownership_governance.py`, `architecture_governance.py` | Domain-specific loaders/validators with explicit repository context. Share only proven identical parsing primitives. | Exact accepted schema and policy values, expiry/version checks, local link safety, exception translation and root commands. |
| 5. `evidence/manifest.py`, `mr.py`, `package.py`, `artifact_supply_chain/bundle.py` | Separate evidence validation, bundle creation and bundle verification services. | Digest/path validation, operation and revision binding, malformed-input rejection, file write boundaries and signature behavior. |
| 6. `ci_policy/runner.py`, `selection.py`, `remote_execution/runner.py` | `CIRunner` and `RemoteExecutionRunner`; use a typed command-execution collaborator where injection is useful. | Fast/full selection, exact argv/environment, trust/secret checks, exit codes, event contents/order and safe fallback. |
| 7. Remaining CLI modules, policies and `src/alpha_research/financial_units/conventions.py` | Thin CLI callbacks delegating to services; evaluate `SettlementConventions(calendar)` for the related high-level settlement operations. | Console scripts, `python -m` entry points and facade imports; settlement date/coverage errors; keep arithmetic and conversion kernels small. |
| 8. `tests/` and residual source helpers | Contract-oriented test classes and a completed function-disposition inventory. | Pytest/Bazel collection, parametrization, fixtures, markers, external selectors and meaningful failures. |

## Validation, compatibility and rollback

No new runtime dependency is necessary for the initial import/docstring checks:
use the installed Ruff/mypy and existing governance tooling. A new type checker
is not part of this plan. Keep any new checking logic inside the owned tooling
target, and update policy models/TOML validators together if their schema changes.

For each implementation slice run the affected root commands:
`make lint format-check typecheck`, plus `make engineering-standards-check` when
its policy or implementation changes. Use the owning Bazel tests and reverse
dependencies. Relevant current targets include
`//tests/build:developer_environment_test`; resolve the exact remaining names
from the checked-in BUILD files before invoking them. Finish the migration with
the authoritative `make ci-full` lane in the pinned environment.

Class refactoring requires behavioral comparisons, not tests asserting that a
class exists. Retain existing tests and add only evidence needed for the changed
boundary: repeat calls on one instance, deterministic findings, identical CLI
results, injected process failures and unchanged serialized output. For calendar,
identity and financial-unit changes retain existing golden, malformed-input,
immutability, timezone, settlement-coverage and rounding checks. Do not rewrite
goldens simply to make a structural migration pass.

Preserve the supported exports in `src/alpha_research` compatibility facades and
both packages' `__all__`/console-script contracts. If modules split, update Bazel
ownership/dependencies, packaging, CI selection and imports together. Keep a
wrapper only while a supported caller needs it, or document it as an intentional
public compatibility boundary. Change no evidence schema as an incidental result
of moving functions into classes.

Rollback is per slice: retain the old public entry point while the implementation
moves, and revert the service/caller change together if behavior differs. Revert
only the newly introduced failing check/configuration when needed; preserve the
existing strict/lint controls and debt record. Import/docstring-only changes can
be reverted independently. No persisted-data migration is intended.

## Completion criteria

- Every nonempty import category has the agreed heading and spacing; Ruff passes.
- Owned source/tests contain no explicit `Any`; signatures remain fully typed.
  Additional mypy checks pass in the agreed complete scope. Any remaining inferred
  dynamic boundary is disclosed as unfinished work, not a claim of full safety.
- Public contracts and nontrivial private code have useful Google-style docs;
  automated presence checks and manual semantic review both pass.
- Every high-level standalone operation has moved to a cohesive class or has a
  documented low-level/framework/compatibility reason to remain a function.
- Supported imports, CLI behavior, serialization, numerical results and test
  collection remain compatible; existing behavioral and full CI checks pass.
- Temporary migration allowances are removed, and the written guide, root
  commands, pre-commit, standards checker and hosted CI enforce the same contract.

## Audit validation record

Installed tools matched repository pins: Python 3.12.14, Ruff 0.16.5, mypy 2.3.1.
Commands used explicit tracked paths from `git ls-files '*.py' '*.pyi'`; mypy
caches and experimental diagnostics were stored under `/private/tmp`.

| Check | Observed result |
| --- | --- |
| `ruff check --no-cache <tracked paths>` | Passed. |
| `ruff format --check --no-cache <tracked paths>` | Passed: 125 files. |
| `mypy --strict --cache-dir=<temporary directory> <tracked paths>` | Passed: 125 files. |
| Ruff import headings + explicit first-party packages, diagnostic-only | 124 `I001` diagnostics in 123 files. |
| `ruff check --select D --config 'lint.pydocstyle.convention="google"' <tracked paths>` | 340 diagnostics in 46 files: 315 `D103`, 20 `D107`, 4 `D105`, 1 `D102`. This understates missing structured sections/private docs. |
| Strict mypy + `--disallow-any-explicit --disallow-any-unimported --disallow-any-decorated` | 173 diagnostics in 27 files: 154 `explicit-any`, 19 `misc`; includes library-derived signatures. |
| Strict mypy + `--disallow-any-expr`, tracked runtime/governance only | 350 diagnostics in 33 files; 94 source files checked. |
| Import-heading fix/format/recheck on temporary sample | Passed after formatting; repository source untouched. |
| Plan links, cited source-line bounds and whitespace | Passed. |
| `UV_NO_SYNC=1 make architecture-check UV='uv --offline --cache-dir /private/tmp/python-standards-uv-cache'` | Passed for 14 ADRs and repository documentation links, using the installed environment. The initial attempt without `UV_NO_SYNC=1` tried a package rebuild and failed because the fresh offline cache lacked Hatchling; no dependencies were installed. |

The stronger settings were probes, not edits to active configuration. This audit
used static inventory and representative manual review; it did not execute the
full behavioral/Bazel/hosted suite or prove every possible runtime defect absent.
Implementation must supply the regression evidence described above.

## Step 1 validation record — 2026-09-05

Validation used an isolated local checkout containing the tracked baseline and
all intended changes, including the new checker, tests, policy files and this
plan. The original checkout's three unrelated untracked ` 2` copies were
preserved and excluded from that snapshot. The checker intentionally includes
new untracked Python files, so `program_governance/status 2.py` caused new
standards findings at that time. It was not added to the debt file. Subsequent
user-authorized cleanup confirmed all three copies were byte-for-byte identical
to their canonical files and removed them, along with an extra generated
`.coverage 2` file, while retaining the canonical files.

The full lane ran with the existing pinned Cosign/Syft executables on `PATH`,
`UV_NO_SYNC=1`, and a temporary uv cache, after rebuilding both local packages
offline with `uv sync --frozen --offline --no-editable --no-build-isolation`.
No dependency or lockfile changed. The first sandboxed full-lane attempt could
not write Bazel's existing cache; the authorized run with cache access passed.

| Check | Observed result |
| --- | --- |
| New source-scanner/debt-policy pytest tests | 55 passed. |
| `make ci-full`, local intended-change snapshot | Passed, including schema compatibility and every pre-commit hook. |
| Full-lane `bazel build --config=ci //...` | Passed. |
| Full-lane `bazel test --config=ci //...` | All 19 test targets passed, including the new `python_standards_test`. |
| Full-lane lint, formatting and strict mypy | Passed over 129 intended Python source files. |
| Full-lane governance and Bandit checks | Passed, retaining the existing provisional package statuses. |
| Full-lane pytest | 628 passed, 9 deselected; separate integration run: 1 passed. |
| Full-lane import smoke test and sdist/wheel build | Passed. |
| Final documentation links and `git diff --check` | Passed. |

This is local full-lane evidence, not a hosted merged-result run. The scanner,
its source tests, and policy documentation were delegated to the review skill's
default Luna-max implementation agents; the main agent reviewed, integrated,
extended edge-case coverage, and validated the combined result. At step-1
completion, steps 2–7 remained unfinished, including retirement of the measured
implicit-library typing debt.

## Step 2 validation record — 2026-09-05

Validation compared the working tree with step-2 starting revision `3c22042`.
Both local packages were rebuilt offline as non-editable installs using the
existing pinned environment, without changing dependencies or lockfiles.

| Check | Observed result |
| --- | --- |
| Import-only fixes, applied separately to runtime, tooling and tests | Exactly 243 heading comments added in 123 files. |
| Complete AST comparison across all 129 tracked Python files | Identical after import normalization; the final checker change only updates the debt checksum constant. Import targets, aliases, relative levels and execution order are unchanged. |
| Debt inventory comparison | Exactly 243 `PYI001` obligations retired; all other entries and metadata preserved. |
| `make lint format-check typecheck engineering-standards-check` | Passed; Ruff formatting and strict mypy cover 129 Python files. |
| `bazel test --config=ci //...` | All 19 test targets passed, including developer-environment and Python-standards tests. |
| Pytest with performance tests excluded | 628 non-integration tests passed; the separate integration rerun passed its one test. |
| `pre-commit run --all-files` | Every hook passed, including documentation links and dependency admission. |
| `git diff --check` | Passed. |

The first pytest/pre-commit attempts lacked the pinned Cosign executable on
`PATH`; dependency admission passed after adding the existing Cosign 3.1.3 and
Syft 1.51.1 directories. The integration test's nested uv command initially hit
a sandbox cache restriction; its authorized rerun used an inherited temporary
uv cache and passed. These are local checks; step 2 did not run `make ci-full`
or hosted CI. Steps 3–7 remain planned.
