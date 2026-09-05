# Python coding standards audit and migration plan

Audit date: 2026-09-05. Baseline revision:
`d3a40ca98d71208426c8501d8d4a1aaaa049768d`.
Status: steps 1–4 implemented on 2026-09-05; steps 5–6 are in progress. Domain
operations, identity/calendar value models, all dedicated governance model
modules, CI/remote-execution, supply-chain, domain, shared model-validation,
change-risk, ownership, evidence, package-metadata and remaining governance test
contracts, remaining build tests and fixtures, and the change-risk service pilot
are implemented; step 7 remains planned. The latest step-5 slice covers 14
governance CLI/shared-operation modules and retires 93 documentation obligations;
12 Typer callback docstrings remain deliberately unchanged as help contracts.
Step 5 still has other governance operations remaining; moved workflow
documentation is combined with step-6 service slices. The findings below describe
the original audited revision, before step-1 enforcement.

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
| 3. Remove explicit Any in tests — implemented | Replaced the two modules' escape hatches with validated fixture records, callable types and runtime narrowing; documented their helpers. Retired all 14 explicit-typing obligations. | Zero source-level `Any`; strict mypy and focused financial-unit/developer-environment tests pass; existing invalid-input entry points and parametrizations are preserved. See the step-3 validation record below. |
| 4. Strengthen library and parsing boundaries — implemented | Activated the Pydantic plugin and stronger scoped flags; typed validation contexts and native stubs; narrowed parsed tables and rejected malformed lock roots. Added an exact, attributed inferred-debt inventory. | Full-scope strict checks and seven expression scopes pass; remaining diagnostics have causes and retirement tasks. Stubtest, native conformance, validation and existing goldens pass. See the step-4 records below. |
| 5. Document existing contracts — in progress | Documented financial-unit models/conventions, the symbology catalog, calendar adapter, identity/calendar value models, shared governance validation, operating/risk/evidence contracts, all dedicated governance model modules, and CI/remote-execution, dependency/artifact, domain, shared model-validation, change-risk, ownership, evidence, package-metadata, remaining governance tests and helpers, remaining build tests and fixtures, and the CLI/shared, secret-scanning and sharding governance operations. Remaining: other governance operations. Combine docs for moved functions with step 6. | The twelve documentation slices retire 185, 268, 76, 80, 22, 158, 109, 109, 97, 116, 16 and 93 obligations respectively, preserving executable ASTs. The step-5 implementation and validation records track each slice. |
| 6. Refactor workflows into classes — in progress | Implemented the change-risk classifier and separate approval evaluator, retaining the function APIs. Continue with loaders and CI services using the queue below. Depends on steps 2–4 for the owning package. | The first queue item preserves serialized decisions, ordered errors and CLI results across 63,404 differential cases; repeated-call regressions pass. See the step-6 records below. |
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

### Step 3 implementation

The financial-unit golden loader now validates JSON against nested `TypedDict`
records using the existing pinned Pydantic `TypeAdapter` in strict mode. Decimal
strings and integer rational components retain their original representation;
missing required fields and scalar coercion fail before numerical assertions.
The `dynamic` identity helper was removed. Invalid-value parameters and native
fake results use `object`; operation callbacks use `Callable[[], object]`.

All negative cases still invoke the original public constructor, method or copy
operation. Twelve deliberately invalid typed calls use line-scoped
`arg-type` suppressions, each with the governed `platform` owner, a specific
runtime-rejection rationale and expiry of 2027-03-01. Strict mypy checks that the
suppressions remain necessary. Production signatures, validation entry points,
golden values and dependency pins are unchanged.

The developer-environment validators accept raw `object` inputs and narrow each
table and consumed scalar before using it. JSON lock structure is checked before
nested access, so malformed tables produce validation findings instead of an
incidental `AttributeError`. TOML inputs remain raw until their field checks;
they are not asserted to have JSON's narrower value domain. Existing duplicate,
floating-version and unsupported-platform mutations now validate their container
shapes before mutation. Additional malformed-table cases exercise the guards.

Both test modules now document their definitions, including nested native fakes.
The debt inventory and checksum retire exactly 67 obligations: all 14 `PYT001`,
46 `PYD001`, six `PYD002`, and the removed helper's one `PYC001`. No allowance or
standards exception was added. The remaining 2,769 obligations across 87 files
are 735 definition summaries, 1,229 structured-documentation obligations and 805
function dispositions. Inferred library and parsing types remain step-4 work;
source-level completion does not claim that every expression is free of inferred
dynamic typing.

### Step 4 implementation

The Pydantic pilot used the small governance `OperatingRules`/change-risk models
and the shared immutable base before enabling `pydantic.mypy` across both
packages. Typed constructors, extra-keyword rejection and dynamic-alias checks
are active. Four validators now use `ValidationInfo[object]` because they consume
only field names and make no assumption about caller-supplied context. Custom
constructors and their owned validation-error translation remain intact.
The plugin identifies frozen fields statically, so the two existing tests of
runtime frozen-field assignment now have governed line-scoped `misc` suppressions.
They still execute the original assignments and expect runtime validation errors.

`disallow_any_explicit` and `disallow_any_unimported` now apply to the entire
root check, including tests and five local stub files. Decorated signatures are
checked across both owned packages. Expression checks additionally apply to
financial conventions, the governance immutable base, change-risk models, CI
policy parsing, the operating model, the new typing checker and its tests.
The engineering-standards policy checks the plugin settings, exact module scopes
and stub search path, preventing configuration drift.

The consumed QuantLib 1.43, exchange-calendars 4.13.2 and pandas 3.0.5 surfaces
have narrow local stubs. All four `import-untyped` suppressions were removed.
QuantLib counters use their actual common `DayCounter` base, and tests access the
native settings and monkeypatch targets through typed module imports. Stubtest
checks the declarations without an allowlist; behavioral tests exercise the
five day-count conventions, date constructors, XNYS/XHKG timestamp shapes and
NaT break sentinels. Stubs are declared in Bazel adapter/build inputs and the
source distribution, with unchanged dependency pins and lockfiles.

TOML readers retain the standard library's guaranteed string-keyed root shape
without asserting JSON's narrower value domain. Operating settings and domain
tables are shape-checked before projection into existing strict models. CI
policy readers use typed raw tables and their existing closed-schema validators.
Artifact JSON is captured as `object` before its existing shape check; toolchain
tables now pass the existing table-array validator before access. Dependency
admission validates both JSON lock roots and the dependency-group/dev shapes
before nested access. Wrong JSON roots now produce the existing domain error.

The separate [inferred-debt inventory](../architecture/python-typing-debt.json)
records **690 remaining diagnostics, 359 exact identities across 50 files**.
Its revision identifies this slice's starting commit; measurements reflect the
completed boundary changes. Each obligation has a cause and concrete retirement
task, including framework signatures, serialized/fixture records, error details,
reflection, collection narrowing, regex results and callback inference. Nine
Hypothesis-decorated test signatures remain among those diagnostics. This is
unfinished inferred-typing work for the later owning-module slices and step 7;
it is not a claim that every expression is free of dynamic types.

`make typecheck`, the rollback lane and pre-commit run strict mypy, the full-scope
stronger inventory probe and native stubtest. The probe validates its machine
output and rejects process failures, new/moved/multiplied debt, stale entries,
missing tasks and duplicate identities. It never writes allowances. Inventory
bytes are checksum-pinned. All 2,769 pre-existing source-standard obligations
remain unchanged; no source debt was regenerated or added. One exact expiring
framework exception retains the upstream `get_calendar` factory as a module-level
stub declaration, with its owner, rationale and AST fingerprint recorded.

### Step 5 implementation — first domain-contract slice

The first slice documents the exported operations in
[financial values](../../src/alpha_research/financial_units/models.py),
[financial conventions](../../src/alpha_research/financial_units/conventions.py),
[the symbology catalog](../../src/alpha_research/instrument_identity/catalog.py),
and [the calendar adapter](../../src/alpha_research/venue_calendar/adapter.py),
including their validators and private helpers. Existing numerical tolerance and
temporal-model explanations are retained. Google sections now specify arguments,
return values, direct and propagated domain errors, and relevant side effects.

The contracts distinguish exact arithmetic from explicit rounding, accounting
minor units from settlement rules, valid-time intervals from historical
knowledge-time selection, and requested snapshot bounds from the source library's
extended loading range. They also describe modified-convention coverage failures,
namespace ambiguity, native-version checks, and explicit overlay attribution.
Financial-unit validation callbacks now explain their specific invariants rather
than repeating a generic validation summary.

The [shared governance model](../../tools/governance/src/alpha_research_governance/_models.py)
documents strict validation, framework error behavior, shallow freezing, and the
inherited trusted-data construction/copy APIs. Financial-unit replacement docs
describe its existing reconstruction and revalidation behavior. No constructors,
copy implementation, validator, public signature, export, or numerical algorithm
changed. Model schema descriptions may reflect the expanded shared class prose;
field definitions and serialized instance values are unchanged.

The source-debt inventory retires exactly **185** existing obligations: 21 missing
summaries and 164 Google-section/parameter obligations. Its checksum pin changes
with those deletions. No allowance was regenerated or added, and the exact
exception policy is unchanged. The five edited source modules have no remaining
documentation findings; their resolved contracts are enforced by the existing
checker without documentation exceptions.

