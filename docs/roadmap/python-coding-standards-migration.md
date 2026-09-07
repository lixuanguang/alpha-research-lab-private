# Python coding standards audit and migration plan

Audit date: 2026-09-05. Original audit baseline revision:
`d3a40ca98d71208426c8501d8d4a1aaaa049768d`.

Status: steps 1–5 are implemented; step 6 remains in progress and step 7 remains
planned. Step 5 closed the existing-source documentation queue in 31 slices on
2026-09-06; its completion snapshot recorded 798 `PYC001` dispositions across
73 files, no `PYD001` or `PYD002`, and 686 inferred-typing diagnostics. The
current Step-6 slice leaves 647 `PYC001` dispositions across 57 files and 533
inferred-typing diagnostics.
Step 6 has completed the change-risk pilot and the program loading/status service
extraction, including the residual package-state and local-evidence workflows.
Queue item 2 is complete, and queue item 3 has completed security-control map
loading and validation. Inventory loading is next. Remaining helper dispositions
stay in queue item 8. The financial settlement-convention service in queue item 7
is also implemented, with the remaining CLI and policy work still open.
The earlier CLI slice preserves 12
Typer callback docstrings as help contracts, and documentation for moved workflows
remains combined with their step-6 service slices.
The financial-model boundary and associated unit-test slice in queue item 8 is
also implemented; its remaining Hypothesis decorator typing is explicitly tracked.
The instrument-identity model and associated unit-test slice in queue item 8 is
also implemented, with six existing Hypothesis decorator diagnostics retained.
The venue-calendar adapter, models and associated unit/evidence-test slice is
also implemented, with its six existing Hypothesis decorator diagnostics retained.
The `tests/build` workflows and associated contract tests in queue item 8 are
also implemented, with no remaining source or inferred-typing debt in that scope.
The nine residual dataclasses in the Python source scanner and security-control
map loader now use Pydantic models, preserving mutable invocation state where needed.

