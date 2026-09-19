# MR 14 — Validate and identify a dataset manifest

Historical commands below retain paths from their tested revision. Current source links
and the [test layout](../../tests/README.md) use the reorganized locations.

Owner: repository founder. Historical validation: implemented and locally verified for review on
2026-09-17. Branch: `codex/mr-14-dataset-manifest`. Base: freshly fetched `main`
at `7ef4892`, which merges prerequisite MR 13 in PR #37. Runtime and regression
fixture commit: `cfd52b0`.

## Problem / change

Admitted canonical partitions previously had no dataset-level identity or verified
manifest reader. `assemble_dataset` now combines ordered, complete acquisitions
with the existing quality gate, returning a manifest and canonical bytes only when
all partitions pass. `DatasetManifest.read` checks the explicitly selected identity,
all canonical files and raw inputs, reproduces admission, and requires exact byte
agreement. It refuses unknown versions, unsupported scope, changed references,
missing bytes and rehashed canonical content that disagrees with its evidence.

The manifest binds ordered partition digests, embedded raw manifests, full resolved
job/universe/catalog, eligibility and correction histories, normalization code/schema,
quality policy and correction/availability rules. Mutable names cannot replace
resolved content. File locations and build time are absent from semantic identity;
original acquisition and evidence clocks remain meaningful provenance. Rebuilds
and relocation retain identity; a changed policy or reference changes it.