Step 5 remains in progress: **1,779** documentation obligations remain (714
summaries and 1,065 sections/parameter descriptions), alongside the unchanged 805
step-6 function dispositions. The source inventory contains 2,584 obligations
across 86 files. The 690 inferred-typing diagnostics remain unchanged. Continue
with identity/calendar value-model APIs and high-level governance operations,
then residual helpers, test classes and fixtures. Global Ruff documentation-rule
activation and complete debt removal remain later adoption work.

### Step 5 implementation — identity/calendar value-model slice

The second slice documents all definitions in
[identity values](../../src/alpha_research/instrument_identity/models.py) and
[calendar values](../../src/alpha_research/venue_calendar/models.py). Public
operations and validation callbacks now describe arguments, results and failure
conditions; model attributes explain their invariants and private helpers have
concise summaries. The two domain bases explain strict construction, error
translation and the inherited trusted-data construction/copy APIs.

Identity contracts distinguish typed UUID construction from canonical-text
parsing, exact identifier values from namespace-broad queries, local validation
from catalog reference checks, and half-open valid time from knowledge time.
They specify namespace/checksum rules, UTC requirements, attribution tokens and
correction-link/reason coupling.

Calendar contracts specify inclusive date coverage and half-open UTC windows,
cross-midnight sessions, independent settlement coverage, and the different
lookup errors for missing sessions, uncovered dates and unavailable settlement
days. Market-state documentation records halt/auction/break precedence, the
independent price-limit state and the venue-local coverage fallback when no
session contains an instant. It also distinguishes override instructions from
their application and MIC shape checks from external registry membership.

The source inventory retires exactly **268** documentation obligations: 33
summaries and 235 Google-section/parameter findings. Identity values account for
150 and calendar values for 118. Only those entries and the inventory checksum
pin change; no new allowance or exception is added. Both modules have zero
remaining documentation findings. Removing docstrings from their ASTs yields
exactly the original executable trees; signatures, validation, ordering and
serialized instance behavior are unchanged. Generated schema descriptions can
reflect the expanded class prose, while schema field contracts are unchanged.

This slice follows the change-risk service pilot. After this slice, the source inventory
held **2,289** obligations across 84 files: **1,491** documentation obligations
(679 summaries and 812 sections/parameters) and 798 function dispositions.
The 686 inferred-typing diagnostics and exact exception inventory are unchanged.
Step 5 remains in progress with governance operations and residual helpers,
tests and fixtures; document moved workflows with their step-6 service slices.

### Step 5 implementation — operating/risk/evidence contracts

The third documentation slice completes the contracts in
[operating rules](../../tools/governance/src/alpha_research_governance/operating_model.py),
[change-risk records](../../tools/governance/src/alpha_research_governance/change_risk/models.py)
and [evidence records](../../tools/governance/src/alpha_research_governance/evidence/models.py).
It documents the existing class operations, serializers, validation callbacks,
model attributes and operating-model loader without moving workflow ownership.

Operating contracts specify canonical individual identities, half-open effective
date intervals, unique founder/domain assignments and the difference between
active reviewer presence and complete role coverage. They explain that local
completion checks neither change handover status nor authorize institutional
operations. Loader docs cover the single UTF-8 file read, projected ownership
fields, JSON date-string representation and propagated file/decode errors.

Risk and evidence contracts distinguish strict record construction from the
policy and manifest checks that establish control requirements, commit binding,
artifact integrity and approval eligibility. They document exact typed dimension
lookup, deterministic JSON set ordering, package-profile consistency, lexical
path checks and the approval projection that copies identity/role claims without
checking status, commit or evidence URL. Callback docs distinguish direct
`ValueError` failures from Pydantic's normal `ValidationError` wrapping.

Exactly **76** documentation obligations are retired: one missing summary and
75 Google-section/parameter findings (24 operating, 27 risk and 25 evidence).
The compact inventory and its checksum change together, with no new allowance
or exception. All three modules have zero remaining documentation findings.
Executable ASTs are unchanged after removing docstrings, and all 23 owned model
schemas match apart from description metadata. Existing identity/calendar docs,
serialized field contracts, function dispositions and inferred-typing debt are
preserved.

After this slice, the source inventory held **2,213** obligations across 82 files:
**1,415** documentation obligations (678 summaries and 737 sections/parameters)
and 798 function dispositions. The inferred inventory still contains 686
diagnostics. Step 5 remains in progress; continue with program, security and
inventory value-model contracts, and document moved loaders with their step-6
service slices before addressing residual helpers, tests and fixtures.

### Step 5 implementation — program/security/inventory models

The fourth documentation slice completes all definitions in
[program models](../../tools/governance/src/alpha_research_governance/program_governance/models.py),
[security-control models](../../tools/governance/src/alpha_research_governance/security_controls/models.py)
and [inventory models](../../tools/governance/src/alpha_research_governance/inventory/models.py).
Class contracts explain stored metadata and local invariants separately from
the reference, ownership, evidence and policy checks performed by the loaders.

Program contracts specify purpose-specific all-of/any-of prerequisites, the
schema-version split in solo readiness, institutional status versus technical
completion, lookup defaults, and first-evidence-path behavior for legacy and
directly constructed states. KPI documentation records exact float and UTC
requirements, reporting cutoffs anchored to the latest supplied observation,
inclusive cutoff comparisons, nearest-rank duration percentiles in seconds,
and ratios computed from summed sufficient statistics across dimensions.
Aggregation requires validated events; retry deduplication, unit/denominator
checks and observation limits remain responsibilities of the loader.

Security and inventory queries now describe exact, case-sensitive matching,
conjunctive filters, empty results and preservation of stored order. Their
serializers describe fresh dictionaries and lists, ISO date text and preserved
reference order. Record documentation identifies declared control, deployment
and applicability states without attributing external evidence checks to simple
construction or querying. Queries and serializers perform no file/network I/O.

Exactly **80** documentation obligations are retired: five summaries and 75
Google-section/parameter findings (50 program, 20 security and 10 inventory).
All three modules have zero remaining documentation findings. The inventory
keeps its compact format, and only resolved entries and its checksum change;
no allowance or exception is added. Executable ASTs match after removing
docstrings, and all 19 owned Pydantic schemas match apart from description
metadata. Earlier documentation, function dispositions and inferred typing are
preserved.

After this slice, the source inventory held **2,133** obligations across 79 files:
**1,335** documentation obligations (673 summaries and 662 sections/parameters)
and 798 function dispositions. The inferred inventory still contains 686
diagnostics. Step 5 remains in progress with the remaining build/CI policy
models, governance operations and residual helpers/tests/fixtures. Continue
documenting moved workflows alongside their step-6 service slices.

### Step 5 implementation — remaining governance value models

The fifth documentation slice covers the remaining six dedicated model modules:
[artifact supply chain](../../tools/governance/src/alpha_research_governance/artifact_supply_chain/models.py),
[CI policy](../../tools/governance/src/alpha_research_governance/ci_policy/models.py),
[dependency admission](../../tools/governance/src/alpha_research_governance/dependency_admission/models.py),
[engineering standards](../../tools/governance/src/alpha_research_governance/engineering_standards/models.py),
[remote execution](../../tools/governance/src/alpha_research_governance/remote_execution/models.py)
and [repository topology](../../tools/governance/src/alpha_research_governance/repository_topology/models.py).
All 33 value models document their stored attributes, units and relevant
relationships. Module contracts distinguish strict field validation from loader,
graph, file and signature checks. The six error constructors now document ordered
message snapshots, duplicate preservation and newline rendering; topology lookup
specifies exact matching, first-result behavior and the missing-unit error.

Artifact contracts distinguish unsigned preparation from verified consumer
acceptance. Dependency contracts describe the authenticated source-binding and
temporary bootstrap profiles, bounded review dates, retained evidence identities,
and digests over both internal and external build parameters. CI contracts
describe rename/copy paths, selection before reverse-dependency attachment and
positive UTC event windows, including shallow freezing of event dimensions.
Remote contracts distinguish transport retries, normal test attempts and
diagnostic repeats; quarantined tests remain in the normal partition. Engineering
baselines are documented as retained measurements, and topology records describe
dependency direction and visibility as the exact direct-consumer set.

Exactly **22** original documentation obligations are retired: six summaries and
16 Google-section/parameter findings. The inventory preserves its compact format
and original attribution, changing only by deletion with the matching checksum
update. All six modules have zero remaining source-scanner findings. Executable
ASTs match the captured working-tree baseline after removing docstrings; all 33
Pydantic schemas match except description metadata. The pre-existing
program/security/inventory documentation changes are preserved.

After this slice, the source inventory held **2,111** obligations across 73 files:
**1,313** documentation obligations (667 summaries and 646 sections/parameters)
and 798 function dispositions. The inferred inventory still contains 686
diagnostics. Step 5 remains in progress with governance operations and residual
helpers, tests and fixtures; document moved workflows with their step-6 services.

### Step 5 implementation — CI and remote-execution test contracts

The sixth documentation slice covers every definition in
[CI policy tests](../../tests/engineering/test_ci_policy.py),
[CI runner tests](../../tests/engineering/test_ci_runner.py) and
[remote-execution tests](../../tests/engineering/test_remote_execution.py).
The 25 test functions have concise behavioral summaries; their 25 helpers and
nested callbacks document fixture I/O, recorded inputs, simulated results and
intentional failure conditions. Structured callback sections distinguish captured
arguments from unused inputs retained for the replaced function's signature.

