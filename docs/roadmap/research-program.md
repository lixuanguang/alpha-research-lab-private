# Research Program

## Purpose

This document sequences the empirical work for the proposed first digital-asset
factor-residual candidate. Digital assets are an optional, separately governed
certification package (`L05`); choosing them for the first workload does not make
the platform crypto-specific or waive the canonical-contract-through-security
foundations (`C` through `K`). This program is subordinate to the 96 platform
[implementation packages](README.md) and the
[promotion controls](../architecture/operations.md#deployment-activation-and-promotion).

The stages are ordered research gates, not calendar promises. Technical work
pauses when an implementation dependency, data-quality check, or required
technical artifact is incomplete. Pending organizational handover does not block
implementation or reproducible research validation. Later results cannot waive
earlier leakage, accounting, entitlement, release, or activation failures.

Stage headings and prose lead with the research objective and place the stable
stage selector in parentheses. Tables retain selectors because dependency and
evidence records require them; a selector is never used as a substitute for a
human-readable stage or work-package name.

## Research execution rules

- Register the hypothesis and primary decision rule before formal comparison.
- A run becomes governed when its result informs comparison, selection, final OOS,
  or promotion. Failed/rejected governed runs remain append-only.
- Use the same point-in-time dataset, splits, cost conventions, risk budget, and
  portfolio constraints for model comparisons.
- Transparent baselines remain permanent challengers.
- Select on predeclared net portfolio utility and stability, not in-sample fit or
  one headline metric.
- Freeze data, code/artifacts, configuration, decision rules, thresholds, and
  candidate family before final OOS.
- Do not access final OOS merely to decide what to try next.
- Use the shared strategy kernel and declared adapters for research, deterministic
  replay, paper, shadow, canary, and live; do not rewrite selected logic during a
  production hand-off.
- Every stage produces a reproducible artifact, not only a narrative conclusion.

## Platform enablement map

The package column below is a technical-work entry rule: each applicable package
must have complete implementation and no technical finding. It does not require
institutional `validated` status. Operation/release edges, entitlements and the
rightmost conditions apply when a result is promoted, released, or given access
to a controlled final-OOS or target environment. Team-handover review activates
only for staffed scope.

| Research stage | Technical-work package entry | Additional operation, claim, or promotion condition |
| --- | --- | --- |
| R01 registered baseline | E01-E04 plus applicable F03/F06 accounting and cost contracts | Reproducible PIT raw-to-report baseline before a stage-complete claim |
| R02 data audit | C01-C08 and D01-D08 | Entitlement and target-source evidence before using controlled data or making an institutional claim |
| R03-R09 factors/signals/models | E03-E08 | Independent research review before institutional acceptance or promotion |
| R10-R12 risk and portfolio | F06 and G01-G04 | Independent risk review before a risk limit or promotion decision |
| R13-R14 execution/financing | F03-F08 and applicable G controls | Calibrated target evidence before operational use or a capacity claim |
| R15 governance/freeze | E02, E06, E08, and K07 | Staffed independent validation before institutional freeze acceptance |
| R16 final OOS/certification | R15 technical freeze plus applicable E08/F08/G08/H01/K07 implementation | Active access control and applicable independent acceptance before final-OOS access and certification |

Synthetic-fixture work may begin earlier, but a technical stage result cannot be
used by a later technical stage until its implementation entry and evidence pass.
Institutional claims, controlled-data access, release, promotion, and activation
remain subject to their separately listed conditions.

## Strategy definition and transparent baseline (research stage `R01`)

**Entry:** the research contract, trial ledger, PIT dataset API, accounting, and
cost conventions required for a reproducible raw-to-report baseline have complete
implementation and passing applicable technical checks (`E` and `F`).

Work packages:

- **Decision contract** (`REP-01A`): freeze horizon, universe rule, decision
  time/price, fill delay, rebalance policy, cost convention, and gross-to-net
  identity.
- **Transparent baselines** (`REP-01B`): run transparent no-trade,
  equal-weight/rank, and simple residual or reversal baselines through the same
  ledger.
- **Economic decomposition** (`REP-01C`): decompose predictability, turnover,
  costs, financing, exposure, and concentration rather than reporting only
  aggregate return.

Required evidence: registered hypothesis, configuration, dataset identity,
baseline report, attribution, leakage checks, and hand-reconciled examples.

Advance only if the sign and economic interpretation are stable under corrected
timing and plausible costs. Otherwise stop or reformulate before adding models.

## Point-in-time data and instrument audit (research stage `R02`)

**Entry:** the applicable canonical-contract and point-in-time data packages
(`C01` through `D08`) have complete implementation and passing technical checks.

Work packages:

- **Canonical lineage** (`REP-02A`): reproduce raw-to-canonical lineage,
  identifiers, aliases, timestamp semantics, and funding/contract metadata.
- **Historical-universe audit** (`REP-02B`): audit historical membership, gaps,
  duplicates, stale periods, revisions, delistings/inactive contracts, and
  exclusion reasons.
- **Data-policy sensitivity** (`REP-02C`): quantify how source, gap, resampling,
  outlier, and eligibility policies change sample composition and baseline results.

Required evidence: data-lineage map, quality report, historical universe artifact,
timestamp audit, policy sensitivity, and source limitations.

Advance technical work only if a clean independent process can rebuild the
dataset and no unresolved look-ahead or survivorship path can change the result
materially. A second person is required for an institutional independent-review
claim, not for the founder to execute and retain that reproducibility check.

## Observable-factor and PCA residual baselines (research stage `R03`)

**Entry:** the feature, split, transform, and evaluation contracts (`E03` through
`E06`) have complete implementation and passing technical checks.

Work packages:

- **Observable factors** (`REP-03A`): implement transparent observable factors
  with explicit units and exposures.
- **Latent-dimension stability** (`REP-03B`): determine rolling latent dimension
  and deterministic PCA sign/basis handling using training data only.
- **Residual comparison** (`REP-03C`): compare residual reconstruction,
  covariance, convergence, turnover, costs, and factor contamination.

Required evidence: factor reconstruction, exposure stability, eigenvalue/dimension
diagnostics, residual properties, and costed portfolio comparison.

Advance only if residual behavior is not an artifact of future normalization,
unstable basis orientation, or uncosted turnover.

## Conditional and pricing-relevant factor robustness (research stage `R04`)

**Entry:** the observable-factor and PCA residual baseline stage (`R03`) passes and
a registered conditional-factor question exists.

Work packages:

- **Conditional exposures** (`REP-04A`): evaluate conditional exposures and
  state-dependent factor behavior.
- **Pricing-relevant challengers** (`REP-04B`): compare pricing-relevant or
  supervised factors with observable/PCA baselines under identical splits.
- **Incremental-value test** (`REP-04C`): measure omitted-factor exposure,
  loading instability, and whether the challenger changes net portfolio value.

Required evidence: aligned challenger comparison, loading/exposure stability,
omitted-factor diagnostics, and incremental net utility.

Advance only when extra complexity improves a predeclared decision metric and
survives stability and cost checks.

## Signal library and economic hypotheses (research stage `R05`)

**Entry:** signal registry and governed trial ledger are active.

Work packages:

- **Signal registration** (`REP-05A`): register every formal signal's formula,
  timing, units, mechanism, direction, horizon, and failure mode.
- **Signal replication** (`REP-05B`): replicate selected signals under original-style and corrected
  point-in-time/cost assumptions.
- **Signal decay and redundancy** (`REP-05C`): measure decay, turnover, coverage,
  missingness, correlation clusters, and incremental value after existing signals.

Required evidence: signal dossiers, replication differences, trial-family manifest,
decay curves, redundancy clusters, and net incremental contribution.

Advance only if signal value is economically interpretable and not explained by
data cleaning, universe selection, or overlap with existing features.

## Normalization and neutralization (research stage `R06`)

**Entry:** the signal-library stage's (`R05`) definitions are frozen for this
comparison.

Work packages:

- **Transform comparison** (`REP-06A`): compare raw, winsorized, ranked,
  z-scored, and other registered transforms fitted inside training windows.
- **Neutralization analysis** (`REP-06B`): measure explicit
  factor/sector/liquidity/venue neutralization where relevant.
- **Orthogonalization sensitivity** (`REP-06C`): test orthogonalization order and
  quantify alpha removed, risk removed, turnover added, and incremental information
  retained.

Required evidence: transform stability, exposure before/after, ordering sensitivity,
future-perturbation tests, and net portfolio results.

Advance only if the selected transformation has a stated economic/statistical
reason and does not gain from future distribution information.

## Predictive-model benchmark matrix (research stage `R07`)

**Entry:** the common model adapters and evaluation controls (`E05` through `E06`)
have complete implementation and passing technical checks.

Work packages:

- **Linear baselines** (`REP-07A`): compare mean/linear/regularized baselines using identical data,
  features, splits, and seeds.
- **Tree challengers** (`REP-07B`): add tree/forest challengers with predeclared
  search space and resource budget.
- **Complex-model admission** (`REP-07C`): add neural or other complex models only
  if simpler challengers leave a documented limitation they can plausibly address.

Required evidence: IC/calibration, turnover, gross/net utility, stability by time
and side, seed/search sensitivity, compute cost, and complete governed trials.

Advance only when the selected model improves locked net utility and stability,
not merely training or validation fit. This is a provisional ranking under the
current cost model; final selection waits for the execution-through-selection-
freeze stages (`R13` through `R15`) and their governance evidence.

## Missing data and representation learning (research stage `R08`)

**Entry:** the predictive-model benchmark stage (`R07`) establishes a stable common
benchmark.

Work packages:

- **Missing-data policies** (`REP-08A`): compare complete-case, indicator, simple
  imputation, and registered model-based missing policies.
- **Missingness signal** (`REP-08B`): test whether missingness itself is
  predictive and point-in-time available rather than a source artifact.
- **Representation-learning comparison** (`REP-08C`): compare any
  representation-learning challenger with transparent factor/model baselines using
  ablations.

Required evidence: missingness by source/time/asset, imputation leakage tests,
coverage/performance trade-offs, ablations, seed stability, and net utility.

Advance only if gains remain after controlling for coverage changes, source
artifacts, and implicit look-ahead.

## Conditional evaluation, regimes, and degradation rules (research stage `R09`)

**Entry:** the factor-through-representation-learning stages (`R03` through `R08`)
produce a bounded candidate family.

Work packages:

- **Regime reporting** (`REP-09A`): report predeclared results by volatility,
  liquidity, trend, funding, crowding, venue, and relevant market states.
- **Degradation analysis** (`REP-09B`): test structural breaks, calibration drift,
  feature drift, model age, and long/short asymmetry.
- **Degradation controls** (`REP-09C`): propose versioned alert, de-risk, pause,
  retrain, and kill criteria using only observable state; final thresholds freeze
  in the multiple-testing and selection-freeze stage (`R15`) after risk and
  execution evidence.

Required evidence: conditional tables with sample counts, break/drift diagnostics,
threshold rationale, expected response, owner, and false-positive analysis.

Advance only if degradation can be observed using information available at the
time and every response is operationally implementable.

## Covariance and risk-model validation (research stage `R10`)

**Entry:** the risk-model and covariance contracts (`G03`) have complete
implementation and passing technical checks.

Work packages:

- **Covariance baselines** (`REP-10A`): compare sample and shrinkage covariance
  baselines.
- **Structured covariance challengers** (`REP-10B`): compare factor and
  sparse-residual covariance where justified.
- **Risk calibration** (`REP-10C`): evaluate forecast versus realized portfolio
  risk, tails, concentration, stability, and optimizer sensitivity.

Required evidence: calibration plots/tables, eigenstructure, factor/residual
reconstruction, tail outcomes, concentration, and runtime/resource cost.

Advance only if risk is validated through realized portfolio behavior and the
selected estimator improves a declared operational decision.

## Static portfolio construction (research stage `R11`)

**Entry:** the portfolio contracts, optimizer diagnostics, constraints, and
fallback behavior (`G01` through `G04`) have complete implementation and passing
technical checks.

Work packages:

- **Portfolio baselines** (`REP-11A`): compare transparent rank/equal-risk
  baselines with the constrained optimizer.
- **Constraint validation** (`REP-11B`): exercise every constraint's sign, unit,
  boundary, feasibility, and comparative statics.
- **Constraint diagnostics** (`REP-11C`): measure transfer coefficient, shadow
  prices, binding frequency, concentration, and incremental signal value after
  netting.

Required evidence: baseline/optimized comparison, constraint diagnostics,
feasibility failures, registered fallback results, and stress response.

Advance only if the optimizer behaves predictably and adds net value rather than
hiding risk or costs behind constraint interactions.

## Dynamic cost-aware trading (research stage `R12`)

**Entry:** static portfolio construction (`R11`) selects a stable reference,
portfolio constraint limiting tests (`G04`) pass, and calibrated transaction-cost
models (`F06`) supply the contract used for net comparison.

Work packages:

- **Linear trading baseline** (`REP-12A`): implement a transparent linear
  cost-aware trading baseline.
- **Multi-period optimizer** (`REP-12B`): evaluate a multi-period optimizer and
  verify its one-period limiting case.
- **Trading-policy comparison** (`REP-12C`): compare trading speed, turnover,
  exposures, capacity, and net value across alpha decay and cost assumptions.

Required evidence: comparative statics, limiting-case tests, cost attribution,
position paths, and robust net benefit over the static reference.

Advance only if higher costs slow trading, slower decay slows trading, and the
dynamic policy survives reasonable cost/forecast error.

## Execution, impact, and capacity (research stage `R13`)

**Entry:** the replay, state-machine, cost, scenario, TCA, and parity packages
(`F05` through `F08`) have complete implementation and passing technical checks.

Work packages:

- **Execution reconciliation** (`REP-13A`): reconcile decision, arrival, and fill
  prices, fees, partial fills, delay, opportunity cost, and ledger P&L.
- **Impact calibration** (`REP-13B`): calibrate or bound
  spread/impact/participation/urgency assumptions and document unsupported venue
  behavior.
- **Capacity frontiers** (`REP-13C`): produce capacity frontiers across capital,
  participation, horizon, liquidity, and stress with uncertainty.

Required evidence: TCA reconciliation, model calibration/limitations, vector/replay
parity, and net-return/risk capacity curves.

Advance only if the proposed capital is below stressed capacity and the result is
not dependent on an unobservable fill assumption.

## Financing, margin, and short-side stress (research stage `R14`)

**Entry:** the applicable accounting, funding, margin, and lifecycle contracts
(`F03` and `F06`) plus isolated asset fixtures have complete implementation and
passing technical checks. Equity
borrow is not applicable to a digital-asset candidate, but exchange/custody credit,
liquidation, stablecoin FX, and venue/chain outage evidence are mandatory under the
digital-asset certification package (`L05`).

Work packages:

- **Financing reconciliation** (`REP-14A`): reconcile funding, financing, margin,
  liquidation, and collateral state across historical regimes.
- **Short-availability modeling** (`REP-14B`): for supported shortable assets,
  model historical availability, fees, recalls, and forced buy-ins; otherwise mark
  the evidence not applicable.
- **Financing stress** (`REP-14C`): run funding jumps, margin changes, liquidity
  withdrawal, squeeze, concentration, and forced-deleveraging stresses.

Required evidence: financing attribution, margin utilization, availability and
source limitations, liquidation paths, concentration, and severe plausible stress.

Advance only if short/financing assumptions are historically available or bounded
conservatively and the candidate survives predeclared operational limits.

## Multiple testing, selection freeze, and independent review (research stage `R15`)

**Entry:** the candidate family is closed and the experiment-ledger, robustness,
model-report, and independent-validation controls (`E02`, `E06`, `E08`, and
`K07`) have complete implementation and passing technical checks.

Work packages:

- **Trial-family reconciliation** (`REP-15A`): reconcile the complete governed
  trial family, search space, abandoned branches, and researcher degrees of
  freedom.
- **Multiple-testing controls** (`REP-15B`): apply dependence-aware uncertainty
  and multiple-testing corrections appropriate to the research design.
- **Selection freeze** (`REP-15C`): freeze candidate, final-OOS inputs, rules,
  thresholds, model card, and independent-review findings.

Required evidence: trial-family manifest, selection rule, corrected uncertainty,
freeze manifest, access policy, model card draft, dissenting findings, and owners.

Advance to a technical freeze only if selection would have chosen the same
candidate using evidence available before final OOS. Institutional freeze
acceptance and final-OOS access additionally require every applicable staffed
review and operation-specific condition to be closed.

## Final OOS and certification package (research stage `R16`)

**Entry:** the multiple-testing and selection freeze (`R15`) is complete; the
final-OOS access control is active; and the applicable model-report, replay-parity,
portfolio-replay, strategy-kernel, and independent-validation certification gates
(`E08`, `F08`, `G08`, `H01`, and `K07`) pass. Paper and shadow are subsequent
operational promotion stages, not prerequisites for opening the final OOS set.

Work packages:

- **Final out-of-sample run** (`REP-16A`): run the frozen candidate once on
  untouched final OOS and retain the access log and complete outcome, including
  failure.
- **Crowding and withdrawal stress** (`REP-16B`): run crowding, capital
  withdrawal, liquidity withdrawal, correlated impact, funding/margin, and
  drawdown scenarios.
- **Replay reconciliation** (`REP-16C`): reconcile research and deterministic
  replay from forecast through target, simulated order/fill, costs, cash,
  positions, and P&L; deliver the
  certification decision package and parity expectations for later paper/shadow.

Required evidence: untouched OOS with access log, attribution, capacity frontier,
stress, model card, reconciliation, review findings, and a
certify/de-risk/reject decision. H07, I, J, and K subsequently add paper/shadow,
operational incidents, recovery, monitoring, security, and activation evidence.

Completion does not authorize live capital. A certified candidate must still pass
paper, shadow, bounded canary, release-manifest, independent-risk, security, SLO,
recovery, rollback, venue/asset certification, and dual-control activation gates.

## Required research deliverables

| Deliverable | Produced primarily in | Promotion check |
| --- | --- | --- |
| Data and universe audit | R02 | No unresolved look-ahead, revision, or survivorship path |
| Baseline replication | R01, R03 | Corrected timing/cost result reproduces independently |
| Signal dossier | R05, R06 | Formula, mechanism, timing, decay, risks, incremental value |
| Model bake-off | R07, R08 | Common data/splits/costs; stability and net utility select |
| Regime/degradation policy | R09 | Observable state, precommitted threshold/response/owner |
| Risk validation | R10 | Forecast risk calibrated through realized outcomes |
| Optimizer validation | R11, R12 | Units, feasibility, shadow prices, limiting cases, fallback |
| Execution/cost model | R13 | Decision-to-fill and ledger reconcile; uncertainty explicit |
| Financing/short report | R14 | Funding/margin/availability and severe stress are credible |
| Capacity/crowding report | R13, R16 | Proposed scale below average and stressed capacity |
| Final OOS package | R15, R16 | Inputs frozen; untouched result and failures retained |
| Model card and decision | R15, R16 | Owners, limits, monitoring, kill/recovery, review complete |

## Decision questions

| Question | Principal evidence | Fail or de-risk trigger |
| --- | --- | --- |
| Is the alpha real? | R01-R06, R09, R15-R16 | Sign/order depends on one period, survivor set, or post-hoc cleaning |
| Is it incremental? | R05-R06, R11 | Value disappears after existing signals, netting, constraints |
| Is it implementable? | R12-R14 | Turnover, impact, delay, financing, or unavailable shorts consume result |
| Is risk understood? | R09-R10, R14, R16 | Neutrality relies only on historical beta or average volatility |
| Is complexity justified? | R07-R08, R12 | Gain comes from leakage, missingness, unstable features, seeds, or costs |
| Can it be operated? | R02, R09, R15-R16 | Manual fixes, unavailable live inputs, unobservable states, failed recovery |

## Research-source policy

Papers and specifications inform hypotheses, baselines, and diagnostics; they do
not substitute for executable evidence. Before starting a replication package:

1. Record a stable DOI, publisher, arXiv, or official specification link.
2. State the exact table, equation, algorithm, or claim being reproduced.
3. Record data, universe, timing, and implementation differences.
4. Define success/failure evidence before seeing the result.
5. Preserve both published-style and corrected point-in-time/costed results where
   they answer different questions.

The earlier untracked local reading-list PDF is not a normative dependency. A
candidate cannot claim replication from an author/year citation alone.
