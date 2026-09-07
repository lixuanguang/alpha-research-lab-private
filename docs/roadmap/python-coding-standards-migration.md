# Python coding standards migration

Status: **steps 1–6 complete as of 2026-09-07; step 7 remains planned.**
The source-standard debt inventory is empty. The separate inferred-typing
inventory retains **172 diagnostics across 109 identities**.

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
| Source debt | Final 324 obligations retired across 36 files; the [inventory](../architecture/python-standards-debt.json) is empty and its checksum matches. |
| Function dispositions | 308 new reviewed entries: 212 low-level helpers, 34 framework callbacks and 62 compatibility adapters. All 173 prior entries remain unchanged in the [exception register](../architecture/python-standards-exceptions.toml). Entries retain owners, rationales, expiry dates and source fingerprints. |
| Affected pytest cases | 527 default, 5 performance and 1 integration case passed. All 531 existing cases remain; two regressions cover loader reuse after failure and resolved-root artifact admission. |
| Owning Bazel targets | All 10 selected targets passed under `--config=ci`, including the three domain-evidence consumers. |
| Static checks | Configured Ruff lint, Google-docstring/`ANN401`, formatting and strict mypy passed for 60 affected/associated files. Source reconciliation and exception fingerprints passed. |
| Inferred typing | 57 diagnostics retired without new, moved or multiplied debt. The [typing inventory](../architecture/python-typing-debt.json) retains 172 diagnostics across 109 identities. |

Validation used the pinned environment and real Cosign 3.1.3. The ownership
integration test passed after access to the existing uv cache was permitted.
The final slice used affected tests and scoped typing checks; it did not run a
full-repository suite, full CI lane or full-scope stronger typing probe.
Remaining inferred typing is unfinished work, even though source debt is zero.

## Step 7: adoption and final enforcement — planned

1. Migrate callers to the owning services and remove unnecessary temporary
   wrappers. Preserve supported facade imports, exports and CLI contracts;
   document any intentional public compatibility boundary. Reassess retained
   function dispositions before their recorded expiry dates.
2. Resolve the remaining inferred-typing obligations at their library, parsing,
   callback and framework boundaries. Preserve exact diagnostic identities until
   resolved; do not rebaseline moved errors, exclude tests, add blanket ignores
   or use casts that claim invalid data is valid.
3. Activate Ruff `D` and `ANN401` with the Google convention and the final mypy
   checks across the agreed complete scope. Remove the empty source-debt
   mechanism while retaining justified, governed exceptions. Keep the guide,
   root commands, pre-commit, Bazel and hosted CI aligned.
4. Verify the final completion criteria: consistent import groups, no explicit
   `Any`, complete typing checks, useful documentation and reviewed workflow
   ownership. Confirm compatible imports, CLI behavior, serialization, numerical
   results and test collection, then pass the authoritative `make ci-full` lane
   in the pinned environment before declaring the entire migration complete.

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
existing lint/typing controls and debt records; revert only the newly introduced
failing configuration where necessary. No persisted-data migration is intended.

## Historical record

The original audit on 2026-09-05 used revision
`d3a40ca98d71208426c8501d8d4a1aaaa049768d`. Detailed slice records and earlier
validation counts remain in the
[full document at Step 6 completion](https://github.com/lixuanguang/alpha-research-lab-private/blob/4492bfc764e9c8eb5acd41dbcf63c3dadb44979c/docs/roadmap/python-coding-standards-migration.md).