CI contracts explain full-lane control ordering, whole-graph selection after
affected-lane preflight, and failed-event emission before command failure is
propagated. They also describe rename-path preservation, reverse dependencies,
synthetic secret detection, merge-parent binding and duration-event ingestion.
Remote contracts cover trust-check/query/execution order, credential-file
inspection, deterministic partitioning and empty-shard behavior. CLI callbacks
document the distinct simulated statuses used to verify dispatch and error
propagation. The Git and policy-copy/mutation helpers describe their temporary
filesystem effects and failure conditions.

Exactly **158** original documentation obligations are retired: 50 summaries and
108 Google-section/parameter findings (12 CI policy, 73 CI runner and 73 remote
execution). All three modules have zero documentation findings. The debt
inventory preserves its compact formatting and original attribution, with only
resolved entries and the matching checksum changed. Executable ASTs, assertions,
fixtures, monkeypatch targets, markers and parametrizations are unchanged. All
672 pytest node IDs match the captured baseline, including the 31 cases in these
modules and the separate performance/integration selections. Test-class grouping
and function dispositions remain step-6 work.

After this slice, the source inventory held **1,953** obligations across 73 files:
**1,155** documentation obligations (617 summaries and 538 sections/parameters)
and 798 function dispositions. The inferred inventory remains at 686 diagnostics.
Step 5 remains in progress with governance operations and residual tests/helpers;
continue documenting moved workflows with their step-6 service slices.

### Step 5 implementation — dependency and artifact test contracts

The seventh documentation slice completes all definitions in
[dependency-admission tests](../../tests/engineering/test_dependency_admission.py)
and [artifact-supply-chain tests](../../tests/engineering/test_artifact_supply_chain.py).
The 44 test functions describe their asserted behavior; the remaining fixtures,
helpers, callbacks and tool-runner class document inputs, outputs, state changes
and relevant errors. All 75 definitions now have their applicable documentation.

Dependency fixtures explain exact-lock audit coverage, synthetic Scorecard
signals, fixed review dates, retained evidence copies and temporary file writes.
Source and bootstrap profiles distinguish build-provenance claims from
publication-only claims with an unresolved source-to-wheel binding. Callback
contracts describe verifier options, staged inputs, injected process failures
and checks that must reject input before a verifier can run. Synthetic evidence
and successful process doubles are explicitly not signature authentication.

The artifact runner documents accumulated command history, forced failures and
the fixture files written by simulated Syft/Cosign calls. Bundle helpers describe
unsigned creation and simulated protected-main signing. Test summaries cover
digest-bound publication, native-library coverage, trust/revocation checks and
release denial before tool execution at all four artifact boundaries. Existing
real repository-admission checks and deliberate test doubles are preserved.

Exactly **109** original documentation obligations are retired: 70 summaries and
39 Google-section/parameter findings (83 dependency admission and 26 artifact
supply chain). Both modules have zero documentation findings. Only matching
debt entries and the checksum pin change, preserving every remaining allowance
and its original attribution. Executable ASTs, assertions, fixture payloads,
monkeypatch targets, markers and parametrizations are unchanged. All 672 pytest
node IDs match the captured baseline, including 129 cases in these two modules.

The current source inventory holds **1,844** obligations across 73 files:
**1,046** documentation obligations (547 summaries and 499 sections/parameters)
and 798 function dispositions. The inferred inventory remains at 686 diagnostics.
Step 5 remains in progress with governance operations and residual tests/helpers;
continue documenting moved workflows with their step-6 service slices.

### Step 5 implementation — domain and shared model-validation tests

The eighth documentation slice completes the remaining contracts in the three
domain unit-test modules, their three evidence-test modules and
[shared model-validation tests](../../tests/engineering/test_pydantic_models.py).
It adds or expands documentation for 78 definitions; all 120 definitions in
these seven modules now have applicable documentation.

Identity tests describe exact identifier lookup, half-open symbol reuse,
correction-history retention and malformed graph rejection. Calendar tests
describe UTC/DST conversion, session and market-window relationships, override
attribution, exact coverage and host-timezone restoration. Their fixture builders
document synthetic identities, provenance, interval bounds and parsing errors.
The three evidence summaries describe the asserted partial R2 profiles, findings
and retained golden digests.

The financial-unit callbacks distinguish fixed 1e-15-year result rounding from
the evaluation context's date and convention revision. Native fakes document
ignored date arguments, absent-break sentinels, deliberately invalid results and
unconditional failures. Shared model tests describe strict inputs, nested-instance
revalidation, deterministic JSON shapes and loader error translation with
preserved causes and hidden rejected values.

Exactly **109** original documentation obligations are retired: 71 summaries and
38 Google-section/parameter findings. All seven modules have zero documentation
findings. The inventory changes only by deleting those entries, with its matching
checksum updated. Executable ASTs, suppression metadata, assertions, fixtures,
markers, signatures and parametrizations are unchanged. All 672 ordered pytest
node IDs match the captured working-tree baseline, including 168 cases in these
modules. The preceding dependency/artifact documentation slice is preserved.

The source inventory now holds **1,735** obligations across 73 files:
**937** documentation obligations (476 summaries and 461 sections/parameters)
and 798 function dispositions. The inferred inventory remains at 686 diagnostics.
Step 5 remains in progress with governance operations and residual tests/helpers;
document moved workflows with their step-6 service slices.

### Step 5 implementation — risk, ownership and evidence test contracts

The ninth documentation slice completes
[change-risk tests](../../tests/engineering/test_change_risk.py),
[ownership tests](../../tests/engineering/test_ownership_governance.py),
[evidence-governance tests](../../tests/engineering/test_evidence_governance.py),
[package-evidence tests](../../tests/engineering/test_package_evidence.py) and
[distribution-contract tests](../../tests/engineering/test_package_definition.py).
Three `gpt-5.6-luna` subagents at `xhigh` reasoning wrote separate files; the main
agent audited every added docstring against the implementation, assertions and
relevant validators before reconciling the inventory. All 101 definitions now
have applicable documentation.

Risk and ownership contracts describe representative classification facts,
conditional gates, canonical reviewer identities, approval minima, policy
mutations, CODEOWNERS precedence and the actual ownership hook's rejection of a
staged unowned path. Evidence contracts describe fixture copies and replacements,
Git/event-file side effects, digest and commit binding, conditional MR sections,
schema compatibility and implementation versus institutional acceptance.
Distribution helpers document repository TOML parsing and installed metadata.

The audit corrected overbroad model-validation claims: adversarial manifest
copies satisfy model fields without rerunning artifact, classification or profile
checks. Profile construction copies the original change facts and gate IDs;
shortening declared open-finding IDs preserves the original finding records.
The revised prose also distinguishes heading renaming from reordering, scopes
the one-approval example to its synthetic version-1 R0 fixture, and records
propagated policy-loading/I/O failures and replacement rather than append behavior.
No actionable documentation findings remain in this slice after those corrections.

Exactly **97** original documentation obligations are retired: 93 summaries and
four Google-section/parameter findings. All five modules have zero documentation
findings. The source inventory now holds **1,638** obligations across 73 files:
**840** documentation obligations (383 summaries and 457 sections/parameters)
and 798 function dispositions. The inferred inventory remains at 686 diagnostics.
Only the resolved entries and matching checksum are changed; no allowances are
added or relocated. Step 5 remains in progress with governance operations and
residual tests/helpers; document moved workflows with their step-6 service slices.

### Step 5 implementation — remaining governance test contracts

The tenth documentation slice completes
[architecture-governance tests](../../tests/engineering/test_architecture_governance.py),
[engineering-standards tests](../../tests/engineering/test_engineering_standards.py),
[inventory tests](../../tests/engineering/test_inventory_governance.py),
[program-governance tests](../../tests/engineering/test_program_governance.py),
[repository-governance tests](../../tests/engineering/test_repository_governance.py),
[topology tests](../../tests/engineering/test_repository_topology.py),
[root-command tests](../../tests/engineering/test_root_commands.py) and
[security-control tests](../../tests/engineering/test_security_controls.py).
Three `gpt-5.6-luna` subagents at `xhigh` reasoning wrote separate files. The main
agent audited every added or revised docstring against the implementation,
assertions and relevant loaders, requested corrections, and reviewed the revised
prose. All 125 definitions now have documentation.

The contracts describe ADR metadata and local links, exact engineering policy
values, suppression boundaries, inventory lineage, dependency graphs, program
readiness and observations, partial acceptance records, topology ownership and
imports, Make dry runs, and security-map references and evidence states. Helper
documentation records fixture copying and overwrites, shallow TOML narrowing,
in-place text mutations, process results and propagated failures.

The audit corrected claims that exceeded the exercised contracts. Synthetic ADR
metadata and metric event payloads remain unvalidated; date checks require the
extended calendar form. Legacy-policy conversion retains implementation fields
for callers to adjust. Inventory and security-map loaders validate references
without running the separate local evidence-bundle checks. Text replacement
after a marker searches the suffix through the end of the file; JSONL writing
preserves event order while sorting object keys. Repository acceptance assertions
exercise the current partial record, and topology summaries identify the actual
diagnostics asserted. No actionable documentation findings remain in this slice.

