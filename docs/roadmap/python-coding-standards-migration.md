# Python coding standards migration

Status: **steps 1–7 implementation and affected validation complete as of
2026-09-07.** The source and inferred-typing migration inventories have been
retired. Global static enforcement replaces their allowances. The full CI
acceptance gate remains unexecuted under the requested affected-test scope.

The [Python coding guide](../coding_standards/python.md) defines the standard;
[pyproject.toml](../../pyproject.toml) and the governance checker enforce it.

## Completed work: steps 1–6

| Step | Result |
| --- | --- |
| 1. Establish the executable contract | Added source checks, exact debt identities, checksum pins and attributed exceptions to the existing checker, pre-commit and Bazel integration. The original inventory recorded 3,079 obligations. |
| 2. Normalize imports | Applied the configured category headings and spacing; retired all 243 import obligations without changing import behavior. |
| 3. Remove explicit Any | Replaced test escape hatches with typed records, callbacks and validated boundaries. Owned source and tests contain no explicit `Any`; invalid-input tests retain their original rejection paths. |
| 4. Strengthen library and parsing boundaries | Enabled the Pydantic mypy plugin and stronger scoped checks; added typed JSON/TOML boundaries, native-library stubs and exact inferred-typing debt tracking. |
| 5. Document contracts | Completed useful Google-style documentation for existing contracts. Documentation for moved workflows was completed with Step 6. |
| 6. Give workflows class ownership | Refactored domain and governance workflows, loaders, validators, evidence/artifact operations, CI runners and test fixtures. Reviewed retained helpers and adapters; retired every remaining source-standard obligation. |

Services bind their repository, policy, path or collaborator dependencies and
keep findings local to each invocation. Constructors avoid fallible I/O.
Pydantic models replace the residual governance dataclasses. The coding guide
retains the measured-performance alternatives for data records and numeric kernels.
Supported public functions, CLI entry points, schemas, serialized results,
exception boundaries, numerical behavior and test contracts remain compatible.

## Step 6 completion evidence

The final governance slice was implemented by Luna subagents at extra-high
reasoning and audited before the combined validation run.

