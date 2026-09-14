# P1 bounded baseline specification

Owner: repository founder. Status: MR 00 specification merged in
[PR 14](https://github.com/lixuanguang/alpha-research-lab-private/pull/14);
implementation and empirical acceptance remain planned. Decision date: 2026-09-11.
Experiment ID: `p1-btcusdt-return-v1`. This page owns the frozen case required by
[MR 00](../roadmap/README.md#mr-00-frozen-experiment).

Contract clarification, 2026-09-14: exact rational representation and stable
source ordering below resolve implementation gaps identified in review. The
digest-based economic tie-break is superseded before any empirical run; sample,
strategy, cash, costs and timing phases remain frozen. Retain this clarification
and the ordering/arithmetic policy versions with future run identities; MR 00's
historical evidence is not evidence of these planned consumers.

The founder explicitly selected Tardis raw Binance spot trades, BTCUSDT only,
2024-06-01 00:00–01:00 UTC, and a fixed one-minute positive-return long-or-flat
baseline, answering: “Select this bounded case; access and evidence unresolved”.
The execution and cost values below are fixed engineering conventions chosen
before any comparative result. They are not estimated venue conditions.
No source data, credentials, comparative returns or holdout were inspected in
MR 00. Public provider documentation was read to specify the access method.

## Source, rights and historical scope

| Item | Frozen selection or explicit unresolved status |
| --- | --- |
| Provider / access method | Tardis HTTP raw replay, exchange `binance`, `/v1/data-feeds/binance`; filter channel `trade`, symbol `btcusdt`; source ID `tardis.binance.spot`. No normalized CSV substitution. |
| Raw sample | Half-open capture interval `[2024-06-01T00:00:00Z, 2024-06-01T01:00:00Z)`. Exactly 60 one-minute partitions, fixed `from` at sample start and offsets 0–59, `sliceSize=1`, gzip. Preserve the exact compressed bytes and blank lines. |
| Source access | Unresolved and unprobed. No account entitlement, credential reference or authorized data-access record has been supplied. MR 05 must establish the permitted smallest probe before accessing data. |
| Use and retention | Intended use is private offline engineering/research and reproduction from retained raw/canonical bytes. Permission, retention duration, redistribution restrictions and a protected retrievable location are unresolved. No permission or indefinite retention is inferred; no data purchase or source access is authorized by this selection. |
| Rights evidence | None supplied. Before acquisition, retain a reference to the applicable dated terms/entitlement covering this interval, intended use and retention. Later request records bind that reference; an unresolved marker cannot pass source-access admission. |
| Universe | One cash-funded, unlevered Binance spot instrument: BTCUSDT, canonical ID `11111111-1111-4111-8111-111111111111`. ETHUSDT remains supported by the foundations but is outside this case. No cross-sectional or survivor ranking. |
| Eligibility evidence | Unresolved. The authored catalog was recorded in 2026 and cannot prove what was known in 2024. MRs 11–12 must preserve separate evidence-backed valid/knowledge intervals; unknown eligibility cannot become eligible. Synthetic eligibility may exercise software only. |
| Reference inputs | Reuse the complete [authored catalog](../../configs/reference/binance-spot.json), schema `1`, recorded at `2026-09-07T18:09:25Z`, with coverage `[2024-06-01, 2024-06-02)` UTC. Do not backdate or relabel its `research_assumption` basis. |

Tardis documents timestamp-prefixed exchange-native JSON, blank disconnect
markers, capture-based minute partitions, lowercase Binance symbols and gzip.
Its HTTP documentation also describes first-of-month access without an API key;
that availability statement does not resolve this experiment's rights or
authorize a probe. MR 05 must recheck the endpoint and framing against actual
permitted bytes. [Tardis HTTP API reference](https://docs.tardis.dev/api/http-api-reference.md),
[Binance capture details](https://docs.tardis.dev/historical-data-details/binance.md)
(read 2026-09-11).

The catalog's canonical identity is
`3125723d3760b4a35238b75a493e1d1e2a6956c66566ac7231c35a0afb59bad6`.
MR 01 must resolve the entire selected interval against it before I/O. Quantity
rules below are explicit experiment assumptions; the catalog has no lot field.

## Time, revisions and coverage

Preserve the [existing clocks](../data/point-in-time-semantics.md): Binance `T`
is trade event time; the original Tardis capture text and its conservative
microsecond ceiling supply source receipt and `source_capture` knowledge.
The existing decoder interprets Binance `T`/`E` as Unix milliseconds; MR 05 must
verify that the selected historical payloads match before admission. Local
receipt and durable ingestion occur at archive acquisition. Persist their
original values for rebuild; new attempt times do not replace them.

Decoder revision `0` is a local initial version, not proof of a vendor revision
history. Source revision availability is unresolved. Keep raw versions and
occurrence identities `(partition, raw digest, zero-based line position)`;
deduplicate economically by source/venue/instrument/stream/trade ID. Exact
duplicates contribute once while retaining lineage. Conflicting payloads need
justified revision order and correction availability or fail publication.
Effective knowledge is no earlier than original capture and any correction's
availability. Unknown revision history cannot establish a historical causal
claim. Do not use today's corrected projection for past decisions.

Order eligible records by effective knowledge, fixed source/stream precedence,
partition start and source-local line position under the
[shared ordering contract](../data/point-in-time-semantics.md#planned-economic-ordering-and-event-stepping).
The selected case has one source/stream. Reconcile raw versions before ordering;
unresolved competing versions fail admission. Raw digests and digest-derived
occurrence identities retain provenance and do not break economic ties.
Filter by knowledge before choosing a revision. At equal simulation times,
admit source events in that order, expire old intents, apply any still-eligible
pending fill, evaluate a scheduled decision, then mark NAV. Half-open intent
expiry prevents a fill at its expiry time; a new decision cannot fill immediately.

Missing partitions, corrupt bytes, unresolved conflicts or required unknown
eligibility fail publication. A verified empty partition is recorded silence,
not a missing object. Empty/stale observation windows remain missing; never pad
prices or returns. A blank's conservative gap runs from the preceding capture
(sample start if absent) to the next capture (sample end if absent), with the
existing next-capture/interval-end proxy as its knowledge time. A gap known at
the cutoff invalidates any overlapping observation window and cancels a pending
intent at that cutoff. Newly discovered gaps do not rewrite prior decisions;
the final report retains their coverage impact and cannot claim uninterrupted
empirical acceptance. No-trade does not waive required dataset quality.

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

Retain the roadmap's [independent example](../roadmap/README.md#independent-accounting-example)
unchanged: arbitrary instrument/currency with quantum `0.01`, initial cash
`1000.00`, quantity `2`, fee rate `0.001`, reference prices `100.00`/`110.00`,
and adverse price cost `0.50` per unit. This separate oracle uses **half-up**
fees; it is not the selected BTC quantity, USDT quantum or half-even cost policy.
C03 does not currently expose half-up rounding. The notebook calculated oracle
fees explicitly with Decimal; future MR 38 must preserve this distinction.
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
checks these Money/Price operations. It does not implement or prove the future
ledger's fill identity, duplicate rejection, state transitions or cost engine.

## Acceptance and research discipline

MR 00 completes the explicit scope, access-status record and synthetic foundation
exercise. It does not complete data feasibility or P1. MR 05 owns actual endpoint,
framing, timestamp and permitted-retention feasibility; MRs 11–12 own historical
eligibility; MRs 10, 17 own revision availability; MR 49 owns saved-source acceptance.
MR 05 also investigates whether historical eligibility and revision evidence can
be obtained for this sample, recording missing evidence early; it does not
implement those later selectors or infer knowability from a successful download.
Absent evidence leaves the empirical causal baseline incomplete even if the
synthetic engineering path works. Do not substitute another source to close it.

The selected hour is an engineering sample, not a validation or final holdout.
No parameters are fitted, so train-only fitting, purge and embargo are currently
inapplicable. No training/validation/holdout intervals are designated or consumed.
Any tuning, alternative symbol/window, or formal strategy selection first needs
a new versioned specification, recorded attempts and the
[research program's split discipline](../roadmap/research-program.md#rules-for-every-workstream).
Before MR 43, retain influencing attempts in the specified append-only protected
text record with the [trial fields](../roadmap/research-program.md#small-records-and-artifacts).

The engineering acceptance rule is reproducible saved-input execution plus exact
no-trade, cash/position/NAV and gross-to-net reconciliation. A negative net result
passes that engineering criterion if all causal, coverage and reproduction
requirements pass. There is no profitability threshold, strategy promotion,
capacity claim, deployment or capital authorization. Future implementation must
retain the frozen values and disclose poor results rather than tune to pass.

“Frozen P1 baseline accepted” means every baseline requirement in the
[P1 acceptance map](../roadmap/README.md#p1-acceptance-map)
passes for the assembled candidate, including MR 49's permitted-source and
fresh-process proof. “M5 accepted” additionally requires the reusable research,
EDA/replay and instance-isolation evidence assigned in that map and the
[milestone plan](../roadmap/README.md#m5-strategy-simulation-and-research-controls).
An early synthetic slice, MR 49 alone without its prerequisites, or an installed
development wheel establishes neither outcome. This scope clarification moves
the broader workflow requirements to M5; it does not retire them or mark them
complete.