Exactly **116** original summary obligations are retired. All eight modules have
zero documentation findings, and no documentation debt remains under
`tests/engineering`. The source inventory now holds **1,522** obligations across
73 files: **724** documentation obligations (267 summaries and 457
sections/parameters) and 798 function dispositions. The inferred inventory
remains at 686 diagnostics. Only resolved entries and the matching checksum
change; every other entry and its original metadata are preserved.

Step 5 remains in progress. The next independent documentation slice is the
remaining build tests and fixtures, with 16 obligations across five files.
Governance operations account for the other 708 documentation obligations;
document moved workflows with their step-6 service slices.

### Step 5 implementation — remaining build tests and fixtures

Starting from clean revision `c2d25d787d0a26590ad17e0564f9056a0210bb54`, the
eleventh documentation slice completes all definitions in the
[Bazel build-graph test](../../tests/build/build_graph_test.py),
[sandbox test](../../tests/build/sandbox_test.py),
[Buf compatibility fixture](../../tests/build/fixtures/proto/buf_compatibility_test.py),
[Buf toolchain fixture](../../tests/build/fixtures/proto/buf_toolchain_test.py) and
[SQL generation fixture](../../tests/build/fixtures/sql/generated_sql_test.py).
Three `gpt-5.6-luna` subagents at `xhigh` reasoning wrote separate files. The
main agent audited every added or revised docstring against the implementation,
assertions and relevant fixtures, then requested revisions for selected sandbox
probes, lexical artifact-path checks, the actual interpretation of nonzero Buf
statuses, and propagated I/O and decoding exceptions. All 11 definitions now
have documentation.

The build-graph contracts describe exact module, lock, CI, version and Makefile
fragments; B02 dependency fields; and selected local evidence identity, gate,
artifact-path and digest checks. The evidence helper preserves the distinction
between lexical path validation and filesystem access and does not claim full
manifest or signature validation. The sandbox contract records the three
selected undeclared runfile paths and one host environment sentinel. The Buf
contracts document temporary fixture copies, isolated cache and home paths,
additive compatibility success, removal incompatibility as the expected
nonzero status, lint and two descriptor-generation runs, and SHA-256 comparison.
The SQL fixture documents UTF-8 reads, golden comparison, unresolved
substitution detection and propagated environment/file errors. Buf compatibility
does not inspect the nonzero diagnostic text; the toolchain helper raises for a
nonzero command status.

After docstrings are stripped, executable ASTs match the baseline, and the
source scanner reports zero documentation findings across all Python files under
`tests`. Exactly **16**
original documentation obligations are retired: 11 PYD001 summaries and five
PYD002 Returns sections. The source inventory now holds
**1,506** obligations across 73 files: **708** documentation obligations (256
summaries and 452 sections/parameters) and 798 function dispositions. The
inferred typing inventory remains unchanged at 686 diagnostics. Every other
inventory entry and its metadata remain unchanged, and the checksum pin matches.
Step 5 remains in progress with governance operations only; combine documentation
for moved workflows with their step-6 service slices.

### Step 5 implementation — governance operation entrypoints and helpers

The twelfth documentation slice covers the shared [CLI runner](../../tools/governance/src/alpha_research_governance/_cli.py),
[secret scanner](../../tools/governance/src/alpha_research_governance/ci_policy/secrets.py),
and [stable sharding helpers](../../tools/governance/src/alpha_research_governance/remote_execution/sharding.py),
plus 11 canonical governance entrypoints:
[artifact supply chain](../../tools/governance/src/alpha_research_governance/artifact_supply_chain/__init__.py),
[change risk](../../tools/governance/src/alpha_research_governance/change_risk/__init__.py),
[CI policy](../../tools/governance/src/alpha_research_governance/ci_policy/__init__.py),
[dependency admission](../../tools/governance/src/alpha_research_governance/dependency_admission/__init__.py),
[engineering standards](../../tools/governance/src/alpha_research_governance/engineering_standards/__init__.py),
[evidence](../../tools/governance/src/alpha_research_governance/evidence/__init__.py),
[inventory](../../tools/governance/src/alpha_research_governance/inventory/__init__.py),
[program governance](../../tools/governance/src/alpha_research_governance/program_governance/__init__.py),
[remote execution](../../tools/governance/src/alpha_research_governance/remote_execution/__init__.py),
[repository topology](../../tools/governance/src/alpha_research_governance/repository_topology/__init__.py)
and [security controls](../../tools/governance/src/alpha_research_governance/security_controls/__init__.py).

The slice adds concise Google summaries and applicable contracts for optional
arguments, status codes, JSON/text output, selected-root versus process-working-
directory paths, process/service timeout behavior, secret-scan pre-read checks and
race limitations, and empty stable-shard results. Twelve Typer callback docstrings remain
unchanged because their text is part of the root and subcommand help contract.
The audit corrected caught-versus-propagated CLI failures, metadata-version versus
PATH-scanner behavior, program status overwrites and aggregation boundaries. All
51 definitions now have documentation; all 12 root/subcommand help outputs and
statuses remain unchanged.

Exactly **93** original documentation obligations are retired: 16 PYD001 summaries
and 77 PYD002 sections/parameters (69 total in the CLI/shared modules and 24 total
in secret scanning/sharding). The source inventory now holds **1,413** obligations across 73
files: **615** documentation obligations (240 summaries and 375 sections/parameters)
and 798 function dispositions. The inferred-typing inventory remains at 686
diagnostics. The deletion and checksum pin are exact; earlier build documentation,
all other tracked files, and the remaining function dispositions are preserved.
Step 5 remains in progress with other governance operations; document moved
workflows with their step-6 service slices.

### Step 6 implementation — change-risk service pilot

[ChangeRiskClassifier](../../tools/governance/src/alpha_research_governance/change_risk/classification.py)
owns the validated policy used for classification.
[ChangeRiskApprovalEvaluator](../../tools/governance/src/alpha_research_governance/change_risk/approvals.py)
owns approval requirements and a classifier bound to the same policy. Constructors
perform no I/O. Every operation creates its own gates, findings and reviewer
assignment state; failed requests cannot contaminate later merge or activation
checks. Shared decision binding still recomputes trusted requirements before
checking supplied evidence.

Both services are exported from the governance package and the existing
`alpha_research.change_risk` facade. The policy loader reuses one classifier for
its samples. The three existing public function signatures delegate to services,
preserving callers, console scripts and `python -m` behavior. Founder/team
operating rules, policy schemas, review thresholds, decision serialization and
error ordering are unchanged. New public methods and wrappers have Google-style
argument, result and error contracts.

The exact source inventory retires **27** obligations: 20 documentation findings
and seven function dispositions. The three compatibility wrappers and four small
gate/identity/role/matching helpers have individually attributed, expiring,
AST-bound exceptions with explicit design rationales. No documentation exception
or new migration allowance was added. Typed sorting callbacks retire the
classifier's four inferred-typing diagnostics instead of relocating them into
the new method; both inventories and their checksum pins change together.

Step 6 remains in progress. The next queue item is program loading/status,
followed by the remaining loaders, evidence/bundle services and CI runners.
After this pilot, the source inventory held **2,557** obligations across 84 files: 712 missing
summaries, 1,047 structured-documentation findings and 798 function dispositions.
The inferred inventory holds **686** diagnostics, 356 identities across 49 files.
Step 7 must also reassess compatibility wrappers and the retained helpers before
their exceptions expire.

### Class migration queue

Paths below are relative to `tools/governance/src/alpha_research_governance` unless
prefixed with `src/`. Names are proposed responsibilities, not mandatory new files.

| Order / current area | Proposed responsibility | Compatibility and behavior to preserve |
| --- | --- | --- |
| 1. `change_risk/classification.py`, then `approvals.py` — implemented | `ChangeRiskClassifier(policy)` and `ChangeRiskApprovalEvaluator(policy)`, with invocation-local state. | Highest-dimension rule, downgrade rejection, gate ordering, founder/team rules and exact errors preserved; existing classification/approval functions delegate temporarily. |
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

## Step 3 validation record — 2026-09-05

Validation compared the working tree with step-3 starting revision `31a8a78`.
Both local packages were rebuilt offline as non-editable installs in the existing
pinned environment. No dependency, lockfile, runtime implementation or golden
fixture changed.

| Check | Observed result |
| --- | --- |
| Source standards scan across runtime, governance and tests | Zero `PYT001` findings; all 14 explicit-typing obligations retired. |
| Financial-unit test compatibility | All 27 existing test-function bodies and parametrizations match after removing annotations, docstrings and the former identity wrapper. All 82 selected existing pytest node IDs remain; five fixture-validation cases were added. |
| Focused financial-unit pytest | 87 passed; the existing performance test was deselected. The five new cases reject missing metadata, boolean/string rational components and numeric values in decimal-string fields. |
| Source-scanner, debt-policy and engineering-standards pytest | 75 passed; one integration test was deselected. |
| `make lint format-check typecheck engineering-standards-check` | Passed; Ruff formatting and strict mypy cover all 129 Python files. Suppression metadata and the revised debt checksum pass the existing policy. |
| Owning Bazel tests | `//tests/unit:financial_units_test`, `//tests/build:developer_environment_test`, `//tests/engineering:python_standards_test` and `//tests/engineering:engineering_standards_test` all passed under `--config=ci`. |
| Debt comparison | Exactly 67 existing obligations retired, preserving every remaining entry and original-revision attribution; no new allowances. |
| Documentation and whitespace | `make architecture-check` passed for 14 ADRs and repository documentation links; `git diff --check` passed. |

