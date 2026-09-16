# MR 09 — Decoded raw occurrences

Owner: repository founder. Status: implemented and locally verified on 2026-09-16;
awaiting review and hosted merge checks. This record covers only
[MR 09](README.md#canonical-datasets-and-publication).

## Problem / change

The saved-row reader preserves bytes but does not interpret trades. Legacy event
IDs can repeat when line sequences restart in another file or input binding.
`iter_occurrences` now composes the existing resolved acquisition manifest, verified
archive reader, individual-trade decoder and occurrence envelope. It yields selected
trades with their exact raw origins and stable identities. No network is involved.

Started from fetched, clean `main` at `f05ef18` and created
`codex/mr-09-raw-occurrences`. Both declared prerequisites are merged ancestors:
MR 08, PR #32 at `f05ef18`; MR 02, M0 PR #23 at `80b5bc6`.
Runtime and regression implementation is committed at `0969f01`; subsequent
documentation/notebook evidence does not change its runtime bytes.

The [Binance primary source contract](https://github.com/binance/binance-public-data#spot),
checked 2026-09-16, defines the seven individual-trade columns and the switch to
microseconds from 2025. The adapter binds that unit by archive date, retains the
integer and exact Decimal values, and rejects malformed semantics or a timestamp
outside the requested UTC day. Source capture and historical knowledge remain
absent; local archive receipt is never substituted. Captured `Trade`,
`EventProvenance`, `Disconnect` and their codecs remain unchanged.

## Affected scope

| Operation / consumer | Inputs, output and lifetime |
| --- | --- |
| `ArchiveTrade.from_row`, called by the dataset pipeline | One MR 08 raw row and explicit request → frozen decoded trade. No mutable state; original values/precision stay attributable through the envelope. |
| `Occurrence`, consumed by the pipeline and saved-line examples | Request, raw descriptor, exact bytes, position and decoded record → frozen binding-scoped occurrence. Message identity excludes record index; occurrence identity includes it. Shared `DomainCodec` caches typed schemas. |
| `iter_occurrences` | Retained resolved acquisition manifest and raw store → a bounded iterator, one partition at a time. All rows are decoded before research-interval selection. Exhaust to validate the complete input; closing a prefix closes the reader. No normalization checkpoint or dataset write. |

Occurrences hash schema, request identity, raw digest, position and record index.
The same saved inputs reproduce identities; a renamed retrieval location does
not change them. Different files or bindings at sequence zero cannot collide.
Equal-time rows retain source order. Identical economic trades remain distinct
occurrences pending MR 10. The request carries the source, selected instrument
subscription, partition and resolved universe. Instrument-less Tardis disconnects
are scoped by this request; the current saved-file inputs have no live session ID.
Original submicrosecond capture text and source-message grouping are preserved.

The new persisted adapter supports Binance individual-trade archives. Existing
Tardis fixtures retain their consumer; no new persisted Tardis gzip reader or
collector adapter is introduced. Public libraries, raw storage, manifest validation,
exact serialization and numerical validators are reused. There are no dependency,
configuration, export, ignore-policy or executable-tooling changes.

Production code-bearing changes against `f05ef18`: **195 additions + 0 deletions =
195** (normalization 91, archive decoder 82, pipeline 22). This excludes docstrings,
comments, blank lines, tests/fixtures and notebook checkpoint evidence. Declarative
configuration/dependency changes: **0**. The 45-line overage keeps the validated
envelope, absent-capture trade representation and their first persisted consumer
together. Splitting these declarations from the consumer would leave an unconsumed
API or an incomplete occurrence workflow. No validation was removed to reduce size.

## Validation result

Commands below ran from the repository root unless stated otherwise. Python was
3.14.7. The focused runtime suite passed **134 tests, 1 integration deselection**;
the explicit installed-command integration run passed **1 test, 21 deselections**.
There were no skips. New checks include exact decimals and publisher quote quantity,
the 2025 timestamp-unit boundary, bad units/days/flags/amounts, equal-time order,
half-open selection, malformed excluded rows, distinct file/binding origins, rebuilds,
codec round trips, unsafe instances, missing/mutated inputs and prefix/retry behavior.
Legacy Tardis/market-event/fixture/serialization regressions also passed.

```sh
uv run --frozen --no-editable pytest -q tests/unit/data/providers/binance tests/unit/data/test_normalization.py tests/unit/pipelines/test_occurrences.py tests/unit/pipelines/test_dataset.py tests/unit/data/providers/tardis tests/unit/data/venues/binance tests/unit/data/test_decoders.py tests/unit/test_serialization.py
uv run --frozen --no-sync pytest -q -m integration tests/unit/pipelines/test_dataset.py
uv run --frozen --no-sync ruff check src/alpha_research/data/normalization.py src/alpha_research/data/providers/binance/trades.py src/alpha_research/pipelines/dataset.py tests/unit/data/providers/binance/test_trades.py tests/unit/data/test_normalization.py tests/unit/pipelines/test_occurrences.py tests/fixtures/mr09/read_occurrences.py examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/normalization.py src/alpha_research/data/providers/binance/trades.py src/alpha_research/pipelines/dataset.py tests/unit/data/providers/binance/test_trades.py tests/unit/data/test_normalization.py tests/unit/pipelines/test_occurrences.py tests/fixtures/mr09/read_occurrences.py examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/data/normalization.py src/alpha_research/data/providers/binance/trades.py src/alpha_research/pipelines/dataset.py tests/unit/data/providers/binance/test_trades.py tests/unit/data/test_normalization.py tests/unit/pipelines/test_occurrences.py tests/fixtures/mr09/read_occurrences.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/normalization.py src/alpha_research/data/providers/binance/trades.py src/alpha_research/pipelines/dataset.py
```

All listed static checks passed (8 Ruff targets, 7 strict-mypy Python files,
repository-wide engineering source rules, 3 Bandit runtime files). Initial iteration
found an int/Decimal loop-variable typing conflict, a reserved pytest fixture name
and minor lint issues; they were corrected. Two initial assertions incorrectly
expected the existing typed Decimal codec to reject JSON number tokens. Inspection
and an exact `9007199254740993.00000001` probe confirmed its lossless decimal parsing.
Tests now prove exact numeric-token input and string output, while direct/unsafe
Python floats still fail domain validation. No existing codec or invariant changed.

### Installed wheel outside the checkout

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr09-validation/dist
mkdir -p /private/tmp/mr09-validation/inputs
cp configs/data-jobs/binance-archive.json configs/reference/binance-archive-spot.json configs/data-jobs/fixture-inspection.json configs/reference/binance-spot.json tests/fixtures/mr09/read_occurrences.py /private/tmp/mr09-validation/inputs/
uv run --frozen --no-sync python /private/tmp/mr09-validation/install.py
cd /private/tmp/mr09-validation
./venv/bin/python -I inputs/read_occurrences.py inputs
```

The temporary `install.py` calls the existing
`alpha_research_governance.wheel_smoke._InstalledWheelCheck.validate` with the
checkout root, `/private/tmp/mr09-validation` and its built wheel. It creates an
isolated runtime environment, exports frozen runtime requirements, installs with
`--require-hashes --only-binary=:all:`, installs the candidate with `--no-deps`, then
checks dependency compatibility and the retained import/codec smoke. All passed.
The copied [consumer](../../tests/fixtures/mr09/read_occurrences.py) passed exact
trades, distinct files/positions, repeat builds, scoped controls, codec, empty,
malformed and missing-input cases using `-I` and external `site-packages` imports.
The environment contains no governance package and uses no checkout path injection.

Wheel: `alpha_research_lab-0.1.0-py3-none-any.whl`, SHA-256
`80ebb4cbbf49f7a39affc7f589b8e36d6778e570727ead85851d1c51d631b143`.
Frozen lock SHA-256:
`e6cd3a169ff4b6850bcb5b09e38c44e1179b0dc1fb7c6a9bd95d2c4a058595e4`.
Wheel and environment remain local development evidence, not a release artifact.

### Fresh-kernel NB 09

```sh
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
```

All **27 cells / 12 code cells** passed from a fresh kernel, including every existing
OKX/Bitfinex saved-input cell. All **61 installed runtime files** matched the committed
candidate before interpretation. Runtime SHA-256:
`6e55ee4ae52c6c743f283e649acf680ff9fe720c6ef93730a84019b5e8344129`;
runtime input diff was empty. Tooling observed in the kernel: nbclient 0.10.4,
nbformat 5.10.4, ipykernel 7.3.0 (despite the requested 7.2.0 overlay).

Successful attempt `7ae4500f-760b-4169-8da9-9a3b819eaf11` is retained under ignored
`examples/runs/research-foundations/`; source SHA-256
`d69708ed22160a39857511af83dc9be7e15e8b614f444f75f38833c08686aee6`.
Section 9 shows four distinct occurrences across BTC file versions and ETH, equal-time
trade IDs 12 then 11, exact values and unknown historical clocks, two identical raw
disconnects with different binding identities, and wrong-instrument/binding failures.
These are synthetic outputs. The existing pinned book inputs are reused unchanged;
no provider download or new market observation was performed. The runner closed its
kernel and removed temporary kernel files. Maintained example sources remain tracked;
run snapshots, checkpoints and temporary kernels remain ignored under unchanged policy.

Final review commands:

```sh
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr09-validation/validate.py
uv run --frozen --no-sync alpha-governance-architecture
git diff --check
git ls-files -- examples/
git check-ignore examples/runs/research-foundations/7ae4500f-760b-4169-8da9-9a3b819eaf11.ipynb examples/.kernel-probe/connection.json examples/.ipynb_checkpoints/checkpoint.ipynb
```

The temporary review script passed notebook schema/syntax, all-cell execution and
source-digest checks; checked local links in the six affected Markdown files plus
extracted notebook prose through `ArchitectureGovernanceService`; matched all 61
runtime files against the built wheel; and verified unchanged P1 bytes. Its initial
global-empty-kernel-directory assertion encountered three older ignored directories
from September 13–14. They were left untouched; the corrected check establishes
that this run left no new kernel directory. Architecture links passed for all
42 documents. Notebook Ruff/format and `git diff --check` passed. Maintained examples
are tracked and the generated paths above are ignored.

The complete local suite and hosted CI were not run; hosted merged-result
checks remain required before merge. Existing acquisition/storage interruption
evidence is reused because this MR does not change those paths.

## Risks / reversal

No empirical coverage, historical eligibility/availability, duplicate/correction
admission, accepted dataset, replay, strategy or P1 result is claimed. Quote quantity
is retained rather than reconciled; stream-specific quantity/quality policy remains
MR 13. Persisted inputs support the bounded single-day individual-trade archive
contract only. A partially consumed iterator is not accepted data. Later query and
collector integration must preserve this lineage and applicable session metadata.
The existing QuantLib release restriction remains in force.

The frozen [P1 specification](../research/p1-baseline.md) is byte-identical to main,
SHA-256 `7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
Revert this branch before dependent consumers merge. There is no existing stored
schema migration or mutable service state to undo; retain raw inputs/manifests and
run attempts. Once later consumers adopt occurrences, revert/select compatible
dependent code together.

**Next: MR 10 — Admit duplicates and corrections explicitly.** It has not been started.
