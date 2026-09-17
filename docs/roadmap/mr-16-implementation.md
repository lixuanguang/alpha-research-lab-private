# MR 16 — Publish and inspect a validated dataset

Owner: repository founder. Historical validation: implemented and locally verified for review on
2026-09-17. Branch: `codex/mr-16-dataset-command`. Base: freshly fetched `main`
at `69a45eb`, merging MR 15 in PR #39. Prerequisites MRs 07–15 are ancestors of
that base (`ddd1bfb`, `f05ef18`, `a66b49a`, `d88ba11`, `5b10f78`, `210db65`,
`7ef4892`, `746e002`, `127efa9`). Runtime/fixture commit: `f3cdf01`.
Merged in PR #40 at `95e1a14` after all three hosted checks passed. The
commands and artifact identities below describe the pre-merge candidate.

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