These are local checks for step 3; this slice did not run `make ci-full` or hosted
CI. Steps 4–7 remain planned.


## Step 4 validation record — 2026-09-05

Validation used starting revision `298091a52aee0488dc545d072c63b9b5809f27d1`.
Both local packages were rebuilt offline as non-editable installs in the existing
pinned environment. Dependencies, lockfiles, source-standard debt and golden
fixtures are unchanged. The existing pinned Cosign and Syft executables were
included on `PATH` for repository checks.

| Check | Observed result |
| --- | --- |
| Initial full-scope extra-flag probe after step 3 | 160 diagnostics in 27 files before enabling the Pydantic plugin and boundary fixes. |
| Pydantic static compatibility probes | Valid governance construction and the custom positional `InstrumentId(UUID)` constructor pass. Four invalid examples are rejected: frozen-field assignment, a list for a tuple field, an extra constructor keyword and a string for a UUID argument. |
| `make lint format-check typecheck engineering-standards-check architecture-check` | Passed. Ruff and strict mypy cover 136 Python/stub files. The seven expression scopes pass; source/typing inventories and exact configuration guards pass; 14 ADRs and documentation links validate. |
| Stronger full-scope diagnostic reconciliation | Exactly 690 remaining diagnostics, 359 identities across 50 files; each has a concrete cause and retirement task. Nine decorated Hypothesis signatures remain in this total. |
| Native `mypy.stubtest` | Passed over 1,548 inspected modules with `--ignore-missing-stub` for the deliberately partial surface; no allowlist. |
| Pytest, default non-integration/non-performance selection | 655 passed, 9 deselected. Includes 22 added cases for inventory drift/tool failures, malformed parsing roots, native signatures/return shapes, plus all existing domain goldens and invalid-input tests. |
| Existing test compatibility | All existing test-function names and decorators in the four modified test modules remain unchanged; native settings checks now use typed access to the same native module and singleton. |
| `bazel test --config=ci //...` | All 20 targets passed, including the new `python_typing_test` and all native-domain, developer-environment and governance tests. |
| `pre-commit run --all-files` | Every hook passed, including the shared typecheck command and all governance policies. |
| Source distribution and wheel | Offline build passed; inspected source archive contains all five native `.pyi` files, their build declaration, documentation and stubtest configuration. The development cache is excluded. |
| Source-standard debt and whitespace | Existing 2,769 source obligations remain byte-for-byte unchanged; no new allowances. The exact upstream-factory exception validates. `git diff --check` passed. |

Early local verification exposed the expected root-command test update and
missing structured docs in a new nested test callback; both were corrected and
the final checks above passed. The initial direct pytest invocation lacked the
installed console-command directory on `PATH`; the final suite ran through the
pinned uv environment after rebuilding both packages.

These are local checks for step 4. This slice did not run `make ci-full`, the
separate integration/performance selections or hosted CI. Steps 5–7 remain
planned, including retirement of the remaining inferred-typing tasks before
unconditional adoption closes.

## Step 5 validation record — first domain-contract slice, 2026-09-05

Validation used starting revision `4fa3c1eab9290858c7af94eacfc87ea3fba2b66e`.
Both local packages were rebuilt offline as non-editable installs in the existing
pinned environment. No dependency, lockfile, golden fixture, or test changed.

| Check | Observed result |
| --- | --- |
| Executable AST comparison | All five documented source files are identical to the starting revision after removing docstrings. The checker change only updates the source-debt checksum. Signatures, imports, validation, arithmetic, and execution order are unchanged. |
| Focused documentation checks | Zero source-scanner documentation findings in all five edited modules. Ruff with `D`, `ANN401`, and the Google convention passes for the financial-unit package, catalog, adapter, and shared governance model. |
| Debt comparison | Exactly 185 original documentation obligations retired (21 summaries, 164 sections/parameters). All other entries and original metadata are preserved; no new allowance or exception. |
| `make lint format-check typecheck engineering-standards-check architecture-check` | Passed. Strict mypy checks 136 Python/stub files; the inferred inventory still matches 690 diagnostics; native stubtest passes over 1,548 modules; source standards and 14 ADRs validate. |
| Focused pytest | 259 passed, 4 deselected across all three domain unit modules, shared Pydantic validation, source/debt/typing/engineering standards, and the three domain evidence modules. Existing goldens, invalid inputs, immutable replacement, temporal boundaries, native conformance, and rounding regressions pass. |
| Owning Bazel targets | All nine selected targets passed under `--config=ci`: instrument identity, venue calendar, and financial units; their three evidence targets; Python source standards, Python typing, and engineering standards. |
| `pre-commit run --all-files` | Every hook passed with the existing pinned Cosign and Syft executables on `PATH`. |
| Final documentation and whitespace | Documentation links validate and `git diff --check` passes. |

These are local checks for this slice; `make ci-full`, hosted CI, and the separate
integration/performance selections were not run. Step 5 remains in progress with
1,779 documentation obligations outstanding; steps 6–7 and inferred-typing debt
retirement remain unfinished.

## Step 6 validation record — change-risk service pilot, 2026-09-05

Validation used starting revision `171595d230f4a752a2df42d79df2c74e69674786`.
Both local packages were rebuilt offline as non-editable installs in the pinned
environment. Dependencies, lockfiles, evidence schemas and golden fixtures are
unchanged. Existing pinned Cosign and Syft executables were supplied on `PATH`.

| Check | Observed result |
| --- | --- |
| Differential behavior | All 63,404 cases matched the original implementation: 60,000 classifications spanning every policy dimension combination, three trigger flags and declarations; 3,400 approval outcomes including mismatched decisions, invalid roles, authorship, Unicode identities and waivers; four CLI argument/result cases. Compared complete JSON decisions, exact ordered errors, exit codes, stdout and stderr. |
| Compatibility and collection | All three exported function signatures are unchanged. All 60 existing change-risk/ownership pytest node IDs remain; eight service cases were added. Existing function callers continue through both facades. |
| Repeated-call regressions | One classifier recovers after escalation and downgrade rejection without retaining gates. One evaluator recovers after merge/activation failures, rejects unbound decisions and canonical duplicates on every call, and preserves error ordering across interleaved operations. |
| Full default pytest selection | 663 passed, 9 deselected, including existing policy, founder/team, evidence, immutable-model and domain golden regressions. |
| `bazel test --config=ci //...` | All 20 targets passed, including governance reverse dependencies, source/typing standards and native-domain tests. |
| `make lint format-check typecheck engineering-standards-check` | Passed. Ruff and strict mypy cover 136 Python/stub files; the stronger probe matches 686 remaining diagnostics; native stubtest passes over 1,548 modules. |
| Focused documentation checks | Both service modules pass Ruff `D`/`ANN401` with the Google convention and have zero source-scanner documentation findings. |
| Debt and exception reconciliation | Exactly 27 source obligations and four inferred diagnostics retired. Every remaining entry and original metadata is preserved. Seven individually fingerprinted function dispositions replace their migration entries without adding allowances. |
| `pre-commit run --all-files` | Every hook passed, including the shared typecheck command, source standards, secret scanning, documentation links and all governance policies. |

These are local checks for the first step-6 slice. The full `make ci-full` lane,
hosted CI and separate integration/performance selections were not run. Step 6
remains in progress with program loading/status next in the queue.

## Step 5 validation record — identity/calendar value-model slice, 2026-09-05

Validation used starting revision `f6cb62d8790be0615bba80745eb7a5e6fa3f33d5`,
which includes the change-risk service pilot. Both local packages were rebuilt
offline in the pinned environment. Dependencies, lockfiles, fixtures, tests,
inferred-typing debt and exception records are unchanged.

| Check | Observed result |
| --- | --- |
| Executable AST and schema comparison | Both documented source files are identical to the starting revision after removing docstrings. All 21 owned Pydantic model schemas match after excluding description metadata. The checker changes only its source-debt checksum. |
| Focused documentation checks | Both modules have zero source-scanner documentation findings and pass Ruff `D`/`ANN401` with the Google convention and formatting checks. |
| Exact debt reconciliation | Retired 268 existing documentation obligations: 33 summaries and 235 sections/parameters. All remaining entries, original metadata, inferred-typing inventory and exceptions are preserved; no additions or relocated allowances. |
| `make lint format-check typecheck engineering-standards-check architecture-check` | Passed. Strict mypy covers 136 Python/stub files; the stronger probe matches 686 diagnostics; native stubtest passes over 1,548 modules; source standards and 14 ADRs validate. |
| Focused pytest | 259 passed, 4 deselected across all three domain unit modules, shared Pydantic validation, source/debt/typing/engineering standards, and the three domain evidence modules. Existing goldens, invalid inputs, temporal boundaries, immutable values, native conformance and financial-unit consumers pass. |
| Owning Bazel targets | All nine selected targets passed under `--config=ci`: instrument identity, venue calendar and financial units; their three evidence targets; Python source standards, Python typing and engineering standards. |
| `pre-commit run --all-files` | Every hook passed with the existing pinned Cosign and Syft executables on `PATH`. |
| Final documentation and whitespace | Documentation links validate and `git diff --check` passes. The debt inventory preserves its original formatting and changes only by deleting resolved entries. |

