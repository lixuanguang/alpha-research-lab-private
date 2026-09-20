# P1 bounded baseline specification

Owner: repository founder. Frozen specification date: 2026-09-11; source amendment:
2026-09-15. Experiment ID: `p1-btcusdt-return-v1`. Raw acquisition and exploratory
dataset publication are implemented; empirical causal acceptance remains open.
This page owns the sample, timing, economic assumptions and acceptance criteria.

The selected source is Binance public spot-trade archives, authorized before any
comparative strategy result. The source policy, exact arithmetic and chronological
ordering below participate in future run identities. Earlier synthetic Tardis
fixtures retain their own source assumptions and prove software behavior only.
BTCUSDT, 2024-06-01 00:00–01:00 UTC and the strategy/economic conventions stay fixed.

The founder selected `data/binance-archives/` for the local working copy and
explicitly requested that downloaded contents be ignored by Git. No data purchase,
account credential, trading access or capital use is involved.

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
