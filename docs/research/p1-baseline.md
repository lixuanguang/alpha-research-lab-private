# P1 bounded baseline specification

Owner: repository founder. Frozen specification date: 2026-09-11; source amendment:
2026-09-15. Experiment ID: `p1-btcusdt-return-v1`. Raw acquisition and exploratory
dataset publication are implemented; empirical causal acceptance remains open.
This page owns the sample, timing, economic assumptions and acceptance criteria.

**Priority clarification, 2026-09-23:** the founder has deprioritised Binance and
Tardis. Empirical acceptance of this legacy case is **deferred and unaccepted**.
Preserve its specification, source bytes and results; do not pursue additional
provider records or outreach as a required next step. The existing OKX order-book
and Bitfinex workflows can proceed independently. The conditional requirements
below describe what this particular frozen case would need if explicitly resumed.

**Milestone scope amendment, 2026-09-23:** the founder subsequently authorized
[replacement MR8 acceptance](saved-baseline-acceptance.md) on saved OKX L2 data.
That revision changes the milestone, not this experiment, its parameters or its
results. References below to closing MR8 describe the superseded P1 milestone
target; the frozen P1 acceptance requirements remain binding only for P1.

The [saved-source verification record](#saved-source-verification) records the
2026-09-21/22 acceptance attempt and the exact evidence still needed. The frozen
economics now have explicit [momentum](../../configs/backtests/p1-btcusdt-return-v1.json)
and [no-trade](../../configs/backtests/p1-btcusdt-no-trade-v1.json) configurations
for the existing `applications.backtest.run_backtest` consumer. These unchanged `BacktestSpec` inputs can be embedded in the explicit
[engineering-sample configuration](../../src/research/experiments/README.md#unfitted-engineering-samples)
for `alpha-backtest run`; no validation or holdout window is invented.

The selected source is Binance public spot-trade archives, authorized before any
comparative strategy result. The source policy, exact arithmetic and chronological
ordering below participate in future run identities. Earlier synthetic Tardis
fixtures retain their own source assumptions and prove software behavior only.
BTCUSDT, 2024-06-01 00:00–01:00 UTC and the strategy/economic conventions stay fixed.

The founder selected `data/binance-archives/` for the local working copy and
explicitly requested that downloaded contents be ignored by Git. No data purchase,
account credential, trading access or capital use is involved.

## QR handoff to finish MR 8

If this deferred case is explicitly resumed, its remaining QR task is to qualify
the saved data for **Binance BTCUSDT,
1 June 2024, 00:00–01:00 UTC**. Keep that sample and the frozen strategy unchanged.
The software is implemented; the missing items are source facts. They are not a
requirement to contact Binance or Tardis or to continue prioritising these sources:

| QR must provide | In simple terms | Useful supporting records |
| --- | --- | --- |
| Historical trading status and reference information | Show that this pair was available to trade throughout this hour, and when the relevant instrument information became available. | Dated exchange/provider instrument records and any status changes covering the hour. Today's listing or the original listing announcement alone is insufficient. |
| Evidence that the recording covers the whole hour | Establish whether trades could be missing because of a recording outage or an incomplete export. | Provider coverage/completeness records, recorder health logs, or an equivalent documented guarantee applicable to this exact interval. Two matching files and no reported outage alone do not establish completeness. |
| Original records and later corrections | Establish which trade values were available then, whether relevant values were corrected later, and when each correction became available. | Original captured records plus a complete applicable correction history, or a provider statement establishing that no relevant corrections occurred. No conflicts in the downloaded files alone is insufficient. |

For each item, retain the actual supporting files, their source URLs or provider
references, retrieval times, and the dates/instrument they cover. Attach them to
the existing [P1 evidence notebook](../../examples/research-foundations-live.ipynb)
using its [handoff instructions](../../examples/notebook-operations.md#frozen-source-evidence).
The notebook's investigation cells check the saved trade stream and provider records,
display the three findings, and write a draft `provider-questions.md` for facts still
missing. It can explicitly refresh four public records or reproduce an earlier
investigation offline; neither path changes the strict admission requirements.
State unresolved facts plainly; do not fill them with guessed timestamps or
assumed trading status. The existing 27,480 matched trades and recorder timestamps
can be reused; QR does not need to repeat that comparison merely to produce a new
handoff.

After QR supplies the evidence, engineering must validate its applicability,
admit the saved sample, run the unchanged strategy and no-trade control through
the installed package, and retain the report showing cash, holdings, fees and
P&L. A fresh run and an interrupted/resumed run must reproduce the results.
QR reviews the report's assumptions and remaining limitations. These actual-data
execution and reproduction results are still needed to accept P1, independently
of the revised MR8 milestone.

**A profitable result is not required.** A new strategy, parameter search or new
backtester is not required. If the source cannot supply the missing facts, QR
should report that limitation; changing the sample or relaxing the frozen
acceptance rule is a separate founder decision. The newer ETH order-book example
does not replace this BTC trade-data acceptance.

## Source, rights and historical scope

| Item | Frozen selection or explicit unresolved status |
| --- | --- |
| Provider / access method | Binance public daily spot **individual `trades`** archive at `data.binance.vision/data/spot/daily/trades/BTCUSDT/BTCUSDT-trades-2024-06-01.zip` and its `.CHECKSUM`; source ID `binance.archive.spot`. No aggregation or kline substitution. |
| Raw sample | Research selection is the half-open **exchange-event** interval `[2024-06-01T00:00:00Z, 2024-06-01T01:00:00Z)`. Download one complete UTC-day ZIP covering June 1; retain its exact bytes, including rows outside the hour. Future readers filter explicitly while preserving archive row positions. |
| Source access | Founder-authorized public archive download, without an API key. The installed acquisition path validates exact publisher SHA-256, ZIP member/CRC and compressed/expanded bounds before publication. |
| Use and retention | Private offline engineering/research. User-selected ignored `data/binance-archives/` contains raw ZIP objects, immutable run inputs, manifests and attempt logs. This working copy has no automatic expiry; a long-term retention entitlement or redistribution permission has not been established. No raw archive is committed. |
| Access reference | `binance-public-data-2026-09-15-private-research` binds the founder's explicit source/use selection to the public archive documentation reviewed on that date. This is an access/use record, not a Tardis entitlement or automated legal conclusion. The code repository's MIT license is not treated as a separate raw-data license. |
| Universe | One cash-funded, unlevered Binance spot instrument: BTCUSDT, canonical ID `11111111-1111-4111-8111-111111111111`. ETHUSDT remains supported by the foundations but is outside this case. No cross-sectional or survivor ranking. |
| Eligibility evidence | Unresolved. The authored catalog was recorded in 2026 and cannot prove what was known in 2024. Eligibility histories preserve separate evidence-backed valid/knowledge intervals; unknown eligibility cannot become eligible. Synthetic eligibility may exercise software only. |
| Reference inputs | Use the [archive-bound authored catalog](../../configs/reference/binance-archive-spot.json), schema `1`, recorded at `2026-09-15T09:44:05Z`, with coverage `[2024-06-01, 2024-06-02)` UTC. Do not backdate or relabel its `research_assumption` basis. |

Binance documents seven columns for individual trades: trade ID, price, quantity,
quote quantity, time, buyer-maker flag and best-match flag. The file is CSV inside
ZIP. Daily/monthly archives and SHA-256 sidecars are publicly downloadable. Spot
timestamps from 2025-01-01 use microseconds; the selected 2024 sample uses
milliseconds, checked against actual bytes in the notebook. Archives can be
updated later, so the observed checksum identifies retained bytes, not their
historical publication or correction availability.
[Binance public archive documentation](https://github.com/binance/binance-public-data)
(read 2026-09-15), [Binance historical-data guide](https://www.binance.com/en/academy/articles/how-to-get-trading-data-via-the-binance-api).

The original Tardis catalog remains unchanged for synthetic fixtures, identity
`3125723d3760b4a35238b75a493e1d1e2a6956c66566ac7231c35a0afb59bad6`.
The new catalog changes source binding and records the amendment without changing
canonical listing IDs or economic assumptions. Acquisition resolves the entire
selected interval before I/O. Quantity rules below remain experiment assumptions;
the catalog has no lot field.

## Time, revisions and coverage

Preserve the distinction between [event, receipt and knowledge clocks](../data/point-in-time-semantics.md).
Binance archive `time` is exchange trade event time. The archive has **no recorder
capture timestamp or historical receipt/knowledge timestamp**. Source policy
`exchange-time-only-v1` records this absence; never fabricate a Tardis prefix or
use the local download clock as availability during 2024. Local receipt and
durable ingestion occur at acquisition and are preserved on rebuild/repeat.

Later exploratory simulation may use the explicitly labeled
`event-time-assumption-v1` policy, assuming availability at exchange event time.
That is a research assumption, not evidence of historical knowability or an
empirically causal baseline. Archive-row decoding preserves absent-source-clock provenance; cutoff selection
preserves availability. Neither source fact is established by this
acquisition amendment. Existing synthetic Tardis decoders retain `source_capture`
semantics for their own inputs.

Decoder revision `0` is a local initial version, not proof of a vendor revision
history. Source revision availability is unresolved. Keep raw versions and
occurrence identities `(archive partition, raw digest, zero-based CSV row position)`;
deduplicate economically by source/venue/instrument/stream/trade ID. Exact
duplicates contribute once while retaining lineage. Conflicting payloads need
justified revision order and correction availability or fail publication.
Under an evidenced availability policy, effective knowledge is no earlier than
original source availability and any correction's availability. Unknown revision history cannot establish a historical causal
claim. Do not use today's corrected projection for past decisions.

Order eligible records by effective knowledge, fixed source/stream precedence,
partition start and source-local row position under the
[shared ordering contract](../data/point-in-time-semantics.md#chronological-ordering-and-event-stepping).
The selected case has one source/stream. Reconcile raw versions before ordering;
unresolved competing versions fail admission. Raw digests and digest-derived
occurrence identities retain provenance and do not break economic ties.
Filter by knowledge before choosing a revision. At equal simulation times,
admit source events in that order, expire old intents, apply any still-eligible
pending fill, evaluate a scheduled decision, then mark NAV. Half-open intent
expiry prevents a fill at its expiry time; a new decision cannot fill immediately.

Missing archives, corrupt bytes, unresolved conflicts or required unknown
eligibility fail publication. Successful SHA/CRC checks establish byte integrity,
not complete trade coverage. Archives contain no Tardis disconnect markers;
absence of a row is not evidence that capture was continuous. Empty/stale
observation windows remain missing; never pad prices or returns. The saved-row reader must
report missing objects, invalid CSV and unavailable recorder-gap evidence
explicitly. Partition validation owns coverage acceptance for the declared use.

A gap evidenced and known at the cutoff invalidates an overlapping observation
window and cancels a pending intent then. Later-discovered gaps do not rewrite
prior decisions; the report retains coverage limits and cannot claim uninterrupted
empirical acceptance. The existing synthetic Tardis blank-marker cases continue
to exercise gap handling but do not establish Binance archive coverage.
No-trade does not waive required dataset quality.

## Observations, hypothesis and targets

| Convention | Fixed value and behavior |
| --- | --- |
| Strategy / control IDs | `p1-btcusdt-return-v1` and `p1-btcusdt-no-trade-v1`; deterministic, recorded seed `0`, no random draws. |
| Cadence | UTC minute boundaries from `00:01` through `00:59`; no new decision at `01:00`. The first possible valid signal is `00:02`, using only this sample for warm-up. |
| Completed observation | For a close `t`, use source event time in `[t-60s, t)` and effective knowledge `<= t`. Select the latest event time, breaking ties with the total order above. Freeze that observation at its own close; later arrival/correction cannot revise it. |
| Age / lookback | Require a positive price and event age `0 < t - ts_event <= 30s` at each close. The return needs two adjacent valid completed observations, so its information window spans 120 seconds and its return lookback is 60 seconds. |
| Hypothesis | The preceding completed one-minute price increase may continue over the next decision interval. This is a transparent internal engineering hypothesis, not a published replication or an established alpha claim. |
| Rule | At decision `t`, compare `P_t` with the frozen `P_(t-60s)`: target `0.00100 BTC` if greater, otherwise zero. A reported return is the exact reduced rational `P_t / P_(t-60s) - 1`, serialized as integer numerator/denominator strings; sign selection needs no division. |
| Invalid input | Warm-up, zero/negative price, missing, stale or known-gapped observations produce no new intent with an explicit reason; holdings remain unchanged. They are not a zero-return signal. |
| Position / capital | Initial cash `1000.00000000 USDT`, zero BTC; target and maximum holding `0.00100 BTC`. Zero and negative signals target flat. No-trade always targets zero through the same costs/accounting. |
| Quantity / price grids | `QuantityKind.BASE_UNIT`; lot `0.00001 BTC`, minimum positive quantity one lot, and tick `0.01 USDT/BTC`. Reject off-grid targets and nonpositive/off-tick reference prices; do not silently resize. No additional venue minimum-notional rule is claimed. |
| Currency | Use the catalog's exact USDT quantum `0.00000001`. No USD/USDT conversion, borrowing, leverage, shorting, derivatives or other cashflows. |
| Intent horizon | An intent expires at `min(t+60s, sample_end)`; expiration does not liquidate an existing holding. Holdings can persist across positive signals or unavailable decisions. |
| Pending / rejection | One outstanding intent. Skip new intents while it is pending; compute the delta from actual holdings. Cancel on a newly known gap, expire without a valid price, and reject insufficient cash or overselling without partial fills, deposits or resizing. Record the reason. |

## Simulated fills, costs and closing treatment

Use the first subsequent eligible trade in the total order whose event time
and effective knowledge are both at least `decision_time + 1s`. Its fill clock
is the later of those two times and must be strictly before intent expiry.
Require event age at fill `<= 30s`, no known gap since the decision, and supported
eligibility at fill. Accept the complete target delta at that reference price
with the adverse cost below. Source trade quantity does not establish available
liquidity, and trade prints do not establish spread or queue priority.

Add one tick (`0.01 USDT/BTC`) to a buy reference price and subtract one tick
from a sell reference price. Reject a nonpositive effective price. Fee rate is
`0.001` of absolute effective fill notional, charged in USDT on both sides,
with no rebates or third-currency discounts. Compute exact notional with C03
`Price.amount(Quantity)` and round each fee once to `0.00000001 USDT` using
`Rounding.HALF_EVEN`. Preserve exact notional and valuation products; do not
silently round them to a display format. These are fixed simulation assumptions,
not a Binance fee schedule or calibrated execution cost.

Cash decreases by buy notional plus fee; it increases by sell notional minus
fee. Cost basis uses effective purchase notional excluding fees. Recognize all
fees immediately as separate costs; proportionally release basis on a partial
sale using rational internal attribution under the
[arithmetic contract](../architecture/financial-units.md#planned-research-and-accounting-arithmetic).
Retain basis and realized/unrealized P&L as currency-bearing rational values;
cash, quantities, notional and marks remain exact C03 values. Do not force a
nonterminating basis allocation onto the C03 grid. Realized effective-price P&L
plus unrealized effective-price P&L minus fees reconciles to NAV change. Reference-price gross
P&L for the same accepted quantities minus adverse slippage and fees must give
the same net result; do not subtract slippage twice. Financing is inapplicable
for this cash-funded unlevered spot case. Cash earns no interest.

At `01:00`, expire pending intents and keep any open BTC position. Mark it with
the latest then-known, eligible, positive trade before sample end, using the
event-time tie rule above and maximum event age 30 seconds. A known gap since
the mark invalidates it. Missing/stale marks invalidate open-position NAV;
never synthesize a liquidation. Flat NAV is cash and needs no price, while the
report still carries dataset coverage failures. The decision horizon is one
minute; actual holding duration is determined by targets, fills and this terminal
marking rule, not capped by forced one-minute liquidation.

### Intent outcomes and run completion

Expected risk rejections, including insufficient cash or overselling, produce
no accepted fill and leave cash/holdings unchanged. Record the intent and reason
in the trace/report and continue under the pending-intent policy. Such a
rejection does not by itself invalidate an otherwise complete, reconciled run.
An applied disallowed fill, broken invariant, incompatible required input or
incomplete required valuation prevents successful completion. A rejection-count
or category threshold can affect acceptance only through an explicit predeclared
evaluation rule; P1 adds no such threshold here.

Keep intent rejection, computational/accounting completion and frozen-baseline
acceptance separate. Baseline acceptance additionally requires the declared
source, causality, coverage and reproduction evidence. A synthetic price-rise
case that makes a proposed fill unaffordable must retain the rejection, zero
fills and unchanged balances in a completed result when all other required
conditions pass. This tests correct enforcement without changing the strategy,
resizing the intent or claiming permitted-source acceptance.

## Independent hand ledger

Retain this independent example
unchanged: arbitrary instrument/currency with quantum `0.01`, initial cash
`1000.00`, quantity `2`, fee rate `0.001`, reference prices `100.00`/`110.00`,
and adverse price cost `0.50` per unit. This separate oracle uses **half-up**
fees; it is not the selected BTC quantity, USDT quantum or half-even cost policy.
C03 does not currently expose half-up rounding. The notebook calculated oracle
fees explicitly with Decimal; the planned cost engine must preserve this distinction.
Add the distinguishing tie `0.205` at quantum `0.01`: half-up is `0.21`,
half-even is `0.20`. The existing fees `0.201` and `0.219` do not distinguish
those modes; preserve the existing hand ledger alongside the new tie case.

| Event | Cash change | Cash | Holding | Reconciliation |
| --- | --- | --- | --- | --- |
| Start / no-trade | `0.00` | `1000.00` | `0` | NAV `1000.00`; no-trade turnover, costs and P&L are zero |
| Buy 2 at 100.50, fee 0.20 | `-201.20` | `798.80` | `2` | Basis excluding fee `201.00`; at mark 105, unrealized `9.00`, net `8.80`, NAV `1008.80` |
| Sell 2 at 109.50, fee 0.22 | `+218.78` | `1017.58` | `0` | Realized before fees `18.00`; fees `0.42`; net `17.58` |
| Reference attribution | — | — | — | Gross `20.00` - slippage `2.00` - fees `0.42` = net `17.58` |

Retained [foundation arithmetic golden](../../tests/unit/financial_units/test_p1_hand_ledger.py)
checks these Money/Price operations. It does not establish ledger transitions by itself. The independent
[accounting consumer tests](../../tests/unit/accounting/test_ledger.py) now exercise
those exact values through identified fills, duplicate rejection, rational basis,
explicit rounding and restart state. The [spot workflow](../../src/simulation/README.md)
implements these economics on synthetic saved inputs; frozen empirical acceptance
remains open.

## Acceptance and research discipline

The specification fixes scope and assumptions; it does not complete data
feasibility or baseline acceptance. Actual endpoint/framing/timestamp/retention
feasibility, historical eligibility, coverage and revision availability each need
their applicable evidence. The [baseline delivery](../roadmap/README.md#frozen-baseline-acceptance)
owns assembled saved-source and fresh-process acceptance. Investigate missing source
evidence early; successful download cannot establish historical knowability.
Absent evidence leaves the empirical causal baseline incomplete even when archive
acquisition or assumed-availability research works.

The selected hour is an engineering sample, not a validation or final holdout.
No parameters are fitted, so train-only fitting, purge and embargo are currently
inapplicable. No training/validation/holdout intervals are designated or consumed.
Any tuning, alternative symbol/window, or formal strategy selection first needs
a new versioned specification, recorded attempts and the
[research program's split discipline](../roadmap/research-program.md#rules-for-every-workstream).
Until the shared experiment journal exists, retain influencing attempts in the specified append-only protected
text record with the [trial fields](../roadmap/research-program.md#small-records-and-artifacts).

The engineering acceptance rule is reproducible saved-input execution plus exact
no-trade, cash/position/NAV and gross-to-net reconciliation. A negative net result
passes that engineering criterion if all causal, coverage and reproduction
requirements pass. There is no profitability threshold, strategy promotion,
capacity claim, deployment or capital authorization. Future implementation must
retain the frozen values and disclose poor results rather than tune to pass.

“Frozen P1 baseline accepted” means the assembled candidate meets every source,
causal, quality, economic and reproduction requirement above, including the
permitted-source and fresh-process proof in [baseline acceptance](../roadmap/README.md#frozen-baseline-acceptance).
The [reusable research workflow](../roadmap/README.md#research-comparison-and-extension)
separately requires comparison, EDA/replay integration and instance-isolation
acceptance. A synthetic slice or an installed development wheel establishes
neither complete outcome. Completing one does not retire the other's requirements.

## Saved-source verification

Owner: repository founder. Status at the first delivery: **acceptance open; source refusal verification
implemented**, 2026-09-22. The continuation below supersedes its software gaps. The implementation starts from main `86835ee8`. No
sample, strategy, timing, fee, rounding, size or capital parameter has changed.
The original acquisition and receipt clocks remain intact.

The actual retained daily ZIP has SHA-256
`c9c333f58fe33faaa0a34d526c61b13f5648b908c4ad341dd6556e15c5bcc46a`.
The publisher's current checksum fetched on 2026-09-21 UTC matches those bytes.
Independent ZIP/CRC and CSV inspection found 7,308,819 compressed bytes,
47,193,701 expanded bytes, 638,484 daily rows and 27,480 selected-hour rows.
All rows have seven columns; observed trade IDs are consecutive and timestamps
do not regress. These observations establish byte/row integrity, not uninterrupted
capture. The publisher sidecar's observed Last-Modified is
`2024-06-02T04:01:16Z`; it cannot establish minute-by-minute knowledge on June 1.

| Required fact | Available evidence and remaining boundary |
| --- | --- |
| Permitted retained source | Existing private-research acquisition, complete daily ZIP, original manifest and fresh matching publisher checksum are available. Long-term retention and redistribution rights remain unestablished. |
| Historical eligibility | The [official listing announcement](https://www.binance.com/en/support/announcement/detail/115001094331) announces BTC/USDT trading in August 2017. It does not establish continuous eligibility or applicable rules during the frozen hour. The 2026 authored catalog is unchanged; the acceptance input records an empty assertion history, preserving unknown membership. |
| Historical receipt/availability | The [pinned archive documentation](https://github.com/binance/binance-public-data/blob/5c7f3197591c0d54d85dc43066226bc4c671d47a/README.md) describes exchange-event timestamps and later daily publication. It supplies no recorder receipt timestamp for the selected trades. Event-time availability would remain an assumption. |
| Revision availability | One retained archive and its current checksum do not establish the sequence and availability of previous economic versions. The published update listing supplies no per-trade history for this sample. |
| Coverage | Native full-file decoding and observed continuity checks cannot prove that no trade was omitted upstream. There is no retained recorder health/disconnect evidence for this hour. |
| Causal publication support | At the first delivery, `QualityPolicy` supported only degraded exploratory publication and rejected causal use. Evidence-backed causal admission needs its own concrete input contract and verification after the required source evidence is obtained; a caller-supplied completeness flag is insufficient. |
| Frozen retained economic reports | At the first delivery, MR 6's configured attempt/report path required validation and holdout windows. P1 has neither. An explicit unfitted engineering-sample representation is still needed before a qualified P1 result can use that retained workflow; inventing split windows would change the frozen specification. |

The [installed source consumer](../../tests/integration/consumers/backtest/source_acceptance.py)
exhausts the saved native reader, retains the real causal quality refusal, verifies
that rejection publishes no snapshot, and reopens a separate explicitly degraded
snapshot. It composes the existing backtest application with both frozen configs.
Unknown clocks and membership must produce no valid observations or fills; unchanged
cash is a non-admission check, **not a measured zero-return strategy result**.
The consumer does not create synthetic corrections, backdate eligibility or substitute
an event-time availability policy. A fresh invocation can reopen the first snapshot
and complete checkpoint and compare all deterministic evidence bytes.

Use an isolated installed wheel outside the checkout. Copy the consumer and both
configs there, and supply the original saved manifest and raw store explicitly:

```sh
/absolute/installed/bin/python -I /absolute/copied/source_acceptance.py \
  --manifest /absolute/saved/acquisition/manifest.json \
  --raw /absolute/saved/raw \
  --spec /absolute/copied/p1-btcusdt-return-v1.json \
  --control /absolute/copied/p1-btcusdt-no-trade-v1.json \
  --max-bytes 134217728 --output /absolute/new/attempt
```

Repeat in a fresh process with another new `--output` and
`--reopen /absolute/first/attempt`. **Exit 3** means the expected source refusal
and non-admission assertions passed while baseline acceptance stays open; an
exception means the verification itself failed. `inventory.json` appears only
after all assertions pass. Interrupted directories remain partial evidence and
must not be relabeled as successful. This manual program is not automatically
discovered by pytest and never downloads data or changes the source store.

Source documentation, checksum/headers, independent byte audit and review summary
are retained in ignored `logs/frozen-baseline/2026-09-21/source-evidence/` in the
founder's primary checkout. The direct announcement download returned empty bytes;
the separately labeled web review summary is not a retained official page capture.
The adjacent `installed-source/` directory retains the failed first invocation,
the corrected refusal check, and its fresh-process reproduction. Both corrected
processes exit 3. Their 11 deterministic artifact digests agree, and the resumed
halfway checkpoint reproduces the complete non-admission trace. The matching wheel,
runtime lock and full validation logs are retained alongside that directory.
Keep source bytes and bulky output outside Git. Original raw data remains in the
selected `data/binance-archives/` store.

Validation results are recorded in the
[roadmap acceptance attempt](../roadmap/README.md#frozen-baseline-acceptance).
Existing synthetic MR 5/6 evidence remains valid for exact accounting, delays,
recovery and report atomicity because their runtime implementations are unchanged.
It cannot fill the empirical gaps above. Reversal removes the consumer/configs and
reverts these acceptance notes together while preserving original raw data,
failed attempts, matching wheels and verification output. No deployment or trading
authority follows from this work.


## Source investigation continuation

The [QR live notebook](../../examples/research-foundations-live.ipynb) provides a
`p1-evidence` route for reopening the exact saved sample, attaching provider records,
retaining strict admission results and reproducing the evidence handoff. Follow its
[operating instructions](../../examples/notebook-operations.md#frozen-source-evidence).
Completing this source investigation does not establish economic acceptance or
change the frozen requirements below.

Owner: repository founder. Updated 2026-09-22. **MR 8 acceptance remains open.**
Continuation starts at `2c93536`; fetched `origin/main` was still `86835ee80a4f420133416d6148886b9a1fbc0150`,
already its parent. No merge or replacement PR was needed. The original ZIP,
acquisition clocks, frozen configurations and previous failed attempts remain intact.

New public evidence is retained in the primary checkout's ignored
`logs/frozen-baseline/2026-09-22/source-evidence/`. Each download has its exact URL,
HTTP headers/status, actual request/receipt clocks, byte length and SHA-256 in a
sibling `.receipt.json`. Tardis permits unauthenticated first-day-of-month native
feed access in its [HTTP API documentation](https://docs.tardis.dev/api/http-api-reference.md).
This is auxiliary evidence for the existing Binance archive, not a source or window
substitution. Private research access does not establish redistribution or indefinite
retention rights. No credential, subscription or purchase was used.

Seven complete native response slices cover recorder time `00:00–01:01 UTC` (six
ten-minute slices plus one terminal minute to inspect delayed arrivals). They contain
28,055 captured messages including boundary events. Independent exact comparison
found all **27,480 frozen-hour archive trades** with matching individual ID, exchange
event time, price, quantity and maker side; zero missing or conflicting selected
payloads. The interval's trade IDs are 3620989757–3621017236. Native receipt timestamps
supply conservative known-by times for those matched fields; they do not rewrite
archive event time or establish an original local-system receipt clock. Sub-microsecond
source capture precision is conservatively rounded upward by the existing decoder.
Archive quote quantity and best-match metadata are not covered by this comparison.
The isolated installed candidate independently verified the same 27,480 matches;
its runtime identity is `6c5a559eea3677ab7343a6175749e959e9673484cd0f0076eaf382eee205788b`.
The exact concrete capture identity is
`99db0e477bf651dadd9ff564cf8fcf4e6cca6632f3cd1d6667b284db4d280385`.
The final selected capture is `2024-06-01T01:00:00.005781+00:00`, after the
sample's end; it cannot be made available to an earlier decision. The retained
`installed-probe.json` and clock manifest identify this check. It does not publish
or run economics on the actual sample.

| Required fact | New evidence and precise consequence |
| --- | --- |
| Historical eligibility and reference availability | Tardis exchange metadata lists BTCUSDT spot data available since 2019-03-30. Its [metadata contract](https://docs.tardis.dev/api/instruments-metadata-api.md) says trading status is current and most historical changes are best-effort. Neither that listing, traded rows, nor the 2017 announcement establishes historical eligibility throughout the hour or when its reference facts became available. No inclusion assertion was authored for the actual sample. |
| Trade availability | Native captured messages corroborate all selected decision-relevant fields at their recorder timestamps. This is stronger than event-time inference, but does not establish the earliest original publication or availability of archive-only fields. |
| Corrections/revisions | No conflicting selected payload appeared in the retrieved tape. That is an observation, not an exhaustive vendor revision history. A provider record establishing original versions and publication/availability of every relevant correction is still missing. |
| Coverage/outages/omissions | No blank disconnect markers appeared. The retained incident inventory reports a June 14 outage, none overlapping this hour. These negative observations and exact archive/tape agreement do not prove uninterrupted recorder health or exclude omissions shared by both representations. Positive interval-applicable coverage evidence remains missing. |
| Rights/access | Official unauthenticated sample access and exact source URLs/receipts are retained. Existing private research scope is unchanged; long-term retention and redistribution rights remain unestablished. |

The existing [market-data owners](../../src/market_data/README.md#witnessed-archive-availability)
now support native evidence-backed **scoped** causal admission (`use="witnessed"`,
`scope="causal_witnessed"`). It requires exact native agreement, historical source
eligibility and no observed policy gap, preserves unknown completeness and unseen
revisions, and binds all evidence into version-2 publication/query/replay identities.
Original archive records remain unchanged. Strict `use="causal"` remains fail-closed;
there is no completion flag that upgrades missing evidence. Full empirical causal
admission still needs a concrete source contract for the remaining coverage/revision
facts; this scope must not be treated as satisfying that requirement.

Explicit unfitted engineering samples now use the existing configured backtest,
attempt journal, complete checkpoints, atomic costed reports and ClearML recovery.
A family cannot switch between this design and a validation/holdout design, and
engineering samples cannot consume a holdout or enter parameter comparisons.
Old inputs omit absent new fields and retain their original identities. No library
command, alternate economic runner or sibling application dependency was added.

The installed synthetic consumer uses **both unchanged frozen configurations** with
native fixture captures and explicitly hypothetical reference facts. Its independent
example buys 0.001 BTC at 111.01 (fee 0.00011101) and sells at 103.99
(fee 0.00010399): gross -0.007 minus slippage 0.00002 and fees 0.000215 equals
net **-0.007235 USDT**, final flat cash/NAV **999.99276500 USDT**. No-trade retains
1000 USDT and zero costs. These are software oracles, not measured strategy results.
The fixture cannot be attached to the actual archive. Fresh-process resume and repeat
compare complete result manifests; admission failure produces no snapshot.

The 2026-09-21 refusal output is reused only for its original state and non-admission
claim. The continuation does not rerun that unchanged actual-source economics merely
to produce another refusal. New runtime behavior requires new checks and installed
proof, recorded in the [roadmap continuation](../roadmap/README.md#frozen-baseline-continuation).
Original source integrity remains supported because its retained bytes and selection
are unchanged. Existing independent monetary/rounding oracles remain authoritative.

Remaining prerequisite: obtain historical BTCUSDT eligibility/reference availability,
positive interval coverage and complete applicable version/correction evidence tied
to these bytes and this hour. If unavailable, purchasing evidence, changing source or
window, or amending the frozen acceptance standard requires an explicit founder
decision; none was made here. Actual-source costed baseline execution and acceptance
remain unproven. Revert the continuation commit and its documentation together;
retain original data, new source responses, all attempts and matching candidate wheels.
Version-2 witnessed snapshots and engineering configurations require this candidate
or later; version-1 readers cannot read them. No deployment or trading follows.

### Executable QR investigation

The [QR notebook](../../examples/research-foundations-live.ipynb) now measures the
three handoff questions directly. Its 2026-09-22 public refresh retained four
official responses with URLs, hashes and actual retrieval times, then read the
same archive and native capture through installed decoders. The refresh replaced
no frozen input and contacted no provider representative.

Observed results: **27,480 selected trades**, IDs **3620989757–3621017236**, no
missing IDs inside that range, no repeated IDs and no event-time regressions.
The longest observed quiet interval, including the sample boundaries, was
**3.689 seconds**. The retained capture contained **28,055 messages** including
boundary events, no disconnect markers and no reported provider incident
overlapping the selected hour. All selected five-field trade values matched;
there were no extra selected native versions or conflicting native IDs.

Matched capture delays ranged from **7,984 to 153,001 microseconds**, measured
between the retained exchange event time and the conservatively decoded recorder
time. **Three selected trades were captured at or after 01:00 UTC**; the latest
capture was `01:00:00.005781`. These are recorder observations, not measured
strategy or order latency, and are not moved before the sample cutoff.

The symbol inventory begins in 2019, but no historical eligibility assertions
were supplied. The retrieved Binance update table lists two replacement bundles
dated 2022; it does not provide a per-trade historical publication/correction
timeline for this hour. The notebook retains these observations without turning
them into trading-status, completeness or full revision-history assertions.
Strict publication still refuses the sample, so **MR 8 remains open**.

Outputs include `trading-status.json`, `coverage-checks.json`,
`correction-checks.json`, a minute-count plot, a plain-language `handoff.md`, and
`provider-questions.md` containing unsent draft questions. The
[operations guide](../../examples/notebook-operations.md#investigate-the-three-questions)
explains saved/refresh modes, supporting-document attachment and offline reproduction.

Final notebook source SHA-256:
`be6038d49a2c3909c32837b70bee48197e3e7741d58ed7aa6ed62895b7331c00`.
It uses the unchanged installed runtime
`c8fcc0d9ee99b0c96fa761ef6370f5b6c60fa1bc3ef2d406623f643dd56c121f`.
Both final offline executions passed all **37 cells (20 code cells)**:
`examples/runs/research-foundations-live/c9ebfec9-3058-40d7-8463-b56e69ce864c.ipynb`
and `examples/runs/research-foundations-live/beea306b-3522-4ddb-8d36-2bf2c666b685.ipynb`.
The latter reopened
`data/notebooks/p1-evidence/175c73bd-ef3a-48a6-b0ab-cdfe7bc11958/`
and reproduced all **25 semantic artifacts byte for byte** in
`data/notebooks/p1-evidence/0f3894be-aeda-4fb7-90ad-784a4d93e792/`.
Each retained the expected refusal and published no snapshot. Attempt clocks and
the reproduction note remain separate from the deterministic evidence inventory.

The initial public refresh is retained in executed attempt
`23e1a654-3d01-465a-a74c-e7eadb0d6a8d` and study
`data/notebooks/p1-evidence/fa8aec4f-cf2a-4f9d-8f89-cd3dac2ebe4c/`.
It preceded presentation/formatting edits; the final executions reuse its exact
four response bodies and receipts, without repeating network requests. The final
chart was visually checked. Maintained notebook outputs and execution metadata
are cleared; these executed copies and source-derived files remain ignored.

Five temporary evidence-file cases checked valid compressed input and rejection
of altered bytes, a wrong source URL, reversed receipt clocks and a missing file.
A separate three-row counterexample checked missing/repeated IDs, event-time
regression, a half-open incident boundary, and unknown native measurements when
no capture is supplied. Both records are retained under
`logs/frozen-baseline/notebook-investigation/`. Notebook Ruff lint/format and
local links, including both changed example guides, passed. Runtime, dependency
and frozen economic configuration files were not changed by this notebook work.

### Strict provider admission implementation

On 2026-09-23 the missing strict coverage/revision admission path was implemented.
The [implementation report](source-qualification.md) supersedes the earlier software
limitation: `use="causal"` now accepts a fully reviewed `SourceQualification`, retains
original/revised archives and applies full-payload availability causally. The
[notebook](../../examples/research-foundations-live.ipynb) consumes the same typed
input as `alpha-dataset` through `ALPHA_P1_ADMISSION_INPUT`.

This does not supply the missing historical facts for the actual hour. **P1 remains
deferred and unaccepted** until provider review, strict actual-source admission,
unchanged costed runs, exact accounting and fresh-process economic reproduction all pass. The earlier
notebook hashes and results above describe the prior candidate; current verification
and limitations are recorded in the linked report. Frozen configuration bytes remain
unchanged.