These are local checks for this slice; `make ci-full`, hosted CI and the separate
integration/performance selections were not run. Step 5 remains in progress with
1,491 documentation obligations outstanding; the 798 function dispositions and
686 inferred-typing diagnostics remain later migration work.

## Step 5 validation record — operating/risk/evidence contracts, 2026-09-05

Validation started from revision `6a09b40d6d96a6fa9a43dc794d73ee5be963e532`,
including the completed identity/calendar value-model slice. The local
governance package was rebuilt offline, and checks used non-editable packages
in the pinned environment with the existing Cosign and Syft tools on `PATH`.
No dependency, lockfile, fixture, test or exception record changed.

| Check | Observed result |
| --- | --- |
| Executable AST and schema comparison | All three documented modules match their starting executable ASTs after removing docstrings. All 23 owned Pydantic model schemas match apart from description metadata. The checker changes only its source-debt checksum. |
| Focused documentation checks | Operating, risk and evidence modules have zero source-scanner documentation findings and pass Ruff `D`/`ANN401` with the Google convention and formatting checks. |
| Exact debt reconciliation | Retired 76 original obligations: one summary and 75 sections/parameters. All other entries and metadata are preserved. The inventory keeps its compact formatting; inferred typing, function dispositions, exceptions and existing identity/calendar source are unchanged. |
| `make lint format-check typecheck engineering-standards-check architecture-check` | Passed. Ruff and strict mypy cover 136 Python/stub files; the stronger inventory probe matches 686 diagnostics; native stubtest passes over 1,548 modules; source standards and 14 ADRs validate. |
| Full default pytest selection | 663 passed, 9 deselected. Includes founder/scoped-team resolution, local versus institutional acceptance, risk classification and approval enforcement, JSON serialization, malformed evidence and policy inputs, artifact/commit binding, source standards and all existing domain goldens. |
| `bazel test --config=ci //...` | All 20 test targets passed, including governance reverse dependencies, source/typing standards and domain evidence targets. |
| `pre-commit run --all-files` | Every hook passed, including the shared typecheck command, source standards, secret scanning, documentation links and all governance policies. |

These are local checks for this slice. The full `make ci-full` lane, hosted CI
and separate integration/performance selections were not run. Step 5 remains
in progress with 1,415 documentation obligations; 798 function dispositions and
686 inferred-typing diagnostics remain later migration work.

## Step 5 validation record — program/security/inventory models, 2026-09-05

The captured comparison baseline matches revision
`26f7cbcff8190e4939b4eb31c5f27d15aa2e647e`, including the completed
operating/risk/evidence slice. The local governance package was rebuilt offline.
Checks used non-editable packages in the pinned environment with the existing
Cosign and Syft executables on `PATH`. Dependencies, lockfiles, fixtures, tests,
prior documentation, exception records and inferred-typing debt are unchanged.

| Check | Observed result |
| --- | --- |
| Executable AST and schema comparison | All three documented modules match their baseline executable ASTs after removing docstrings. All 19 owned Pydantic schemas match apart from description metadata. The checker changes only its source-debt checksum. |
| Focused documentation checks | All three modules have zero source-scanner documentation findings and pass Ruff `D`/`ANN401` with the Google convention and formatting checks. |
| Exact debt reconciliation | Retired 80 original documentation obligations: five summaries and 75 sections/parameters. All other entries and original metadata are preserved; the compact inventory has no new or relocated allowances. Function dispositions, exceptions and inferred typing remain unchanged. |
| `make lint format-check typecheck engineering-standards-check architecture-check` | Passed. Ruff and strict mypy cover 136 Python/stub files; the stronger probe matches 686 diagnostics; native stubtest passes over 1,548 modules; source standards and 14 ADRs validate. |
| Full default pytest selection | 663 passed, 9 deselected. Covers schema-version readiness, dependency purposes, KPI percentiles and pooled ratios, reporting cutoffs, event retry/overlap rejection, control/evidence references, inventory filtering and lineage, stable CLI/dashboard serialization, and existing domain goldens. |
| `bazel test --config=ci //...` | All 20 test targets passed, including governance reverse dependencies, source/typing standards and domain evidence targets. |
| `pre-commit run --all-files` | Every hook passed, including shared typechecking, source standards, secret scanning, documentation links and all governance policies. |

These are local checks for this slice. The full `make ci-full` lane, hosted CI
and separate integration/performance selections were not run. Step 5 remains
in progress with 1,335 documentation obligations; 798 function dispositions and
686 inferred-typing diagnostics remain later migration work.

## Step 5 validation record — remaining governance value models, 2026-09-05

Validation used a captured working-tree baseline at revision
`26f7cbcff8190e4939b4eb31c5f27d15aa2e647e`, including the pre-existing
program/security/inventory documentation slice. The local governance package
was rebuilt offline as a non-editable install in the pinned environment. Checks
used the existing Cosign and Syft executables on `PATH`. Dependencies, lockfiles,
fixtures, tests, prior model documentation, exception records and inferred-typing
debt remain byte-for-byte unchanged from the captured working tree.

| Check | Observed result |
| --- | --- |
| Executable AST and schema comparison | All six documented modules match their baseline executable ASTs after removing docstrings. All 33 owned Pydantic schemas match except description metadata, and installed modules match repository source. The checker changes only its source-debt checksum. |
| Focused documentation checks | All six modules have zero source-scanner findings and pass Ruff `D`/`ANN401` with the Google convention and formatting checks. Every dedicated governance `models.py` module now has zero documentation findings. |
| Exact debt reconciliation | Retired 22 original documentation obligations: six summaries and 16 sections/parameters. All other entries and metadata are preserved; the compact inventory has no new or relocated allowances. Function dispositions and inferred typing are unchanged. |
| `make lint format-check typecheck engineering-standards-check architecture-check` | Passed. Ruff and strict mypy cover 136 Python/stub files; the stronger probe matches 686 diagnostics; native stubtest passes over 1,548 modules; source standards and 14 ADRs validate. |
| Full default pytest selection | 663 passed, 9 deselected. Includes artifact preparation/signing/verification, wheel-source and bootstrap admission, CI selection/events, remote trust and sharding, topology relationships, immutable models, source standards and existing domain goldens. |
| `bazel test --config=ci //...` | All 20 test targets passed, including governance reverse dependencies, source/typing standards and domain evidence targets. |
| `pre-commit run --all-files` | Every hook passed, including shared typechecking, source standards, secret scanning, documentation links and all governance policies. |
| Change-scope comparison | Only the six selected model modules, the source-debt inventory/checksum and this plan differ from the captured working tree. The existing program/security/inventory source edits are preserved. |

These are local checks for this slice. The full `make ci-full` lane, hosted CI
and separate integration/performance selections were not run. Step 5 remains
in progress with 1,313 documentation obligations; 798 function dispositions and
686 inferred-typing diagnostics remain later migration work.

## Step 5 validation record — CI and remote-execution test contracts, 2026-09-05

Validation used a captured working-tree baseline including both preceding
governance model documentation slices. The local governance package was rebuilt
offline as a non-editable install to include the revised source-debt checksum.
Checks used the pinned environment and the existing Cosign and Syft executables
on `PATH`. Earlier model edits, runtime implementations apart from the checker
pin, policy files, fixture data, dependencies, lockfiles, exceptions and inferred
typing remain byte-for-byte unchanged from the captured working tree.

| Check | Observed result |
| --- | --- |
| Executable AST comparison | All three test modules match their baseline ASTs after removing docstrings. Test bodies, assertions, signatures, monkeypatch targets, fixtures, markers and parametrizations are unchanged. All 50 definitions are documented. |
| Test collection compatibility | The complete ordered list of 672 pytest node IDs matches before/after, including integration and performance selections. All 31 cases in the three documented modules retain their identities. |
| Focused documentation checks | All three modules have zero source-scanner documentation findings and pass Ruff `D`/`ANN401` with the Google convention and formatting checks. |
| Exact debt reconciliation | Retired 158 original documentation obligations: 50 summaries and 108 sections/parameters. Every remaining entry and original metadata is preserved; the inventory changes only by deletion, with the matching checksum update. All 798 function dispositions remain unchanged. |
| `make lint format-check typecheck engineering-standards-check architecture-check` | Passed. Ruff and strict mypy cover 136 Python/stub files; the stronger probe matches 686 diagnostics; native stubtest passes over 1,548 modules; source standards and 14 ADRs validate. |
| Full default pytest selection | 663 passed, 9 deselected. Existing CI selection, ordered preflight, event/failure propagation, CLI dispatch, remote trust, credential-file, sharding and quarantine regressions pass alongside the repository suite. |
| Focused performance selection | `test_ci_policy.py -m performance`: 1 passed, 10 deselected. The 1,000-path selection workload remains within its policy budget. |
| `bazel test --config=ci //...` | All 20 test targets passed, including both owning runner targets, source/debt standards and governance reverse dependencies. |
| `pre-commit run --all-files` | Every hook passed, including shared typechecking, source standards, secret scanning, documentation links and all governance policies. |
| Change-scope comparison | Only the three selected test modules, the source-debt inventory/checksum and this plan differ from the captured working tree. All earlier model documentation edits are preserved. |

