# Python coding standards audit and migration plan

Audit date: 2026-09-05. Original audit baseline revision:
`d3a40ca98d71208426c8501d8d4a1aaaa049768d`. Current slice baseline (2026-09-06):
captured working tree at `c710114972071e3d1512609d4de6bafed0a6ddcf`, including
the uncommitted twenty-second slice.
Status: steps 1–4 implemented on 2026-09-05; steps 5–6 are in progress. Domain
operations, identity/calendar value models, all dedicated governance model
modules, CI/remote-execution contracts, supply-chain, domain, shared model-validation,
change-risk, ownership, evidence, package-metadata and remaining governance test
contracts, remaining build tests and fixtures, and the change-risk service pilot
are implemented; high-level workflow refactoring remains in step 6, and step 7
remains planned. The twenty-third step-5 slice expands seven public Git,
audit-signal and status contracts across three files, retiring 37 structured
documentation obligations. Three `gpt-5.6-luna` writers at `xhigh` reasoning
prepared the documentation; the parent completed semantic audit and combined
validation after corrections. The source inventory holds 1,032 obligations
across 73 files: 234 documentation obligations (all sections/parameters) and
798 function dispositions. No missing-summary debt remains. The separate
inferred-typing inventory remains at 686 diagnostics. The earlier CLI slice
preserves 12 Typer callback docstrings as help contracts.
Step 5 remains in progress on the 234 structured-documentation obligations;
documentation for moved workflows is combined with their step-6 service slices.
The findings below describe the original audited revision, before step-1
enforcement.

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
| 5. Document existing contracts — in progress | Documented financial-unit models/conventions, the symbology catalog, calendar adapter, identity/calendar value models, shared governance validation, operating/risk/evidence contracts, all dedicated governance model modules, and CI/remote-execution, dependency/artifact, domain, shared model-validation, change-risk, ownership, evidence, package-metadata, remaining governance tests and helpers, remaining build tests and fixtures, and the CLI/shared, secret-scanning, sharding, CI-policy, remote-policy, artifact-policy, change-risk-policy, evidence-policy and wheel-source governance operations, plus selected architecture/ownership/standards helpers, records and CLI entrypoints and inventory, topology and security registry helpers, program, dependency-admission and artifact-supply-chain operation helpers, CI selection and execution helpers, CI event/checkout helpers, evidence input/parsing helpers, security/inventory/topology registry parser and graph helpers, remaining private governance helpers, and public Git, audit-signal and status contracts. The missing-summary queue is complete. Step 5 retains structured governance contracts; document moved workflows with step 6. | The twenty-three documentation slices retire 185, 268, 76, 80, 22, 158, 109, 109, 97, 116, 16, 93, 52, 76, 42, 35, 40, 36, 9, 21, 12, 21 and 37 obligations respectively, preserving executable ASTs. Parent reconciliation verified 1,032 obligations across 73 files: 234 documentation obligations (0 summaries and 234 sections/parameters) and 798 function dispositions; the separate inferred-typing inventory remains at 686 diagnostics. The step-5 implementation and validation records track each slice; the current slice passed semantic audit and combined validation. |
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

### Step 5 implementation — CI, remote-execution and artifact policy contracts

The thirteenth documentation slice completes all 29 functions in the
[CI policy](../../tools/governance/src/alpha_research_governance/ci_policy/policy.py),
[remote-execution policy](../../tools/governance/src/alpha_research_governance/remote_execution/policy.py)
and [artifact-supply-chain policy](../../tools/governance/src/alpha_research_governance/artifact_supply_chain/policy.py)
modules. Three `gpt-5.6-luna` subagents at `xhigh` reasoning wrote separate files.
The parent agent audited the documentation against each body, relevant models
and evidence loaders, then requested corrections and inspected the revisions.

The contracts describe parsed table and collection shapes, exact configured
values, ordered results and findings, file reads, Git inspection, and translated
versus propagated failures. CI documentation distinguishes its final-entry-per-ID
lane comparison from lane uniqueness, and dependency-record findings from
uncaught lockfile or process failures. Remote documentation scopes integration
checks to selected configuration fragments and quarantine dates to the policy's
reference date. Artifact documentation distinguishes lexical path checks from
filesystem inspection, records the non-atomic final-component symlink check,
and explains which lock, toolchain, date and evidence failures are aggregated,
translated or propagated. These operations preserve the existing partial
package status and do not establish hosted execution or release readiness.

Exactly **52** original documentation obligations are retired: 21 PYD001
summaries and 31 PYD002 section/parameter findings (17 CI, 16 remote execution
and 19 artifact supply chain). All three modules have zero documentation
findings. Only their docstrings, those debt deletions, the matching checksum pin
and this plan change relative to the captured working tree. Existing uncommitted
build and CLI documentation slices are preserved.

The source inventory now holds **1,361** obligations across 73 files:
**563** documentation obligations (219 summaries and 344 sections/parameters)
and 798 function dispositions. The inferred-typing inventory remains at 686
diagnostics. Step 5 remains in progress with other governance operations;
document moved workflows with their step-6 service slices.

### Step 5 implementation — risk/evidence policy and wheel-source contracts

The fourteenth documentation slice completes all 52 definitions in
[change-risk policy loading](../../tools/governance/src/alpha_research_governance/change_risk/policy.py),
[evidence-policy loading](../../tools/governance/src/alpha_research_governance/evidence/policy.py)
and [wheel-source verification](../../tools/governance/src/alpha_research_governance/dependency_admission/wheel_sources.py).
Three `gpt-5.6-luna` writers at `xhigh` reasoning worked on separate files.
The parent agent reviewed the prose against implementations, model fields,
callers and existing tests, requested corrections, and audited the revisions.

The policy contracts distinguish strict structural input validation from later
semantic checks, closed tables from extensible records, and input defaults from
output projection. Change-risk documentation covers ordered dimension/class
processing, minimum versus exact controls, duplicate conditional-trigger behavior,
error selection and retained sample reclassification. Evidence documentation
covers version selection, independent institutional and founder/conditional field
groups, lexical host-path normalization, finding-ID projection and propagated
file/decode errors. The 15 input-model schemas retain their field contracts;
generated description metadata can reflect the new class docstrings.

Wheel contracts separate source-binding provenance from bootstrap publication
with an unresolved source-to-wheel gap. They describe caller-supplied review
dates, parser preconditions, exact locked filename/digest coverage, bounded local
evidence reads, symlink-check limitations, JSON/DSSE error translation, temporary
staging and verifier invocation order. The Cosign helper uses a subprocess
timeout and returns a bounded diagnostic excerpt; its temporary output file is
not size-limited, and local verification inputs do not establish offline execution.
The module compares supplied wheel digests without downloading wheel or source
archive bytes.