See the [consolidated step-5 validation record](#step-5-validation-record-consolidated-completion-2026-09-06)
for evidence recorded at completion.

The findings below describe the original audited revision, before step-1
enforcement.

The requested target is segregated, commented import groups; stringent typing
without `Any`; useful Google-style docstrings; and a preference for classes over
standalone functions, with small low-level operations remaining functions.
The last requirement reflects the user's clarification. New or migrated data
records use Pydantic `BaseModel`, not dataclasses; workflow services use ordinary
classes with explicit typed constructors.

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
| 5. Document existing contracts — implemented | Closed the existing-source documentation queue in 31 doc-only slices across domain, governance, test, policy, helper, loader, runner and artifact contracts. Moved workflows remain step 6; global rule activation remains deferred. | Final scan: zero `PYD001`/`PYD002`; 798 `PYC001` dispositions across 73 files; inferred typing remains at 686 diagnostics. See the consolidated Step-5 validation record below. |
| 6. Refactor workflows into classes — in progress | Implemented the change-risk classifier and approval evaluator, program loading/status services, residual program workflows, security-control map loader and financial settlement conventions while retaining the public function APIs. Queue items 1 and 2 are complete; inventory loading is next in queue item 3. The settlement responsibility in queue item 7 and financial-model/test, instrument-identity-model/test and venue-calendar source/test portions of queue item 8 are complete. Depends on steps 2–4 for the owning package. | The completed slices preserve schemas, serialized results, ordered findings, exception boundaries, evidence and CLI contracts. See the step-6 records below. |
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

### Step 5 implementation — completion summary

Step 5 was completed on 2026-09-06 through 31 documentation-only slices covering
existing runtime, governance, test, policy, helper, loader, runner and artifact
contracts. The source docstrings were reviewed against their bodies, helpers,
models, callers and tests. Detailed function behavior remains documented in the
source modules; this summary records scope and progression without repeating each
function contract.

| Slices | Scope |
| --- | --- |
| 1–5 | Financial-unit, symbology, calendar, identity/calendar and shared governance model contracts |
| 6–11 | CI/remote tests, dependency/artifact tests, domain/model-validation tests, risk/ownership/evidence tests, remaining governance tests, and build tests/fixtures |
| 12–18 | CLI/shared entrypoints, governance operations and policies, architecture/ownership/standards helpers, registries, operation helpers, and CI/remote selection helpers |
| 19–23 | CI event/checkout, evidence parsing, security/inventory/topology registries, private governance helpers, and public Git/audit/status contracts |
| 24–29 | Validation/preflight, admission/package evidence, policy loading/repository validation, public architecture/evidence and registry contracts, and program/MR contracts |
| 30–31 | CI/remote runner contracts and public artifact bundle contracts |

Across the completed slices, executable ASTs, runtime APIs, dependencies, locks,
global tool settings and class boundaries were preserved. Expanded model docstrings
may change generated schema descriptions; schema fields and serialized model values
remain unchanged. Twelve Typer callback docstrings remain as help contracts. Exact
resolved documentation entries were retired together with their checksum updates.
No global rule activation or runtime fix was introduced. Migrations that move workflows
remain in step 6, and step 7 remains planned.

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

At the time of this 2026-09-05 pilot record, Step 6 remained in progress and
program loading/status was the next queue item. That statement is a historical
snapshot; the program loading/status service extraction is recorded below. Queue
item 2 remains in progress while residual contextual validation helpers are moved
behind an owning service, followed by the remaining loaders, evidence/bundle
services and CI runners.
After this pilot, the source inventory held **2,557** obligations across 84 files: 712 missing
summaries, 1,047 structured-documentation findings and 798 function dispositions.
The inferred inventory held **686** diagnostics, 356 identities across 49 files.
Step 7 must also reassess compatibility wrappers and the retained helpers before
their exceptions expire.

### Step 6 implementation — program loading/status service slice

`ProgramRepository` now owns explicit repository and optional ownership-register
context. Its constructor performs no file I/O or validation; `load_program`,
`load_observations`, and `validate_repository` create operation-local parsing and
validation state so a failed call cannot contaminate a later call on the same
instance. The repository service composes `RoadmapParser` for the ordered
96-package Markdown graph and `ObservationReader` for one immutable program's
bounded JSONL KPI contract.

`RoadmapParser.parse` retains wave placement, package-order, dependency-purpose,
unknown-reference, self-reference and cycle checks. `ObservationReader(program).read`
retains metric-specific fields, duplicate-event handling, UTC windows, bounded
ratios, dimensions, evidence URLs, observation limits and overlap checks while
returning unique observations in first-seen order. `ProgramStatusRenderer` owns
deterministic Markdown rendering and exact decoded UTF-8 document validation after
universal-newline translation; its
constructor performs no I/O and its repeated renders and validations derive their
state from the immutable program model.

The existing `load_roadmap`, `load_program`, `load_observations`,
`validate_repository`, `render_status_markdown`, and `validate_status_document`
functions remain compatibility wrappers with their existing signatures and
failure translation boundaries. `RoadmapParser`, `ProgramRepository`,
`ObservationReader`, and `ProgramStatusRenderer` are exported through both
the canonical governance package and the `src/alpha_research` facade. Focused
regression coverage also exercises repeated renderer failures, loader error
translation, parser boundaries, and the public class exports.

At completion, this slice left queue item 2 open because `_parse_package_states`
and `_validate_local_evidence` still needed service ownership. The following
slice closes those residual workflows.

### Step 6 implementation — package-state and local-evidence ownership

The private `_PackageStateParser` binds the resolved repository root, ownership
roles, schema version and optional operating model without performing I/O. Its
`parse` method creates a fresh evaluation date and state collection for each call.
Separate methods parse one state, validate its evidence, resolve versioned
implementation governance and check package ordering. Schemas 1–3 retain their
UTF-8 evidence-content checks; schema 4 retains its single existing Markdown
capability path requirement without reading that file's content.

`ProgramRepository` now owns local-evidence validation as a private method using
the root resolved for the current operation. Policy and manifest failures retain
the A08 error prefix and chained cause; package-profile failures retain their
ordered findings and original cause. Program loading, evidence validation and
generated-status validation still run in that order. Neither service caches
invocation findings or performs fallible work during construction.

The two old private module functions were removed, retiring exactly two
`PYC001` entries and updating the checksum without adding exceptions or migration
allowances. Public functions, facade exports and schemas are unchanged. This
closes queue item 2's workflow extraction; the remaining helper
dispositions are part of queue item 8. Luna subagents at extra-high reasoning
implemented the source and focused regression tests, followed by the parent
agent's code, behavior and documentation audit.

### Step 6 implementation — security-control map loader

`SecurityControlMapLoader` binds repository and optional ownership-register paths
without I/O. Its `load` method reads ownership first, parses the fixed metadata
and ordered record collections, and creates a fresh typed validation context.
Separate methods apply identifier, structural-reference, evidence,
authority/mapping, coverage, package-finding and local-evidence-metadata checks
in the original order before constructing the immutable map. Findings, used
roles and lookup indexes belong to that invocation. Authority freshness and
legal-review horizons continue to use the map's recorded `as_of_date`.

`validate_repository` binds the operation to its first resolved root, loads the
authoritative map with the configured ownership register, and validates the
manifest, artifacts and fixed A07 evidence profile. Retargeting an input root
symlink affects a later invocation without mixing repository contexts within
the current call. The parent audit identified and corrected this boundary while
the Luna subagents implemented the service and focused regression tests.

The service is exported through the canonical package and both compatibility
facades. `load_control_map` retains its signature and Pydantic-error translation;
the private `_load_control_map` wrapper retains the existing validation-error
injection seam. The public `validate_repository` function delegates to the
service. Three fingerprinted compatibility dispositions replace their migration
entries, and removal of the module-level local-evidence workflow retires a fourth
entry. Other inventory metadata and existing exceptions are preserved. Small
record parsers remain for the helper-disposition work in queue item 8.

This slice completes security-control loading within queue item 3. Inventory
loading remains the next bounded slice.

### Step 6 implementation — financial settlement conventions

`SettlementConventions(calendar)` owns business-day adjustment and T+n lag
calculation against one independently revalidated, immutable C02 calendar copy.
Construction rejects invalid calendar instances without I/O. Adjustment and lag
state remain local to each operation, so failed calls do not affect later uses.
The service is exported from `alpha_research.financial_units`.

The exported `adjust_business_day` and `settlement_date` functions retain their
signatures and delegate to the service. Narrow compatibility guards retain
candidate/calendar/convention error precedence and reject invalid lags first.
Coverage remains explicit: modified adjustments cannot reverse direction until
the primary search succeeds, and positive lags count eligible dates strictly
after the adjusted anchor. QuantLib day counts, result models, rounding and
native dependency contracts are unchanged.

This bounded slice completes the settlement-convention responsibility in queue
item 7. Other CLI and policy workflows in that item remain open; inventory
loading remains next in queue item 3.

Ten existing convention tests now belong to contract-oriented classes. The
shared golden reader and calendar factory retain narrow low-level dispositions;
the additive-day-count Hypothesis callback retains a framework disposition and
its separately tracked upstream typing debt. Together with two compatibility
wrappers, these five fingerprinted exceptions retire 15 migration entries
without adding allowances. Typed native-version callbacks and a typed calendar
update retire three inferred diagnostics. Unrelated arithmetic/model tests and
the mixed C01/C02 boundary test remain unchanged for later migration slices.

### Step 6 implementation — financial model boundaries and test contracts

The financial value models already own construction, validated replacement and
dimension-aware arithmetic. This slice strengthens those existing boundaries:
constructor error details pass through a strict record containing only locations
and messages, and reflected field reads have an explicit raw-value contract before
reconstruction validates them. Error inputs, URLs and unused exception context
are excluded from the error-detail conversion; the original validation exception
remains the cause of the owned error.

`require_type`, `require_decimal`, `exact_decimal` and `round_fraction` remain
small low-level validation and arithmetic kernels. Their source-bound dispositions
record why they remain functions. The financial arithmetic and model tests are
grouped by contract, with the existing Hypothesis callback identities retained.
This is the financial-model and associated unit-test portion of queue item 8;
the broader migration remains in progress.

### Step 6 implementation — instrument-identity models and test contracts

`_InstrumentIdentityModel` now owns constructor error translation. A typed reader
exposes raw Pydantic error details for immediate validation into precise location,
message and optional context records. The boundary retains original exception
objects, preserving the distinction between owned identity failures and ordinary
subclass validator failures, ordered messages and chained causes. Inputs and URLs
remain excluded. The public value models, constructors, schemas, serialization,
UTC interval semantics and trusted construction/copy entry points are unchanged.

The golden-fixture loader owns strict typed JSON loading and catalog construction
through a named factory. Its constructor binds already-built state. Non-property
tests are grouped into golden, model-boundary and catalog-validation contract
classes. Both Hypothesis callbacks retain their original pytest node identities.
The eleven UUID, text, namespace, checksum and UTC helpers remain small stateless
functions with individual source-bound dispositions, alongside dispositions for
the two retained property callbacks.

This slice retires 32 source migration obligations and ten inferred diagnostics.
Six existing Hypothesis decorator diagnostics remain in the exact typing inventory;
no new or relocated typing allowance is introduced. Step 6 remains in progress
outside this model and unit-test slice.

### Step 6 implementation — venue-calendar ownership and test contracts

`ExchangeCalendarsAdapter` now directly owns source loading, session adaptation
and override application. Private test-only forwarding functions are removed;
the exported adapter API and the existing native stubs are unchanged. Read-only
source protocols use the pinned stub contract, and timestamp conversion keeps
raw values at the boundary until runtime validation establishes their types.

`_VenueCalendarModel` owns error-message translation through strict validated
error-detail records. Typed session keys preserve sorting and bisect behavior.
The unit tests now use calendar contract classes and precise fixture/payload
records; the C02 evidence assertion belongs to its own test class. Ten low-level
source helpers and two retained Hypothesis callbacks have individual fingerprinted
dispositions. All 48 source obligations for this slice are retired, together with
34 inferred diagnostics. The six original Hypothesis decorator diagnostics remain
explicitly tracked without changing their identities or multiplicities.

This completes the venue-calendar source and associated unit/evidence-test portion
of queue item 8. Step 6 remains in progress elsewhere.

### Step 6 implementation — build checks and associated test contracts

`BuildGraphValidator(root)` and `DeveloperEnvironmentContractChecker(root)` now
own build, dependency, environment, lock and evidence validation. Constructors
bind context without I/O; each invocation owns its findings. Dependency/tool
field checks, environment-file checks, mutation probes and bootstrap checks have
separate methods. Typed parser boundaries narrow raw values before field checks
without casts or new suppressions.

`BufCompatibilityCheck`, `BufToolchainCheck`, `GeneratedSqlCheck` and
`SandboxInputCheck` own the fixture workflows. Their six existing `main()`
entry points retain Bazel target identities, command arguments, runfiles,
subprocess environments, error ordering and exit behavior. Five new contract-test
modules cover recovery after failure, malformed gates, subprocess isolation and
cleanup, and SQL/sandbox diagnostics, with explicit Bazel dependencies and suite
membership. The sandbox probe keeps its original isolated runfiles.

The build validation result is a strict, frozen Pydantic `BaseModel`, with direct
Pydantic dependencies declared on its two Bazel targets. The four fixture
services use explicit typed constructors without dataclasses. The Python guide
records this model/service distinction and the Pydantic preference for future
migration slices.

The audit also closes a malformed-input gap in both evidence checks: an extra
non-table gate now yields the existing applicable-gates finding instead of being
ignored, and an unhashable gate ID yields that finding instead of `TypeError`.
Missing or other invalid gate IDs continue to fail. These deliberately tightened
cases have dedicated regression coverage; retained evidence and goldens are
unchanged.

All 19 source obligations and all 65 inferred diagnostics across 21 identities
retire from `tests/build`. Twenty individual fingerprinted dispositions cover
the six entry points and their small parsing, path, runfiles and process helpers.
This completes the `tests/build` portion of queue item 8; step 6 remains in
progress elsewhere.

### Class migration queue

Paths below are relative to `tools/governance/src/alpha_research_governance` unless
prefixed with `src/`. Names are proposed responsibilities, not mandatory new files.

| Order / current area | Proposed responsibility | Compatibility and behavior to preserve |
| --- | --- | --- |
| 1. `change_risk/classification.py`, then `approvals.py` — implemented | `ChangeRiskClassifier(policy)` and `ChangeRiskApprovalEvaluator(policy)`, with invocation-local state. | Highest-dimension rule, downgrade rejection, gate ordering, founder/team rules and exact errors preserved; existing classification/approval functions delegate temporarily. |
| 2. `program_governance/registry.py`, `status.py` — implemented | `ProgramRepository` for loading and local-evidence validation with explicit root/ownership context; distinct roadmap parsing, observation reading, status rendering and private package-state parsing responsibilities. Remaining helper dispositions belong to queue item 8. | Schema versions 1–4, dependency purposes/cycles, finding mapping, deterministic status text and existing exported loaders. |
| 3. `security_controls/registry.py`, `inventory/registry.py` — in progress (security loader implemented) | `SecurityControlMapLoader` owns security-map and local-evidence validation with explicit repository context. `InventoryLoader` is next; pure field/ID parsing stays small. | Error categories, complete references, source identity, ownership and deterministic findings. |
| 4. `repository_topology/registry.py`, `engineering_standards/policy.py`, `dependency_admission/policy.py`, `ownership_governance.py`, `architecture_governance.py` | Domain-specific loaders/validators with explicit repository context. Share only proven identical parsing primitives. | Exact accepted schema and policy values, expiry/version checks, local link safety, exception translation and root commands. |
| 5. `evidence/manifest.py`, `mr.py`, `package.py`, `artifact_supply_chain/bundle.py` | Separate evidence validation, bundle creation and bundle verification services. | Digest/path validation, operation and revision binding, malformed-input rejection, file write boundaries and signature behavior. |
| 6. `ci_policy/runner.py`, `selection.py`, `remote_execution/runner.py` | `CIRunner` and `RemoteExecutionRunner`; use a typed command-execution collaborator where injection is useful. | Fast/full selection, exact argv/environment, trust/secret checks, exit codes, event contents/order and safe fallback. |
| 7. Remaining CLI modules, policies and `src/alpha_research/financial_units/conventions.py` — settlement service implemented | Thin CLI callbacks delegating to services remain; `SettlementConventions(calendar)` now owns settlement adjustment and lag operations. | Console scripts, `python -m` entry points and facade imports; settlement date/coverage errors; keep arithmetic and conversion kernels small. |
| 8. `tests/` and residual source helpers — `tests/build` slice implemented | Contract-oriented test classes and a completed function-disposition inventory. Build/environment/fixture workflows now have explicit service ownership; remaining test and source-helper scopes stay open. | Pytest/Bazel collection, parametrization, fixtures, markers, external selectors and meaningful failures. |

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

## Step 5 validation record — consolidated completion, 2026-09-06

This record consolidates the completion evidence captured across the 31 Step-5
slices. The results below were recorded at Step-5 completion; this condensation
does not constitute a new runtime validation run. The final slice baseline was HEAD
`7d3c3bdc92c5d975b03488edaca595bb0eabac4e` with the complete uncommitted slice
30; the final debt checksum is
`68f450c0e20904b1ca06cff9880f06e733b80cf75e1a71c60ede38a7c15f10a9`.

| Check | Recorded result |
| --- | --- |
| Documentation and semantic audit | All 31 slices were reviewed against source bodies, helpers, models, callers and tests. The final full tracked-source scan covered 131 `.py` files and found zero `PYD001` or `PYD002`; no actionable documentation findings remain. |
| Debt and typing inventories | The final inventory contains 798 `PYC001` dispositions across 73 files and no `PYD001`/`PYD002`; the separate inferred-typing inventory remains at 686 diagnostics across 356 identities and 49 files. |
| Source and schema compatibility | Documentation-only slices preserve executable ASTs, runtime APIs, dependencies, locks, global tool settings and class boundaries. Expanded model docstrings can change generated schema descriptions; schema fields and serialized instance values remain unchanged. |
| Help and collection compatibility | Twelve Typer callback docstrings remain as help contracts, and all 672 ordered pytest node IDs are unchanged. |
| Lint, format and type checks | Lint/format checks cover 136 Python/stub files; strict mypy covers the same 136 files; native stubtest covers 1,548 modules; the stronger 686-diagnostic inventory matches. |
| Tests | Recorded result: 663 tests passed with 9 deselected. This cleanup did not rerun the suite. |
| Bazel | Recorded result: all 20 Bazel targets pass under the configured CI lane. |
| Hooks and architecture | All pre-commit hooks passed, including source standards, typing, governance, dependency/lock and secret checks; architecture governance and local links passed for 14 ADRs. |
| Package provenance | Both owned packages remained non-editable, and the recorded installed-source/checker provenance matched the audited working tree after the final corrections. |
| Scope and deferred evidence | No global rule activation was included. Real signing, registry publication, hosted CI, `make ci-full`, and separate integration/performance selections were not run. |

The concise rollback principle remains per slice: restore the affected docstrings,
matching exact debt deletions and checksum, and this roadmap record together. No
persisted-data migration or runtime fix is part of Step 5. Step 5 existing-source
documentation is complete. At Step-5 completion, the recorded 2026-09-06 snapshot
described program loading/status as next in Step 6; that historical statement
predates the current service extraction. Step 6 remains in progress and Step 7
global adoption remains planned.

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
hosted CI and separate integration/performance selections were not run. At the
time of this 2026-09-05 pilot record, program loading/status was next in the
queue; that historical statement predates the current service extraction.
Queue item 2 remains in progress as recorded below.

## Step 6 validation record — program loading/status service slice, 2026-09-06

Validation compared the completed service code with the captured baseline at
revision `6f9e7d4287af9c1dedd71203b834813465624bcb`. The comparison covered
successful and malformed policy records, legacy schemas, roadmap and dependency
mutations, observation boundary events, repository validation, deterministic
status rendering, status-file validation, and the recorded CLI cases.

| Check | Observed result |
| --- | --- |
| Differential behavior | All 2,843 cases matched the baseline: 1,644 program-load cases, 482 roadmap cases, 698 observation cases, three legacy-schema cases, one repository-validation case, one status-render case, five status-file-validation cases, and nine CLI cases. Comparisons include return values, exception types, exception-cause types, exact exception messages, ordered findings, rendered status text, exit codes, stdout and stderr. |
| Focused governance and model tests | 42 passed, one deselected across `test_program_governance.py` and `test_pydantic_models.py`, including repeated renderer failures, loader error translation, parser boundaries and public service exports. |
| Full pytest and collection compatibility | 668 passed, 9 deselected. All 663 existing default-selected pytest node IDs remain in order, and five service tests were added. |
| Public API compatibility | All six public function signatures remain unchanged. The four service classes are exported through both the canonical governance package and the `src/alpha_research` facade. |
| Repository lint, format, type and standards checks | `make lint format-check typecheck engineering-standards-check` passed over 136 Python/stub files. Native stubtest passed over 1,548 modules. Scoped Ruff checks passed for the affected governance package, compatibility facades and tests; the Google-docstring/`ANN401` check also passed for `registry.py` and `status.py`. |
| Source-standard reconciliation | Exactly 11 existing `PYC001` function dispositions were retired into reviewed, fingerprinted exceptions: nine compatibility wrappers and two small status helpers. The current inventory contains 787 `PYC001` dispositions across 72 files and zero `PYD001`/`PYD002` findings. |
| Inferred-typing reconciliation | Exactly 16 diagnostics were retired, leaving 670 diagnostics across 349 identities in 49 files; the probe reported no new or relocated diagnostics. |
| Bazel | `bazel test --config=ci //...` passed all 20 targets. |
| Package rebuild | Both local packages rebuilt and reinstalled offline with the frozen environment and non-editable mode; dependencies and lockfiles were unchanged. |
| Pre-commit and initial documentation audit | `pre-commit run --all-files` passed every hook, including architecture/local links, program governance, source standards, typing, all governance policies and secret checks. Luna at extra-high reasoning authored the service and roadmap documentation; the parent audit corrected attribute, newline, path and error-translation descriptions. That initial audit missed inadequate summaries and overstated assertions in `test_program_governance.py`; passing automated checks did not establish the semantic completeness of those test docstrings. |
| Test-docstring correction and audit | Luna at extra-high reasoning revised 35 docstrings in `test_program_governance.py`: the module, two classes and 32 test functions/methods. The parent audited scenario descriptions and fixture/parameter `Args` against the test bodies and corrected claims exceeding the assertions. Executable AST comparison was unchanged, and all 37 ordered collected cases were preserved, including the performance case. The focused default selection passed with 36 tests and one deselected; pinned Ruff lint, Google-docstring/`ANN401`, format, source-documentation and engineering-standards checks passed. |

These are local checks for the program loading/status slice. The full `make ci-full`
lane, hosted CI, and separate integration/performance selections were not run.
At this slice's completion, queue item 2 remained in progress because package-state
parsing and local-evidence validation still needed the following bounded service slice.

## Step 6 validation record — package-state and local-evidence ownership, 2026-09-06

The parent audit compared this slice with saved source from revision
`b26667b18e57a07d869897b768c41bd875b07fca`. Luna subagents used `gpt-5.6-luna`
at `xhigh` reasoning for implementation and test corrections. The audit covered
service ownership, validation order, accurate typing boundaries and docstrings,
public compatibility, and recovery between calls.

| Check | Observed result |
| --- | --- |
| Differential behavior | All 1,295 cases matched: 1,280 package-state cases across schemas 1–4, 13 local-evidence success/failure cases, and two public loading/repository-validation cases. Comparisons include serialized values, exception types and exact messages, ordered findings, and chained cause types and messages. State cases cover malformed tables and fields, missing/unknown keys, ordering, ownership, operating-model absence, completion combinations, unsafe/missing paths, absent findings and invalid UTF-8. |
| Focused pytest | 51 passed, one performance case deselected: 47 in `test_program_governance.py` plus the four selected standards, inventory, model-error-translation and CI-observation cases listed below. New cases cover schema-specific evidence and ordering, date/ownership refresh, local-evidence failure recovery, and profile finding/cause preservation. |
| Collection and compatibility | All 36 existing default-selected program-governance node IDs remain in order; 11 cases were added. All 39 existing test/helper function ASTs are unchanged. The four public registry wrappers are AST-identical; facade exports and status APIs are unchanged. |
| Scoped lint, docs, format and strict typing | Ruff 0.16.5 lint/format and mypy 2.3.1 strict checks passed for the three changed Python files under Python 3.12.14. Google-docstring/`ANN401` checks passed for the registry and program tests. Manual review corrected new test documentation, the date override, exception-identity assertions, and a premature literal return annotation before final validation. |
| Source-standard reconciliation | The engineering-standards command passed. Exactly two `PYC001` entries were retired, leaving 785 across 72 files, with no new allowances or exceptions and no `PYD001`/`PYD002` findings. |
| Scoped inferred typing | The stronger probe on the three changed Python files matched all 22 existing diagnostics across eight identities, with no additions, relocations or multiplicity changes. The repository inventory remains unchanged at 670 diagnostics; the full-repository probe was not rerun. |
| Owning Bazel check | `bazel test --config=ci //tests/engineering:python_standards_test` passed its single target. |

The four additional pytest selections were:

- `test_engineering_standards.py::test_repository_standards_bind_exact_tools_languages_and_baselines`
- `test_python_debt.py::TestPythonDebt::test_reviewed_inventory_is_exact_and_attributed`
- `test_pydantic_models.py::test_public_loaders_translate_validation_errors_without_leaking_details`
- `test_ci_policy.py::test_ci_duration_event_matches_program_observation_contract_and_local_log_scope_is_bounded`

All pytest paths are under `tests/engineering/`. Local Python commands used
`PYTHONPATH=src:tools/governance/src` and the pinned `.venv` interpreter to exercise
the changed source directly. Validation was limited to affected tests and checks
as requested; the full test suite, full Bazel selection, all-file pre-commit,
hosted CI, and integration/performance lanes were not run. Queue item 2 is complete;
queue item 3 is the next workflow slice.

## Step 6 validation record — security-control map loader, 2026-09-06

This slice used saved security source and tests from revision
`b26667b18e57a07d869897b768c41bd875b07fca`, preserving the preceding uncommitted
program-governance slice. Two `gpt-5.6-luna` subagents at `xhigh` reasoning
implemented the service and regression tests. The parent audited the source,
documentation, exception boundaries, root binding and compatibility before
running the final affected checks.

| Check | Observed result |
| --- | --- |
| Differential behavior | All 5,354 comparisons matched: 2,664 document mutations through the public function and the same 2,664 through the service, one repository-validation case, one service-load case, 12 local-evidence failure cases, four file-boundary cases, and eight CLI cases. Comparisons covered serialized models, exact exception types/messages, ordered findings, cause types/messages, exit codes and stdout/stderr. Mutations included simultaneous failures to verify validation precedence. |
| Root binding | One additional baseline comparison verified a root symlink retargeted immediately after its first resolution. The service remained bound to the original repository for that call. A new pytest case also proved that the next invocation observes the replacement repository. The audit corrected an intermediate implementation that resolved the original symlink again while loading. |
| Focused pytest | 26 passed: all 23 cases in `test_security_controls.py`, plus the selected model-error-translation, debt-inventory and engineering-standards cases listed below. The five new service cases cover deferred constructor I/O and exports, root binding, default/explicit ownership refresh, repeated ordered findings, and evidence failure recovery. |
| Collection and API compatibility | All 18 existing security pytest node IDs remain in order, with five added service cases. All 21 existing test/helper function ASTs are unchanged. The two public function signatures are unchanged; the loader class is identical across canonical and facade package/module exports. Remaining standalone parsing and validation functions are AST-identical. |
| Scoped lint, typing, documentation and security | Ruff lint/format and strict mypy passed over the nine files in the affected canonical/facade packages, test module and debt checker. Google-docstring/`ANN401` checks passed for the registry and security tests. Scoped Bandit passed for the registry. Manual audit corrected public service and compatibility-wrapper descriptions. |
| Source-standard reconciliation | Engineering-standards validation passed. Exactly four `PYC001` migration entries retired: three wrappers received fingerprinted compatibility dispositions, and the old local-evidence function was removed. The inventory now contains 781 entries across 72 files, with no new migration allowances or documentation findings. Existing exceptions and the preceding slice's program source/tests were preserved. |
| Scoped inferred typing | The stronger probe on the six changed Python files matched 16 existing diagnostics across four identities, with no additions, relocations or count changes. The repository inventory remains unchanged at 670; the full-repository stronger probe was not run. |
| Bazel | `bazel test --config=ci //tests/engineering:python_standards_test //tools/governance/src/alpha_research_governance:cmd_security` passed its single test target and built the security command. |
| Governance command | The canonical security command passed for 12 threats, 12 controls and four jurisdiction profiles. |

The additional pytest selections were:

- `test_pydantic_models.py::test_public_loaders_translate_validation_errors_without_leaking_details`
- `test_python_debt.py::TestPythonDebt::test_reviewed_inventory_is_exact_and_attributed`
- `test_engineering_standards.py::test_repository_standards_bind_exact_tools_languages_and_baselines`

All pytest paths are under `tests/engineering/`. Python validation used the pinned
`.venv` tools and `PYTHONPATH=src:tools/governance/src` to exercise the current
source. The full pytest/Bazel suites, all-file pre-commit, hosted CI, and separate
integration/performance lanes were not run. Queue item 3 remains in progress;
inventory loading is next.

## Step 6 validation record — financial settlement conventions, 2026-09-06

The baseline was the clean checkout at
`bb2cf9829fce357456ec23ec692913279706749c`. Two `gpt-5.6-luna` subagents at
`xhigh` reasoning implemented the source/exports and tests in disjoint files.
The parent audited the final code using the calendar/reference-data profile,
risk tier 2, because bounded settlement dates are shared financial-domain
outputs. The audit checked calendar ownership, numerical compatibility, error
precedence, test collection, documentation and exact debt retirement. No
actionable findings remained after corrections.

| Check | Observed result |
| --- | --- |
| Differential behavior | All 154,320 comparisons matched the saved baseline: every eligible-date subset of the eight-day synthetic calendar, all five conventions, ten candidate dates, five valid lags, and simultaneous malformed inputs. Comparisons covered both public wrappers and valid-calendar service methods, exact results, exception types/messages and chained causes. Invalid calendars are rejected at service construction; wrapper validation precedence remains unchanged. |
| API and numerical compatibility | Both existing public function signatures are unchanged. The ASTs for `ConventionError`, `BusinessDayConvention`, `DayCountResult` and `QuantLibConventions` are unchanged. The version constant only gains an explicit annotation. Goldens, models, stubs, dependencies and global settings are unchanged. |
| Focused pytest | `PYTHONPATH=src:tools/governance/src .venv/bin/python -m pytest -q tests/unit/test_financial_units.py`: **104 passed**, one existing performance case deselected. Sixteen added cases cover missing primary/alternate dates, explicit coverage, unadjusted lag anchors, lag-error precedence, constructor revalidation and causes, repeated failure recovery and strict dates. |
| Collection and test audit | All 88 previously selected cases remain by leaf name and parameter ID; class-qualified node IDs change for the ten migrated functions. No external references to those old node IDs were found. All 19 retained module-level test/helper ASTs are unchanged. The audit corrected two temporarily nested, undiscovered tests, a wrong cause assertion, missing primary-search cases and overly broad calendar payload annotations. |
| Source standards and policy | The selected `TestPythonDebt::test_reviewed_inventory_is_exact_and_attributed` and `test_repository_standards_bind_exact_tools_languages_and_baselines` cases passed (**2 passed**). Source inventory is 766 entries across 71 files; 15 entries retired, with five explicit source-bound dispositions and no added migration allowances. Both checksum pins match their inventories. |
| Scoped lint, documentation, format, security and typing | Ruff lint/format and strict mypy passed for the five changed Python files. Google-docstring/`ANN401` checks passed for conventions and its tests; scoped Bandit passed for conventions. The audit corrected callback documentation and one source line-wrap defect. |
| Scoped stronger typing | The stronger mypy probe over those five files exactly matched 26 retained diagnostics across 24 identities. Three test diagnostics retired; no diagnostic was added, moved or multiplied. The repository inventory is 667 diagnostics. The standalone Hypothesis callback's existing framework typing remains tracked. |
| Owning Bazel target | `bazel test --config=ci //tests/unit:financial_units_test` passed its single target. |

The two additional pytest cases are in `tests/engineering/test_python_debt.py`
and `tests/engineering/test_engineering_standards.py`, respectively. All Python
execution used the pinned `.venv` tools and current source through
`PYTHONPATH=src:tools/governance/src`. Static checks covered
`financial_units/conventions.py`, `financial_units/__init__.py`,
`tests/unit/test_financial_units.py`, and the two engineering-standards checksum
modules. No full pytest/Bazel suite, full-repository stronger typing probe,
all-file pre-commit, hosted CI or separate integration/performance lane was run.
Step 6 remains in progress outside this bounded settlement slice.

## Step 6 validation record — financial models and tests, 2026-09-06

The baseline was the clean checkout at
`7e1b60a29a36e96014e8fb73eada1d72a8215c30`. `gpt-5.6-luna` subagents at
`xhigh` reasoning implemented the source and tests in separate file scopes.
The parent reconciled the inventories and audited the integrated changes with the
model-risk profile, risk tier 2, because these shared financial
values enforce exact monetary arithmetic and explicit dimensions. This was a
technical code audit, not independent organizational model approval.

| Check | Observed result |
| --- | --- |
| Differential behavior | **2,331 comparisons** matched the saved baseline, including strict construction and replacement failures, error text and chained causes, public model schemas, all reflected fields, subclass dimensions, signed rounding, FX directions, magnitude/precision boundaries and Decimal-context independence. All four kernel signatures are unchanged. |
| Focused pytest | `PYTHONPATH=src:tools/governance/src .venv/bin/python -m pytest -q tests/unit/test_financial_units.py`: **105 passed**, one existing performance case deselected. The new regression checks subclass fields in arithmetic and copies, mismatched subclass dimensions and an unchanged caller update mapping. |
| Collection and test audit | All **104** previously selected cases and **36** original test definitions remain. Fourteen standalone tests moved into two contract classes; the three Hypothesis callbacks retain their node identities. Six existing test definitions have reviewed strategy, raw-payload or reflection changes; the remaining original test ASTs are unchanged after accounting for `self`. No external references to the moved node IDs were found. The audit restored omitted invalid-input and immutability cases, retained both concrete `model_validate` entry points, and removed temporary suppressions and constructor-dispatch helpers. |
| Scoped lint, documentation, format, typing and security | Ruff lint/format and strict mypy pass for the source, unit-test and two checksum modules. Google-docstring/`ANN401` checks pass for the source and unit-test files. Scoped Bandit passes for `models.py`. |
| Stronger typing | The probe uses both `--disallow-any-expr` and `--disallow-any-decorated`. `models.py` has **zero** diagnostics; the unit-test file retains **nine** existing Hypothesis decorator diagnostics. The checksum modules retain two existing `PythonStandardsChecker.findings` diagnostics. No new, moved or multiplied diagnostic is accepted. |
| Inventory reconciliation | Exactly **20** `PYC001` migration entries retired, leaving **746** entries across **69** files. Six fingerprinted dispositions cover the four low-level kernels and two retained property callbacks. Exactly **25** inferred diagnostics retired, leaving **642** across **329** identities. Both checksum pins match their inventories; unrelated obligations and exceptions are unchanged. |
| Source standards and policy | Source-standard reconciliation and all exception fingerprints pass. The selected `TestPythonDebt::test_reviewed_inventory_is_exact_and_attributed` and `test_repository_standards_bind_exact_tools_languages_and_baselines` cases pass (**2 passed**). |
| Owning Bazel target | `bazel test --config=ci //tests/unit:financial_units_test` passed its single target. |

All Python execution used the pinned `.venv` tools and current checkout sources.
No full pytest/Bazel suite, full-repository stronger typing probe, all-file
pre-commit, hosted CI or separate integration/performance lane was run. The
remaining Hypothesis decorator typing is explicitly unresolved framework debt.
Step 6 remains in progress outside this financial-model and unit-test slice.

## Step 6 validation record — instrument-identity models and tests, 2026-09-07

The baseline was the clean checkout at
`1a3df5249bac982478af99453ee3b3c7633a5445`. Two `gpt-5.6-luna` subagents at
`xhigh` reasoning implemented the source and test scopes. The parent reconciled
inventories and audited the integrated result with the market-data profile, risk
tier 2, because these shared reference-data boundaries enforce instrument identity
and UTC validity. The audit found no remaining actionable issues in this slice.

| Check | Observed result |
| --- | --- |
| Differential behavior | **3,227 comparisons** matched the saved baseline, covering strict constructors, canonical UUID parsing, all identifier schemes, invalid values and namespaces, nested identity validation, correction metadata, UTC/half-open intervals, ordered error text and chained causes, six public model schemas, and ordinary/owned/assertion/custom subclass-validator failures. Seven public constructor/function signatures also match. |
| Focused pytest | `PYTHONPATH=src:tools/governance/src .venv/bin/python -m pytest -q tests/unit/test_instrument_identity.py`: **20 passed**, one marked performance case deselected. The same module with `-m performance`: **1 passed**. |
| Affected downstream tests | The selected financial-model tests `TestFinancialModelContracts::test_c01_c02_unvalidated_copies_cannot_bypass_boundary_validation` and `TestFinancialModelContracts::test_nested_models_reject_dict_coercion_subclasses_and_unchecked_copies`: **2 passed**. |
| Collection and test audit | All **19** original cases and **13** original test definitions remain, with unchanged decorators and both Hypothesis node identities retained. Eleven ordinary tests moved into three contract classes. Two additional tests cover three malformed fixture shapes and owned versus ordinary constructor error messages/causes. Collection with all markers enabled grows from **19 to 21**. No external references to the moved node IDs were found. Seven original test ASTs are unchanged after normalizing `self` and builder references; the six remaining original tests have reviewed typed-fixture or boundary-typing changes. |
| Scoped static checks | Ruff lint, format, Google-docstring/`ANN401` checks and strict mypy pass. The strict check covers the identity package, its unit tests and the two checksum modules. Scoped Bandit passes for `models.py`. |
| Stronger typing | The four changed Python files were probed with `--strict --disallow-any-expr --disallow-any-decorated --follow-imports=silent --no-warn-unused-configs --output=json`. `models.py` has **zero** diagnostics; the test module retains **six** existing Hypothesis decorator diagnostics. The checksum modules retain two existing `PythonStandardsChecker.findings` diagnostics. Exact scoped reconciliation accepts no new, moved, multiplied or stale debt. |
| Inventory reconciliation | Exactly **32** `PYC001` migration entries retired, leaving **714** entries across **67** files. Thirteen fingerprinted dispositions cover eleven low-level helpers and two retained property callbacks. Exactly **ten** inferred diagnostics across five identities retired, leaving **632** diagnostics across **324** identities. Both checksum pins match; unrelated inventory records and exceptions are unchanged. |
| Source standards and policy | Full source-standard reconciliation and exception fingerprints pass. The selected `TestPythonDebt::test_reviewed_inventory_is_exact_and_attributed` and `test_repository_standards_bind_exact_tools_languages_and_baselines` cases pass (**2 passed**). |
| Owning Bazel target | `bazel test --config=ci //tests/unit:instrument_identity_test`: **one target passed**. |

All Python execution used the pinned `.venv` tools and current checkout sources.
Only the named affected tests and owning Bazel target were run; no full pytest or
Bazel suite, full-repository stronger typing probe, all-file pre-commit, hosted CI
or separate integration lane was run. Six upstream Hypothesis decorator diagnostics
remain explicitly tracked. Step 6 remains in progress outside this bounded slice.

## Step 6 validation record — venue-calendar source and tests, 2026-09-07

The baseline was the clean checkout at
`53b469dd257e3e5839bae474c977a14b21e977ca`. Three `gpt-5.6-luna` subagents at
`xhigh` reasoning implemented the adapter, model and test scopes. The parent
audited the integrated result using the market-data profile, risk tier 2, because
the shared calendar contract governs UTC sessions, reference-data coverage and
settlement eligibility. No actionable audit findings remain in this slice.

| Check | Observed result |
| --- | --- |
| Differential behavior | **5,403 model results** and **63 adapter results** match the saved baseline. Coverage includes strict construction and raw validation, all public model schemas, serialized values, ordered error text and causes, market-state intervals, settlement queries, complete 2024 XNYS/XLON/XHKG snapshots, empty ranges and invalid adapter inputs. |
| Focused pytest | **90 passed, one performance case deselected** across the two calendar files, settlement consumers and the two selected standards checks listed below. Nine added calendar cases cover malformed nested fixture values and range cardinality, ordered error translation, dynamic timestamp converters, missing converter properties and non-callable converter objects. |
| Performance | The separately selected calendar projection diagnostic passed: **one passed**, covering ten thousand queries over the existing 185-session fixture. |
| Collection and assertions | All **51 baseline selected cases** retain their leaf names, parameter IDs and order; nine cases are added. The performance case is preserved separately. Class ownership changes node IDs, with no external selectors found. Twenty-five unit-test/helper functions and the evidence-test body are unchanged after normalizing method ownership. Changed assertions preserve original validation entry points and explicit Pydantic ancestry checks. |
| Audit corrections | Removed private forwarding wrappers that created fresh adapters, replaced unchecked type-guard claims with the pinned native stub contract, restored reflective timestamp behavior and the original callability gate, tightened known fixture/payload shapes, and completed new callback docstrings. |
| Source standards and inventory | The full source reconciliation and fingerprint checks pass through the selected engineering-standards test. Exactly **48** `PYC001` entries retire, leaving **666** across **63** files. Twelve individually fingerprinted dispositions cover ten low-level source helpers and two retained property callbacks. |
| Scoped inferred typing | The stronger probe over the five calendar source/test files exactly matches the **six original Hypothesis decorator diagnostics**. Exactly **34** diagnostics across **23** identities retire, leaving **598** across **301** identities repository-wide. No new, moved or multiplied diagnostics are allowed; unrelated obligations, metadata and prior exceptions are unchanged. Both inventory checksum pins match. |
| Lint, format and types | Ruff lint, Google-docstring/`ANN401` checks and formatting pass for the five calendar files. Lint/format and strict mypy also cover the two checksum-bearing checker modules: **seven files** pass strict typing. Bandit passes for the calendar source package. |
| Bazel | `//tests/unit:venue_calendar_test` and `//tests/engineering:venue_calendar_evidence_test` both pass. Native schedule-conformance cases remain in the unit target; stubs, dependencies, public exports and golden fixture bytes are unchanged. |

Final focused pytest command, using the pinned existing Python environment and
the checkout's source paths:

```sh
PYTHONPATH=src:tools/governance/src .venv/bin/python -m pytest -q \
  tests/unit/test_venue_calendar.py \
  tests/engineering/test_venue_calendar_evidence.py \
  tests/unit/test_financial_units.py::TestSettlementConventions \
  tests/unit/test_financial_units.py::TestFinancialModelContracts::test_c01_c02_unvalidated_copies_cannot_bypass_boundary_validation \
  tests/engineering/test_python_debt.py::TestPythonDebt::test_reviewed_inventory_is_exact_and_attributed \
  tests/engineering/test_engineering_standards.py::test_repository_standards_bind_exact_tools_languages_and_baselines
```

The performance case was selected directly with `-m performance`. Scoped mypy
used `--strict --follow-imports=silent --no-warn-unused-configs`; the stronger
probe additionally used `--disallow-any-expr --disallow-any-decorated --output=json`
and reconciled its six diagnostics by exact symbol, message and multiplicity.
The full repository test suite, full repository stronger typing probe and native
stubtest were not run. The six framework diagnostics remain an explicit
step-7 task; this record does not claim their retirement or completion of step 6
outside the venue-calendar slice.

## Step 6 validation record — build checks and contract tests, 2026-09-07

The baseline was the clean checkout at
`0bb6c0b0f295cf509b02e2c96189b443e662fd18`. Three `gpt-5.6-luna` subagents at
`xhigh` reasoning implemented the build-graph, developer-environment and fixture
scopes. The parent audited the combined source, regression tests, Bazel wiring
and inventory retirement using the general software profile, risk tier 1.
No actionable audit findings remain in this slice.

| Check | Observed result |
| --- | --- |
| Differential validation | **1,091** retained outcomes match across dependency records, developer-environment contracts, flake locks and both evidence manifests. **30** build-graph and **15** environment CLI comparisons match, including ordered errors, exit codes, malformed roots and combined fail-fast conditions. |
| Intentional malformed-input hardening | Both evidence validators reject extra non-table gates and return the existing applicable-gates finding for unhashable IDs. Tests distinguish those changes from the unchanged missing/scalar/unknown-ID failures and preserve valid gate/status behavior. |
| Focused pytest | **25 passed**: 22 cases in the five new build contract-test modules and the three directly relevant source-inventory, repository-standards and CI-policy checks below. Recovery, child-process environment/failure/cleanup, SQL diagnostics and sandbox diagnostics are covered. |
| Model representation | The validation report uses strict, frozen Pydantic fields; its regression test checks wrong primitive types, forbidden fields, list-to-tuple coercion rejection and frozen assignment. Four workflow services use explicit typed constructors. No dataclass reference remains in `tests/build`; Pydantic is declared directly on the two report-consuming Bazel targets, and the Python guide reflects this preference. |
| Bazel | All **12** explicitly selected affected targets pass under `--config=ci`; ten executed and two were cached. This includes all six original Python entry targets, all five new regression targets and the existing SQL invalid-substitution target. New pytest entry guards, source inputs, imports and suite membership are present; the isolated sandbox target has no added data dependencies. |
| Source standards | Full source-inventory reconciliation and exception fingerprints pass. Exactly **19** `PYC001` obligations retire, leaving **647** across **57** files. Twenty explicit dispositions cover retained entry points and low-level helpers; there is no remaining `tests/build` source debt or documentation finding. |
| Scoped inferred typing | The baseline exactly matched **65** diagnostics across **21** identities. The final stronger probe over all **11** `tests/build` Python files is empty. Only those inventory entries retire, leaving **533** diagnostics across **280** identities elsewhere. Unrelated obligations, metadata and prior exceptions are unchanged; both checksum pins match. |
| Lint, documentation and types | Ruff lint, Google-docstring/`ANN401` checks and formatting pass for `tests/build`. Lint/format and strict mypy also include the two checksum-bearing checker modules: **13** affected Python files pass. |

Final focused pytest command:

```sh
PYTHONPATH=src:tools/governance/src .venv/bin/python -m pytest -q \
  tests/build \
  tests/engineering/test_python_debt.py::TestPythonDebt::test_reviewed_inventory_is_exact_and_attributed \
  tests/engineering/test_engineering_standards.py::test_repository_standards_bind_exact_tools_languages_and_baselines \
  tests/engineering/test_ci_policy.py::test_repository_ci_policy_is_complete_partial_and_fail_closed
```

Final Bazel selection:

```sh
bazel test --config=ci \
  //tests/build:build_graph_test \
  //tests/build:build_graph_contracts_test \
  //tests/build:developer_environment_test \
  //tests/build:developer_environment_contracts_test \
  //tests/build:sandbox_test \
  //tests/build:sandbox_contract_test \
  //tests/build/fixtures/proto:buf_compatibility_test \
  //tests/build/fixtures/proto:buf_toolchain_test \
  //tests/build/fixtures/proto:buf_contract_test \
  //tests/build/fixtures/sql:generated_sql_test \
  //tests/build/fixtures/sql:generated_sql_contract_test \
  //tests/build/fixtures/sql:invalid_substitution_test
```

Scoped mypy used `--strict --follow-imports=silent --no-warn-unused-configs`;
the stronger build-only probe additionally used `--disallow-any-expr
--disallow-any-decorated --output=json`. No full pytest/Bazel suite,
full-repository stronger typing probe, native stubtest, or all-file pre-commit
run was performed. Step 6 remains open outside this completed build/test slice.

## Step 6 validation record — residual governance records, 2026-09-07

Against baseline `04d1fea`, two `gpt-5.6-luna` subagents at `xhigh` reasoning
migrated all nine dataclasses in `engineering_standards/python_source.py` and
`security_controls/registry.py`. Seven records inherit the shared strict frozen
`ImmutableModel`; lexical scopes and map-validation contexts remain mutable,
with strict construction, assignment validation and independent collection defaults.
Lexical scopes preserve live parent identity. Arbitrary-type support is limited
to the import record's AST field. Finding constructors now use keyword arguments,
and the source-standards Bazel target declares its direct Pydantic dependency.

The parent audited the changes using the general software profile, risk tier 1;
no actionable findings remain. Validation was limited to affected checks:

- **85 pytest cases passed** across the source scanner, debt checker, security
  controls, repository-standards binding and source-tree rejection checks.
- `//tests/engineering:python_standards_test` passed under `--config=ci`.
- Differential checks match the original scanner on **147 source inputs**
  (**754 findings**, including exact order and line numbers) and the original
  security loader on **26 cases**, including serialized maps, ordered errors,
  malformed inputs and recovery using the same loader instance.
- Ruff lint, Google-docstring checks, formatting and strict mypy passed for all
  five affected Python files. The stronger scoped probe exactly matches the
  existing **37 diagnostics across 11 identities**, with no additions or retirements.
- Source inventory reconciliation and exception fingerprints pass. Debt inventories
  and their checksum pins remain unchanged; step 6 remains open elsewhere.
