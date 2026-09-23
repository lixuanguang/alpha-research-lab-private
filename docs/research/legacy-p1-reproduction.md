# Legacy P1 source-evidence reproduction

Owner: repository founder. Status: deferred historical reproduction only; updated
2026-09-23. The current research path starts with the saved [OKX order-book
study](l2-book-backtest.md) or the maintained [Bitfinex live
route](../../examples/research-foundations-live.ipynb). This page owns the
instructions for reopening the frozen Binance/Tardis P1 source-evidence
investigation. It does not reopen the experiment, qualify the source, contact a
provider or run economics.

The [P1 baseline](p1-baseline.md) remains frozen and unaccepted. Its original
acceptance requirements, source identity and v1 report semantics remain
historical evidence. The [historical P1 notebook](../../examples/research-foundations-live-p1-evidence.ipynb)
reopens the explicitly pinned Binance archive and auxiliary native capture in
saved mode without a network call. Its deliverable is a reproducible
source-evidence handoff. The archived notebook remains byte-identical to the
tested historical checkout and keeps its original imports and source identity.

Use checkout `1ec24eb` and its frozen environment for this record. Its
`examples/research-foundations-live.ipynb` is byte-identical to the archived P1
notebook (SHA-256 `1a4c6fdd3abbdd140f74aef0e6f5cdd26a95b2d7a28d8189f86daf248cf304e5`).
The old notebook imports `ResultManifest` from `research.experiments`; that type
now belongs to `research.studies`, so installing current `main` is not a compatible
reproduction environment. The commands below refer to the original filename in
that historical checkout, with its pinned notebook kernel and retained input files.

## Frozen source evidence

Binance and Tardis are deprioritised. These instructions preserve reproduction
of P1; they are not a requirement to obtain provider records or contact either
provider. If the deferred investigation is resumed, use its recorded
checkout/environment and the historical commands below. The maintained current
notebooks follow the current package exports.

The default paths name the retained acquisition
`data/binance-archives/runs/acb948277201cc169d32c2bb874fb40ce9e9c33c893e56a992faa47853147f80/manifest.json`,
its `data/binance-archives/raw/` store, and
`logs/frozen-baseline/2026-09-22/source-evidence/archive-capture.json`.
These ignored inputs are local; a clean checkout does not contain them. Supply
explicit paths using `ALPHA_P1_MANIFEST`, `ALPHA_P1_RAW` and `ALPHA_P1_CAPTURE`
when reopening retained inputs elsewhere. A nonempty missing selector fails.
Set `ALPHA_P1_CAPTURE=''` deliberately for an archive-only investigation. The
notebook verifies the frozen archive/configuration digests, source, instrument,
interval and capture binding. It never selects a latest run or substitutes a
fixture.

Each execution creates an exclusive `data/notebooks/p1-evidence/<uuid>/` study
containing the verified archive, acquisition, both unchanged economic
configurations, supplied capture/eligibility, source summary, measured
trading-status/coverage/correction checks, public source records and receipts,
the actual strict publication report, document review, semantic hash inventory
and `handoff.json`/`handoff.md`. Restart from setup to repeat cells that retain
immutable outputs. The existing notebook runner archives successful and failed
executions separately.

### Investigate the three questions

The notebook performs the investigation before asking for additional records:

| Question | Executed checks | Retained output |
| --- | --- | --- |
| Could this pair trade during the hour? | Provider symbol inventory and each interval of supplied eligibility, with source facts available at the frozen sample's start | `trading-status.json` |
| Does the recording cover the hour? | Missing/repeated IDs, timestamp ordering, quiet intervals including boundaries, native disconnect markers, overlapping provider incidents and a minute-count plot | `coverage-checks.json` |
| Were trade values changed later? | Exact native/archive comparison, conflicting native versions, capture delays, late captures and the provider's published archive-update table | `correction-checks.json` |

The last cell displays a plain-language three-row summary and writes
`findings.json`, `handoff.md` and `provider-questions.md`. The questions are a
draft for remaining provider evidence; the notebook sends no message. Matching
records and missing incident reports never become a completeness guarantee.
Archive-only investigations report native measurements as unknown, not zero.

