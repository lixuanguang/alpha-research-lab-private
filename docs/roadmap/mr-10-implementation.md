# MR 10 — Trade duplicate and correction admission

Historical commands below retain paths from their tested revision. Current source links
and the [test layout](../../tests/README.md) use the reorganized locations.

Owner: repository founder. Historical validation: implemented and locally verified on 2026-09-16.
This record covers only
[MR 10](README.md#canonical-datasets-and-publication).

## Problem / change

Raw occurrence positions cannot identify economic trades after a file gains an
inserted row. The dataset pipeline now admits one economic trade per source,
venue, canonical instrument, stream and trade ID, preserving duplicate lineage.
Explicitly evidenced corrections append immutable versions with publication and
availability clocks. An unresolved conflict returns no admitted result.

Started from fetched, clean `main` at `a66b49a` (MR 09, PR #33), satisfying the
sole MR 10 prerequisite, and created `codex/mr-10-trade-revisions`. Runtime and
regression implementation is committed in `cbd54ff` and `27d8a2f`. Subsequent
notebook/documentation evidence does not change the tested runtime bytes.

## Affected scope

| Operation / actual consumer | Inputs, output and lifetime |
| --- | --- |
| `TradeRevision.admit`, called by the dataset pipeline | Complete bounded occurrence batch plus explicit `reject`/`evidenced` policy and corrections → one immutable head per economic key. State is local to the call; failure/retry cannot retain partial admission. |
| `TradeRevision` and `Correction` | Retained raw occurrences, predecessor/replacement identities, UTC publication/availability and evidence reference → validated immutable envelopes. The existing cached `DomainCodec` round-trips the entire history. |
| `admit_saved_trades` | Explicit original/revised acquisition manifests, raw store and per-archive byte cap → complete admitted histories. Reuses the MR 08/09 reader/decoder and closes every iterator. No file is published or rewritten. |

Payload identity excludes raw position, duplicate count, retrieval location and
Decimal formatting. Every supported economic field participates, including archive
quote quantity, source timestamp/precision and flags. Exact integer ratios avoid
Decimal-context rounding when identifying equivalent amounts. Original decimal
scales, raw bytes and all distinct lineage remain in their occurrences. Repeating
an identical occurrence is idempotent; reordered inputs reproduce the same result.

Conflicts retain their payloads and lineage in `RevisionConflictError.revisions`.
Correction admission rejects absent, malformed, dangling, branched, cyclic,
cross-trade and temporally reversed evidence. The evidence reference is a retained
caller assertion, not independently fetched proof. Effective knowledge uses the
envelope: it cannot precede original/own capture, prior effective knowledge or
correction availability. Initial archive knowledge remains unknown; explicit
correction evidence establishes only that corrected version's availability.
Local acquisition clocks never replace absent historical market clocks.

The [data contract](../data/contracts.md#trade-duplicate-and-correction-admission-mr-10)
explains supported inputs and consumer obligations. Tardis `Trade`, `ArchiveTrade`,
`Occurrence`, controls, storage, configuration and existing serialized fixtures
remain unchanged. There are **no dependency, declarative configuration, export,
ignore-policy or executable-tooling changes**.

Review sizes use added plus deleted code-bearing physical lines, excluding blank
lines, docstrings, comments, tests/fixtures and notebook checkpoint evidence:

| Review boundary | Additions | Deletions | Total |
| --- | ---: | ---: | ---: |
| `cbd54ff`: usable duplicate admission plus saved-input consumer | 115 | 0 | 115 |
| `27d8a2f`: evidenced corrections plus consumer and invariant changes | 103 | 6 | 109 |
| Entire MR against actual base `a66b49a` | 212 | 0 | 212 |

The combined MR exceeds the 150-line preference by 62 lines. It is split into two
independently usable, tested review commits, each below 150. Keeping the complete
MR together delivers its required duplicate, correction, lineage and availability
behavior; validation and the first useful consumer were retained in each slice.
No declaration-only scaffolding or deferred invariant was used to lower the count.

## Validation result

Commands ran from the repository root unless stated otherwise, with CPython 3.14.7.
The first duplicate slice passed **12 tests**, and the complete admission selection
passed **24 tests**, without skips/deselections. The broader affected regression
selection passed **109 tests, 1 integration deselection**. Explicitly selecting the
installed-command integration case passed **1 test, 21 deselections**. No tests skipped.

```sh
uv run --frozen --no-editable pytest -q tests/unit/data/test_revisions.py tests/unit/data/test_normalization.py tests/unit/pipelines/test_occurrences.py tests/unit/pipelines/test_dataset.py tests/unit/data/providers/binance/test_trades.py tests/unit/test_serialization.py
uv run --frozen --no-sync pytest -q -m integration tests/unit/pipelines/test_dataset.py
uv run --frozen --no-sync ruff check src/alpha_research/data/revisions.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_revisions.py tests/unit/pipelines/test_occurrences.py tests/fixtures/mr10/admit_revisions.py examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/revisions.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_revisions.py tests/unit/pipelines/test_occurrences.py tests/fixtures/mr10/admit_revisions.py examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/data/revisions.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_revisions.py tests/unit/pipelines/test_occurrences.py tests/fixtures/mr10/admit_revisions.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/revisions.py src/alpha_research/pipelines/dataset.py
```

Ruff, strict typing, repository engineering rules and Bandit passed. Tests cover
shifted-row/formatting duplicates, every economic field, independent instruments,
complete raw lineage, exact round trips, unknown archive availability, multiple
corrections, retained earlier history, inclusive knowledge boundaries, capture and
prior-knowledge lower bounds, unsafe instances, missing/malformed clocks/evidence,
ambiguous links, malformed trailing rows and missing saved inputs.

Initial failures were in test preparation: a price substitution did not match the
existing fixture, strict typing needed explicit union narrowing, and the temporary
duplicate-only split retained correction keywords in one test. Each was corrected
before its review commit. Early notebook lint findings were formatting only;
the first fresh-kernel NB 10 execution passed. A sandbox denial for uv cache access
was resolved through the normal escalated command path.

### Installed wheel outside the checkout

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr10-validation/dist
mkdir -p /private/tmp/mr10-validation/inputs
cp configs/data-jobs/binance-archive.json configs/reference/binance-archive-spot.json tests/fixtures/mr10/admit_revisions.py /private/tmp/mr10-validation/inputs/
uv run --frozen --no-sync python /private/tmp/mr10-validation/install.py
cd /private/tmp/mr10-validation
./venv/bin/python -I inputs/admit_revisions.py inputs
```

The temporary `install.py` calls the existing
`alpha_research_governance.wheel_smoke._InstalledWheelCheck.validate` with the
checkout root, external validation directory and built wheel. It installs frozen
runtime requirements using `--require-hashes --only-binary=:all:`, then the candidate
with `--no-deps`, and runs dependency/import/codec smoke checks. All passed.

The copied [retained consumer](../../tests/integration/consumers/datasets/admit_revisions.py) ran
with `-I`, external `site-packages` and no governance package or checkout path
injection. It reopened saved manifests, admitted shifted-row duplicates, rejected
unevidenced conflicts and incomplete inputs, admitted a linked correction, retained
its predecessor, round-tripped exact envelopes and reproduced reordered input results.

Wheel SHA-256:
`3c7fcdc004f96e5f12f7f79b076352d978a42458ade61fa54923c13f60a4f970`.
Frozen lock SHA-256:
`e6cd3a169ff4b6850bcb5b09e38c44e1179b0dc1fb7c6a9bd95d2c4a058595e4`.
The wheel/environment remain local development evidence, not a release artifact.

### Fresh-kernel NB 10

```sh
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
```

All **34 cells / 15 code cells** passed in a fresh kernel against runtime commit
`27d8a2f`. All **62 installed runtime files** matched the candidate before interpretation.
Runtime SHA-256: `6658b00490837a0d91381b1bb410ec401df3c568d322089913c900f68882ca59`;
runtime input diff was empty. Actual kernel tooling: nbclient 0.10.4,
nbformat 5.10.4 and ipykernel 7.3.0 (despite the requested 7.2.0 overlay).

Successful attempt `8e11de2d-a1ef-40a8-a286-3ac31b8d6e4f` is retained under ignored
`examples/runs/research-foundations/`. Notebook source SHA-256:
`6ee8f5a69fc89dd7e0347759123dac696f90e0dcfc2cbb21be867467f8823549`.
Section 10 displays two raw origins at positions 0/1 contributing one trade, an
appended correction, absent original archive knowledge, and a captured price of
`67540.01000000` before the late correction changes it to `67541.01000000` exactly
at `2024-06-01T00:00:10Z`. Before original capture, neither version is usable.
Required failures display unevidenced conflict, missing reference, invalid/naive
clocks and non-trade controls. These are synthetic assertions; the earlier pinned
OKX/Bitfinex book cells use unchanged saved inputs. No network or new observation.

Final review commands:

```sh
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr10-validation/validate.py
uv run --frozen --no-sync alpha-governance-architecture
git diff --check
git ls-files -- examples/
git check-ignore examples/runs/research-foundations/8e11de2d-a1ef-40a8-a286-3ac31b8d6e4f.ipynb examples/.kernel-probe/connection.json examples/.ipynb_checkpoints/checkpoint.ipynb
```

The temporary review script checks notebook schema/syntax, all-cell execution and
source digest, selected Markdown/notebook links through the existing architecture
validator, wheel/source/installed runtime parity and unchanged P1 bytes. All passed:
12 existing code cells were unchanged, **63 packaged files** matched the wheel and
both installations, and the architecture check passed for **43 documents**. Maintained
`.ipynb`, `.py` and `.md` examples stay tracked. The runner closed its execution
kernel; generated run, checkpoint and temporary kernel paths retain the unchanged
ignore policy. The documentation skill's referenced `docs/coding_standards/documentation.md`
is absent; the actual engineering guide's Documentation section was followed.

The complete local suite and hosted CI were not run. Hosted merged-result checks
remain required before merge. Existing acquisition/storage failure and real-source
probe evidence is reused because those implementations and inputs did not change.

## Risks / reversal

This is bounded in-memory trade admission. The selected policy supports linear
histories with distinct economic payloads; reverting to an identical previous
payload requires additional source revision evidence and is rejected. It does not
claim historical Binance revision evidence, eligibility, coverage, quality acceptance,
snapshot publication, a shared as-of reader, replay or a P1 result. Later consumers
must retain full envelopes and use effective knowledge. No whole-day memory or
latency qualification is claimed. The existing QuantLib release restriction remains.

The frozen [P1 specification](../research/p1-baseline.md) is byte-identical to main:
SHA-256 `7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
Revert this MR's commits before dependent consumers merge. Raw objects, acquisition
manifests and previous notebook attempts need no migration or deletion. After later
adoption, revert/select compatible dependent code together.
