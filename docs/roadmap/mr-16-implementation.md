# MR 16 — Publish and inspect a validated dataset

Owner: repository founder. Historical validation: implemented and locally verified for review on
2026-09-17. Branch: `codex/mr-16-dataset-command`. Base: freshly fetched `main`
at `69a45eb`, merging MR 15 in PR #39. Prerequisites MRs 07–15 are ancestors of
that base (`ddd1bfb`, `f05ef18`, `a66b49a`, `d88ba11`, `5b10f78`, `210db65`,
`7ef4892`, `746e002`, `127efa9`). Runtime/fixture commit: `f3cdf01`.
Merged in PR #40 at `95e1a14` after all three hosted checks passed. The
commands and artifact identities below describe the pre-merge candidate.
The [MR 16 follow-up](#mr-16-follow-up-acquisition-handoff) records the later
multi-instrument acquisition handoff and its current acceptance evidence.

## Problem / change

Saved acquisitions could previously be published only through Python calls.
`alpha-dataset publish` now reads strict bounded acquisition, quality, eligibility
and optional correction files, normalizes and admits partitions, publishes atomically
and reopens the resulting explicit snapshot ID. `alpha-dataset inspect` verifies
an explicit ID with its retained raw inputs and embedded admission evidence.

Flushed JSON progress exposes reached partition invalid/gap/duplicate counts and
reasons, then separates candidate identity, durable persistence and verified
completion. Rejected inputs never publish a partial accepted prefix. A publication
failure reports its stage and candidate ID when known, plus retry guidance; a
post-rename failure may leave a complete visible snapshot requiring acknowledgement.
Exact repeated saved manifests reuse logical content and snapshot identity.
Nonidentical overlapping instrument/time selections fail instead of adding duplicate
partition economics. Changing the supported instrument needs only configuration.

The [command guide](../../src/alpha_research/data/README.md#publish-and-inspect-from-the-command-line-mr-16)
owns arguments, preparation and recovery, the
[contract](../data/contracts.md#installed-dataset-command-mr-16) owns behavior,
and NB 16/the [researcher guide](../../examples/README.md) explain the outputs.

## Affected scope

The dataset pipeline owns command composition and error handling. Its existing
`assemble_dataset` adds an optional synchronous quality sink before each admission
gate; existing callers retain their behavior. `_DatasetArguments` owns typed CLI
input/bounded file decoding, and `_DatasetOutput` owns attempt-local progress and
compact JSON serialization. Both have immediate consumers. Existing
`DomainCodec`, `AcquisitionManifest`, `QualityPolicy`, `EligibilityAssertions`,
`Correction`, `DatasetManifest` and `SnapshotStore` retain their contracts.

The command accepts complete single-instrument/day acquisitions, with several
compatible manifests selectable together. It does not split a multi-instrument
acquisition, reconcile arbitrary overlapping histories, query events, select as-of
revisions or change the acquisition/source adapter. `alpha-inspect-fixture` remains
compatible. No new canonical schema, dependencies or policy defaults are introduced.

Against base `69a45eb`, production code-bearing changes are **141 additions +
3 deletions = 144 lines**, all in `pipelines/dataset.py`. The count includes imports,
annotations, validation, control flow and serialization; blank/comment/docstring
lines, tests/fixtures and notebook examples are excluded per the roadmap.
Declarative configuration is **one added console-script entry** in `pyproject.toml`;
there are **zero dependency/lock changes and zero executable-tooling changes**.
No review-size overage is needed.

## Validation result

CPython 3.14.7, macOS arm64. Commands below ran from the checkout unless stated
otherwise. The documentation skill's `docs/coding_standards/documentation.md`
reference is absent; the engineering guide's Documentation section was followed.

```sh
uv run --frozen --no-editable pytest -q -m 'not performance' tests/unit/pipelines/test_dataset_command.py tests/unit/pipelines/test_dataset.py tests/unit/data/test_snapshots.py tests/unit/data/test_datasets.py
uv run --frozen --no-sync ruff check src/alpha_research/pipelines/dataset.py tests/unit/pipelines/test_dataset_command.py tests/fixtures/mr16 examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/pipelines/dataset.py tests/unit/pipelines/test_dataset_command.py tests/fixtures/mr16 examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/pipelines/dataset.py tests/unit/pipelines/test_dataset_command.py tests/fixtures/mr16
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/pipelines/dataset.py
```

All passed: **69 focused tests, no skips or deselections**. The changed console-script
entry also required updating the existing package-definition contract; a separate
`uv run --frozen --no-editable pytest -q tests/engineering/test_package_definition.py`
passed **4 tests**, bringing the total to **73 tests**. Ruff format/check and strict
mypy also passed for that file, followed by the complete engineering-standards check. This explicitly includes the
existing process-interruption and installed fixture-inspection integration cases.
MR 16 adds 21 command cases: publication/reopening, ordered progress, duplicate
rows/ranges, a second configured instrument, late partition failure, wrong
schema/instrument/time/units/quantity, altered policy/eligibility, missing input,
invalid limits, gap/causal refusal, explicit correction histories/unknown keys,
handled interruption, pre-rename I/O failure, post-rename parent-sync failure,
nonidentical overlap refusal and damaged raw/canonical inspection or mutable IDs.
Earlier MR 15 process-death tests cover all three publication boundaries.

Initial static checks caught an untyped empty argparse default, an untyped mock
failure list, one missing fixture `Raises:` section and an overlong notebook display
expression. All were corrected before final checks. Sandbox uv cache/Git/kernel
access used the required escalation path; it did not change validation scope.

### Installed wheel outside the checkout

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr16-validation/dist
mkdir -p /private/tmp/mr16-validation/inputs /private/tmp/mr16-validation/delivery-installed
cp configs/data-jobs/binance-archive.json configs/reference/binance-archive-spot.json tests/fixtures/mr12/eligibility.json tests/fixtures/mr16/dataset_command.py tests/fixtures/mr16/interrupt_command.py /private/tmp/mr16-validation/inputs/
uv run --frozen --no-sync python /private/tmp/mr16-validation/install.py
cd /private/tmp/mr16-validation
./delivery-installed/venv/bin/python -I inputs/dataset_command.py inputs
```

The temporary installer invokes existing
`alpha_research_governance.wheel_smoke._InstalledWheelCheck.validate` with the
checkout, `delivery-installed/` and the built wheel. Frozen hash-verified binary-only
runtime dependencies, candidate installation without dependency resolution,
dependency compatibility, public imports/exact codecs and absence of governance
imports all passed. An earlier installer rerun refused its already-existing venv;
the final wheel was installed in a fresh directory, without deleting that attempt.

The [retained consumer](../../tests/fixtures/mr16/dataset_command.py) invokes actual
installed console scripts outside the checkout. For BTC and ETH selected through
configuration, a child exits abruptly with status 75 before rename; inspection
refuses the absent candidate, retry/repeated ranges succeed, and earlier snapshots
remain readable. It also verifies counts, causal-gap refusal, explicit-ID behavior
and two hidden staging remnants. All imports use external `site-packages`.
Published synthetic snapshots:

- BTC: `2303ed8694f4cdf20679ad6259078027e008f8dc55f426068596d8aa2cd2cf7c`.
- ETH: `83dc3a7fbaf54fde08f98d6c8536b5897c76c389b390fb8ff53159158350133b`.

Final wheel SHA-256: `c60a7637f2401375abc6232d635597834f982dad3ea0ef74024ea833cbfae77f`.
The original executed wheel was
`b118d9487d117c76f9444c8ab6d6c050ad07cf9be3fd81a3cf5fc016ea07cd3b`, installed in
`final-installed/`. Rebuilding after the component guide changed produced the final
wheel: ZIP comparison confirms only `alpha_research/data/README.md` differs. All
67 package files match the final source, wheel and new external installation.
The installed synthetic consumer passed against both wheels. Real-sample and
notebook evidence is reused because every executable/runtime input is identical.
Lock SHA-256: `e6cd3a169ff4b6850bcb5b09e38c44e1179b0dc1fb7c6a9bd95d2c4a058595e4`.
The external temporary environments/artifacts are local development evidence,
not a durable release archive.

### Retained permitted Binance sample

The original permitted public archive is reused from the MR 07 source follow-up;
no new network request or source substitution was made. Acquisition/source evidence
is unchanged. Its retained run is
`acb948277201cc169d32c2bb874fb40ce9e9c33c893e56a992faa47853147f80`,
with raw SHA-256 `c9c333f58fe33faaa0a34d526c61b13f5648b908c4ad341dd6556e15c5bcc46a`
and size **7,308,819 bytes**. The saved acquisition and exact raw object were copied
from ignored `data/binance-archives/` into `/private/tmp/mr16-validation/permitted/`.
The copied descriptor retains its original request and acquisition clocks.

The temporary `permitted_sample.py` decodes that saved manifest with `DomainCodec`,
writes `EligibilityAssertions(catalog=acquisition.run.catalog, assertions=())` and
`QualityPolicy(use="exploratory", known_at=acquisition.run.job.start,
max_gap=timedelta(seconds=30))`, then invokes these installed commands from the
external directory (the publish command deliberately repeats the manifest):

```sh
cd /private/tmp/mr16-validation
./final-installed/venv/bin/python -I permitted_sample.py
# Commands executed by that driver from permitted/:
../final-installed/venv/bin/alpha-dataset publish --store /private/tmp/mr16-validation/permitted/raw --snapshots /private/tmp/mr16-validation/permitted/snapshots --max-bytes 268435456 --manifests /private/tmp/mr16-validation/permitted/acquisition.json /private/tmp/mr16-validation/permitted/acquisition.json --policy /private/tmp/mr16-validation/permitted/policy.json --eligibility /private/tmp/mr16-validation/permitted/eligibility.json
../final-installed/venv/bin/alpha-dataset inspect --store /private/tmp/mr16-validation/permitted/raw --snapshots /private/tmp/mr16-validation/permitted/snapshots --max-bytes 268435456 --snapshot-id c0f8f3953dee8a15a79d1e9a597e37220c094b3d3c555c8f06d0ec366d3ed278
```

Publication and its verified reopen exited **0** after **429.74 seconds**. The
scope remains **`exploratory_degraded`**, with **0 invalid inputs, 0 observed gaps
exceeding 30 seconds and 0 economic duplicates**. The duplicate manifest selection
produced one partition, snapshot
`c0f8f3953dee8a15a79d1e9a597e37220c094b3d3c555c8f06d0ec366d3ed278`.

The separate installed `inspect` command also exited **0**, reproduced the same
scope/counts/reasons and required only the snapshot ID and retained stores. The
canonical partition is **88,792,611 bytes**, contains **27,480 trade revisions** and
**0 controls**, and retains the selected hour's exact original inputs. The complete
temporary driver (publish, independent inspect and summary parsing) took **648.68
seconds**. These are observed local wall times, not a latency benchmark; repeated
full verification and in-memory canonical bytes are a material operating limit.

An empty eligibility history is intentional: no synthetic membership was presented
as actual evidence. Reports explicitly retain unknown membership for the selected
2024-06-01 00:00–01:00 UTC hour, unknown original trade availability, unknown
recorder coverage and authored catalog units. A successful exploratory command
therefore does not close M1's external evidence or P1 causal acceptance. JSONL
progress/terminal logs and copied input/snapshot bytes remain local under
`/private/tmp/mr16-validation/permitted/`; original raw acquisition remains under
ignored `data/binance-archives/`. These locations are not a durable release archive.

### Fresh-kernel NB 16

```sh
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.3.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
```

Successful fresh attempt: **`75d308c7-0924-4828-bca7-ea5e2802c036`**, all **62 cells /
26 code cells** passed. The import check matched all **66 runtime source/data files**
to installed `site-packages`; the runtime-input diff against `f3cdf01` was empty.
All 24 earlier code-cell sources remain unchanged and reran. Notebook source SHA-256:
`add383b49993b2e0042ad42a5c4a5ba66e603192ec5ab49927c1650460a96a4b`.
Runtime SHA-256: `a1a722de376672dae09374ba38a4d998e191d749a56b5147f7e39edb1d743497`.
The runner closed its fresh kernel and removed temporary connection files.

The first attempt, `4abe593b-bf56-429b-aa10-69b00ef81efa`, passed earlier sections
but failed in NB 16's console-script lookup: uv's separate tooling interpreter had
no adjacent `alpha-dataset`. The notebook now resolves the installed command through
PATH and uses its sibling runtime Python for the interruption fixture. The failed
snapshot remains ignored and retained; the corrected full run passed.

NB 16 displays stages, scope and `0 / 0 / 1` invalid/gap/duplicate counts, with the
same snapshot after repeated range selection and explicit inspection:
`e604d884246fc9016135cd30f92ed0ec6eec6844946390d604c2846fb8de7ff3`.
Four wrong schema/instrument/time/units examples each report one invalid input;
required causal coverage reports one gap and rejects publication. Actual process
death before rename exposes no partial ID while the earlier snapshot remains
readable. Retry publishes
`508c66b7d05f3e07202bc682bf9de0f9844cd9a919d255ece85eccf017bd73a8`.
These are synthetic teaching results. Saved OKX/Bitfinex inputs are reused without
new acquisition, source acceptance or strategy evaluation.

### Final source and documentation review

```sh
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr16-validation/review.py
uv run --frozen --no-sync alpha-governance-architecture
uv run --frozen --no-sync python /private/tmp/mr16-validation/count.py
git diff --check
git ls-files -- examples/
git check-ignore examples/runs/research-foundations/75d308c7-0924-4828-bca7-ea5e2802c036.ipynb examples/.kernel-probe/connection.json examples/.ipynb_checkpoints/checkpoint.ipynb
```

The temporary review validates notebook schema, sequential complete execution,
source identity, unchanged earlier code-cell sources and P1 bytes. All 266 relative
links in changed Markdown/notebook source resolve; Markdown target anchors also
verify. The architecture checker passes 49 documents. Maintained `.ipynb`, `.py`
and `.md` examples remain tracked; generated runs/kernel/checkpoints stay ignored.
Outputs and metadata are small and reviewed, with no credentials or raw archive
exports added. The notebook runner, ignore policy and lock remain unchanged.
Ruff was renewed after execution; no additional behavioral rerun was needed for
prose/packaged-guide changes. Runtime source remains at `f3cdf01`.

## Risks / reversal

Admission remains explicitly exploratory degraded. Historical eligibility,
original trade availability and complete recorder coverage remain unknown; no
M1 external completion, causal P1 acceptance or strategy result is claimed. The
command retains all existing strict financial/time/schema checks. It uses the
bounded in-memory reference implementation, including repeated full verification;
no performance/scalability claim or automatic overlap repair is made.

Both stores must remain available and protected. Local same-filesystem rename and
synchronization semantics are required. Abrupt death can leave hidden staging files;
no orphan collection, physical power-loss qualification, network-store support or
release/deployment authority is introduced. The QuantLib release restriction remains.
Full hosted CI is still the merge gate; the full local suite was not run.

The frozen [P1 specification](../research/p1-baseline.md) is byte-identical to base,
SHA-256 `7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
Revert this MR before dependent consumers merge; retain existing raw objects and
snapshots, which use unchanged formats and remain readable with compatible code.
No data removal or migration is required. Unchanged acquisition/source and snapshot
semantics reuse previous evidence; the new command and full notebook are renewed.

**Next: MR 17 — Read point events as of a cutoff.** It has not been started.

## MR 16 follow-up: acquisition handoff

Owner: repository founder. Implemented and locally verified for review on
2026-09-18 (Asia/Singapore), branch `codex/mr-16-acquisition-handoff`. Base is freshly
fetched `main`/`origin/main` at `ff2b28e01305ce4c90be9fcaf78cbf78f91c5389`.
All required MR 07–15 merge commits in the roadmap's record index, plus original
MR 16 (`95e1a14`), are merged ancestors. This follow-up closes MR 16's configured
acquisition-to-publication handoff; it does not implement MR 23 or later work.
The earlier sections retain their historical candidate identities and results.

### Problem / change

A configured two-instrument acquisition could complete, but passing its saved
manifest directly to `alpha-dataset publish` failed at the single-partition quality
gate. Publication now expands complete daily acquisitions into one immutable view
per instrument, in original request order. The same behavior serves shared evidence,
per-input `DatasetInput` records, the Python callable and the installed command.

`AcquisitionManifest.partitions()` owns complete-checkpoint validation and the pure
projection. It narrows only the resolved instrument tuple; descriptors, source
request identities, original receipt/ingestion clocks, job, catalog and implementation
binding are retained. The original manifest is never rewritten and remains the
acquisition resume checkpoint. A single-partition input is returned unchanged.
The dataset pipeline owns iteration, correction routing, quality reporting and
atomic publication using existing readers and gates. Partition quality reports and
saved partition manifests use the narrowed run identity.

Corrections remain keyed to the original input run. For multi-instrument input,
economic payload identities select each partition's evidence; unknown, unused,
cross-instrument, conflicting and duplicate links remain refusals. Selecting either
endpoint routes a malformed cross-partition link to validation instead of dropping
it. An input decoding failure still reaches the existing quality gate and its
invalid count. No successful prefix is published when any selected partition fails.
Exact repeated input selections remain idempotent; nonidentical overlaps still fail.

### Affected scope

Runtime changes are limited to `data/manifests.py` and `pipelines/dataset.py`.
Against `ff2b28e`, code-bearing changes are **55 additions + 18 deletions = 73 lines**
(19 in the manifest operation; 54 in dataset composition), excluding tests,
fixtures, notebook examples, blank lines, comments and docstrings. No cohesive
size overage, new runtime abstraction, schema, dependency, lock, entry point,
declarative configuration or ignore-policy change is needed.

The retained [integration consumer](../../tests/fixtures/mr16/ingestion_workflow.py)
is invoked by its [integration test](../../tests/unit/pipelines/test_ingestion_workflow.py)
and notebook section 13. It injects only source HTTP; transport checksum/ZIP handling,
installed commands, filesystem persistence, normalization, quality, snapshot and EDA
are real. The existing abrupt-publication fixture is reused. MR 17–21 APIs are
consumed unchanged; this adds no query, replay, live source or scheduling behavior.

### Validation result

CPython 3.14.7, macOS arm64. **92 focused tests passed, zero skips or deselections**,
including the explicitly selected installed-process integration case and existing
acquisition/snapshot recovery cases. Focused Ruff, strict mypy (eight Python files),
repository engineering standards and focused Bandit checks passed.

```sh
uv run --frozen --no-editable pytest -q -m 'not performance' tests/unit/data/test_manifests.py tests/unit/data/test_datasets.py tests/unit/data/test_snapshots.py tests/unit/pipelines/test_dataset_command.py tests/unit/pipelines/test_ingestion_workflow.py tests/unit/pipelines/test_eda_pipeline.py tests/unit/pipelines/test_acquisition_resume.py
uv run --frozen --no-sync ruff check src/alpha_research/data/manifests.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_manifests.py tests/unit/pipelines/test_dataset_command.py tests/unit/pipelines/test_ingestion_workflow.py tests/fixtures/mr16 examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/manifests.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_manifests.py tests/unit/pipelines/test_dataset_command.py tests/unit/pipelines/test_ingestion_workflow.py tests/fixtures/mr16 examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/data/manifests.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_manifests.py tests/unit/pipelines/test_dataset_command.py tests/unit/pipelines/test_ingestion_workflow.py tests/fixtures/mr16
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/manifests.py src/alpha_research/pipelines/dataset.py
```

The first focused run passed 52 tests. Initial strict typing found three test-only
variadic tuple expressions inferred as `Any` in `msgspec.replace` arguments; typed
intermediate tuples resolved them before final validation. No source or notebook
acceptance failed. Cache, Git, isolated-install and kernel access used the required
sandbox escalation path.

The new cases cover whole-manifest and `--inputs` parity, repeated selections,
request/clock preservation, complete/pending checks, unsupported minute partitions,
overlap refusal, corrupted/missing/malformed later inputs, correction routing and
unused/cross-instrument evidence. Existing cases retain schema/time/unit, causal-gap,
correction history and publication-failure coverage.

#### Isolated candidate and complete workflow

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr16-followup/dist
mkdir -p /private/tmp/mr16-followup/installed /private/tmp/mr16-followup/inputs
cp configs/data-jobs/binance-archive.json configs/reference/binance-archive-spot.json tests/fixtures/mr12/eligibility.json tests/fixtures/mr16/ingestion_workflow.py tests/fixtures/mr16/dataset_command.py tests/fixtures/mr16/interrupt_command.py /private/tmp/mr16-followup/inputs/
uv run --frozen --no-sync python /private/tmp/mr16-followup/install.py
cd /private/tmp/mr16-followup
./installed/venv/bin/python -I inputs/ingestion_workflow.py inputs integration > integration-result.json
./installed/venv/bin/python -I inputs/dataset_command.py inputs > legacy-consumer.log
./installed/venv/bin/python -I verify.py
```

The temporary installer invokes existing `_InstalledWheelCheck.validate` with the
checkout, `installed/` and the candidate wheel. Hash-locked binary runtime dependencies,
isolated public imports/exact codecs, absent governance imports and compatibility
checks passed. A temporary verifier compared all **77 runtime files** across source,
wheel and isolated installation; no file was missing, extra or stale.

The standalone chain acquired BTC, stopped before ETH with exit **130**, refused
publication of that incomplete acquisition with exit **3**, and resumed without
refetching BTC or changing its descriptor. There were exactly **four HTTP requests**
(two checksums and two archives); a repeat acquisition made **zero** additional
requests and preserved checkpoint bytes. Publication was then stopped before rename
with process exit **75**; inspection of the uncommitted ID failed with exit **4**.
Retry published that same candidate ID, and repeated publication/reopening succeeded.

The final snapshot is
`22d5bf59ab3e6650821e88af4562db89aa56c8ce1bed995a16e9dafe27b898a2`:
**two partitions**, **one economic duplicate per partition**, **six history rows**,
**zero cutoff rows**, scope **`exploratory_degraded`**. The original manifest and
raw descriptors remain unchanged. The zero cutoff is required because synthetic
archive download clocks do not supply historical availability. The earlier installed
MR 16 consumer also passed, including its single-instrument command and recovery
cases. All retained source HTTP in the new consumer is synthetic; no network source
request, purchase or new source entitlement was used.

The installed candidate also reopened the existing permitted-source snapshot from
outside the checkout, verifying raw bytes, reproducing normalization/quality and
matching canonical bytes without changing the saved dataset:

```sh
cd /private/tmp/mr16-followup
./installed/venv/bin/alpha-dataset inspect --store '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/silver/mr18-query-workload/raw' --snapshots '/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/silver/mr18-query-workload/snapshots' --max-bytes 268435456 --snapshot-id c0f8f3953dee8a15a79d1e9a597e37220c094b3d3c555c8f06d0ec366d3ed278 > retained-source-inspect.jsonl
```

Exit **0**, one partition, **0 invalid / 0 observed gaps / 0 duplicates**, with
original availability, membership and recorder coverage still unknown. The original
single-instrument permitted acquisition/publication evidence above is reused;
this new verification proves candidate read/admission compatibility, not a fresh
source download or a causal acceptance claim.

| Candidate input | SHA-256 |
| --- | --- |
| Wheel | `2655536e40da0ed75f7a555060af43553c89a257018eef627ea34af13ff567ab` |
| All 77 runtime files: sorted relative path, NUL, bytes, NUL | `9967d04b2bfd43d8b7a8385f2de8f669b28d7bf0b7f85ec3131a34196db63ec8` |
| Unchanged lock | `e6cd3a169ff4b6850bcb5b09e38c44e1179b0dc1fb7c6a9bd95d2c4a058595e4` |
| Preserved P1 | `7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d` |

Temporary `install.py` and `verify.py`, wheel/environment, generated inputs and
JSONL command/EDA reports live under `/private/tmp/mr16-followup/`. They are local
acceptance artifacts, not a durable release archive. Maintained test consumers
reproduce the synthetic workflow. Original source-access evidence is reused; the
follow-up neither changes acquisition/transport nor upgrades source completeness.

#### Fresh-kernel notebook

```sh
uv pip install --python /private/tmp/mr16-followup/installed/venv/bin/python --only-binary=:all: 'ipykernel==7.2.0' 'matplotlib==3.10.8'
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb --kernel-python /private/tmp/mr16-followup/installed/venv/bin/python
```

All **58 cells / 29 code cells passed** on the first fresh-kernel attempt
`40609f65-79d1-4ed3-9ecd-baa09198fb42`, completed at `2026-09-18T08:25:10Z`.
Notebook source SHA-256:
`14e10536bdddf14f0faa1339c7a038b0191140e56ba43c0b9841297854675bf5`.
Section 13 displays the two partitions, six history/zero cutoff rows, duplicate
counts, zero repeat fetches, preserved descriptor and four required failure exits.
The original kernel display-name edit is preserved. All previous checkpoints reran;
existing saved book inputs were read only, and the runner closed the kernel.

Final notebook schema, syntax, sequential execution, source digest and byte equality
with its archived attempt passed. Its plot and compact HTML tables were inspected.
The final verifier checked **358 local links**, including changed component/example
Markdown and notebook cells; the architecture command passed **55 governed documents**.
Maintained examples are tracked, while run snapshots, kernel files and checkpoints
remain ignored. These checks used:

```sh
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr16-followup/final_check.py
uv run --frozen --no-sync alpha-governance-architecture
uv run --frozen --no-sync alpha-governance-ci scan-secrets --all
git diff --check
git ls-files -- examples/
git check-ignore examples/runs/research-foundations/40609f65-79d1-4ed3-9ecd-baa09198fb42.ipynb examples/.kernel-probe/connection.json examples/.ipynb_checkpoints/checkpoint.ipynb
```

MR 18's historical measurements and hashes are unchanged. Section 9 additionally
proves `pipelines/dataset.py` is outside the query import path and compares the
manifest module's syntax tree to its measured version after removing only the new
`partitions` method. All pre-existing query-side operations must still match. This
is explicit reuse of unchanged query evidence, not a new ingestion or scale benchmark.

### Risks / reversal

Jobs still select one UTC day; saved canonical admission remains Binance trades
and exploratory degraded. Complete recorder coverage, original historical availability
and empirical membership are not established. Live-book integration belongs to
MR 25/27. Multi-instrument correction routing adds a bounded decoding pass; no
performance or process-memory-limit claim is made. Nonidentical overlapping input
selections still require explicit reconciliation outside this consumer.

The canonical and snapshot schemas are unchanged. Preserve original checkpoints,
raw stores and published datasets; reverting this code restores the earlier
single-partition input restriction without deleting evidence. P1, runtime dependency
lock, notebook runner and ignore policy are byte-identical to the base. The complete
hosted CI lane remains the merge gate; no full local `make check`, push, merge,
release or deployment is claimed.

**Next roadmap MR: MR 23 — Capture durably before downstream use.** It is not
started by this follow-up.

### Integration with MR 23

Integration review: [PR #50](https://github.com/lixuanguang/alpha-research-lab-private/pull/50).
The original handoff commit is retained as a parent of integration commit `4226bb8`.

On 2026-09-18, the existing handoff commit `bcbc26f` was integrated with freshly
fetched `main` at `4308a5a` (MR 23, PR #49), on `codex/mr-16-handoff-merge`.
Its original prerequisite ancestry remains satisfied. The two runtime files are
byte-identical to the handoff commit: **73 production code-bearing changed lines**
against main, with no additional production changes. MR 23 runtime, configuration,
lock, ignore rules, notebook runner and the frozen P1 specification are unchanged.
The original checkout's uncommitted notebook display-name edit was left untouched.

Only overlapping documentation and notebook edits needed reconciliation. The
combined notebook retains MR 23 section 13 and adds the handoff as section 14.
Section 9 retains both evidence-reuse checks: the live modules are outside the
measured query import path, and all existing manifest operations must match the
historically measured AST after excluding only `partitions`. Original measurements
and their digests remain historical, without a new performance claim.

The following commands ran from `/private/tmp/alpha-mr16-handoff` with CPython
3.14.7 on macOS arm64:

```sh
uv run --frozen --no-editable pytest -q -m 'not performance' tests/unit/data/test_manifests.py tests/unit/data/test_datasets.py tests/unit/data/test_snapshots.py tests/unit/pipelines/test_dataset_command.py tests/unit/pipelines/test_ingestion_workflow.py tests/unit/pipelines/test_eda_pipeline.py tests/unit/pipelines/test_acquisition_resume.py tests/unit/data/live
uv run --frozen --no-sync ruff check src/alpha_research/data/manifests.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_manifests.py tests/unit/pipelines/test_dataset_command.py tests/unit/pipelines/test_ingestion_workflow.py tests/fixtures/mr16 examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/manifests.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_manifests.py tests/unit/pipelines/test_dataset_command.py tests/unit/pipelines/test_ingestion_workflow.py tests/fixtures/mr16 examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/data/manifests.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_manifests.py tests/unit/pipelines/test_dataset_command.py tests/unit/pipelines/test_ingestion_workflow.py tests/fixtures/mr16
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync alpha-governance-architecture
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/manifests.py src/alpha_research/pipelines/dataset.py
uv run --frozen --no-sync alpha-governance-ci scan-secrets --all
uv run --frozen --no-sync uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr16-merge-validation/dist
uv run --frozen --no-sync python /private/tmp/mr16-merge-validation/install.py
uv pip install --python /private/tmp/mr16-merge-validation/installed/venv/bin/python --only-binary=:all: 'ipykernel==7.2.0' 'matplotlib==3.10.8'
ALPHA_OKX_ARCHIVE_DIRECTORY='/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f' ALPHA_BITFINEX_CAPTURE_DIRECTORY='/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private/data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43' uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb --kernel-python /private/tmp/mr16-merge-validation/installed/venv/bin/python
```

All **142 focused tests passed**, without skips or deselections, including the
installed-process handoff and shared live-capture regressions. Ruff, format, strict
mypy (eight Python files), engineering standards, architecture (56 documents),
Bandit and secret scanning passed. The temporary installer calls the existing
`_InstalledWheelCheck.validate`; locked binary runtime installation, dependency
compatibility, isolated public imports/codecs and absent governance imports passed.
All **77 packaged files** matched source, wheel and external installation. The
notebook independently checked the complete **76-file runtime inventory**.

All **64 cells / 32 code cells** passed in fresh attempt
`4aac3e54-ca95-45ce-b04f-b5ea386962cc`, completed at `2026-09-18T10:18:38Z`.
Section 14's external installed consumer again showed two partitions, six history
rows, zero cutoff rows, one duplicate per partition, four injected HTTP requests,
zero repeated fetches and the preserved first descriptor. Required failures were
**130** (interrupted acquisition), **3** (incomplete publication), **75** (abrupt
publication interruption) and **4** (absent candidate inspection). Retry published
and reopened snapshot
`894f5ac3b86fb2aba3a8c8957195a8c3c7017fdd66db2410281d720358efd90e`.
MR 23's committed-prefix, failed-writer and invalid-unit examples also reran.

| Integrated candidate input | SHA-256 |
| --- | --- |
| Wheel | `5744b726368ac04ddf781a415e16f3e30e8a859d9923f74372a4445bfb0b68a7` |
| Runtime inventory | `75006fa6f99bf0813b3a5627f9fdf002e63b07176634cd89934c83f0fc50b33e` |
| Notebook source | `46bba3d287eaeea8d3565aa23801dacb4b66751293434c1b07cdcedadae50199` |

The notebook retains its actual pre-commit base and dirty runtime diff. Validation
artifacts under `/private/tmp/mr16-merge-validation` and generated notebook attempts
are local evidence, not a release archive. Maintained examples remain tracked;
only generated runs, transient kernels and checkpoints are ignored. No new source
request, empirical eligibility, historical availability or scalability claim is
made. The original handoff's permitted-source inspection is reused because its
runtime files are unchanged; the integrated run renews synthetic workflow and saved
book verification. Full hosted CI remains the merge gate; no full local `make check`
was needed. **Next roadmap MR: MR 24 — Recover sessions without hiding gaps.**
It has not been started.

Final notebook schema/syntax, 32 sequential execution counts, source digest and
byte equality with the archived attempt passed, along with **363 local links**,
maintained-example tracking and unchanged P1. Ruff was renewed after execution;
architecture passed again after the evidence update. Commands:

```sh
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr16-merge-validation/final_check.py
uv run --frozen --no-sync ruff check examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check examples/research-foundations.ipynb
uv run --frozen --no-sync alpha-governance-architecture
git diff --check
git check-ignore examples/runs/research-foundations/4aac3e54-ca95-45ce-b04f-b5ea386962cc.ipynb examples/.kernel-probe/connection.json examples/.ipynb_checkpoints/checkpoint.ipynb
```