Saved mode is the default. `ALPHA_P1_PUBLIC_DIRECTORY` selects a bundle
containing `binance-public-readme.md`, `tardis-exchange.json`,
`tardis-metadata.md` and `tardis-data-faq.md`, each with its original
`.receipt.json`. The default bundle is the retained
`logs/frozen-baseline/2026-09-22/source-evidence/`. The notebook verifies source
URLs, successful HTTP status, hashes, lengths and acquisition clocks before
using these records. It preserves compressed original bytes and bounds decoding.
Missing or altered selected files fail; there is no online fallback.

From the matching historical checkout, saved reproduction uses:

```sh
uv run --frozen --no-editable python -c 'from research.experiments import ResultManifest'
ALPHA_P1_PUBLIC_MODE=saved uv run --frozen --no-sync \
  --with 'nbclient==0.10.4' --with 'nbformat==5.10.4' \
  python examples/run_notebook.py examples/research-foundations-live.ipynb \
  --kernel-python .venv/bin/python
```

The historical kernel setup supplies `ipykernel`. An explicitly resumed
investigation can select `ALPHA_P1_PUBLIC_MODE=refresh` for those four records.
Refresh permits one request per record, with a 15-second socket timeout and an
8 MiB raw/decoded byte limit. It
retains failures and stops, and does not purchase data, use credentials,
download the archive again or change the frozen sample. Each successful response
and its actual receipt is copied under the new study's `public/`. A new retrieval
does not establish when a fact was known during the historical hour.

To reproduce an earlier study, keep saved mode, set `ALPHA_P1_PUBLIC_DIRECTORY`
to its exact `public/` directory and `ALPHA_P1_REOPEN` to the study directory.
The notebook prints both paths. Refreshing again creates a
new investigation because retrieval records change.

To add evidence, copy the generated `review-template.json` to a separate
working file. Keep its exact `scope`, and add objects to `documents` with:

- `requirement`: `historical_eligibility`, `coverage` or `revisions`;
- `path`: an absolute path to a retained provider record;
- `source_reference`: provider provenance or reference;
- `claim`: the precise fact and interval the record supports;
- `limitations`: what remains unproven.

Set `ALPHA_P1_DOCUMENTS` to that working file and rerun. At most 20 documents,
each at most 8 MiB, are copied and hashed. They remain candidate evidence
requiring review; no attachment or authored status upgrades quality. If actual
historical eligibility evidence is available, provide its existing typed
`EligibilityAssertions` JSON through `ALPHA_P1_ELIGIBILITY`. Otherwise the
notebook passes an empty history, preserving unknown eligibility.

Run with the pinned tooling command above. To verify reproduction, restart
through the runner with `ALPHA_P1_REOPEN` set to the exact earlier study. It
verifies the earlier retained bytes and compares deterministic input, code,
configuration and quality digests. Changing inputs or notebook source is a new
investigation and fails this reproduction comparison. UUIDs and execution clocks
are excluded from semantic comparison.

Strict publication currently refuses the source: historical eligibility and
positive coverage/complete revision evidence remain unresolved. The shared
strict contract accepts a completed externally reviewed `SourceQualification`
inside a `DatasetInput`; supply that JSON through `ALPHA_P1_ADMISSION_INPUT` and
retain every referenced current/prior archive under `ALPHA_P1_RAW`. The primary
acquisition and causal policy must match the frozen selection exactly. Optional
separate eligibility must agree with the input's embedded history. See the
[contract and preparation requirements](../../src/market_data/README.md#reviewed-provider-qualification).
The notebook records the complete input and original payload identities without
filling unknown clocks. Hash verification cannot authenticate provider claims.

Expected source refusal completes the evidence handoff with an open P1 acceptance
status, without running economics. P1 remains deferred and unaccepted. The
current baseline specification is the separate [saved-OKX simulation
scope](saved-baseline-acceptance.md). A completed notebook is not empirical
acceptance. Unexpected input/runtime errors fail the run. The legacy handoff
records remaining source investigation, external provider review, and subsequent
actual-source economic/report/recovery proof only for an explicitly resumed P1
case. It does not change the frozen sample or its acceptance standard; those
actions remain deferred.
