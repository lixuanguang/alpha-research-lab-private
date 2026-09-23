# Study protocol and decision record

Use this record for a concrete experiment from the [agenda](research-agenda.md).
Owner: the researcher conducting the study. Status: template, updated 2026-09-23.
Fill it before formal comparison; retain changes and the trials that prompted
them. The [research program](../docs/roadmap/research-program.md#rules-for-every-workstream)
owns formal methodology.

## Research ticket

| Field | Record |
| --- | --- |
| Question and agenda IDs | One economic decision and the relevant A–F questions |
| Mechanism | Why the observable state could change a subsequent outcome |
| Competing explanation | Recent returns, spread mechanics, stale data, selection, exposure or another account |
| Information set | Fields, receipt cutoff, lookbacks, warm-up, missing/stale rules and units |
| Sample | Venue, exact instrument/product/currency, historical eligibility, dates, channels and exclusions |
| Outcome | Executable return, direction, fill probability or fill-conditioned markout; clock, horizon and availability |
| Policy | Trigger, action, size, delay, entry, exit/timeout, overlapping positions, inventory and independent risk limits |
| Comparisons | Transparent rule, recent-return baseline, no-trade, ablations and model progression |
| Selection | Primary economic criterion, bounded search space, chronological splits and trial family |
| Falsification | Conditions that reject the mechanism or make it untradeable |
| Evidence needed | Retrievable inputs, code/config, trials, results and missing dependencies |

Example: after unusually large ask-side depletion, persistent bid depth predicts
positive five-second executable returns beyond recent returns. Define “large”
on training data and “persistent” from observations received before entry. Match
events, costs, size and delay. Reject if incremental OOS net value vanishes at
achievable delay or depends on invalid data.

## Time, comparisons and uncertainty

Use local receipt to bound information; retain source time separately. For every
feature and label, record the complete information interval and availability.
A future outcome labels a prior decision; it never enters its features. For
replenishment, the decision is after the condition becomes observable.

Use chronological train, validation and untouched test periods. Fit transforms,
feature selection and thresholds on past training data. Purge overlapping label
intervals and choose any embargo from actual feature, publication and execution
overlap. Select with earlier validation; freeze before final test. A consumed
test period is no longer a new holdout.

Compare a common opportunity set. Include abstentions, failed entries, partial
fills, forced exits and no-trade days. Align paired daily results by study, date
and execution scenario. Dropping hard days or non-fills changes the question.

Report net P&L per opportunity and executed trade, frequency, exposure, drawdown,
tail loss, capital use, turnover, size and delay sensitivity. State denominators
and currencies. Choose uncertainty blocks reflecting event and position
dependence; inspect day/regime concentration and account for all attempted
variants. Justify the candidate's economic and statistical acceptance criteria;
these templates impose no universal Sharpe or confidence threshold.

## Executable economics

Define entry and exit at feasible arrival times. Walk depth or state a supported
execution model; include participation limits, unfilled quantity and failed
exits. Midpoint return is a diagnostic, not a completed trading return.

Record product/account/historical fees and rebates, funding, borrowing and other
financing when applicable. Spread and slippage embedded in execution prices must
not be charged again. Separate realized P&L, marked inventory and executable
liquidation cost. Reconcile cash and positions.

For passive policies, retain placement, acknowledgment, modification,
cancellation and fill times; queue assumptions; partial fills; timeout;
inventory; markouts and unwind cost. Model filling and adverse selection jointly.
Do not vary fill rate while assuming favorable post-fill returns stay unchanged.
Include cancellation races and priority loss. Compare plausible execution
scenarios before calibration with authorized own-order observations.

## Retained evidence

Record study/config and code revision; selection and retrievable input bytes;
feed/fee/clock assumptions; splits and fitted state; all variants; predictions,
actions and economic traces; aggregation and uncertainty methods. The workbook
is an analysis surface, not the trial journal or sole storage.

The [attempt store](../src/research/experiments/README.md) and
[study reports](../src/research/studies/README.md) cover their implemented paths.
Outside those paths, keep an append-only research record with the relevant
identities. Notebook execution success is only software execution evidence.

## Decision memo

Finish with **continue**, **narrow**, **reject**, or **insufficient evidence**.
Record the result against the baseline, economic magnitude and uncertainty,
daily/regime concentration, delay/size/fill sensitivity, unresolved assumptions
and next decisive experiment. State when to stop or revisit. A deployment
proposal identifies the frozen policy, capital/risk limits, calibration and
operational requirements; it does not itself authorize activation.