Exactly **76** original documentation obligations are retired: 44 PYD001
summaries and 32 PYD002 sections/parameters (27 change risk, 12 evidence and 37
wheel sources). All three modules have zero documentation findings. The source
inventory now holds **1,285** obligations across 73 files: **487** documentation
obligations (175 summaries and 312 sections/parameters) and 798 function
dispositions. The inferred-typing inventory remains unchanged at 686 diagnostics.
Only docstrings, those exact debt deletions, the matching checksum and this plan
change relative to the captured working tree; the preceding policy slice is
preserved. Step 5 remains in progress with other governance operations; document
moved workflows with their step-6 service slices.

### Step 5 implementation — architecture, ownership and standards helpers

The fifteenth documentation slice covers 31 selected definitions in
[architecture governance](../../tools/governance/src/alpha_research_governance/architecture_governance.py),
[ownership governance](../../tools/governance/src/alpha_research_governance/ownership_governance.py)
and [engineering standards](../../tools/governance/src/alpha_research_governance/engineering_standards/policy.py).
Three `gpt-5.6-luna` writers at `xhigh` reasoning documented disjoint files;
the parent agent audited the selected contracts, requested corrections and
reviewed the revisions. The larger validation/orchestration functions retain
their existing docstrings and debt for the step-6 workflow slices.

Architecture coverage includes the decision-log input record, error constructor,
metadata and section extraction, canonical dates, approval syntax, decision-row
parsing, heading anchors and CLI entrypoint. The docs explain regex limitations,
last-key-wins metadata, retained duplicate rows, findings-list mutation and
syntactic approval checks without claiming external evidence verification.
Ownership coverage includes its error constructor, optional table/list helpers,
TOML loading, CODEOWNERS parsing and matching, Git path discovery and CLI. The
contracts distinguish aliasing from copying, the restricted pattern syntax from
full CODEOWNERS semantics, and tracked paths from nonignored untracked paths.

Standards coverage includes table/string/integer/date parsing, exact tool and
language contracts, suppression metadata validation, owner-role collection and
lock-record projection. The docs describe inclusive expiry boundaries, raised
date failures versus returned findings, permissive role collection, skipped
malformed table fields and last-usable-entry overwrites. The semantic audit
corrected overbroad claims about ignored metadata rows, prefix matching and
malformed lock entries. All selected definitions have their applicable contracts;
unselected function docstrings are unchanged.

Exactly **42** original documentation obligations are retired: 25 PYD001
summaries and 17 PYD002 sections/parameters (13 architecture, 13 ownership and
16 standards). The source inventory holds **1,243** obligations across 73 files:
**445** documentation obligations (150 summaries and 295 sections/parameters)
and 798 function dispositions. The inferred-typing inventory remains at 686
diagnostics. Only the selected docstrings, exact debt deletions/checksum and
this plan change relative to the captured working tree. Step 5 remains in
progress; the unedited workflows retain 41 documentation obligations across
these three modules, to be handled with their step-6 service work.

### Step 5 implementation — inventory, topology and security registry helpers

The sixteenth documentation slice covers 35 selected definitions across the
[inventory registry](../../tools/governance/src/alpha_research_governance/inventory/registry.py),
[repository-topology registry](../../tools/governance/src/alpha_research_governance/repository_topology/registry.py)
and [security-controls registry](../../tools/governance/src/alpha_research_governance/security_controls/registry.py):
10 inventory definitions, 12 topology definitions including two nested
definitions, and 13 security definitions. Three `gpt-5.6-luna` writers at
`xhigh` reasoning documented disjoint assignments from clean revision
`2a25a10c000c11cfee9c26d1e0ce36087591a437`; the parent agent audited all added
prose and revisions against the bodies, models and relevant tests. The exact
executable ASTs and comments are unchanged, and no other docstrings are changed.

The contracts distinguish TOML shape checks from parser-provided key/value
typing and from returned aliases or copies. They record whitespace, empty-list,
duplicate and role-collection differences, canonical date round-trips, and
caught versus propagated parser, I/O and path errors. Inventory path checks are
observational: they resolve candidates and append findings, permitting symlinks
that resolve to in-root files; topology path validation rejects symlink
components. The topology docs also cover static import extraction and DFS cycle
detection, while the inventory and security docs describe reference and URL
checks without claiming network or broader security verification.

Exactly **35** original documentation obligations are retired: 35 PYD001
summaries (10 inventory, 12 topology and 13 security). The source inventory now
holds **1,208** obligations across 73 files: **410** documentation obligations
(115 summaries and 295 sections/parameters) and 798 function dispositions. The
inferred-typing inventory remains at 686 diagnostics; all other inventory
metadata and entries are preserved except the exact deletions and matching
checksum update. The selected definitions have zero source-scanner PYD findings.
The larger parsers, loaders and workflows remain unchanged with 39
documentation obligations across these modules, to be handled with their
step-6 service work. Step 5 remains in progress.

### Step 5 implementation — program, dependency and artifact operation helpers

The seventeenth documentation slice covers 40 selected helpers in the
[program-governance registry](../../tools/governance/src/alpha_research_governance/program_governance/registry.py),
[dependency-admission policy](../../tools/governance/src/alpha_research_governance/dependency_admission/policy.py),
and [artifact-supply-chain bundle](../../tools/governance/src/alpha_research_governance/artifact_supply_chain/bundle.py)
modules: 17 program definitions, including the nested JSON-object hook, 10
dependency definitions, and 13 artifact definitions. Three `gpt-5.6-luna`
source writers at `xhigh` reasoning handled disjoint assignments, and one
`gpt-5.6-luna` integration writer prepared the debt and plan update. The parent
agent reviewed all 40 docstrings against their bodies, constants, models, tests
and baseline probes. The audit classified this as an R0 general-software slice.
No actionable documentation findings remain after corrections.

Program-helper contracts cover parsed table and list shapes, string/value
preservation, positive integers and finite or optional numbers; canonical dates
and `Z`-terminated UTC timestamps; TOML roots, JSON objects and nested duplicate
key rejection; ownership-role collection; repository-file containment and
symlink resolution; credential-free HTTPS syntax; inclusive package ranges; and
comma-separated dependency-list expansion. They distinguish parser-provided
typing from helper validation, aliases from copies, lexical checks from I/O, and
caught from propagated failures.

Dependency-helper contracts cover table/list/string/date/URL boundaries and
exact package parsing; lock-file root and package extraction; wheel-platform
coverage heuristics and finding order; raw source-text scanning for recognized
runtime-install commands; and the pre-read size check and JSON decoding boundary
for pip-audit and scorecard signals. The descriptions preserve the helpers'
skipping, ordering and error-propagation behavior without implying a full wheel
tag parser, code parser, network check or atomic size guarantee.