The [manifest contract](../data/contracts.md#dataset-manifest-identity-and-verification-mr-14)
and [component guide](../../src/alpha_research/data/README.md#identify-and-verify-a-dataset-manifest-mr-14)
own semantics and usage. NB 14 and the [researcher guide](../../examples/README.md)
explain the observable outputs and limits.

## Affected scope

`data/datasets.py` owns immutable manifest records, semantic identity and bounded
verified reading. The dataset pipeline composes saved acquisition, quality and
manifest construction. Both operations retain only invocation-local state. Existing
`DomainCodec`, `RawStore`, archive readers/decoders, occurrences, correction admission
and eligibility selection supply their existing contracts. No dependency, CLI,
configuration format, export wrapper or storage service is added.

Against base `7ef4892`, production code-bearing changes are **170 additions +
1 deletion = 171 lines**: 131 in the new module and 40 in the pipeline. This counts
imports, annotations, validators and codec setup, excluding blank/comment/docstring
lines, tests/fixtures and notebook examples. There are **zero declarative runtime
configuration/dependency changes and zero executable-tooling changes**.

The cohesive overage is 21 lines above the preferred ceiling. Keeping strict records,
verified reading and their first working pipeline consumer together avoids an unused
schema-only slice or a reader that trusts unchecked quality labels. Reconstructing
admission from verified raw bytes closes that integrity boundary without another
parser/schema for canonical histories. Atomic publication remains MR 15; no later-MR
behavior was added to justify the overage.

## Validation result

CPython 3.14.7, macOS arm64. Commands ran from the checkout unless stated otherwise.
The new test selection initially had one fixture error: it tried to change a
nonexistent catalog `version` field. The test now changes the real `evidence` field;
all assertions pass. Initial unused test imports were removed. Sandbox cache/process
restrictions followed the required escalation path. The documentation skill's
referenced `docs/coding_standards/documentation.md` is absent, so the engineering
guide's Documentation section was followed.

```sh
uv run --frozen --no-editable pytest -q tests/unit/data/test_datasets.py tests/unit/data/test_quality.py tests/unit/data/test_manifests.py tests/unit/data/test_revisions.py tests/unit/pipelines/test_occurrences.py tests/unit/pipelines/test_dataset.py tests/unit/test_serialization.py
uv run --frozen --no-editable pytest -q -m integration tests/unit/pipelines/test_dataset.py
uv run --frozen --no-sync ruff check src/alpha_research/data/datasets.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_datasets.py tests/fixtures/mr14/identify_dataset.py examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/datasets.py src/alpha_research/pipelines/dataset.py src/alpha_research/data/README.md tests/unit/data/test_datasets.py tests/fixtures/mr14/identify_dataset.py examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/data/datasets.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_datasets.py tests/fixtures/mr14/identify_dataset.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/datasets.py src/alpha_research/pipelines/dataset.py
```

All passed: **112 focused tests, 1 deselected, no skips**; separate integration
selection **1 passed, 21 deselected, no skips**. Nine new manifest cases cover
rebuild/round-trip/relocation parity, explicit partition ordering, same job name with
different actual instruments, changed policy/eligibility/catalog/provenance/code,
stale bytes, each missing/mutated file class, forged quality scope with a new digest,
unknown versions and fields, unsafe nested copies, byte limits, empty/duplicate
selections, unused correction keys, no returned prefix after a later failure, causal
refusal and retained correction predecessors/effective availability. The integration
case renews the existing installed fixture command after the pipeline import change.

### Installed wheel outside the checkout

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr14-validation/dist
mkdir -p /private/tmp/mr14-validation/inputs /private/tmp/mr14-validation/installed
cp configs/data-jobs/binance-archive.json configs/reference/binance-archive-spot.json tests/fixtures/mr12/eligibility.json tests/fixtures/mr14/identify_dataset.py /private/tmp/mr14-validation/inputs/
uv run --frozen --no-sync python /private/tmp/mr14-validation/install.py
cd /private/tmp/mr14-validation
./installed/venv/bin/python -I inputs/identify_dataset.py inputs
```

The temporary `install.py` invokes the existing
`alpha_research_governance.wheel_smoke._InstalledWheelCheck.validate` with the
checkout, `/private/tmp/mr14-validation/installed`, and the built wheel. Frozen,
hash-verified binary-only runtime dependencies, `--no-deps` candidate installation,
dependency compatibility, public imports/exact codecs and governance-package absence
all passed. An interrupted earlier orchestration left a separate external venv;
the explicitly reported check completed in `installed/` without reusing uncertain
installation evidence.

The [retained isolated consumer](../../tests/integration/consumers/datasets/identify_dataset.py) runs
with `-I` from outside the checkout, using external `site-packages` and copied inputs.
It rebuilt twice, verified saved canonical/raw bytes, changed a policy, exercised
six failures (unknown nested version, scope, expected identity, missing canonical,
missing raw and causal admission), restored inputs and reopened successfully.
Original dataset identity was
`17b9b29058bc4d37f28c75de3c594c891b4cb58cc3d8f655e2f616e547353766`;
the changed-policy identity was
`a922a5bec161bd42d5ddf3b12c11fed07505eff26736fd11f83f09e9b730c172`.

Wheel SHA-256: `b1ac2e4845d2646bd5bda851e054fb6d68f658f2a87880aa8e0d81112c92e59d`.
Lock SHA-256: `e6cd3a169ff4b6850bcb5b09e38c44e1179b0dc1fb7c6a9bd95d2c4a058595e4`.
These local artifacts are development evidence, not a durable release archive.

### Fresh-kernel NB 14

```sh
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.3.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
```

The first attempt, `429bbc24-5f62-467b-b399-c0bac0ff3a64`, reached NB 14 but failed
in its failure-example preparation: `DomainCodec` is a typed record boundary and
does not decode arbitrary `dict[str, object]`. The notebook now uses `json.loads`
only to edit deliberately invalid JSON. Runtime code was unchanged. The failed
snapshot remains under ignored `examples/runs/research-foundations/`.

Successful fresh attempt: **`a16b9210-5746-400d-a69c-4ee8df857134`**, all **54 cells /
23 code cells** passed. The initial import check matched all **65 runtime files**
to installed `site-packages` before interpretation. Runtime is committed at
`cfd52b0`; the displayed nonempty runtime-input diff covers the component README,
not modified runtime code. Tooling versions are nbclient 0.10.4, nbformat 5.10.4 and
ipykernel 7.3.0. The runner shut down its fresh kernel and removed its temporary
directory. A preexisting unrelated interactive kernel was left intact.

Notebook source SHA-256: `828523c44e4897971dd047446c9bc625422c6dd7aed994b14b8034d2e86afc8b`.
Runtime SHA-256: `5e77876ffdf0e562f72ed6ec269411921441a0ab8b7d699b92d98affef99242c`.
NB 14 displays two matching manifest hashes
`1fb4c44147097efbb5765fe953ee5d9722c229d4c093168e96e0a5c0d3ec74f3`, then
`ea85fefc5b2b6f9f4694fb454cace169c5e0bfbba4172d3be940f686c5b1e384` after changing
the gap policy. It shows resolved identities, explicit degraded scope and five
failures: unknown top-level manifest version, unsupported scope, changed code
identity and missing canonical/raw bytes. Relocation/restoration recovers identity.
Earlier code-cell sources are unchanged and reran against the candidate; saved
OKX/Bitfinex inputs were reused without acquisition or new empirical acceptance.

Final review commands:

```sh
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr14-validation/review.py
uv run --frozen --no-sync alpha-governance-architecture
python3 /private/tmp/mr14-validation/count.py
git diff --check
git ls-files -- examples/
git check-ignore examples/runs/research-foundations/a16b9210-5746-400d-a69c-4ee8df857134.ipynb examples/.kernel-probe/connection.json examples/.ipynb_checkpoints/checkpoint.ipynb
```

The temporary review validates notebook schema, sequential completed execution,
source identity, preservation of earlier code cells, changed local Markdown links,
source/wheel/external-install parity and preserved P1 bytes. Ruff is renewed after
execution. All checks passed: 21 earlier code-cell sources are unchanged, all
66 packaged files match source/wheel/external installation, changed document and
notebook links are valid, and the architecture check covers 47 documents.
Maintained `.ipynb`, `.py` and `.md` examples stay tracked; only existing
generated run/kernel/checkpoint paths are ignored. Runner and ignore policy are
unchanged. Small outputs and metadata are reviewed without committing raw data,
secrets or bulk artifacts.

## Risks / reversal

Acceptance is synthetic and bounded: one complete Binance archive per canonical
partition, with ordered multiple partitions allowed. Combining separate original
and revised acquisition archives for one canonical partition is outside this consumer.
The reader replays admission in memory; no large-input performance, authenticity,
empirical coverage/eligibility, atomic snapshot, M1 completion or P1 result is claimed.
Original quality limitations and full histories survive. The QuantLib release
restriction remains unchanged. No deployment or trading authority is implied.

The frozen [P1 specification](../research/p1-baseline.md) remains byte-identical to base,
SHA-256 `7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
Revert this MR before dependent consumers merge, retaining raw/manifests/canonical
working files and selecting compatible code for old formats. There is no stored-data
migration, deletion or operational rollback. Existing source and raw-storage evidence
is reused; the affected composed installed path is renewed above.
