# MR 15 — Publish and reopen one snapshot atomically

Historical commands below retain paths from their tested revision. Current source links
and the [test layout](../../tests/README.md) use the reorganized locations.

Owner: repository founder. Historical validation: implemented and locally verified for review on
2026-09-17. Branch: `codex/mr-15-atomic-snapshots`. Base: freshly fetched `main`
at `746e002`, which merges prerequisite MR 14 in PR #38. Runtime and regression
fixture commit: `847c7ce`.

## Problem / change

Previously, manifest and canonical working files had no atomic visibility boundary.
`SnapshotStore.publish` now writes synchronized read-only files in a hidden staging
directory, verifies them through the existing manifest reader, synchronizes that
directory, then publishes it with one same-filesystem directory rename. Parent
synchronization completes durable acknowledgement. `publish_dataset` composes
admission, manifest assembly and publication, returning the snapshot's explicit
SHA-256. `SnapshotStore.read` reopens that ID and verifies every retained input.

An interrupted prepublication build has no readable snapshot ID. An interruption
or synchronization failure after rename may leave a complete visible snapshot;
retry verifies and synchronizes it. Earlier snapshots remain readable after both a
later failed build and successful publication. Existing snapshots are never replaced;
concurrent same-ID publishers verify the winner. Mutable tags such as `latest`,
symlinks, missing inputs and damaged bytes fail visibly.