These are local checks for this slice. The full `make ci-full` lane, hosted CI,
integration selection and remaining performance tests were not run. Step 5
remains in progress with 1,155 documentation obligations; 798 function dispositions
and 686 inferred-typing diagnostics remain later migration work.

## Step 5 validation record — dependency and artifact test contracts, 2026-09-05

Validation started from clean revision
`ff42310e8910793de69f4506b8efdb9f25713d7b`, which includes the preceding model
and CI/remote-execution test documentation slices. Initial collection failed on
unavailable runtime-package imports. Rebuilding and reinstalling both owned
packages offline as non-editable installs restored all 672 collected cases
before source edits. The governance package was rebuilt again for the revised
debt checksum. Checks used the pinned environment with the existing Cosign and
Syft executables on `PATH`.

| Check | Observed result |
| --- | --- |
| Executable AST comparison | Both test modules match their baseline ASTs after removing docstrings. Assertions, fixture payloads, signatures, process doubles, monkeypatch targets, markers and parametrizations are unchanged. All 75 definitions have documentation. |
| Test collection compatibility | The complete ordered list of 672 pytest node IDs matches before/after, including integration and performance selections. All 129 cases in the two documented modules retain their identities. |
| Focused documentation checks | Both modules have zero source-scanner documentation findings and pass Ruff `D`/`ANN401` with the Google convention and formatting checks. |
| Exact debt reconciliation | Retired 109 original documentation obligations: 70 summaries and 39 sections/parameters. Every remaining entry and original metadata is preserved, with only the matching checksum changed in the checker. All 798 function dispositions and the inferred-typing inventory remain unchanged. |
| `make lint format-check typecheck engineering-standards-check architecture-check` | Passed. Ruff and strict mypy cover 136 Python/stub files; the stronger probe matches 686 diagnostics; native stubtest passes over 1,548 modules; source standards and 14 ADRs validate. |
| Full default pytest selection | 663 passed, 9 deselected. Existing exact-lock admission, vulnerability/Scorecard assessment, source/bootstrap evidence, verifier failure, artifact digest/trust and release-denial regressions pass alongside the repository suite. Synthetic signature fixtures remain distinct from the real repository-admission checks. |
| `bazel test --config=ci //...` | All 20 test targets passed, including both owning supply-chain targets, source/debt standards and governance reverse dependencies. |
| `pre-commit run --all-files` | Every hook passed, including shared typechecking, source standards, secret scanning, documentation links and all governance policies. |
| Change-scope comparison | Only the two selected test modules, source-debt inventory/checksum and this plan differ from the baseline. Earlier documentation, fixture data, runtime implementation apart from the pin, policies, dependencies, lockfiles and exceptions are preserved. |

These are local checks for this slice. The full `make ci-full` lane, hosted CI
and separate integration/performance selections were not run. Step 5 remains
in progress with 1,046 documentation obligations; 798 function dispositions and
686 inferred-typing diagnostics remain later migration work.

## Step 5 validation record — domain and shared model-validation tests, 2026-09-05

Validation used a captured working-tree baseline at revision
`ff42310e8910793de69f4506b8efdb9f25713d7b`, including the pre-existing
dependency/artifact test documentation slice. Both owned packages were rebuilt
offline as non-editable installs in the pinned environment. Checks used the
existing Cosign and Syft tools on `PATH`. The initial sandboxed Bazel command
could not write its external cache; the authorized rerun passed all nine targets.

| Check | Observed result |
| --- | --- |
| Executable AST comparison | All seven test modules match their captured baseline after removing docstrings and normalizing source-line positions in type-ignore records. Suppression tags, assertions, fixture payloads, signatures, process doubles, monkeypatch targets, markers and parametrizations are unchanged. All 120 definitions have documentation. |
| Test collection compatibility | All 672 ordered pytest node IDs match before/after, including integration and performance selections and the 168 cases in these seven modules. |
| Focused documentation checks | All seven modules have zero source-scanner documentation findings and pass Ruff `D`/`ANN401` with the Google convention and formatting checks. |
| Exact debt reconciliation | Retired 109 existing documentation obligations: 71 summaries and 38 sections/parameters. Every remaining entry and original metadata is preserved. The checker changes only its matching checksum; installed source matches the working tree. |
| `make lint format-check typecheck engineering-standards-check architecture-check` | Passed. Ruff and strict mypy cover 136 Python/stub files; the stronger typing inventory matches 686 diagnostics; native stubtest passes over 1,548 modules; source standards and all 14 ADRs validate. |
| Full default pytest selection | 663 passed, 9 deselected. Includes existing goldens, exact arithmetic, native exception translation, temporal boundaries, immutable models, nested revalidation, evidence binding and governance regressions. |
| Domain performance selection | 3 passed, 156 deselected across the three unit-test modules. Existing ten-thousand-operation rounding, identifier-resolution and market-state workloads pass their local budgets. |
| Owning Bazel targets | All nine selected targets passed under `--config=ci`: the three domain unit targets, their three evidence targets, Python source/debt standards, Python typing and engineering standards. |
| `pre-commit run --all-files` | Every hook passed, including shared typechecking, source standards, secret scanning, documentation links and all governance policies. |
| Change-scope comparison | Only the seven selected test modules, source-debt inventory/checksum and this plan differ from the captured working tree. Prior supply-chain edits, runtime implementations, policies, fixture data, dependencies, lockfiles, exceptions, function dispositions and inferred typing are preserved. |

This is an R0 documentation-only slice: no capital exposure, data/model change
or privilege change, with immediate reversal by reverting its docstrings, debt
deletions/checksum and plan entry together. These are local checks; `make ci-full`,
hosted CI, integration selection and non-domain performance selections were not
run. Step 5 remains in progress with 937 documentation obligations; 798 function
dispositions and 686 inferred-typing diagnostics remain later migration work.

## Step 5 validation record — risk, ownership and evidence tests, 2026-09-05

Validation used a captured working-tree baseline at revision
`ff42310e8910793de69f4506b8efdb9f25713d7b`, preserving the preceding uncommitted
supply-chain and domain-test documentation slices. Three Luna subagents used
`gpt-5.6-luna` with `xhigh` reasoning for separate writing assignments. The main
agent audited their completed drafts, requested corrections, inspected the revised
docstrings and ran the combined checks. The governance package was rebuilt
offline as a non-editable install for the revised checksum; the runtime package
remained installed. Checks used the pinned environment and existing Cosign/Syft
executables on `PATH`.

| Check | Observed result |
| --- | --- |
| Documentation audit | General software, risk tier 0, focused on the repository's Python/Google documentation contract. All added prose was compared with assertions, defaults, return shapes, mutations, file/process side effects and relevant validators. Model-only validation, retained finding records, R0 approval scope, actual heading mutation and propagated failures were clarified; no actionable findings remain in the five modules. |
| Executable AST comparison | All five modules match their captured baseline after stripping docstrings and normalizing type-ignore source-line positions. Assertions, annotations, suppression metadata, signatures, fixtures, subprocess arguments, markers and parametrizations are unchanged. All 101 definitions have documentation. |
| Test collection compatibility | All 672 ordered pytest node IDs match before/after, including all 146 cases in the five documented modules and the integration/performance selections. |
| Focused documentation checks | All five modules have zero source-scanner documentation findings and pass Ruff `D`/`ANN401` with the Google convention and formatting checks. |
| Exact debt reconciliation | Retired 97 original obligations: 93 summaries and four sections/parameters. Every remaining entry and original metadata is preserved. The checker changes only its matching checksum, and the installed checker matches repository source. |
| `make lint format-check typecheck engineering-standards-check architecture-check` | Passed. Ruff and strict mypy cover 136 Python/stub files; the stronger typing inventory matches 686 diagnostics; native stubtest passes over 1,548 modules; source standards and all 14 ADRs validate. |
| Full default pytest selection | 663 passed, 9 deselected. Includes classification/approval reuse, canonical identities, ownership, hosted-event CLI simulation, evidence tampering, schema/error contracts, exact package profiles, distribution metadata and existing domain regressions. |
| Ownership integration selection | 1 passed, 19 deselected. The actual pre-commit ownership hook rejects the staged unowned root path in the temporary Git repository. |
| `bazel test --config=ci //...` | All 20 targets passed, including the shared governance checker and its reverse dependencies; 12 executed and eight reused valid cached results. The documented governance tests also ran through the default pytest suite and the dedicated integration selection above. |
| `pre-commit run --all-files` | Every hook passed, including shared typechecking, source standards, secret scanning, documentation links and all governance policies. |
| Change-scope comparison | Only the five selected test modules, source-debt inventory/checksum and this plan differ from the captured working tree. Prior edits, runtime implementations, policy/configuration files, fixtures, dependencies, lockfiles, exceptions, function dispositions and inferred typing are preserved. |

This is an R0 documentation-only slice with no capital, data/model or privilege
change. Reversal restores this slice's docstrings, debt entries/checksum and plan
record together. These are local checks; `make ci-full`, hosted CI, other
integration tests and separate performance selections were not run. Step 5 remains
in progress with 840 documentation obligations; the 798 function dispositions and
686 inferred-typing diagnostics remain later migration work.

## Step 5 validation record — remaining governance tests, 2026-09-05

