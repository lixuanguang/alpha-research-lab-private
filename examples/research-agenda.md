# Ranked research agenda

Owner: repository founder. Research design refreshed 2026-09-23 from the supplied
notes. Status: planned, not started; none carries a profitability claim.
[Start with the workbooks](README.md).

All studies start after the complete infrastructure is accepted at MR17/G5.
The [research delivery milestones](../docs/roadmap/research-program.md#post-infrastructure-research-milestones)
own readiness, reproducible strategy delivery and decisions. This agenda owns
the questions to select, not a parallel infrastructure backlog.

The objective is to find at least one implementable after-cost edge, or establish
why the current opportunity set does not justify further investment. Start with
one execution venue and one product. A second venue can supply information
without becoming an execution venue. Compare a small fixed horizon grid, such
as 250 ms, 1 s, 5 s, 30 s and 120 s, without assuming the fastest are tradeable.

## P0: Where is research economically justified?

These questions own the [opportunity map](opportunity-map.ipynb). Resolve them
before selecting a strategy family; revisit them when the feed, costs or stack
changes.

| ID | Research question | Decision |
| --- | --- | --- |
| A1 | Which venue–instrument–horizon combinations move enough relative to executable spread, fees and slippage? | Allocate research effort |
| A2 | How much potential edge remains after observation, decision, submission and cancellation delays? | Identify accessible horizons |
| A3 | How do tick size, spread in ticks, depth and update frequency change the opportunity? | Choose direction, spread capture or slower dislocations |
| A4 | Do effects survive exclusion of stale books, gaps, resynchronizations, asynchronous updates and ambiguous timestamps? | Separate behavior from data artifacts |
| A5 | At what size does expected net profit disappear, and is remaining capacity meaningful against capital and operating costs? | Continue, narrow or reject on capacity |
| A6 | Are there enough independent days and liquidity, volatility, fee and feed regimes? | Proceed, collect data or restrict the claim |

Map **venue × instrument × horizon × execution style × size × latency scenario**.
Show coverage, spread/depth and movement distributions, estimated cost, event
frequency and delay sensitivity. Unconditional movement is a feasibility screen,
not a selectable trade or an estimate of attainable profit.

For a completed long round trip in a consistent quote currency:

\[
\Pi_{net}=q(P_{exit,sell}-P_{entry,buy})-fees-financing.
\]

Use executable or explicitly modeled prices. If prices include spread and
slippage, do not subtract those costs again. Keep current-account fee scenarios
separate from historical product/account schedules, rebates, funding and borrowing.

## P1: Which local book states change a decision?

Combine these into the taking and shock studies. Evaluate a signal as an entry,
a quote adjustment and a reason to abstain.

| ID | Research question | Possible use |
| --- | --- | --- |
| B1 | Does depth imbalance predict future changes beyond spread and recent returns at feasible delay? | Direction, quote skew or veto |
| B2 | Does recent order-flow imbalance predict subsequent returns, rather than explain a completed move? | Continuation or adverse-selection avoidance |
| B3 | Does the size-weighted best-quote midpoint improve on ordinary midpoint and recent-price baselines? | Simple fair value |
| B4 | Does deeper-book shape add value beyond best quotes: depth, slope, gaps or asymmetry at fixed basis-point distances? | Incremental forecasts or fragility filter |
| B5 | After displayed liquidity disappears, does already-observed replenishment distinguish reversal from continuation? | Conditional shock policy |
| B6 | Are imbalances that persisted before the decision more useful than brief ones? | Transient-liquidity filter |
| B7 | When recent returns and current pressure disagree, which predicts subsequent executable returns? | Momentum versus reversal |
| B8 | Can book state predict widening spreads, volatility bursts or liquidity deterioration better than direction? | Withdraw, reduce positions or abstain |

For a depth baseline, define the levels or fixed distance in advance:

\[
I_k(t)=\frac{\sum_{i=1}^k Q^b_i(t)-\sum_{i=1}^k Q^a_i(t)}
{\sum_{i=1}^k Q^b_i(t)+\sum_{i=1}^k Q^a_i(t)}.
\]

Specify missing/zero-depth treatment. Aggregate L2 reductions do not identify
individual cancellations, executions or queue priority. OFI from published
updates describes that feed, not a complete matching-engine event history.
Record channel aggregation, truncation and clocks.

## P1: Can the signal be monetized?

Execution research runs alongside signal work. Public trades and own-order
lifecycle records become necessary inputs for passive calibration.

| ID | Research question | Decision |
| --- | --- | --- |
| C1 | Given state, quote distance, size and placement time, what is the probability of filling before an adverse move or timeout? | Whether and where to post |
| C2 | What is the subsequent price move conditional on our order actually filling? | Measure adverse selection |
| C3 | For the same signal, when should we take, post or do nothing? | Choose an action |
| C4 | Does cancellation or repricing improve value after delay, missed fills and lost priority? | Quote management |
| C5 | How should inventory change quote price, size and willingness to trade on each side? | Bound exposure |
| C6 | Which exit preserves value: fixed horizon, signal decay/reversal, inventory threshold or a specified combination? | Complete the policy |
| C7 | How do size, depth participation and simultaneous orders affect execution quality? | Sizing and capacity |
| C8 | Does profitability survive plausible queue, partial-fill, cancellation and latency models? | Whether a passive experiment is justified |

Estimate passive outcomes **conditional on filling**, not just on the signal.
Include non-fills, partial fills, cancellations in flight, inventory and unwind
costs. Public replay screens hypotheses. Before scaling, calibrate against the
firm's genuine orders under the applicable operating authorization. If plausible
fill assumptions change the sign, the strategy remains unvalidated.

## First three MVP candidates

Use common data, evaluation periods, cost assumptions and risk budgets where
applicable. Test alternatives without presuming a winning execution style.

| Candidate | Core experiment | Comparisons | Reject or narrow when |
| --- | --- | --- | --- |
| [Selective liquidity-taking](liquidity-taking.ipynb) | Persistent pressure pays for delayed aggressive entry and exit; B1/B2/B4/B7 | No-trade, recent returns, imbalance, linear model, then tree challenger | Feasible delay erases value, capacity is negligible, or tiny subsets require repeated tuning |
| [Replenishment-conditioned shocks](liquidity-shocks.ipynb) | Observed replenishment separates temporary dislocation from repricing; B5–B8 | Matched reversal, continuation and abstention on the same shocks | Future-defined events, recovery before entry, gaps or a few episodes drive the result |
| [Cross-venue information, one execution venue](#p1p2-does-another-market-add-incremental-value) | The other venue improves local decisions with then-available observations; D1–D3 | Strong local-only model on matched opportunities, costs, capital and periods | Availability alignment, staleness or quote-currency differences explain the apparent edge |

Use candidate 1 as the economic baseline, candidate 2 as the focused alternative,
and candidate 3 as an information extension, without trading both venues.
[Selective liquidity provision](liquidity-provision.ipynb), B8/C1–C8, is a later
candidate: compare a constrained passive baseline with toxicity filters, skew and
inventory adjustments separately. Reject or defer if favorable fill assumptions,
hidden inventory risk or absent calibration drive the gains. A linear model is a
sensible first fitted comparator, not a requirement for every experiment.

## P0/P1 throughout: Is the result credible and useful?

Constrain every comparison from the start. The [study protocol](study-protocol.md)
translates these questions into a study record.

| ID | Research question | Decision |
| --- | --- | --- |
| E1 | What incremental economic value does each model add over imbalance, recent returns and linear/logistic baselines? | Justify complexity |
| E2 | Which target supports the action: direction, executable return, quantiles, fill probability or conditional post-fill loss? | Choose the objective |
| E3 | Which representations transfer across prices, ticks, volatility, instruments and venues? | Bound expansion claims |
| E4 | Are predictions calibrated, especially in the selected trading region? | Set confidence and abstention |
| E5 | Does chronological testing exclude feature, label, normalization and cross-market timing leakage? | Establish credible OOS evidence |
| E6 | Does evidence survive accounting for all tested features, horizons, thresholds, instruments and models? | Address selection bias |
| E7 | Is profit broad or concentrated in a few events, directional exposure, financing or rare inventory losses? | Understand risk |
| E8 | Which observable changes require reduced size, a stop or revalidation? | Define failure conditions |

Progress from hand-specified rules to linear/logistic models, then a tree
challenger. A sequence model needs an identified limitation of simpler models.
Use chronological splits, separation of overlapping information intervals,
past-only fitting and complete trial history. Assess independent days and
uncertainty that respects dependence; correlated updates are not independent
strategy outcomes.

## P1/P2: Does another market add incremental value?

D1–D3 support the third MVP candidate when receipt alignment and comparable
instruments are available. D4–D6 remain later expansion questions.

| ID | Research question | Decision |
| --- | --- | --- |
| D1 | Does one venue's price or pressure predict another's executable prices when aligned by local receipt? | Observable lead–lag |
| D2 | Does another venue improve entry, cancellation or quote skew beyond a strong local-only model? | Add information to one execution venue |
| D3 | Are discrepancies opportunities or quote-currency, financing, contract and venue effects? | Specify fair relative value |
| D4 | Does two-venue trading survive prefunding, asymmetric fills, hedge delay, inventory limits and rebalancing costs? | Add a second execution venue |
| D5 | Does spot–perpetual dislocation predict convergence after funding, specifications, financing and both executable legs? | Investigate basis |
| D6 | Do related assets exhibit lead–lag or residual reversion after changing hedge ratios and both-leg costs? | Cross-asset relative value |

Prioritize D2 before D4. Join using what the local process had received at the
decision, with staleness limits and clock uncertainty. Sequential captures are
not synchronized observations. USD, USDT and other quote currencies remain
distinct. Match local-only and augmented models on decision times, capital,
execution assumptions and test periods.

## Expansion only for a demonstrated limitation

| ID | Addition | Research question |
| --- | --- | --- |
| F1 | Public trades — first data addition | Does signed trade flow add predictive or execution value, especially when it disagrees with displayed depth? |
| F2 | Funding, open interest, liquidations | Can publication-timed observations separate persistent pressure from exhaustion? |
| F3 | Order-level data | Do identities and lifetimes improve fill, persistence or adverse-selection estimates within the feed's actual coverage? |
| F4 | News, macro, on-chain | Do available-at-decision observations explain slower returns missing from L2? |
| F5 | More crypto instruments | Does the mechanism diversify after liquidity constraints and hedge costs? |
| F6 | Listed futures and equities | What transfers after sessions, auctions, ticks, financing, trading rules and data costs are redesigned? |
| F7 | Options | Does book information improve volatility-relative-value or execution after Greeks, hedges and multi-leg costs? |
| F8 | FX and fixed income | Which questions should use executable quotes, RFQs, credit constraints and hedging on the chosen venue? |

The reusable outcome is a research and decision process. Transfer of a feature
tensor, fitted model or execution assumption is a hypothesis to test.

## Source assumptions to establish for each study

Record a dated source/account reference for channel cadence and depth, update
and snapshot semantics, coverage, source/receipt timestamps, fees and product
specification. Keep current fee scenarios separate from historical backtests.
The supplied notes' vendor facts are context, not verified settings for these
unrun studies. Use the [source catalog](../docs/data_source/README.md) and retained
metadata to establish the actual sample.
