# Study protocol and decision record

Use this record for a concrete experiment from the [agenda](agenda.md).
Owner: the researcher conducting the study. Status: template.
Fill it before formal comparison; retain changes and the trials that prompted
them. The [research program](program.md#rules-for-every-workstream)
owns formal methodology.

Use this record to establish bounded offline entry for QR stages A–C, or to
document a study after full QR onboarding. Follow the
[bounded offline research policy](../roadmap/overview.md#bounded-offline-research).
G2 interface evidence alone does not accept a selected dataset or workflow.
Source inspection and bounded validation runs may establish the entry evidence
below; record it before formal comparisons and keep the study within its measured
scope. Offline admission does not qualify full-scale capacity or forward
paper/shadow operation. Link the study to the
[QR milestones and deliverables](program.md#research-milestones); an empty record,
entry validation or successfully executed worksheet completes none of them.

Before starting or resuming any study, run `make local-services-up` from the
repository root and complete the [research-session prerequisites](guide.md#before-every-research-session),
including access to lakeFS and ClearML. Keep both services running during the study.
Starting these local research services does not authorize paper or shadow activation.

## Bounded offline entry and scope

Record the actual validation evidence before formal study comparisons. The declared
scope must stay within what the evidence measured; do not use extrapolation as
acceptance. Record concrete observed limits rather than relying on universal
thresholds.

| Entry evidence | Declared scope or limit | Observed value and retained evidence reference |
| --- | --- | --- |
| Venue, product, instruments, channels/depth and UTC date windows |  |  |
| Dataset version, retrievable raw bytes/manifests, provenance, record count, coverage, quality/gaps and eligible windows |  |  |
| Replay/retrieval identity and outcome |  |  |
| Feature and label definitions/counts, cutoffs, causal/availability checks and train-only fitting where used |  |  |
| Code, environment and configuration identities; end-to-end costed workflow and execution assumptions; decisions and trial count |  |  |
| Deterministic rerun, independent cost/ledger reconciliation and no-trade control |  |  |
| Fresh-process reopen, retry/recovery and backup/restore evidence, preserving identities and results |  |  |
| Concurrent studies, peak RAM, peak disk and measured end-to-end runtime |  |  |
| Admission decision, owner/date and maximum accepted scope |  |  |

The accepted scope includes its actual instruments, dates, records, features,
decisions, trials, concurrency, RAM, disk and runtime. Keep all work within those
limits. Reuse relevant existing evidence and validate affected boundaries when
the scope changes, following the roadmap. Full capacity and forward paper/shadow
operation retain their separate qualification requirements.

## Research ticket

| Field | Record |
| --- | --- |
| Question and agenda IDs | One economic decision and the relevant A–F questions |
| Mechanism | Why the observable state could change a subsequent outcome |
| Competing explanation | Recent returns, spread mechanics, stale data, selection, exposure or another account |
| Information set | Market fields and account/order state, receipt cutoff, lookbacks, warm-up, missing/stale rules and units |
| Sample | Venue, exact instrument/product/currency, historical eligibility, dates, channels and exclusions |
| Outcome | Executable return, direction, fill probability or fill-conditioned markout; clock, horizon and availability |
| Policy | Trigger, action, size, delay, entry, exit/timeout, overlapping positions, inventory and independent risk limits |
| Comparisons | Transparent rule, recent-return baseline, no-trade, ablations and model progression |
| Selection | Primary economic criterion, bounded search space, chronological splits, final-period reservation/access history and trial family |
| Falsification | Conditions that reject the mechanism or make it untradeable |
| Evidence needed | Retrievable inputs, code/config, trials, results and missing dependencies |
| Delivery | Target QR milestone, applicable QR deliverables, implementation/test references and acceptance evidence; missing platform capabilities go to QD |

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

Record quality-flag availability. A defect discovered later may inform a declared
sample-quality diagnostic, but cannot retrospectively tell the strategy to avoid
a trade. Retain exclusion effects separately. Warm-up, stale data and recovery
must match the intended runtime. Align cross-venue inputs by local availability;
an exchange-time-only join is an idealized information study unless tradable
availability is established.

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

Retain the dataset recipe, feature/label definitions and tests, rule/model artifact,
complete strategy implementation, policy configuration, execution assumptions and
reconciled ledger. A predictor or chart alone is not a delivered prototype.

The [attempt store](../packages/research-experiments.md) and
[study reports](../packages/research-studies.md) cover their implemented paths.
Outside those paths, keep an append-only research record with the relevant
identities. Notebook execution success is only software execution evidence.

## Decision memo

Finish with **continue**, **narrow**, **reject**, or **insufficient evidence**.
Record the result against the baseline, economic magnitude and uncertainty,
daily/regime concentration, delay/size/fill sensitivity, unresolved assumptions
and next decisive experiment. State when to stop or revisit. A forward-validation
proposal identifies the frozen policy, capital/risk limits, calibration needs,
measures and stop criteria. Surviving candidates then retain reproduction/parity
and authorized forward evidence under QR-16–QR-18. Shadow establishes no actual
fill quality; paper fills remain modeled. Live development stays out of scope until the
same frozen strategy shows net-of-cost profitability in both untouched OOS and
forward paper evidence under the
[live-trading reconsideration policy](../roadmap/overview.md#live-trading-kept-in-view);
a recommendation does not authorize activation.
