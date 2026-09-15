# MR 07: Make acquisition usable and observable

Owner: repository founder. Status: implemented and locally verified on 2026-09-15
on `codex/mr-07-acquisition-cli`. The original delivery below covers synthetic
installed-command acceptance at `dbd94b9`. The separately reviewable
[Binance source follow-up](#binance-source-follow-up) adds the founder-authorized
actual download. No M1 or P1 completion is claimed.

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

At the original `dbd94b9` delivery, `docs/research/p1-baseline.md` was unchanged, SHA-256
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


## Binance source follow-up

### Problem and affected scope

The original notebook did not expose an actual-source workflow. The founder
asked for practical downloading, then explicitly selected **Binance public daily
trade archives**, authorized revision of the affected frozen source contract,
and chose ignored `data/binance-archives/` storage on 2026-09-15. This follow-up
supersedes Tardis access as P1's prerequisite while preserving BTCUSDT, the selected
hour, strategy, units, cash, costs and economic timing rules. Earlier Tardis test
records remain historical evidence of that implementation, not Binance acceptance.

The [revised contract](../research/p1-baseline.md) and roadmap now distinguish a
full-day source ZIP from the selected exchange-event hour, absent recorder and
knowledge timestamps, missing gap evidence and potentially revised archives.
No historical availability, eligibility or causal result is inferred. The original
Tardis fixture catalog and decoders remain unchanged. A separately authored archive
catalog retains the same canonical IDs and economic assumptions with a new source
binding; provider/catalog mismatches fail before HTTP.

`BinanceArchiveTransport` owns credential-free public HTTPS, bounded checksum and
ZIP reads, filename-bound publisher SHA-256, expected single CSV member, deflate,
CRC and expansion validation. The pipeline selects it from the resolved job and
reuses the existing raw store, receipts, checkpoints, retries and console reporting.
Shared transient-error classification moved to its provider-neutral module; the
old Tardis import remains the same class. No dependencies, raw-manifest/event schema
or storage algorithms changed. Notebook-only CSV inspection is feasibility evidence;
MR 08's reusable reader and MR 09's canonical decoding are not implemented.

Against `dbd94b9`, the follow-up changes **160 added + 26 deleted = 186 production
code-bearing lines**: transport 98, configuration 39, requests 12, pipeline 28,
reference source selection 4, and shared/Tardis exception binding 5. The 36-line
overage keeps the new adapter with its first working consumer, explicit source/day
bindings and mandatory checksum/ZIP/resource validation. Splitting those would
leave an unusable adapter or weaken source identity/integrity. New JSON jobs/catalog
are declarative; tests and the worked notebook are excluded under the roadmap's
counting rule. Combined against updated-main base `0e35496`, the MR 07 command
and source amendment total **314 added + 26 deleted = 340** production code-bearing
lines; the original command remains a separate `dbd94b9` commit for review.

### Observed real acquisition

- Public archive: `BTCUSDT-trades-2024-06-01.zip`, **7,308,819 bytes**.
- Publisher-verified exact ZIP SHA-256:
  `c9c333f58fe33faaa0a34d526c61b13f5648b908c4ad341dd6556e15c5bcc46a`.
- Full-day CSV: **638,484 rows**; frozen hour: **27,480 rows**.
- First/last selected event: `2024-06-01T00:00:00.001Z` /
  `2024-06-01T00:59:59.997Z`; integer timestamps verified as milliseconds.
- Original local receipt: `2026-09-15T09:46:04.103212Z`; durable ingestion:
  `2026-09-15T09:46:04.125052Z`. These are acquisition clocks, not 2024 knowledge.
- Implementation identity:
  `bb9784e3bead20cdd4fa0723ef033931aa633d3585e2d219ba0bb7441fc2e27f`.
- Resolved run identity:
  `acb948277201cc169d32c2bb874fb40ce9e9c33c893e56a992faa47853147f80`.

Local retrievable bytes are `data/binance-archives/raw/<zip-sha256>`; run inputs,
manifest, use/retention record and attempt logs are under
`data/binance-archives/runs/<run-identity>/`. The founder-selected working copy has
no automatic expiry; long-term archival/redistribution rights are not established.
No API key, raw ZIP or bulk CSV is tracked. Only this generated data directory was
added to `.gitignore`; maintained example `.ipynb`, `.py`, `.md` remain tracked.
The public archive documentation and the founder's use selection are recorded;
the GitHub code license is not represented as a raw-data license.

### Validation and limitations

Focused tests: **115 passed**, no skips or deselections. They cover new daily
request/source serialization, narrower-selection identities, mixed sources,
checksum/member/CRC/expansion/HTTP failure, admission/credential rejection, shared
receipt recovery, repeats and damaged-byte refusal, alongside existing configuration,
reference, Tardis acquisition and CLI regressions. Ruff lint/format, configured
strict mypy, full engineering-source checks and focused Bandit pass. Local links
are checked in `docs/` and explicitly in the component/examples guides. Full hosted
CI remains required before merge; this is a development candidate, not release
or trading authorization.

Commands (checkout unless another directory is specified):

```sh
uv run --frozen --no-editable pytest -q \
  tests/unit/pipelines/test_binance_archive.py \
  tests/unit/pipelines/test_acquisition.py \
  tests/unit/pipelines/test_acquisition_command.py \
  tests/unit/pipelines/test_acquisition_resume.py \
  tests/unit/data/test_requests.py tests/unit/test_configuration.py \
  tests/unit/test_reference_data.py
uv run --frozen --no-sync ruff check src/alpha_research/configuration.py \
  src/alpha_research/reference_data.py src/alpha_research/data/requests.py \
  src/alpha_research/data/providers src/alpha_research/pipelines/acquisition.py \
  tests/unit/pipelines/test_binance_archive.py
uv run --frozen --no-sync ruff format --check src/alpha_research/configuration.py \
  src/alpha_research/reference_data.py src/alpha_research/data/requests.py \
  src/alpha_research/data/providers src/alpha_research/pipelines/acquisition.py \
  tests/unit/pipelines/test_binance_archive.py
uv run --frozen --no-sync mypy --strict src/alpha_research/configuration.py \
  src/alpha_research/reference_data.py src/alpha_research/data/requests.py \
  src/alpha_research/data/providers src/alpha_research/pipelines/acquisition.py \
  tests/unit/pipelines/test_binance_archive.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -r src/alpha_research/configuration.py \
  src/alpha_research/reference_data.py src/alpha_research/data/requests.py \
  src/alpha_research/pipelines/acquisition.py src/alpha_research/data/providers
uv run --frozen --no-sync alpha-governance-architecture
uv run --frozen --no-sync python /private/tmp/mr07-verification/check_links.py
```

Fresh-kernel notebook command:

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' \
  --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py
```

First actual-source success `5661d1ca-aa84-43b7-89a4-c36662fd346d` ran 23 code
cells and downloaded the ZIP. The follow-up with explicit real-byte/checksum
rejections, `6c249ef2-5c4d-4fce-b1a0-8600c93277c5`, ran **24 code cells**, reused
the completed object and preserved its manifest/clocks. Outputs show actual
counts, timestamp bounds, three decimal-text trade previews and required failures.
These generated attempts remain locally retrievable under `examples/runs/`.
Failed attempt `e744a5a7-7b41-44fb-9062-2735abc9c1b0` encountered an installed-file
race caused by concurrent uv synchronization; rerunning after stopping environment
mutations passed. Do not synchronize `.venv` while its kernels/children are running.

The hash-locked runtime-only wheel environment was built with existing
`_InstalledWheelCheck.validate` under `/private/tmp/mr07-binance-verification/consumer`.
It passes public imports and `uv pip check`, with governance absent. Its Python
ran `consumer_check.py` with `-I` from the outside-checkout `consumer-repeat/`
directory, using copied configuration and actual HTTPS. A process exited **75**
after real raw publication but before completion; the installed console command
then resumed and repeated with **one completion, no fetch stages and unchanged
original receipt**. Mutated/missing test copies returned **3/4** without changing
the manifest. Results/logs are retained there. The first fixture attempt stopped
at its deliberate mutation because published files are read-only; making only the
test copy writable allowed the complete verification to pass. The user's original
archive was never modified.

Only the selected day/hour is empirically checked. Daily archives can change;
repeats intentionally use retained bytes without requesting today's checksum.
Downloads buffer compressed bytes within the explicit bound; this is not a
large-universe streaming collector. ZIP integrity is not CSV/canonical quality,
complete market coverage, eligibility or revision-availability evidence. The
source-capture Tardis entitlement question is superseded for this case, not resolved
for other Tardis uses. **Next: MR 08**, saved archive reading with explicit missing
and unknown-coverage outcomes. No later MR was started.


Final artifact command (no concurrent environment synchronization):

```sh
uv run --frozen --no-sync uv build --no-build-isolation --wheel --no-sources . \
  --out-dir /private/tmp/mr07-binance-verification/wheels
uv run --frozen --no-sync uv pip install --python .venv/bin/python --no-deps --reinstall \
  /private/tmp/mr07-binance-verification/wheels/alpha_research_lab-0.1.0-py3-none-any.whl
```

Final wheel SHA-256:
`89a8cd420a6d43482237d6f4ccda32c31b693ab2c3fdbdcf6bb9c4786a33ef1f`.
All **41** packaged files equal the checkout and isolated installed consumer.
The final wheel includes the updated packaged guide; executable/JSON implementation
bytes match the already tested first wheel. Reinstallation into both consumers
and a further outside-checkout console repeat pass with no fetch, unchanged
manifest and one completion (`consumer-repeat/final-wheel-results.json`). The
final notebook run uses the command above with `--no-sync` plus the same pinned
notebook tools, preserving the explicitly installed final wheel. P1's amended
specification SHA-256 is
`7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`;
`uv.lock` remains unchanged at the original digest recorded above.

Final fresh-kernel attempt: `abc10b50-4ba5-4c67-82c8-fba30d9808b4`, all **24** code cells passed.
Notebook source SHA-256: `ea43aa4668d789ba942a6adf5e41109835873e9473d5f0c86768686047f0db2e`.
The final output verifies reuse of the real archive, displays the selected-hour
preview and rejects changed bytes and a mismatched publisher checksum.


## Notebook flow review and connection

Scope: founder-requested review and connection of the actual historical-data
parts after `5b23cdc`, on the same MR 07 branch. Review profile: market data,
risk tier 2, offline research; the affected contracts are source identity,
actual-versus-synthetic evidence, storage recovery, clocks and exact units.
No live streaming or trading boundary is activated.

### Findings addressed

- **P2, reliability/usability:** the former real-data section followed 19 synthetic
  code cells and relied on setup from those demonstrations. In particular,
  `mr07-binance-failures` used `HTTPSConnection`, `TemporaryDirectory` and `patch`
  imported in earlier synthetic sections. Running the actual workflow by itself
  could fail with missing names. The main notebook now declares its own imports
  and carries one resolved run/checkpoint through all eight explained sections.
- **P2, first-use reliability:** `_NotebookArchiveFiles.directory` required an
  existing parent. A fresh checkout or new nested destination could fail before
  acquisition. The notebook helper now creates missing private ancestors and
  synchronizes each directory entry; a fresh nested path and repeat both pass.
- **Usability improvement:** disabling downloads previously skipped all actual
  inspection, even with a complete saved archive. `ALPHA_BINANCE_DOWNLOAD=0` now
  verifies and reads cached real data; absent/incomplete cache fails with an
  explicit recovery instruction and creates no data directory.

The [main notebook](../../examples/research-foundations.ipynb) now has **10 code
cells**: installed environment, actual config/catalog selection, acquisition or
cached read, descriptor/clocks, the selected real hour, exact C03 financial values,
repeat/rejections and summary. Every stage explains its inputs, work and output.
It inspects 27,480 selected trades from the same saved ZIP and applies
`Price.amount(Quantity)` and `DomainCodec` to three actual preview rows. Their
exact quote amounts match the source quote-quantity fields: `66.86460990`,
`47.95340710`, `79.69721180` USDT. This is a preview comparison, not a full
canonical-data validation, simulated fill or strategy result.

The [companion notebook](../../examples/foundation-contract-checks.ipynb) preserves
all 44 original foundation/checkpoint cells, including **19 code cells**, fixed
hand-ledger assertions and existing synthetic process fixtures. Only its own
path and navigation references changed. A real successful source cannot exercise
capture rounding, disconnects, process death or bad authentication on demand;
those tests remain explicit synthetic demonstrations. The main path retains two
controlled failures on copies/injected checksums of the actual archive.

No production Python, configuration, baseline, lockfile, dependency or ignore rule
changes are needed: **0 production code-bearing changed lines** for this review
follow-up. MR 08 remains unstarted; archive inspection stays notebook-local.
Updated guide/roadmap links locate the moved numbered checkpoints. Prior attempt
records above describe the original notebook layout and are not rewritten.

### Verification

Commands used the existing installed candidate with `--no-sync` to avoid changing
an environment while its kernels/child processes were running:

```sh
uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' \
  --with 'nbformat==5.10.4' python examples/run_notebook.py
uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' \
  --with 'nbformat==5.10.4' python examples/run_notebook.py examples/foundation-contract-checks.ipynb
ALPHA_BINANCE_DOWNLOAD=0 uv run --frozen --no-sync --with 'nbclient==0.10.4' \
  --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py
uv run --frozen --no-sync ruff check examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check examples/research-foundations.ipynb
uv run --frozen --no-sync alpha-governance-architecture
uv run --frozen --no-sync python /private/tmp/mr07-verification/check_links.py
```

The connected real-data run and the independent companion both pass from fresh
kernels against the installed runtime. Real cache-only run
`778a2048-91df-4270-bccd-65085c1ce94c` passed all 10 cells. Adding
`ALPHA_BINANCE_DIRECTORY=/private/tmp/mr07-notebook-flow/absent-cache` deliberately
failed at acquisition with `FileNotFoundError`, attempt
`7fb7a868-8ab2-4321-8290-c18a595e8371`; no source request or data directory was
created. The existing runtime's focused test and installed-consumer evidence above
is reused because runtime behavior is unchanged; this follow-up did not rerun
all package tests or assert new publisher/coverage evidence. The main notebook's
lint/format checks pass; the unchanged synthetic code retains its prior style.

The review skill's default implementation delegation used one
`gpt-5.6-luna` agent at `max` for the companion and its README. The main agent
implemented the connected notebook, inspected the actual companion diff and
performed the integrated fresh-kernel and link verification. No additional
code findings remain in this bounded notebook review. Historical eligibility,
knowledge/revision availability, full market coverage and canonical publication
remain the explicit future-work limits; no value or source timestamp is invented.

Final current-source notebook evidence:

| Notebook | Code cells passed | Attempt | Source SHA-256 |
| --- | --- | --- | --- |
| `research-foundations.ipynb` | 10 | `fc36c320-8a26-4c66-b408-d4a441365726` | `8544111c8caadf5460732031dcaf3f1549be1b048bf0d1dc06c24d632cebf45c` |
| `foundation-contract-checks.ipynb` | 19 | `aa3cd64a-f768-4be5-adf2-973afcb9c5e9` | `45439a9d2364eb78e591b7478377b5c518b2ea26fdad3c7ee3b5b631d0f033e2` |

The final companion navigation edit was recovered from its verified executed
snapshot after a malformed metadata edit, then parsed and fully rerun. Final
source hashes match execution metadata and all expected cells are executed;
no uncaught errors remain. The actual archive digest and P1 baseline hash remain
unchanged. No new archive download was needed for this review.

## Pull request CI follow-up

[PR 28](https://github.com/lixuanguang/alpha-research-lab-private/pull/28)'s first
[source-validation run](https://github.com/lixuanguang/alpha-research-lab-private/actions/runs/34975156630/job/104400912671)
at `38f98ad` completed with 627 passed, one failed and three deselected. The
package-definition test still expected only `alpha-inspect-fixture`, omitting
MR 07's `alpha-acquire` from both the declared and installed command sets. The
dependent merged-result gate failed and macOS smoke was skipped.

The follow-up retains exact command-set assertions and adds the implemented
acquisition command to both expectations. Runtime, project metadata, dependency
lock and notebooks are unchanged. Focused validation passes:

```sh
uv run --frozen --no-editable pytest -q tests/engineering/test_package_definition.py
uv run --frozen --no-sync ruff check tests/engineering/test_package_definition.py
uv run --frozen --no-sync ruff format --check tests/engineering/test_package_definition.py
uv run --frozen --no-sync mypy --strict tests/engineering/test_package_definition.py
```

All four package tests pass; lint, format and strict typing pass. Existing
runtime and current-source notebook evidence above remains applicable. The
hosted lane must rerun on the corrected commit before merge; this local check
does not replace that gate or rewrite the failed attempt.