Artifact-helper contracts cover local deterministic JSON serialization and file
overwrite I/O; duplicate-key object construction and pre-read bounded JSON
object loading; subprocess/tool invocation, output combination and admitted
version-fragment matching; lexical bundle-relative helper paths; file digest and
size records; native-library name heuristics and ZIP/TAR archive inventory; and
the selected SPDX normalization and file-name extraction rules. The descriptions
state the local JSON format, non-atomic/pre-read limitations, archive inventory
boundary and limited SPDX validation without claiming RFC 8785 serialization,
archive extraction safety or complete SPDX validation.

The parent audit corrected the documented UTC parsing acceptance, JSON integer
and recursion errors, combined stdout/stderr stripping, wheel URL substring
rules, exact SPDX metadata requirements and lexical path-component rules.
Focused Ruff checks with `D`/`ANN401`, the Google convention and formatting pass
for all three modules, and `git diff --check` passes. See the [final validation
record](#step-5-validation-record-program-dependency-and-artifact-operation-helpers-2026-09-06).

Exactly **40** original documentation obligations are retired: 40 `PYD001`
summaries (17 program, 10 dependency and 13 artifact). The source inventory now
holds **1,168** obligations across 73 files: **370** documentation obligations
(75 summaries and 295 sections/parameters) and 798 function dispositions. The
three edited modules retain 99 documentation obligations (26 program, 29
dependency and 44 artifact) and 71 `PYC001` dispositions. The inferred-typing
inventory remains at 686 diagnostics. All other entries and metadata are
preserved; no allowance, exception, `PYC001` or typing-debt change is made.
Step 5 remains in progress.

### Step 5 implementation — CI selection and execution helpers

The eighteenth documentation slice covers 17 selected definitions across the
[CI selection](../../tools/governance/src/alpha_research_governance/ci_policy/selection.py),
[CI runner](../../tools/governance/src/alpha_research_governance/ci_policy/runner.py),
and [remote-execution runner](../../tools/governance/src/alpha_research_governance/remote_execution/runner.py)
modules: six selection definitions, seven CI execution helpers and four remote
execution helpers. The seven CI helpers are `_run_command_and_capture_output`,
`_run_command_with_visible_output`, `_git_tracked_paths`,
`_reject_generated_artifact_paths`, `_query_bazel_labels`,
`_changed_schema_modules` and `_git_worktree_state`. The clean baseline is
`a7fa4932c9d4c494b99c58b4035961213c73352e`.
Three `gpt-5.6-luna` source writers used `xhigh` reasoning for disjoint
assignments, and this plan record was prepared alongside their work. The parent
agent completed the semantic audit and combined verification.

The selection documentation covers NUL-delimited Git name-status boundaries,
rename/copy path handling, lexical Bazel source-label conversion and its limited
checks, XML declaration and entity restrictions, deterministic owner selection,
reverse-dependency attachment and full-graph fallback behavior. The CI runner
documentation covers argv execution, cwd/environment and byte/error boundaries;
exact Git status and tracked-path options, cwd-relative path reporting and
ignored-file behavior; raw Bazel output-line handling; and schema-root matching.
Remote-execution documentation covers credential trust and ownership, temporary
cleanup, command timeouts and exit/output propagation, and executable resolution.

The baseline AST, comment and unselected-docstring comparison passes, with all
other metadata preserved and no selected PYD findings. Selection has no
remaining PYD obligations; CI runner retains 48 and remote runner retains 29,
for 77 selected-module PYD obligations that belong to later work.

Exactly **36** original documentation obligations are retired: 12 `PYD001`
summaries and 24 `PYD002` sections/parameters, allocated as 25 selection, seven
CI runner and four remote runner obligations. The source inventory now holds
**1,132** obligations across 73 files: **334** documentation obligations (63
summaries and 271 sections/parameters) and 798 function dispositions. Step 5
remains in progress; high-level workflow refactoring remains step 6.

### Step 5 implementation — CI event and checkout helpers

The nineteenth documentation slice covers nine definitions in the [CI
runner](../../tools/governance/src/alpha_research_governance/ci_policy/runner.py):
event context/duration events, serialization/emission, event-log opening, secret
scanning, schema compatibility, pre-commit mutation checks and hosted checkout
cleanliness. Three `gpt-5.6-luna` writers at `xhigh` handled disjoint slices; the
captured working-tree baseline `a7fa4932c9d4c494b99c58b4035961213c73352e`
already included the earlier eighteenth slice.

The contracts distinguish captured versus visible output, raw Git status bytes,
local versus hosted checkouts, and lexical paths from file/process effects. They
record timezone equality with `datetime.UTC`, positive event windows,
finalization errors that can mask a command error, and truncating event-log writes
while preserving timeout, environment, schema-baseline and scanner boundaries.

Exactly **9** `PYD001` summaries are retired. The inventory after this slice holds
**1,123** obligations across 73 files: **325** documentation obligations (54
summaries and 271 sections/parameters) and 798 function dispositions. The parent
semantic audit and combined validation are complete; shared results are recorded
with slices 20–21 below.

### Step 5 implementation — evidence input and parsing helpers

The twentieth documentation slice covers 21 definitions across the [evidence
manifest](../../tools/governance/src/alpha_research_governance/evidence/manifest.py)
and [merge-request evidence](../../tools/governance/src/alpha_research_governance/evidence/mr.py)
modules: seven strict input classes, ten manifest helpers and four MR helpers.
Three `gpt-5.6-luna` writers at `xhigh` handled disjoint assignments; final
evidence-prose corrections are complete before combined validation.

The contracts separate strict Pydantic structure from parser semantics, including
mutable lists inside frozen models, immutable parser copies, and schema dispatch
by equality before strict integer validation. They cover exact string, role, digest, URL, path,
approval-commit and duplicate rules, limited Markdown parsing, GitHub event fields,
and the implemented filesystem and digest checks. JSON duplicate-key and size guards
are absent, and Markdown parsing remains limited to the documented subset.

Exactly **21** `PYD001` summaries are retired. The inventory after this slice holds
**1,102** obligations across 73 files: **304** documentation obligations (33
summaries and 271 sections/parameters) and 798 function dispositions. The evidence
semantic audit and combined validation are complete.

### Step 5 implementation — security, inventory and topology registry helpers

The twenty-first documentation slice covers 12 definitions in the [security
registry](../../tools/governance/src/alpha_research_governance/security_controls/registry.py),
[inventory registry](../../tools/governance/src/alpha_research_governance/inventory/registry.py)
and [topology registry](../../tools/governance/src/alpha_research_governance/repository_topology/registry.py):
eight security parsers, three inventory parser/graph helpers and one topology
validator. The parent completed semantic audit against implementations, models,
callers and tests.

The contracts distinguish exact-key preflight, scalar/list whitespace and ordering,
local date/ID/list checks from loader-wide references, URLs, statuses and freshness,
and caller-list finding mutation from immediate domain errors. Inventory docs record
iterative cycle traversal, duplicate-ID overwrite, first-seen rendering and ignored
unresolved edges; topology docs record filesystem/import checks and helper failures.

Exactly **12** `PYD001` summaries are retired. The inventory after this slice holds
**1,090** obligations across 73 files: **292** documentation obligations (21
summaries and 271 sections/parameters) and 798 function dispositions. The source
semantic audit and combined validation are complete.

### Step 5 implementation — remaining private governance helper contracts

The twenty-second documentation slice covers 21 private helper definitions across
six governance modules from clean HEAD `c710114972071e3d1512609d4de6bafed0a6ddcf`:
eight definitions in the [program-governance registry](../../tools/governance/src/alpha_research_governance/program_governance/registry.py),
including nested `visit_dependency`, two in [program status](../../tools/governance/src/alpha_research_governance/program_governance/status.py),
five in the [dependency-admission policy](../../tools/governance/src/alpha_research_governance/dependency_admission/policy.py),
four in the [artifact-supply-chain bundle](../../tools/governance/src/alpha_research_governance/artifact_supply_chain/bundle.py),
one in [architecture governance](../../tools/governance/src/alpha_research_governance/architecture_governance.py),
and one in the [engineering-standards policy](../../tools/governance/src/alpha_research_governance/engineering_standards/policy.py).
Three `gpt-5.6-luna` documentation writers at `xhigh` reasoning prepared
disjoint source slices. The parent audited every new docstring, requested
corrections and verified the revised contracts against the implementation.

The program helpers document legacy and purpose-specific dependency-expression
grammar; depth-first cycle traversal including the nested visitor; schema-specific
package-state and evidence handling; metric, finding-record and finding-disposition validation;
and the local evidence reads performed during repository validation. Status
helpers cover Markdown cell escaping and deterministic POSIX relative-link
rendering without owning file I/O.

The dependency helpers document exact vulnerability-decision and emergency-override
windows, roles, dispositions, identity handling and error translation; ordered
Python lock findings including retained local evidence and delegated Cosign
verification; migrated-record findings; and the limited Bazel, Nix, requirements
and workflow lock-surface checks. Artifact helpers document lexical bundle-relative
path checks, file digests and byte counts, archive-member inventory, selected SPDX name
coverage, repository identity reads and delegated release-admission effects.
Architecture logging documents ordered finding mutation, first-row duplicate
handling and propagated ADR reads. The engineering helper
documents exact Hypothesis dependency-record projection and drift findings.
These descriptions preserve helper ordering, input mutation boundaries, local I/O,
subprocess delegation and propagated versus translated errors without claiming
broader workflow, security or admission guarantees.

This slice retires exactly **21** `PYD001` summaries and no `PYD002` sections. The
missing-summary queue is therefore complete. The remaining **271** documentation
obligations are structured sections and parameter contracts across step 5; moved
workflow documentation is combined with the relevant step-6 service work. The
798 function dispositions are unchanged, and the separate inferred-typing
inventory remains at 686 diagnostics. Parent verification of the inventory
deletion, checksum update, focused checks and semantic audit is recorded below.

### Step 5 implementation — public Git, audit-signal and status contracts

The twenty-third documentation slice covers seven definitions across the [CI
runner](../../tools/governance/src/alpha_research_governance/ci_policy/runner.py),
[dependency-admission
policy](../../tools/governance/src/alpha_research_governance/dependency_admission/policy.py),
and [program-governance
status](../../tools/governance/src/alpha_research_governance/program_governance/status.py)
modules. Three `gpt-5.6-luna` writers at `xhigh` reasoning handled disjoint assignments. The
parent audit reviewed the source bodies, helpers, models, callers, and captured baseline before
integration. The captured working-tree baseline at `c710114972071e3d1512609d4de6bafed0a6ddcf`
already included the uncommitted twenty-second slice; those earlier changes are preserved.

The CI contracts document shell-free Git argument boundaries, exact lowercase commit resolution,
strict ASCII and embedded-NUL handling, changed-path expansion and ordering, and exact
two-parent merge verification. The dependency signal contracts document bounded JSON loading,
exact pip-audit lock coverage, owned expiry checks, unused `fixes` payloads, ordered findings,
repository and version binding, broader `fromisoformat` timestamp handling, freshness,
duplicate-name checks, required Scorecard checks, nonnegative score rules, and advisory-only
limits. The status contracts document deterministic Markdown rendering, limited objective-cell
escaping, POSIX relative links, one trailing LF, and UTF-8 reads with universal-newline
translation before exact text comparison for generated files.

This slice retires exactly **37** `PYD002` documentation obligations: 17 from the three Git
helpers, 12 from the two audit-signal assessors and eight from the two status functions. The
inventory now contains 1,032 obligations across 73 files: 234 `PYD002` and 798 `PYC001`, with no
`PYD001` obligations. The separate inventory of 686 inferred-typing diagnostics is unchanged.
Step 5 remains in progress with 234 documentation sections and parameters; documentation for
moved workflows is combined with the corresponding step-6 services. Validation is recorded
below.

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

## Step 5 validation record — CI, remote-execution and artifact policy contracts, 2026-09-05

The captured baseline used working-tree revision
`c2d25d787d0a26590ad17e0564f9056a0210bb54`, including the existing uncommitted
build-test and CLI/helper documentation slices. A copy of every tracked file
was captured before this slice. HEAD advanced independently to
`b3d9f1568d51b43611796e3d146ca18441ce1ce6` during the run; the final
comparison confirmed the tracked file set and all content outside this slice
remained identical to the captured working tree. Three `gpt-5.6-luna` writers used `xhigh`
reasoning on disjoint policy modules; the parent agent performed the semantic
audit, requested revisions and checked the final prose. The governance package
was rebuilt offline as a non-editable install. The three installed modules and
source-debt checker match the working tree byte-for-byte; both owned packages
remain installed non-editably.

| Check | Observed result |
| --- | --- |
| Documentation audit | General software, R0, against the repository's Python/Google documentation contract. All 29 functions have documentation. The audit corrected lane duplicate handling, fragment-check scope, reference-date semantics, file-check limitations, and translated versus propagated failures. No actionable documentation findings remain in the three modules. |
| Executable AST and comment comparison | All three executable ASTs match after stripping docstrings and normalizing type-ignore line offsets. Comment text, including import headings and suppression metadata, is unchanged. Signatures, constants, file/process operations, return values and validation behavior are preserved. |
| Test collection compatibility | The complete ordered list of 672 pytest node IDs is unchanged. |
| Focused documentation checks | All three modules have zero source-scanner PYD findings; Ruff `D`/`ANN401` with the Google convention and `ruff format --check` pass. |
| Exact debt reconciliation | Retired exactly 52 obligations: 21 PYD001 summaries and 31 PYD002 sections/parameters. The remaining source inventory holds 1,361 obligations across 73 files: 563 documentation obligations and 798 function dispositions. Every other entry and its metadata are unchanged, and the checksum pin matches. |
| `make lint format-check typecheck engineering-standards-check` | Passed across 136 Python/stub files; the inferred-typing inventory matches 686 diagnostics and native stubtest passes over 1,548 modules. |
| Default pytest | `uv run --frozen --no-editable pytest -q` passed 663 tests with 9 deselected, using the pinned installed environment and existing tools. |
| Bazel | With the host sentinel, `bazel test --config=ci //...` passed all 20 targets: 12 executed and eight cached. The initial sandbox attempt could not write the external cache; the authorized rerun passed. |
| Pre-commit | `pre-commit run --all-files` passed every hook, including typing, source standards, architecture/documentation links, secret scanning and all governance policies. |
| Change scope | Only the three policy docstring targets, exact debt deletion/checksum and this plan differ from the captured working tree. Earlier uncommitted slices, tests, configuration, fixtures, dependencies, locks, exceptions, function dispositions and typing inventory are preserved. |

This is an R0 documentation slice with no capital, data/model or privilege
change. Reversal restores these docstrings, debt deletions/checksum and this
plan record together. Step 5 remains in progress with 563 documentation
obligations; 798 function dispositions and 686 inferred-typing diagnostics
remain later migration work. These are local checks; hosted CI, `make ci-full`,
and separate integration and performance selections were not run.

## Step 5 validation record — risk/evidence policy and wheel-source contracts, 2026-09-05

The captured baseline used working-tree revision
`b3d9f1568d51b43611796e3d146ca18441ce1ce6`, including the uncommitted preceding
CI/remote/artifact policy slice. Three `gpt-5.6-luna` writers at `xhigh`
reasoning documented separate modules. The parent agent audited each definition,
checked relevant models, callers and existing tests, requested revisions, and
reviewed the final prose. The governance package was rebuilt offline as a
non-editable install; all three installed modules and the debt checker match
the working tree byte-for-byte. Both owned packages remain non-editable.

| Check | Observed result |
| --- | --- |
| Documentation audit | General software, R0, against the repository's Python/Google documentation contract. All 52 definitions have documentation. Corrections distinguish nested closed schemas, allowed empty lists and duplicate triggers, JSON encodings and numeric handling, parser preconditions, verifier ordering, timeout semantics, and propagated versus translated errors. No actionable documentation findings remain in the three modules. |
| Executable AST and comments | All three ASTs match the captured baseline after removing docstrings and normalizing type-ignore line offsets. All comments, including suppression metadata, are unchanged. Signatures, validation, subprocess arguments, file operations and return expressions are preserved. |
| Schema and output compatibility | All 15 private input-model schemas match after excluding description metadata. Both loaded policy results serialize identically under a fixed hash seed. |
| Test collection | The complete ordered list of 672 pytest node IDs is unchanged. |
| Focused documentation checks | Zero PYD findings across the three modules; Ruff with the configured rules plus `D`/`ANN401` and Google convention passes, as does formatting. |
| Exact debt reconciliation | Retired 76 obligations: 44 PYD001 summaries and 32 PYD002 sections/parameters. The inventory holds 1,285 obligations across 73 files: 487 documentation obligations and 798 function dispositions. Other entries, attribution, exceptions and inferred-typing debt are unchanged; the checksum pin matches. |
| `make lint format-check typecheck engineering-standards-check` | Passed across 136 Python/stub files. The inferred inventory matches 686 diagnostics, and native stubtest passes over 1,548 modules. |
| Default pytest | `uv run --frozen --no-editable pytest -q` passed 663 tests with 9 deselected in the pinned installed environment. |
| Bazel | `bazel test --config=ci //...` passed all 20 targets, with the host sentinel and authorized external cache: 12 executed and eight cached. |
| Pre-commit | `pre-commit run --all-files` passed every hook, including typing, source standards, architecture/documentation links, secret scanning and all governance policies. |
| Change scope | Only the three documentation targets, exact debt deletions/checksum and this plan differ from the captured working tree. The preceding slice and all other tracked file contents are preserved. |

This is an R0 documentation slice. Reversal restores these docstrings, matching
debt entries/checksum and the plan record together. Step 5 remains in progress
with 487 documentation obligations; the 798 function dispositions and 686
inferred-typing diagnostics remain later work. Hosted CI, `make ci-full`, and
separate integration and performance selections were not run.

## Step 5 validation record — architecture, ownership and standards helpers, 2026-09-05

The captured baseline used working-tree revision
`b3d9f1568d51b43611796e3d146ca18441ce1ce6`, including both preceding uncommitted
policy documentation slices. Three `gpt-5.6-luna` writers used `xhigh` reasoning
for disjoint assignments. The parent agent audited each selected definition
against its body, relevant models, callers and tests, requested corrections and
inspected the revisions. The governance package was rebuilt offline as a
non-editable install. All three installed modules and the source-debt checker
match the working tree byte-for-byte; both owned packages remain non-editable.

| Check | Observed result |
| --- | --- |
| Documentation audit | General software, R0, against the repository's Python/Google documentation contract. All 31 selected definitions have documentation. Corrections cover exact metadata keys, section boundaries, prefix matching, Git path inclusion, permissive role collection, lock-record shape rejection versus field skipping, suppression failure ordering and propagated CLI errors. No actionable findings remain in the selected documentation. |
| Executable AST and comments | All three ASTs match the captured baseline after stripping docstrings and normalizing type-ignore line offsets. All comments are unchanged. Signatures, validation, subprocess arguments, file operations and return expressions are preserved. |
| Deferred workflow scope | Every unselected docstring is unchanged. The same 41 workflow documentation obligations remain across these modules for step-6 service slices; the source checker has zero PYD findings for the 31 selected definitions. |
| Schema and CLI compatibility | The decision-log input-model schema matches after excluding description metadata. All six captured CLI statuses and stdout/stderr outputs match, covering success, missing repository and excess arguments for both entrypoints. |
| Test collection | The complete ordered list of 672 pytest node IDs is unchanged. |
| Focused documentation checks | All three modules pass Ruff with the configured rules plus `D`/`ANN401` and the Google convention, and formatting passes. |
| Exact debt reconciliation | Retired exactly 42 obligations: 25 PYD001 summaries and 17 PYD002 sections/parameters. The inventory now holds 1,243 obligations across 73 files: 445 documentation obligations (150 summaries and 295 sections/parameters) and 798 function dispositions. All other entries and metadata are unchanged; the checker changes only the matching checksum. |
| `make lint format-check typecheck engineering-standards-check` | Passed across 136 Python/stub files. The inferred-typing inventory matches 686 diagnostics, and native stubtest passes over 1,548 modules. |
| Default pytest | `uv run --frozen --no-editable pytest -q` passed 663 tests with 9 deselected, using the pinned installed environment and existing Cosign/Syft executables. |
| Bazel | `bazel test --config=ci //...` passed all 20 targets, with the host sentinel and authorized external cache: 12 executed and eight cached. |
| Pre-commit | `pre-commit run --all-files` passed every hook, including strict typing, source standards, architecture/documentation links, secret scanning and all governance policies. |
| Change scope | Only the three selected documentation targets, exact debt deletions/checksum and this plan differ from the captured working tree. The tracked file set, prior uncommitted work, tests, fixtures, configuration, dependencies, locks, exception records, function dispositions and inferred-typing inventory are preserved. |

This is an R0 documentation slice. Reversal restores these docstrings, matching
debt entries/checksum and the plan record together. Step 5 remains in progress
with 445 documentation obligations; the 798 function dispositions and 686
inferred-typing diagnostics remain later work. Hosted CI, `make ci-full`, and
separate integration and performance selections were not run.

## Step 5 validation record — inventory, topology and security registry helpers, 2026-09-05

Validation used the clean captured baseline revision
`2a25a10c000c11cfee9c26d1e0ce36087591a437`. Three `gpt-5.6-luna` writers used
`xhigh` reasoning for disjoint assignments; the parent agent completed the
semantic audit and revisions against the implementations, models and tests. The
governance package was rebuilt offline as a non-editable install; the final
three registry files and source-debt checker matched the installed sources
byte-for-byte, and the runtime package remained non-editable. The last writer
revision briefly exposed three long documentation lines; final wrapping was
fixed before rebuilding and rerunning the checks.

| Check | Observed result |
| --- | --- |
| Documentation audit | General software, R0 documentation-only review. All 35 selected definitions have documentation, with no actionable findings remaining. |
| Executable AST and comments | All three module ASTs match after stripping docstrings and normalizing `TypeIgnore` offsets. All comments and unselected docstrings are unchanged. |
| Deferred workflow scope | The unedited workflows retain 39 PYD obligations across the three registry modules for their step-6 service slices. |
| Focused documentation checks | The selected 35 definitions have zero source-scanner PYD findings; Ruff with the configured rules plus `D`/`ANN401` and the Google convention passes, as does formatting. |
| Exact debt reconciliation | Retired exactly 35 PYD001 summaries: 10 inventory, 12 topology and 13 security. The inventory now holds 1,208 obligations across 73 files: 410 documentation obligations (115 PYD001 summaries and 295 PYD002 sections/parameters) and 798 PYC001 function dispositions. Inferred typing remains at 686 diagnostics; all other inventory metadata and entries are preserved, with only the exact deletions and matching checksum change. |
| `make lint format-check typecheck engineering-standards-check` | Passed across 136 Python/source-stub files; the 686-diagnostic inferred-typing inventory matches and native stubtest covers 1,548 modules. |
| Test collection compatibility | The ordered node IDs for the 663 selected tests match before and after; the full collection contains 672 nodes with 9 deselected. |
| Documentation links | The architecture-governance check passed for 14 ADRs, including local Markdown link validation. |
| Default pytest | `uv run --frozen --no-editable pytest -q` passed 663 tests with 9 deselected in the pinned environment using the existing Cosign and Syft executables. |
| Bazel | With the host sentinel and authorized external cache, `bazel test --config=ci //...` passed all 20 targets: 12 executed and 8 cached. The initial sandbox external-cache attempt failed; the authorized rerun passed. |
| Change scope | Only the three registry docstring targets, exact debt deletions/checksum and this plan changed. Tests, fixtures, configuration, dependencies, locks, exception records, typing inventory and function dispositions are unchanged. |

This is an R0 documentation slice. Reversal restores these docstrings, debt
deletions/checksum and this plan record together. Step 5 remains in progress
with 410 documentation obligations; 798 function dispositions and 686
inferred-typing diagnostics remain later work. Pre-commit, hosted CI,
`make ci-full`, and separate integration and performance lanes were not run.

## Step 5 validation record — program, dependency and artifact operation helpers, 2026-09-06

Validation used the captured working-tree baseline at revision
`2a25a10c000c11cfee9c26d1e0ce36087591a437`, which included the uncommitted
sixteenth slice. Three `gpt-5.6-luna` source writers and one integration writer
worked at `xhigh` reasoning; a fifth `gpt-5.6-luna` validation executor also used
`xhigh` for reconciliation and verification. The parent agent completed the semantic audit
after submissions, made direct corrections, independently reviewed the output
and diff, and ran the Bazel and architecture checks.

| Check | Observed result |
| --- | --- |
| Documentation audit | General software, R0. All 40 selected definitions were reviewed against their bodies, constants, models, tests and baseline probes. No actionable documentation findings remain after corrections. |
| Executable AST, comments and scope | All three module executable ASTs match after stripping docstrings and normalizing `TypeIgnore` offsets. All comments and unselected docstrings are unchanged; exactly the selected 40 docstrings changed. |
| Focused documentation checks | The three modules pass Ruff with the configured rules plus `D`/`ANN401` and the Google convention, and formatting passes. |
| Exact debt reconciliation | Retired exactly 40 `PYD001` summaries: 17 program, 10 dependency and 13 artifact. The inventory now holds 1,168 obligations across 73 files: 370 documentation obligations (75 summaries and 295 sections/parameters) and 798 function dispositions. The three modules retain 99 documentation obligations and no selected `PYD` findings. The inferred-typing inventory remains at 686 diagnostics. |
| Package and checksum evidence | The governance wheel was rebuilt offline as non-editable; the three source modules and checker match installed sources byte-for-byte. Both owned packages remain non-editable. Four source hashes and the debt hash remain stable across validation. |
| Type and native checks | `make lint format-check typecheck engineering-standards-check` passed across 136 Python/source-stub files; the 686-diagnostic inventory matches, and native stubtest passes over 1,548 modules. |
| Collection and pytest | All 672 ordered pytest node IDs match before and after when overriding `addopts` to collect every test. The default pytest selection passed 663 tests with nine deselected. |
| Bazel and architecture | `bazel test --config=ci //...` passed all 20 targets with the host sentinel and authorized existing cache: 12 executed and eight cached. The architecture check passed for 14 ADRs, including local Markdown links. |
| Whitespace and scope | `git diff --check` passed. Only the three selected source modules, exact 40 debt deletions/checksum and this plan differ from the captured tree; prior sixteenth-slice registry docstrings, tests, fixtures, configuration, dependencies, locks, exceptions, function dispositions and inferred-typing inventory are unchanged. |

No pre-commit-all, hosted CI, `make ci-full`, or separate integration/performance
lanes were run. Reversal restores the 40 docstrings, matching debt entries and
checksum, and this plan record together. Step 5 remains in progress with 370
documentation obligations. The source inventory also retains 798 function
dispositions, for 1,168 obligations in total; 686 inferred-typing diagnostics
remain in the separate typing inventory.

## Step 5 validation record — CI selection and execution helpers, 2026-09-06

Validation used the clean baseline revision
`a7fa4932c9d4c494b99c58b4035961213c73352e`. Three `gpt-5.6-luna` source writers
used `xhigh` reasoning for disjoint assignments; this plan record was prepared
alongside their work. The parent agent completed the semantic audit and combined
verification. The audit specifically covers output
whitespace, Git cwd-relative paths and ignored files, raw status bytes, credential
trust and ownership, temporary cleanup, exact Git status/path parsing, XML and
source-label boundaries, and full-selection fallback behavior. All corrections
are complete, including final ASCII, NUL and source-prefix wording refinements.
The regression runs below preceded the final selection wording; no executable
changes were made.

| Check | Observed result |
| --- | --- |
| Documentation audit | General software, R0. All 17 source docstrings were audited against bodies, models, callers, tests and baseline probes. All corrections are complete, and no actionable documentation findings remain. |
| Executable AST, comments and scope | Final comparison confirms executable ASTs, comments and unselected docstrings are unchanged; the regression runs preceded the final wording corrections, and no executable differences were introduced. |
| Exact debt reconciliation | Retired exactly 36 obligations: 12 `PYD001` summaries and 24 `PYD002` sections/parameters, allocated as 25 selection, seven CI runner and four remote runner. The inventory now holds 1,132 obligations across 73 files: 334 documentation obligations (63 summaries and 271 sections/parameters) and 798 function dispositions. |
| Deferred module scope | Selection has zero remaining PYD obligations; CI runner retains 48 and remote runner retains 29, for 77 selected-module PYD obligations remaining for later work. |
| Package evidence | The final offline-rebuilt non-editable governance wheel matches all three changed source modules and the `python_debt` checker byte-for-byte; the runtime package remains non-editable. All four audited/installed source hashes remain stable after aggregate hooks. |
| Focused documentation checks | Focused Ruff with the configured rules plus `D`/`ANN401` and the Google convention, together with format-check, passed all three modules on the final docs. |
| Root aggregate validation | `pre-commit run --all-files --verbose` exited 0 with every hook passing, including root lint/format, strict mypy across 136 source files, the 686-diagnostic inferred inventory, native stubtest over 1,548 modules, source standards, all governance checks, architecture/documentation links for 14 ADRs, secrets, lock and whitespace checks. |
| Full pytest | The default selection passed 663 tests with 9 deselected in 17.77 seconds, using the offline-rebuilt non-editable governance wheel and the existing non-editable runtime package. |
| Bazel | The authorized existing-cache rerun passed all 20 targets: 12 executed and 8 cached, with the synthetic host sentinel. The initial sandbox run failed on external-cache write access. |
| Collection comparison | The final ordered collection comparison matches before and after at 672 pytest node IDs, with `addopts` overridden to include all tests. |
| Change scope | Parent comparison confirms that only the six slice files changed; final AST/comment/unselected-docstring comparison confirms no executable differences, all other metadata is preserved, and `git diff --check` passes. |

This is an R0 documentation slice. Reversal restores the 17 docstrings, matching
debt entries/checksum and this plan record together. Step 5 remains in progress
with 334 documentation obligations; the source inventory also retains 798
function dispositions, for 1,132 obligations in total, and 686 inferred-typing
diagnostics remain in the separate typing inventory. High-level workflow
refactoring remains step 6. Semantic review, aggregate hooks, focused Ruff,
collection comparison, Bazel and the recorded pytest result are complete. No
`make ci-full`, hosted CI or separate integration/performance lanes were run.

## Step 5 validation record — CI event/checkout, evidence input/parsing, and registry helpers, 2026-09-06

This combined record uses the captured working-tree baseline at revision
`a7fa4932c9d4c494b99c58b4035961213c73352e`. That capture already included the
prior uncommitted eighteenth slice, so it is not described as a clean baseline
and its changes are not attributed to these three slices. Three
`gpt-5.6-luna` source writers worked at `xhigh` reasoning on disjoint source
assignments; the parent agent audited all 42 added docstrings after the final
corrections. The parent-provided debt reconciliation uses pin SHA
`c3c3acb0c655b8d7498419a4568ab9d3630389957409aa005719901955de4e59`, with
`PYC001` and inferred-typing inventories unchanged. The records below consolidate
the shared final-state checks; the cumulative debt counts remain separate in the
three implementation sections above.

| Check | Observed result |
| --- | --- |
| Documentation audit | DONE: all 42 selected docstrings across slices 19–21 were audited against implementations, helpers, models, callers, tests and targeted probes; no actionable documentation findings remain. Classification: R0 general software documentation audit. |
| Executable AST, comments and unselected docs | DONE: all six source modules retain unchanged executable ASTs, comments and unselected docstrings; prior uncommitted slice-18 changes and unrelated captured-tree content are preserved. |
| Exact debt reconciliation | DONE: 9 + 21 + 12 = 42 `PYD001` summaries retired; the final inventory is 1,090 obligations across 73 files, comprising 292 documentation obligations (21 `PYD001` and 271 `PYD002`) plus 798 `PYC001` dispositions. The debt pin is `c3c3acb0c655b8d7498419a4568ab9d3630389957409aa005719901955de4e59`; `PYC001` and 686 inferred-typing diagnostics are unchanged. |
| Focused documentation checks | DONE: configured Ruff with `D`/`ANN401` and Google convention, plus Ruff format, passes all six source modules. |
| Package and installed-source evidence | DONE: the governance wheel was rebuilt offline after final edits; both owned packages remain non-editable, all six source modules and the `python_debt` checker byte-match installation, and seven hashes remain stable after hooks. |
| Captured-tree scope | DONE: the parent verifier passes the entire captured tracked tree outside the six source modules, debt JSON, checker and plan (nine files); prior uncommitted slice-18 changes are preserved. |
| Root aggregate validation | DONE: `pre-commit run --all-files --verbose` exited 0 with all hooks, including strict mypy across 136 source files, native stubtest across 1,548 modules, the 686-diagnostic typing inventory, governance checks, architecture checks for 14 ADRs with local links, lock/secrets checks and whitespace checks. |
| Default pytest | DONE: the default selection passed 663 tests with 9 deselected in 17.09 seconds. |
| Test collection | DONE: all 672 ordered pytest node IDs are identical before and after with `addopts` overridden. |
| Bazel | DONE: `bazel test --config=ci //...` passed all 20 targets, with 12 executed and 8 cached using the synthetic host sentinel and authorized existing external cache. |
| Final plan and scope checks | The parent audited the completed plan, confirmed that only the six source modules, exact debt deletions/checksum and this plan differ from the captured tree, and reran `make architecture-check` for 14 ADRs/local links and `git diff --check`; both passed. Tests, fixtures, configuration, dependencies, locks, exceptions, function dispositions and the inferred-typing inventory are unchanged. |

Reversal restores the 42 docstrings, matching debt entries and pin, and this plan
record together. Step 5 remains in progress; high-level workflow refactoring
remains step 6. Hosted CI, `make ci-full`, and separate integration/performance
lanes were not run.

## Step 5 validation record — remaining private governance helper contracts, 2026-09-06

This record uses clean HEAD `c710114972071e3d1512609d4de6bafed0a6ddcf` as the
slice baseline. Three `gpt-5.6-luna` writers at `xhigh` reasoning produced the
requested documentation. The parent audited all 21 source contracts and the
plan, corrected the drafts, and verified the final combined tree.

| Check | Observed result |
| --- | --- |
| Documentation audit | Passed: general software documentation, R0, against the repository's Python/Google contract. All 21 docstrings were checked against implementations, helpers, models, callers and tests. Corrections cover dependency-overlap scope, limited lock checks, temporary verifier effects, ADR finding order and file-size units. No actionable documentation findings remain. |
| Semantic probes | Passed: legacy all-of/any-of overlap, cross-purpose reuse and paired clause acceptance match the prose; temporary fixtures confirm that requirements versions and Nix revision/hash contents are not checked by the lock-surface helper. |
| Executable AST, comments and unselected docs | Passed: all six source modules retain unchanged executable ASTs, comments and unselected docstrings. All selected definitions have zero remaining documentation findings. |
| Exact debt reconciliation | Passed: exactly 21 `PYD001` summaries were removed with no additions or inventory-metadata edits. The source inventory has 1,069 obligations across 73 files: 271 `PYD002` sections/parameters and 798 `PYC001` dispositions. The debt pin is `c068d63832d2aab7a5666b032d199f265337c6671001109bf75879c918749e26`. |
| Inferred-typing inventory | Passed: the separate inventory remains unchanged at 686 diagnostics. |
| Lint and formatting | Passed: scoped Ruff with `D`/`ANN401` and the Google convention for all six modules; `make lint format-check` passed across 136 Python files. |
| Package and installed-source evidence | Passed: the final governance package was rebuilt offline as non-editable; all six source modules and the checker byte-match installation. Both owned packages remain non-editable, and seven audited source/checker hashes are unchanged after final hooks and tests. |
| Aggregate pre-commit validation | Passed: `pre-commit run --all-files --verbose` exited 0 on the stable tree. This includes strict mypy across 136 files, native stubtest across 1,548 modules, the typing inventory, source standards, governance, architecture/local links, lock, secrets and whitespace checks. An earlier run detected concurrent plan edits despite its tools passing; the stable-tree rerun resolved that transient failure. |
| Default pytest | Passed: the final default selection passed 663 tests with 9 deselected in 16.10 seconds. |
| Test collection | Passed: all 672 ordered pytest node IDs match before and after with `addopts` overridden. |
| Bazel | Passed: the final `bazel test --config=ci //...` run exited 0 with all 20 targets passing, 12 executed and 8 cached, using the authorized existing external cache and synthetic host sentinel. The first sandboxed attempt could not write the cache. |
| Final plan and change scope | Passed: only six source modules, the debt JSON, the checker pin and this plan differ from the clean baseline (nine files). The parent audited the completed plan and checked architecture/local links and whitespace after recording the results. Tests, fixtures, configuration, dependencies, locks, exceptions and both function dispositions and inferred-typing debt are unchanged. |

Reversal restores the 21 added docstrings, their matching debt entries and pin,
and this plan record together. Step 5 remains in progress with 271 structured
sections/parameter obligations; moved workflow documentation is combined with
step-6 service slices. Hosted CI, `make ci-full`, and separate integration and
performance lanes were not run.

## Step 5 validation record — public Git, audit-signal and status contracts, 2026-09-06

The baseline is the captured working tree at
`c710114972071e3d1512609d4de6bafed0a6ddcf`, including the previously completed,
uncommitted twenty-second slice. Three `gpt-5.6-luna` writers used `xhigh`
reasoning. The parent audited all seven revised docstrings and the plan, then
verified the combined tree without attributing the earlier slice to this work.

| Check | Observed result |
| --- | --- |
| Documentation audit | Passed: general software documentation, R0, against the repository's Python/Google contract. All seven public contracts were checked against implementations, helpers, models, callers and tests. Corrections clarify Scorecard duplicate-name scope and timestamp parsing, pip-audit error aggregation, and propagated embedded-NUL Git errors. No actionable documentation findings remain. |
| Semantic probes | Passed: Scorecard accepts Boolean and unbounded nonnegative required scores, ISO week-date timestamps and negative scores for additional names; duplicate additional names are rejected and a naive validation clock propagates `TypeError`. pip-audit ignores `fixes` contents and extra dependency fields. Generated status accepts CRLF through newline translation and rejects a missing trailing LF. A NUL-bearing Git ref propagates `ValueError`. |
| Executable AST, comments and unselected docs | Passed: all three modules retain unchanged executable ASTs, comments and unselected docstrings, including prior slice-22 additions. All seven selected definitions have zero remaining documentation findings. |
| Exact debt reconciliation | Passed: exactly 37 `PYD002` obligations retired, with no additions or inventory-metadata changes. The inventory has 1,032 obligations across 73 files: 234 `PYD002` and 798 `PYC001`, with no `PYD001`. The checksum pin is `cd2f855bbf4dd49d893e2d858fe77ca9525f82e828aef219e7c664797f189a3d`. The separate 686-diagnostic inferred-typing inventory is unchanged. |
| Lint and formatting | Passed: scoped Ruff with `D`/`ANN401` and the Google convention for all three modules; `make lint format-check` passed across 136 Python files. |
| Package and installed-source evidence | Passed: the governance package was rebuilt offline as non-editable; all three changed modules and the checker byte-match installation. Both owned packages remain non-editable, and all four audited source/checker hashes remain unchanged after hooks and tests. |
| Aggregate pre-commit validation | Passed: `pre-commit run --all-files --verbose` exited 0 with every hook passing, including strict mypy across 136 files, native stubtest across 1,548 modules, typing and source inventories, governance, architecture/local links, lock, secrets and whitespace checks. |
| Default pytest | Passed: 663 tests passed with 9 deselected in 16.35 seconds. |
| Test collection | Passed: all 672 ordered pytest node IDs match the captured baseline with `addopts` overridden. |
| Bazel | Passed: `bazel test --config=ci //...` exited 0 with all 20 targets passing, 12 executed and 8 cached, using the authorized existing external cache and synthetic host sentinel. |
| Final plan and captured-tree scope | Passed: only the three selected source modules, exact debt deletions, checksum pin and this plan differ from the captured tree (six files). All other tracked-file hashes and the pre-existing untracked-file list are unchanged. The parent audited the final plan and checked architecture/local links and whitespace after recording results. Tests, fixtures, configuration, dependencies, locks, exceptions, function dispositions and inferred-typing debt are unchanged. |

Reversal restores the seven prior docstrings, their 37 matching debt entries and
pin, and this plan record together, preserving the earlier uncommitted slice.
Step 5 remains in progress with 234 structured sections/parameter obligations;
documentation for moved workflows is combined with step-6 service slices. Hosted
CI, `make ci-full`, and separate integration/performance lanes were not run.