| Check | Result recorded on 2026-09-07 |
| --- | --- |
| Source debt | Final 324 obligations retired across 36 files; the [Step 6 inventory](https://github.com/lixuanguang/alpha-research-lab-private/blob/da39356edfb9a067521b1fc02152599da4dc9c62/docs/architecture/python-standards-debt.json) is empty and its checksum matches. |
| Function dispositions | 308 new reviewed entries: 212 low-level helpers, 34 framework callbacks and 62 compatibility adapters. All 173 prior entries remain unchanged in the [exception register](../architecture/python-standards-exceptions.toml). Entries retain owners, rationales, expiry dates and source fingerprints. |
| Affected pytest cases | 527 default, 5 performance and 1 integration case passed. All 531 existing cases remain; two regressions cover loader reuse after failure and resolved-root artifact admission. |
| Owning Bazel targets | All 10 selected targets passed under `--config=ci`, including the three domain-evidence consumers. |
| Static checks | Configured Ruff lint, Google-docstring/`ANN401`, formatting and strict mypy passed for 60 affected/associated files. Source reconciliation and exception fingerprints passed. |
| Inferred typing | 57 diagnostics retired without new, moved or multiplied debt. The [Step 6 typing inventory](https://github.com/lixuanguang/alpha-research-lab-private/blob/da39356edfb9a067521b1fc02152599da4dc9c62/docs/architecture/python-typing-debt.json) retains 172 diagnostics across 109 identities. |

Validation used the pinned environment and real Cosign 3.1.3. The ownership
integration test passed after access to the existing uv cache was permitted.
The final slice used affected tests and scoped typing checks; it did not run a
full-repository suite, full CI lane or full-scope stronger typing probe.
These historical results preceded the Step 7 typing retirement below.

## Step 7: adoption and final enforcement

The remaining 172 diagnostics across 109 identities are addressed at their
sorting, parsing, Pydantic, Hypothesis and Typer boundaries. Raw external values
are received as `object` and narrowed before use. Generated property tests keep
their existing names, bodies and settings; model serialization keeps its original
serializer and JSON settings.

Ruff `D` and `ANN401` are enabled with the Google convention. Strict mypy now
applies `disallow_any_explicit`, `disallow_any_unimported`,
`disallow_any_decorated` and `disallow_any_expr` across runtime source, tests,
governance tooling and owned native stubs. The root typecheck runs mypy once
and retains native stubtest. Pre-commit and hosted CI use that configuration;
Bazel's hermetic suite now explicitly includes the source-standards tests.
The instrument-identity and venue-calendar unit targets now invoke pytest;
their previous module entry points exited without executing the collected cases.

Both migration inventories and their checksum/reconciliation machinery are
retired. Source findings must pass directly or match an exact reviewed design
exception. The historical `python_typing` module command remains available and
fails directly on diagnostics; it no longer accepts a debt inventory.

### Adoption and compatibility boundaries

CI lane operations call methods on their existing `CIRunner` instance. The
temporary pre-commit and dependency-record wrappers are removed, and their
focused tests use the owning runner and validator. Remaining supported
boundaries are intentional:

- `alpha_research.*` facade imports and exports, canonical exported functions,
  console commands and module entry points remain compatible.
- Public function adapters delegate to owning services and preserve argument,
  error, serialization and numerical contracts.
- Private loader seams exercised by failure-injection tests remain in place;
  their owning services retain the actual workflow. Pure parsing/serialization
  helpers and required framework callbacks keep attributed dispositions.

The exception register retains its existing expiry dates. Definition changes
require reviewed fingerprint updates; expired, moved, duplicated or stale
exceptions still fail. Review retained dispositions before **2027-03-01**.

### Completion evidence and validation scope

Implementation details were completed by Luna subagents at extra-high reasoning,
then reviewed and validated together.

| Check | Result recorded on 2026-09-07 |
| --- | --- |
| Migration debt | All remaining 172 inferred-typing diagnostics across 109 identities retired; both migration inventories and their allowances removed. |
| Static enforcement | Complete configured Ruff lint and formatting passed; strict mypy with global inferred-`Any` restrictions passed for 141 source files. Native stubtest passed across 1,548 modules. |
| Governed exceptions | All 486 exact entries passed source reconciliation: 48 reviewed fingerprints renewed, two obsolete wrappers removed and seven narrowly attributed helpers added. Existing owners, rationales and expiry dates were preserved. |
| Affected pytest | 676 default cases passed. Six additional performance cases covering the changed catalog and governance code passed. Eight performance cases were deselected in the default run; two covering unchanged financial and calendar implementations were not rerun. |
| Coverage preservation | Collection comparison retained every existing domain and non-inventory governance case. Retired inventory tests were replaced by direct-failure and configuration-regression coverage; malformed-input tests and property-test names, bodies and settings remain intact. |
| Owning Bazel targets | All 15 selected targets passed under `--config=ci`. Logs confirmed actual pytest execution, including 20 instrument-identity and 59 venue-calendar cases. Four environment-dependent cases skipped under Bazel passed in the affected pytest run. |
| Governance and compatibility | `make engineering-standards-check` passed. All 218 facade/domain exports matched the starting revision and resolved at runtime; CI and remote-execution CLI help dispatched successfully. |

Validation used the pinned environment and real Cosign 3.1.3. Only affected
pytest cases, their relevant performance checks and owning Bazel targets ran.
Complete-scope lint and mypy checks were required because their configuration
changed globally. Neither the full repository pytest suite nor `make ci-full`
was run, as requested.

The authoritative `make ci-full` acceptance gate remains a separate unexecuted
validation requirement; scoped results must not be reported as a full-lane pass.

## Validation and rollback

Continue in small slices under the existing operating policy. Run the affected
lint, formatting, typing and owning tests; include `make engineering-standards-check`
when its policy or implementation changes. Resolve Bazel targets and relevant
reverse dependencies from the checked-in build files.

Preserve behavioral coverage: repeated calls, deterministic findings, injected
failures, malformed inputs, exact errors and existing goldens. Do not replace
behavioral tests with assertions that a class exists or bypass the entry point
under test. If modules move, update build ownership, packaging, CI selection and
imports together; do not change evidence schemas incidentally.

Rollback the service and caller changes together if behavior differs. Preserve
existing lint/typing controls and governed exception records; use the historical
revision if rollback requires the retired inventories. Revert only newly
introduced failing configuration where necessary. No persisted-data migration is intended.

## Historical record

The original audit on 2026-09-05 used revision
`d3a40ca98d71208426c8501d8d4a1aaaa049768d`. Detailed slice records and earlier
validation counts remain in the
[full document at Step 6 completion](https://github.com/lixuanguang/alpha-research-lab-private/blob/4492bfc764e9c8eb5acd41dbcf63c3dadb44979c/docs/roadmap/python-coding-standards-migration.md).