Validation used a captured clean working-tree baseline at revision
`7ccbc92d6470e3f5df41df0c5753017d92791158`. Three Luna subagents used
`gpt-5.6-luna` with `xhigh` reasoning for separate writing assignments. The main
agent audited the drafts, requested corrections, inspected the revised prose,
and ran the combined checks. The governance package was rebuilt for the revised
checksum; final root checks and pytest used non-editable packages with
`UV_NO_EDITABLE=1`, the pinned environment, and existing Cosign/Syft executables
on `PATH`.

| Check | Observed result |
| --- | --- |
| Documentation audit | General software, risk tier 0, against the repository's Python/Google documentation contract. Added and revised prose was compared with function bodies, assertions, loader boundaries, fixture mutations, returns, exceptions and file/process side effects. The corrections described above resolve all actionable findings in the eight modules. |
| Executable AST comparison | All eight modules match the captured baseline after stripping docstrings and normalizing type-ignore source-line positions. Signatures, annotations, assertions, markers, parametrizations, fixtures, subprocess arguments and suppression metadata are unchanged. All 125 definitions have documentation. |
| Test collection compatibility | All 672 ordered pytest node IDs match before/after, including the 124 cases in the eight documented modules and the integration/performance selections. |
| Focused documentation checks | All eight modules have zero source-scanner documentation findings and pass Ruff `D`/`ANN401` with the Google convention and formatting checks. |
| Exact debt reconciliation | Retired exactly 116 original summary obligations. Every remaining entry and original metadata is preserved. The checker changes only its matching checksum; the installed checker matches repository source and the inventory bytes. |
| `make lint format-check typecheck engineering-standards-check` | Passed. Ruff and strict mypy cover 136 Python/stub files; the stronger typing inventory matches 686 diagnostics; native stubtest passes over 1,548 modules; source standards validate. |
| Full default pytest selection | 663 passed, 9 deselected with non-editable packages. Includes all selected default tests, deterministic governance outputs, policy and reference rejection, CLI contracts, existing domain goldens and native regressions. |
| Affected performance selection | 4 passed, 83 deselected across engineering standards, inventory, program governance and topology. Existing suppression-validation, inventory-query, observation-aggregation and topology-validation workloads pass their local budgets. |
| `bazel test --config=ci //...` | All 20 targets passed; 12 executed and eight reused valid cached results. Covers the changed engineering-standards test target and the shared checker with its reverse dependencies. The other documented modules also ran through pytest above. |
| `pre-commit run --all-files` | Every hook passed, including shared typechecking, source standards, secret scanning, documentation links and all governance policies. |
| Change-scope comparison | Only the eight selected test modules, source-debt inventory/checksum and this plan differ from baseline. Runtime behavior, policy/configuration files, fixtures, dependencies, lockfiles, exceptions, function dispositions and inferred-typing inventory are preserved. |

This is an R0 documentation-only slice with no capital, data/model or privilege
change. Reversal restores this slice's docstrings, debt entries/checksum and plan
record together. These are local checks; `make ci-full`, hosted CI, integration
execution and other performance selections were not run. Step 5 remains in
progress with 724 documentation obligations; 798 function dispositions and 686
inferred-typing diagnostics remain later migration work.

## Step 5 validation record — remaining build tests and fixtures, 2026-09-05

Validation used a captured clean working-tree baseline at revision
`c2d25d787d0a26590ad17e0564f9056a0210bb54`. Three Luna subagents used
`gpt-5.6-luna` with `xhigh` reasoning for separate writing assignments. The main
agent audited every added or revised docstring against the implementation,
assertions, fixture mutations, file/process side effects, expected command
statuses and propagated exceptions, then requested and reviewed revisions for
selected sandbox probes, lexical path checks, Buf nonzero-status interpretation
and I/O/decoding exceptions. Both installed packages were non-editable; the
governance package was rebuilt offline, and the installed checker matches the
repository source and checksum pin byte-for-byte.

| Check | Observed result |
| --- | --- |
| Documentation audit | General software, risk tier 0, against the repository's Python/Google documentation contract. No actionable findings remain in the five modules. |
| Executable AST comparison | All five modules match the captured baseline after stripping docstrings. Definitions, signatures, assertions, imports, constants, process arguments and file operations are unchanged; all 11 definitions have documentation. |
| Test collection compatibility | The complete ordered list of 672 pytest node IDs matches before/after. These five build entrypoint modules contribute no pytest cases and run through Bazel. |
| Focused documentation checks | All five modules have zero source-scanner PYD findings and pass Ruff `D`/`ANN401` with the Google convention and formatting checks. |
| Exact debt reconciliation | Retired exactly 16 original documentation obligations: 11 PYD001 summaries and five PYD002 Returns sections. The source inventory now holds 1,506 obligations across 73 files: 708 documentation obligations (256 summaries and 452 sections/parameters) and 798 function dispositions. The inferred typing inventory remains at 686 diagnostics; every other entry and its metadata are unchanged, and the checksum pin matches. |
| `make lint format-check typecheck engineering-standards-check` | Passed. Ruff and strict mypy cover 136 Python/stub files; the inferred typing inventory matches 686 diagnostics; native stubtest passes over 1,548 modules. |
| Full default pytest selection | The initial direct `.venv/bin/pytest` run had one environment failure because `PATH` lacked `.venv/bin`; the `uv run --frozen --no-editable pytest -q` rerun with `UV_NO_SYNC=1` and `UV_OFFLINE=1` passed 663 tests with 9 deselected. |
| `bazel test --config=ci //...` with `UNDECLARED_HOST_SECRET` sentinel | The initial sandbox run could not write the external cache; the authorized rerun passed all 20 targets, with 16 executed and four reused from cache. |
| `pre-commit run --all-files` | Passed every hook, including mypy and source standards, documentation links and architecture checks, secret scanning and all governance policies, using the pinned non-editable environment with existing Cosign/Syft tools and temporary caches. |
| Change-scope comparison | Only the five selected test modules, source-debt inventory/checksum and this plan differ from the baseline. Runtime behavior is unchanged; no configuration, fixture, dependency, lockfile, exception, typing or function-disposition changes were made. |

This is an R0 documentation-only slice with no capital, data/model or privilege
change. Reversal restores this slice's docstrings, debt entries/checksum and plan
record together. These are local checks; `make ci-full`, hosted CI, integration
execution and performance selections were not run. Step 5 remains in progress
with 708 documentation obligations; 798 function dispositions and 686
inferred-typing diagnostics remain later migration work.

## Step 5 validation record — governance operation entrypoints and helpers, 2026-09-05

Validation used captured working-tree revision
`c2d25d787d0a26590ad17e0564f9056a0210bb54`, including the uncommitted eleventh
build-test/fixture slice; the baseline was not clean. Three
`gpt-5.6-luna` writers used `xhigh` reasoning for separate assignments. The parent
agent completed the semantic audit and corrections. The governance package was
rebuilt offline as a non-editable install; all 14 installed files and the checker
match the working tree byte-for-byte, and the runtime package remains installed
non-editably.

| Check | Observed result |
| --- | --- |
| Documentation audit | General software, R0, with no remaining actionable findings. All 51 definitions have documentation; 12 Typer callback docstrings remain deliberately unchanged. |
| Executable AST and CLI comparison | All 14 executable ASTs match after stripping docstrings and normalizing type-ignore line offsets. All 12 root/subcommand help outputs and statuses are unchanged. |
| Test collection compatibility | The complete ordered list of 672 pytest node IDs is unchanged. |
| Focused documentation checks | The source checker reports zero PYD findings in all 14 modules; Ruff `D`/`ANN401` with the Google convention and `ruff format --check` pass. |
| Exact debt reconciliation | Retired 93 obligations: 16 PYD001 summaries and 77 PYD002 sections/parameters (69 total in CLI/shared modules and 24 total in secret scanning/sharding). The remaining inventory has 1,413 obligations across 73 files: 615 documentation obligations (240 summaries and 375 sections/parameters) and 798 function dispositions; inferred typing remains at 686 diagnostics. |
| `make lint format-check typecheck engineering-standards-check` | Passed across 136 Python/stub files; the 686-diagnostic typing inventory matches and native stubtest covers 1,548 modules. |
| Default pytest | `uv run --frozen --no-editable pytest` passed 663 tests with 9 deselected. |
| Bazel | With the host sentinel and authorized external cache, `bazel test --config=ci //...` passed all 20 targets: 13 executed and 7 cached. |
| Pre-commit | `pre-commit run --all-files` passed every hook, including strict typing, source standards, architecture/documentation links, secret scanning and governance policies. |
| Change scope | Only the 14 docstring targets, exact debt deletion/checksum and this plan changed. Tests, fixtures, configuration, dependencies, lockfiles, exception records, function dispositions and typing inventory were unchanged. |

The semantic audit corrected CLI failure ordering and caught-versus-propagated
errors, current-working-directory versus selected-root paths, optional argument
defaults, program status overwrites and aggregation, metadata-version versus
PATH-scanner behavior, process/service timeout contracts, secret-scan pre-read
checks and race limitations, and empty stable-shard results. Reversal restores the docstrings,
debt deletions/checksum and this plan record together. Step 5 remains in progress
with other governance operations; moved workflows remain combined with step-6
service slices. Hosted CI, `make ci-full`, separate integration and performance
lanes were not run.
