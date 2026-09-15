# MR 07: Make acquisition usable and observable

Owner: repository founder. Status: implemented and locally verified on 2026-09-15
on `codex/mr-07-acquisition-cli`. This record covers synthetic installed-command
acceptance. The permitted bounded download remains unproven under MR 05's
unresolved rights admission and retention; no M1 or P1 completion is claimed.

## Problem / change

Acquisition previously required Python composition and lacked a whole-job terminal
report. The installed `alpha-acquire` command now resolves the selected configuration
and catalog, reads an optional credential from an explicitly named environment
variable, and resumes through the existing `acquire` operation and manifest.
Flushed JSON exposes job/partition identity, retries, response bytes, acknowledged
completions/bytes, last acknowledged ingestion and terminal status. Its startup
record includes normalized non-secret command inputs and their SHA-256; the
existing manifest retains resolved job/catalog/code identity.

The [component guide](../../src/alpha_research/data/README.md#installed-acquisition-command)
owns flags, telemetry meanings, exit codes, storage prerequisites and recovery.
`stored` does not acknowledge a completion; totals advance after checkpoint save.
Resume verifies the entire prefix before claiming totals or fetching. Repetition
preserves the manifest, logical completions and original completed clocks.
Keyboard interruption returns 130; exhausted transient retries return 4. An abrupt
process exit retains the last flushed progress and durable state, without inventing
a terminal record. Damaged completed objects fail instead of being replaced.

## Affected scope

Fetched `origin`; clean `main` equaled `origin/main` at `0e35496`, MR 06's merge
in PR #27. Its history includes MR 05/PR #26 (`48bf9b7`), MR 04/PR #25 (`b136b36`),
MR 03/PR #24 (`bf3fb99`) and M0/PR #23 (`80b5bc6`). MR 07's 05–06 prerequisites
were merged before branch creation. The roadmap's stale MR 06 review status is
updated; its ownership, dependencies and acceptance are unchanged.

The command, argument boundary and invocation-scoped output adapter live in
[`pipelines/acquisition.py`](../../src/alpha_research/pipelines/acquisition.py).
`Configuration`, `CatalogSnapshot`, `DomainCodec`, `TardisTransport`, `RawStore`
and `AcquisitionManifest` retain their responsibilities. Existing library reports
are extended additively with verified-resume and checkpoint totals. The output
adapter owns console formatting and per-invocation correlation; it does not own
workflow advancement. No second acquisition wrapper, manifest schema, frame reader
or later-MR dataset behavior was introduced.

Against `0e35496`: **156 added production code-bearing lines, 2 deleted, total
158**, all in the acquisition pipeline. Counts include imports, annotations,
signatures and executable statements; exclude comments, docstrings, blank lines,
tests/fixtures and the worked notebook artifact. **Declarative configuration:**
one added console-script entry in `pyproject.toml`. No dependencies, lockfile,
maintained executable tooling or ignore rules changed. The cohesive overage keeps
setup validation, safe command identity, acknowledged progress and terminal handling
with the first installed consumer. Splitting would deliver a command without its
required failure/observation contract; validation and invariants were retained.

`docs/research/p1-baseline.md` is unchanged, SHA-256
`a00d4a2e6bc4e5b31576abc3cbcc8d794b4da7b522f3d439fe0424374199b17a`.
`uv.lock` is unchanged, SHA-256
`1159199bc83be7a75b0ccd2df3a401f3239eda11e37892f5e32d3a88ecf5fc6d`.

## Validation result

CPython 3.14.7, macOS arm64. The focused suite passes **74 tests**, with no skips
or deselections. It includes 17 new command cases and the retained transport,
resume and manifest tests. New subprocess cases execute installed entry points
with copied inputs outside the checkout; they are included in the default focused
selection. No storage algorithm or integration-marked test was changed; MR 06's
raw-store interruption evidence remains applicable. No full local suite was run;
the complete hosted lane remains required before merge.

Ruff lint/format, configured strict mypy for all three affected Python files,
the complete engineering-source checker and focused Bandit pass. The architecture
checker covers `docs/`; component/example guide links are checked explicitly.
Commands run from the checkout unless a `cd` is shown:

```sh
uv run --frozen --no-editable pytest -q \
  tests/unit/pipelines/test_acquisition_command.py \
  tests/unit/pipelines/test_acquisition_resume.py \
  tests/unit/pipelines/test_acquisition.py tests/unit/data/test_manifests.py
uv run --frozen --no-sync ruff check src/alpha_research/pipelines/acquisition.py \
  tests/unit/pipelines/test_acquisition_command.py tests/fixtures/mr06/acquire.py
uv run --frozen --no-sync ruff format --check src/alpha_research/pipelines/acquisition.py \
  tests/unit/pipelines/test_acquisition_command.py tests/fixtures/mr06/acquire.py
uv run --frozen --no-sync mypy --strict src/alpha_research/pipelines/acquisition.py \
  tests/unit/pipelines/test_acquisition_command.py tests/fixtures/mr06/acquire.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/pipelines/acquisition.py
uv run --frozen --no-sync alpha-governance-architecture
uv run --frozen --no-sync python /private/tmp/mr07-verification/check_links.py
python3 /private/tmp/mr07-verification/count_lines.py
git diff --check 0e35496
```

The [command tests](../../tests/unit/pipelines/test_acquisition_command.py) also
reject unknown jobs, invalid timeouts/byte bounds/retry delays, unresolved admission,
a missing credential variable and an output/input alias. They prove a failed
checkpoint retains previous acknowledged totals and that a supplied credential
appears only in the HTTP header, not command reports or saved state. Missing,
mutated, truncated and foreign-run inputs fail at resume. The shared
[process fixture](../../tests/fixtures/mr06/acquire.py) adds command execution and
HTTP/keyboard fault modes to MR 06's real filesystem interruption boundaries.

Initial static failures were inferred untyped lists in argparse/mock inputs,
union ordering, and a missing test-fixture argument docstring. These were fixed
without suppressions. Sandbox cache/Git-reference writes required authorized
execution. No provider endpoint was accessed.

### Installed wheel and notebook

Built the wheel once after the final runtime and packaged guide changes. Existing
`_InstalledWheelCheck.validate` created a fresh environment outside the checkout,
installed hash-locked runtime dependencies and the non-editable wheel, and passed
public imports/round trips, governance absence and `uv pip check`. Copied inputs
and the synthetic process fixture then executed the actual installed console script;
complete repeats and corrupt-object checks ran it without HTTP injection.

```sh
uv run --frozen --no-sync uv build --no-build-isolation --wheel --no-sources . \
  --out-dir /private/tmp/mr07-verification/wheels
uv run --frozen --no-sync python /private/tmp/mr07-verification/verify_installed.py
cd /private/tmp/mr07-verification/final-consumer
venv/bin/python -I consumer_check.py > installed-results.json
cd /private/tmp/mr07-verification/metadata-consumer
../final-consumer/venv/bin/python -I ../final-consumer/consumer_check.py > installed-results.json
```

The last run renews the same four scenarios using the final fixture's metadata-based
entry-point discovery. The relative `../` interpreter path emitted startup
`sys.prefix`/`sys.exec_prefix` normalization warnings; all scenario assertions and
exit/status checks passed. Both runs are local temporary evidence, not a release archive.

| Scenario | First exit | State after resume | Repeat | Damaged-byte exits |
| --- | --- | --- | --- | --- |
| Exit after second raw publication | 75 | 3 unique completions / 132 acknowledged bytes | Same manifest, no fetch | Mutation 3; missing 4 |
| Keyboard interruption on second fetch | 130 | 3 / 132 | Same manifest, no fetch | Mutation 3; missing 4 |
| Exhausted transient retries | 4 | 3 / 132 | Same manifest, no fetch | Mutation 3; missing 4 |
| One transient retry then success | 0 | 3 / 132 | Same manifest, no fetch | Mutation 3; missing 4 |

Wheel SHA-256:
`e4c656978bee40e949295839776f710f6294e128898d7f5d7e6b6404580db6f2`.
Resolved synthetic run identity:
`107e2653d2d6d406a27aa53d5b056d9ed4283bf9a5e32634e05f599a195b7c48`.
Implementation identity:
`ac632014037e8bfba0fcbc4ede57eb68b0a415dd9c9f6db73e0f16c8c3a5fd52`.
Command hashes vary with absolute destinations and remain identical on repeats.
Final source retains these runtime bytes; docs and notebook outputs do not change
the implementation identity.

[Notebook section 15](../../examples/research-foundations.ipynb) completes synthetic
NB 07 with command/config identity, intermediate progress/retry tables, three
interruption boundaries, repeat parity and mutation/missing-byte failure examples.
All **19 code cells** pass in order in a fresh kernel, after exact installed/source
runtime comparison and installed entry-point verification. Notebook tooling remains
separately pinned; no runtime Jupyter dependency or lock change was introduced.

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' \
  --with 'nbformat==5.10.4' python examples/run_notebook.py
```

Final completed attempt: `4ad26182-6074-4460-aa1d-0ab6943bfdef`; notebook source SHA-256:
`29253ec0a0e4952219141819aa91032ad9082b7ff0ad87aa63022d39335076f4`. The earlier completed attempt
`b6d9242d-14ee-48b3-bdae-efddba8087d0` preceded the notebook helper's parameter
documentation; the final run covers the maintained notebook source.
Two earlier failed attempts remain under ignored `examples/runs/`: `95bb90b5-e832-44ea-9793-6fddfd77307b`
used integer entry-point indexing; `b47443a1-437c-4483-ae29-888913d65e60` assumed
that uv's separate tooling interpreter and the installed command share a directory.
Both reached the new cell after the existing 17 passed. Entry-point metadata now
locates the installed script, including under the standard separate-tooling command.
The final kernel closed normally. Maintained `.ipynb`, `.py` and `.md` examples
remain tracked; generated attempts/kernel/checkpoint artifacts remain ignored.

## Risks / reversal

One caller owns the manifest and protects the provisioned storage. The existing
bounded-job memory, whole-prefix validation/rewrite and local filesystem sync
requirements remain. Process-failure tests do not prove physical power-loss
behavior. A hard kill or failed report sink cannot guarantee a terminal report.
Telemetry is not an atomic attempt journal; retain stdout/stderr with the saved
config/manifest. Last persistence means acknowledged raw ingestion, not checkpoint
mtime, network throughput or proof of dataset quality.

The permitted bounded source download is still blocked by rights admission and
protected retention. Historical eligibility/revision availability are unproven.
No acquisition rights were purchased or inferred from a synthetic reference.
QuantLib's existing release restriction and the hosted merge gate remain unchanged.
No semantic frame reader, canonical publication, research or trading behavior was added.

Revert this isolated branch before dependent consumers merge, retaining raw bytes,
manifest/config files and prior attempts. Existing code-bound manifests reject a
changed implementation identity; no automatic migration or deletion is introduced.
**Next: MR 08 — Read saved raw frames with explicit gaps.** MR 08 was not started.
