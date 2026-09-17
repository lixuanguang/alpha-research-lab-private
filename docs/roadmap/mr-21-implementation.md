# MR 21 — Exercise EDA and extension boundaries

Owner: repository founder. Status: implemented and locally verified for review on
2026-09-18 (Asia/Singapore). Branch: `codex/mr-21-eda-extensions`. Base: fetched,
updated `main` at `f8ef338`. Prerequisites MR 19 (`0898d0a`, PR #44) and MR 20
(`f8ef338`, PR #46) are merged ancestors. The [roadmap row](README.md#m2-research-data-access-and-replay)
owns scope; this record describes the tested candidate and its limitations.
[PR #47](https://github.com/lixuanguang/alpha-research-lab-private/pull/47)
retains the hosted checks and merge status. Tested implementation: `900a0a5`.

## Problem / change

`pipelines.eda.inspect_eda` reads a strict `EdaQuery` JSON file, opens its explicit
saved snapshot through `QueryReader`, and sends complete/failed attempt records
to a required retention callback. Records bind the resolved selection and installed
implementation to semantic query/summary identities. `QuerySummary.collect` reduces
projected batches into exact per-binding price ranges and counts while preserving
controls and complete quality, unit and membership evidence. An optional batch
observer supplies the notebook plot without duplicating query or summary logic.

Attempt observations include query/total seconds, rows, controls, batches, maximum
batch rows, process lifetime peak RSS bytes and OS input-block delta. They do not
enter semantic identities. Empty results retain evidence; invalid selections,
missing/corrupt snapshots and observer failures cannot report a completed query.
The callback owns persistence; a failed reporting sink cannot guarantee delivery.

## Affected scope

Runtime changes are confined to `data/eda.py` and `pipelines/eda.py`. The schema,
summary reducer and first orchestration consumer ship together. Existing query,
replay, source configuration, exact-unit codecs, snapshot publication and adapter
contracts are reused unchanged. The installed consumer and NB 21 section 11 query
two supported instruments and replay their three-second business interval outside
Jupyter. The notebook calls the same installed orchestration to plot it.

The explicit [synthetic contract fixture](../../tests/fixtures/mr21/contract.json)
exercises neutral contract identity, quantity/multiplier and projected-batch summary
contracts. Two contracts × 50 underlying units/contract × 4200.25 USD/unit yields
exactly 420025 USD. Wrong dimensions, a future product at the spot adapter boundary,
unsupported lifecycle/adapter fields, unsupported selection and insufficient byte
budget fail. The fixture is not a `SpotInstrument` and is not admitted to the spot
snapshot/replay path; no second-family production support is claimed.

Against `f8ef338`, production code-bearing changes are **191 additions + 0 deletions
= 191 lines**: 114 in the configuration/summary library and 77 in orchestration,
including imports, annotations, validators and executable statements. This cohesive
41-line overage above the 150-line preference keeps strict file/config validation,
exact summaries and failure/observation reporting with their first working consumer.
Splitting declarations or removing these protections would leave an incomplete EDA
entry. A separate CLI framework was unnecessary; the installed Python entry is
exercised from a standalone process. Tests/fixtures, notebook acceptance exercises,
comments/docstrings and prose are excluded; no maintained executable tooling script
changed. Declarative runtime configuration, dependencies, `pyproject.toml`, `uv.lock`,
public exports and ignore policy are unchanged. One synthetic JSON fixture is added.

The notebook additionally verifies the complete installed runtime file inventory
and selects the installed dataset command beside its kernel interpreter. These
acceptance fixes ensure all cells use the same candidate. The [API guide](../../src/alpha_research/data/README.md#configured-eda-and-extension-boundaries-mr-21),
[researcher guide](../../examples/README.md) and [operations guide](../../examples/notebook-operations.md#mr-21-configured-eda-and-clean-kernel-acceptance)
describe current use.

## Validation result

CPython 3.14.7, macOS arm64. Focused regression command: **74 passed, 1 deselected,
0 skipped**. The deselected case is the existing integration-marked dataset CLI
smoke; the new external installed consumer and the notebook's candidate-specific
CLI/Python parity exercise ran separately.

```sh
uv run --frozen --no-editable pytest -q tests/unit/data/test_eda.py tests/unit/pipelines/test_eda_pipeline.py tests/unit/data/test_query.py tests/unit/data/test_event_stepping.py tests/unit/data/test_asof.py tests/unit/pipelines/test_dataset.py
uv run --frozen --no-sync ruff check src/alpha_research/data/eda.py src/alpha_research/pipelines/eda.py tests/unit/data/test_eda.py tests/unit/pipelines/test_eda_pipeline.py tests/fixtures/mr21/eda_consumer.py examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/eda.py src/alpha_research/pipelines/eda.py tests/unit/data/test_eda.py tests/unit/pipelines/test_eda_pipeline.py tests/fixtures/mr21/eda_consumer.py examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src tests tools/governance/src tools/typing/stubs
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/eda.py src/alpha_research/pipelines/eda.py
uv run --frozen --no-sync alpha-governance-architecture
uv run --frozen --no-sync --with 'nbformat==5.10.4' python -c 'import nbformat; nbformat.validate(nbformat.read("examples/research-foundations.ipynb", as_version=4)); print("Notebook schema valid")'
python3 /private/tmp/mr21-validation/verify.py
git diff --check
```

All passed. Full configured mypy covered 168 files; architecture checked 54 documents.
Additional local verification checked component/example/notebook links, sequential
execution counts, no cell errors, source/output snapshot equality, complete wheel
inventory, production line count, and byte-identical P1 and lockfile. No full local
`make check` or hosted result is claimed. Unchanged acquisition, interruption,
publication and live-source behavior retains prior evidence; no network market-data
request or empirical research run was needed.

Nine new focused cases cover strict config round trips and invalid capabilities,
exact grouped summaries, scoped controls, empty evidence, delivery-independent
identities, changed cutoffs, mixed-query rejection, failed observer recovery, contract
units, missing/corrupt snapshots and pre-read configuration refusal.

### Installed wheel and standalone replay

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr21-validation/dist
mkdir -p /private/tmp/mr21-validation/inputs /private/tmp/mr21-validation/installed
cp tests/fixtures/mr21/eda_consumer.py tests/fixtures/mr21/contract.json tests/fixtures/mr12/eligibility.json configs/data-jobs/binance-archive.json configs/reference/binance-archive-spot.json /private/tmp/mr21-validation/inputs
uv run --frozen --no-sync python /private/tmp/mr21-validation/install.py
cd /private/tmp/mr21-validation
./installed/venv/bin/python -I inputs/eda_consumer.py inputs installed-sample
```

The temporary installer calls the existing `_InstalledWheelCheck.validate` with
the checkout, `installed/` and the built wheel. Frozen, hash-locked, binary-only
runtime installation, dependency compatibility, governance-free imports and exact
codec smoke passed. Source, wheel and external installation matched all **76**
packaged runtime files, with no extra runtime files. The standalone consumer uses
only copied fixtures/configuration and installed runtime imports under `-I`.

The retained external sample has snapshot
`43ddfc31694ef2620d4859449019c6c5cc5bc029712fb39a8c2929d4d4ad1545`, query
`c52d7c3ff17664c2eb0a13950c14246503d82d17fad7f390ff2b8f62c2c02d20`, and summary
`4c426d5bff4300ec02d3a69ea294456d23e53e147f1e1fd35b3270b7f4f12d2c`.
It produced **6 rows / 3 batches**, exact ranges **101–103** and **201–203**, and
six replay sources at **10, 10, 20, 20, 30, 30 seconds**. Batch sizes 2/8 retained
the same semantic identities. The external query observed **0.02601 seconds**,
**126,091,264 bytes** process peak RSS and **0 OS input blocks**. Independent audit
observations counted **1 manifest, 4 canonical and 4 raw file opens** during the
verified query. Counts include admission rereads; cached reads can produce zero
OS input blocks. These are tiny-sample observations, not performance guarantees.

The consumer preserves `query.json`, `attempts.jsonl`, `replay.json`,
`extension.json` and the synthetic stores under the local output directory.
Four EDA failure attempts are retained separately; adapter and wrong-unit refusals
are also exercised. Runtime evidence remains exploratory degraded; original archive
availability is never inferred from acquisition time. The initial development
fixture run failed because `ZipInfo` defaulted to stored compression; explicitly
selecting the required DEFLATE format corrected the fixture. No product invariant
was weakened.

### Fresh-kernel NB 21

```sh
uv pip install --python /private/tmp/mr21-validation/installed/venv/bin/python --only-binary=:all: 'ipykernel==7.2.0' 'matplotlib==3.10.8'
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb --kernel-python /private/tmp/mr21-validation/installed/venv/bin/python
```

All **51 cells / 26 code cells** passed in a fresh clean external kernel, verifying
all 76 runtime files before any result. Successful attempt:
`7331b72d-8c6b-43db-b713-8dd05f68816f`; source SHA-256:
`3be4bf8524c7a3ac0e287fc754f064172408cae526bfccf0b03fedd2c245ee08`.
Execution finished at `2026-09-17T16:01:56Z` (2026-09-18 Singapore).
Notebook, child-process and standalone-wheel query/summary identities match.
The bounded plot was visually inspected; exact labels and separate instrument
units remain readable. Saved real books were read only, temporary synthetic stores
were cleaned up, and finished kernels were shut down.

The earlier successful attempt `cb7cd904-28e0-4b23-abda-c181bd8f5fb2` used a development
installation containing 200 extra duplicate runtime files. Although the expected
files matched source, the extras changed implementation fingerprints; it is not
the final artifact acceptance. The complete-inventory check now rejects that
state. The first clean-kernel attempt `2d8d609b-1b6b-492a-a842-e2f858e66ac8` failed
existing section 6 CLI/Python identity parity: `PATH` selected the other environment's
`alpha-dataset`. Binding that command to the selected kernel fixed the harness;
the final fresh run above passed. No existing environment files were removed.
Source/wheel runtime bytes stayed unchanged, so focused tests and external wheel
proof remain applicable. Notebook outputs retain only small synthetic examples,
permitted saved-input identities and one bounded plot, not raw market exports.

Maintained `.ipynb`, `.py` and `.md` examples remain tracked. `git ls-files -- examples/`
and `git check-ignore` confirm that only generated runs, kernel files and checkpoints
are ignored under the existing policy. No notebook runtime dependencies were added
to the project lock; pinned plotting/kernel tools live in the identified temporary
development environment.

| Tested identity | SHA-256 |
| --- | --- |
| Runtime source aggregate (relative path, NUL, bytes, NUL; sorted) | `a1e72040eceb8da2316fd476d7ea5fac8e44795ca7e15fd0d575c342e57dd27a` |
| `data/eda.py` | `b1cdd3ae453234882da2723838ea9aa20f080c8c6b25bcd65adba7b9bc107c09` |
| `pipelines/eda.py` | `2e405c3192c21f370abc3891135a397412fa8ca5fe5bb3d247ad34524e91e176` |
| Wheel | `e04574a33963e2000300c042b4a662e4302ff6cd77145f4f2e69841e26eecc9f` |
| Standalone consumer | `7b492601a0c344d0f5f1ae9bca380e54ae9bf0598d684b1220871666a645bb60` |
| Contract fixture | `713eaee64470970b0472c5eb788cbb2dcbf56ff4096f2a1543b9e872a4248c00` |
| Unchanged `uv.lock` | `e6cd3a169ff4b6850bcb5b09e38c44e1179b0dc1fb7c6a9bd95d2c4a058595e4` |
| Preserved P1 specification | `7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d` |

## Risks / reversal

The reader retains bounded canonical inputs, admitted partitions and selected
history in memory. Neither row batching nor reported RSS is a process-memory cap;
no streaming storage backend or I/O pushdown is claimed. The reducer retains only
groups/evidence, while plot/export observers own any buffered rows. History ranges
are head summaries; causal replay uses the existing version-expanding operation.
The process observation fields are qualified for the tested macOS/Linux convention,
with only macOS exercised here.

The different-family fixture is projection/identity/unit evidence, not derivative
admission, lifecycle, accounting or execution support. No real historical eligibility,
coverage, empirical alpha, book adapter, feature platform, service or deployment
acceptance follows. MR 18's measured backend deferral and release restrictions remain.
Local wheel, environment and `/private/tmp/` outputs are not a durable release archive;
retained source/fixtures reproduce the sample. The existing development environment
still needs a clean replacement before it can pass the stricter notebook inventory
check; the documented external kernel is the verified route.

Revert this MR before dependent consumers merge; no saved dataset or existing query
API migration is required. Preserve raw inputs and failed attempt history. The frozen
P1 specification is byte-identical to the base. **Next: MR 22 — Bind and verify one
live source**, after MR 21 merges. No MR 22 work is started here.