The [snapshot contract](../data/contracts.md#atomic-local-snapshots-mr-15) and
[component guide](../../src/alpha_research/data/README.md#publish-and-reopen-an-atomic-snapshot-mr-15)
own behavior and usage. NB 15 and the [researcher guide](../../examples/README.md)
explain the outputs and retained limitations.

## Affected scope

`data/snapshots.py` owns publication, retry and explicit-ID reopening. It binds the
snapshot directory and retained `RawStore`; all staging and verification state is
local to an invocation. The dataset pipeline calls it after assembling every
admitted partition. Existing `DatasetManifest`, `DomainCodec`, raw verification,
quality, correction and eligibility contracts are reused. The existing raw publisher
commits one file with a hard link; its primitive cannot itself commit a directory
of canonical files plus manifest. MR 15 therefore uses a directory rename without
changing raw publication or adding another serialization schema.

Each snapshot contains `manifest.json` and canonical digest-named files. Embedded
raw descriptors still reference the original raw store; that store must remain
available and protected. No acquisition, dataset CLI, query service, latest alias,
automatic orphan collection, dependency or configuration change is introduced.
MR 16 owns the installed dataset command.

Against base `746e002`, production code-bearing changes are **94 additions +
0 deletions = 94 lines**: 74 in `snapshots.py` and 20 in the pipeline. The count
includes imports, declarations, validation and executable statements; it excludes
blank/comment/docstring lines, tests/fixtures and notebook examples according to
the roadmap. There are **zero declarative runtime configuration/dependency changes
and zero executable-tooling changes**. No review-size overage is needed.

## Validation result

CPython 3.14.7, macOS arm64. Commands ran from the checkout unless stated otherwise.
The first static pass found a bare pytest fixture decorator that carried `Any` and
missing test-fixture/callback docstring sections. Those test-only issues were fixed;
no runtime behavior changed. Sandbox cache/Git/kernel access used the required
escalation path. The documentation skill's referenced
`docs/coding_standards/documentation.md` is absent; the engineering guide's
Documentation section was followed.

```sh
uv run --frozen --no-editable pytest -q -m 'not performance' tests/unit/data/test_snapshots.py tests/unit/data/test_datasets.py tests/unit/pipelines/test_dataset.py
uv run --frozen --no-sync ruff check src/alpha_research/data/snapshots.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_snapshots.py tests/fixtures/mr15 examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/snapshots.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_snapshots.py tests/fixtures/mr15 examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/data/snapshots.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_snapshots.py tests/fixtures/mr15
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/snapshots.py src/alpha_research/pipelines/dataset.py
```

All passed: **48 tests, no skips or deselections**. The explicit selection includes
three process-interruption integration cases and the existing installed fixture
command case. The snapshot cases exercise two-partition pipeline publication,
read-only bytes, repeated publication preserving file identities, changed-policy
identity with the prior snapshot retained, invalid limits/counts, late damaged
partitions, causal refusal, missing/mutated manifest/canonical/raw bytes, explicit-ID
and nonregular-file rejection, file/staging-directory/parent-directory sync failure,
a real nonempty-directory race and abrupt process death at three boundaries.
The parent inspects the selected IDs before retry: partial-write and pre-rename
exits expose nothing; a post-rename exit exposes a complete verified snapshot.
Earlier snapshots reopen before and after recovery in all three cases.

### Installed wheel outside the checkout

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr15-validation/dist
mkdir -p /private/tmp/mr15-validation/inputs /private/tmp/mr15-validation/installed
cp configs/data-jobs/binance-archive.json configs/reference/binance-archive-spot.json tests/fixtures/mr12/eligibility.json tests/fixtures/mr15/publish_snapshot.py tests/fixtures/mr15/interrupt_snapshot.py /private/tmp/mr15-validation/inputs/
uv run --frozen --no-sync python /private/tmp/mr15-validation/install.py
cd /private/tmp/mr15-validation
./installed/venv/bin/python -I inputs/publish_snapshot.py inputs
```

The temporary `install.py` invokes the existing
`alpha_research_governance.wheel_smoke._InstalledWheelCheck.validate` with the
checkout, external `installed/` directory and built wheel. The frozen hash-verified
binary-only runtime dependency installation, `--no-deps` candidate installation,
dependency compatibility, public imports/exact codecs and absence of the governance
package all passed.

The [retained isolated consumer](../../tests/integration/consumers/datasets/publish_snapshot.py) runs
with `-I` outside the checkout, using external `site-packages` and copied inputs.
It publishes through the pipeline, abruptly exits installed child writers during
the first staged file, before rename and after rename, checks reader visibility,
retries each ID twice, and reopens the original snapshot throughout. It rejects
mutable/path/staging selectors and missing raw bytes, then restores verified raw
input and reopens successfully. Original snapshot:
`f5ab6e22f007582ba6ac46b949f062de46628e85f90bb54774f9b76ec834168a`.

Wheel SHA-256: `320e71b09b1bcdcabbb559fbe45495a9cf2148f7c0953f305d5acc4de670354c`.
Lock SHA-256: `e6cd3a169ff4b6850bcb5b09e38c44e1179b0dc1fb7c6a9bd95d2c4a058595e4`.
These temporary local artifacts are development evidence, not a durable release archive.

### Fresh-kernel NB 15

```sh
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.3.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
```

Successful fresh attempt: **`4312d8e6-8544-4ed4-ad7c-e7a4f2cda8a0`**, all **57 cells /
24 code cells** passed. The initial import check matched all **66 runtime files**
to installed `site-packages`. Runtime is committed at `847c7ce`; the runtime-input
diff is empty. Tooling versions are nbclient 0.10.4, nbformat 5.10.4 and ipykernel
7.3.0. The runner shut down its fresh kernel and removed temporary kernel files.
The first sandbox invocation failed before starting a kernel because uv cache access
was denied; the escalated execution succeeded with no failed notebook attempt.

Notebook source SHA-256: `cf810e1abde536d4ae5b9ac32c4d6b6066eacf2b4968429bdb8b65c9e3046f05`.
Runtime SHA-256: `a2f16f51908a9b4665ed388203cf7e7b4ccfd520f7b70c50c236360dcc65f7da`.
NB 15 shows the original snapshot
`759941012fbd171b96502098e377b881675fa61b52b53a98e4127b30335b33b4` and changed-policy
snapshot `836629043959a498b5af023758ce68dca8be9e46fb3b9b21859305ccb4ac2972`.
Its six reader observations show absence after each injected prepublication failure,
readable completed retries, and prior-snapshot survival during failure and after
new publication. It also rejects `latest`. All earlier code-cell sources are
unchanged and reran against this candidate; saved OKX/Bitfinex inputs were reused
without acquisition or renewed empirical acceptance.

Final review commands:

```sh
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr15-validation/review.py
uv run --frozen --no-sync alpha-governance-architecture
python3 /private/tmp/mr15-validation/count.py
git diff --check
git ls-files -- examples/
git check-ignore examples/runs/research-foundations/4312d8e6-8544-4ed4-ad7c-e7a4f2cda8a0.ipynb examples/.kernel-probe/connection.json examples/.ipynb_checkpoints/checkpoint.ipynb
```

All final checks passed. The temporary review validates notebook schema, sequential
complete execution and source identity; all 23 earlier code-cell sources are
unchanged. All 67 packaged files match source, wheel and external installation.
Changed Markdown and 11 notebook local links pass; the architecture command covers
48 documents. P1 bytes are preserved, and Ruff is renewed after execution.
Maintained `.ipynb`, `.py`
and `.md` examples remain tracked; only existing generated run/kernel/checkpoint
paths are ignored. Notebook outputs/metadata are small and reviewed; runner, ignore
policy and runtime dependency lock remain unchanged. Full hosted CI is still the
merge gate; no full local suite or physical power-loss test was performed.

## Risks / reversal

Acceptance is synthetic and bounded to the existing exploratory Binance trade
consumer: one complete raw archive per partition, with ordered multiple partitions
supported. Both raw and snapshot stores must remain available and protected from
external mutation. Same-filesystem atomic directory rename and synchronization are
required; no network/object-store or power-loss qualification is claimed. Process
death can retain hidden staging directories; no automatic cleanup is implemented.
Admission still uses bounded in-memory verification and retains unknown coverage,
availability and empirical eligibility. No M1 completion or P1 result is claimed.
The QuantLib release restriction remains; no deployment or trading is authorized.

The frozen [P1 specification](../research/p1-baseline.md) remains byte-identical to base,
SHA-256 `7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
Revert this MR before dependent consumers merge, retaining all snapshots and raw
inputs; select compatible code to reopen stored snapshots. No stored-data migration,
removal or operational rollback is needed. Existing acquisition/source evidence is
reused; the changed installed publication path and complete notebook are renewed.
