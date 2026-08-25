# Research Program

## Purpose

This document sequences the empirical work for the proposed first digital-asset
factor-residual candidate. Digital assets are an optional, separately governed
asset package under L05; choosing them for the first workload does not make the
platform crypto-specific or waive any C-K foundation. This program is subordinate
to the 96 platform [implementation packages](README.md) and the
[promotion controls](../architecture/operations.md#deployment-activation-and-promotion).

The stages are ordered research gates, not calendar promises. A stage pauses when
its platform dependency, data quality, or required evidence is incomplete. Later
results cannot waive earlier leakage, accounting, or governance failures.

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

| Research stage | Minimum implementation packages | Blocking evidence |
| --- | --- | --- |
| R01 registered baseline | E01-E04 plus applicable F03/F06 accounting and cost contracts | Reproducible PIT raw-to-report baseline |
| R02 data audit | C01-C08 and D01-D08 | Snapshot, lineage, correction, entitlement, and leakage evidence |
| R03-R09 factors/signals/models | E03-E08 | Trial-complete independent research report |
| R10-R12 risk and portfolio | F06 and G01-G04 | Accounting, cost, risk, constraints, fallback, and stress evidence |
| R13-R14 execution/financing | F03-F08 and applicable G controls | Replay parity, calibrated cost/capacity, lifecycle and financing evidence |
| R15 governance/freeze | E02, E06, E08, and K07 | Complete trial family, independent validation, immutable freeze |
| R16 final OOS/certification | R15 plus applicable E08/F08/G08/H01/K07 gates | One-time final OOS and certification decision package |

Work may prototype earlier on synthetic fixtures, but its result is not eligible
for a later-stage claim until the required platform gate passes.

## R01: strategy definition and transparent baseline

**Entry:** the research contract, trial ledger, PIT dataset API, accounting, and
cost conventions required for a reproducible raw-to-report baseline pass their
applicable E/F gates.

Work packages:

- `REP-01A`: freeze horizon, universe rule, decision time/price, fill delay,
  rebalance policy, cost convention, and gross-to-net identity.
- `REP-01B`: run transparent no-trade, equal-weight/rank, and simple residual or
  reversal baselines through the same ledger.
- `REP-01C`: decompose predictability, turnover, costs, financing, exposure, and
  concentration rather than reporting only aggregate return.

Required evidence: registered hypothesis, configuration, dataset identity,
baseline report, attribution, leakage checks, and hand-reconciled examples.

Advance only if the sign and economic interpretation are stable under corrected
timing and plausible costs. Otherwise stop or reformulate before adding models.

## R02: point-in-time data and instrument audit

**Entry:** applicable canonical-contract and point-in-time data packages C01-D08
pass.

Work packages:

- `REP-02A`: reproduce raw-to-canonical lineage, identifiers, aliases, timestamp
  semantics, and funding/contract metadata.
- `REP-02B`: audit historical membership, gaps, duplicates, stale periods,
  revisions, delistings/inactive contracts, and exclusion reasons.
- `REP-02C`: quantify how source, gap, resampling, outlier, and eligibility policies
  change sample composition and baseline results.

Required evidence: data-lineage map, quality report, historical universe artifact,
timestamp audit, policy sensitivity, and source limitations.

Advance only if an independent reviewer can rebuild the dataset and no unresolved
look-ahead or survivorship path can change the result materially.

## R03: observable-factor and PCA residual baselines

**Entry:** E03-E06 feature, split, transform, and evaluation contracts pass.

Work packages:

- `REP-03A`: implement transparent observable factors with explicit units and
  exposures.
- `REP-03B`: determine rolling latent dimension and deterministic PCA sign/basis
  handling using training data only.
- `REP-03C`: compare residual reconstruction, covariance, convergence, turnover,
  costs, and factor contamination.

Required evidence: factor reconstruction, exposure stability, eigenvalue/dimension
diagnostics, residual properties, and costed portfolio comparison.

Advance only if residual behavior is not an artifact of future normalization,
unstable basis orientation, or uncosted turnover.

## R04: conditional and pricing-relevant factor robustness

**Entry:** R03 passes and a registered conditional-factor question exists.

Work packages:

- `REP-04A`: evaluate conditional exposures and state-dependent factor behavior.
- `REP-04B`: compare pricing-relevant or supervised factors with observable/PCA
  baselines under identical splits.
- `REP-04C`: measure omitted-factor exposure, loading instability, and whether the
  challenger changes net portfolio value.

Required evidence: aligned challenger comparison, loading/exposure stability,
omitted-factor diagnostics, and incremental net utility.

Advance only when extra complexity improves a predeclared decision metric and
survives stability and cost checks.

## R05: signal library and economic hypotheses

**Entry:** signal registry and governed trial ledger are active.

Work packages:

- `REP-05A`: register every formal signal's formula, timing, units, mechanism,
  direction, horizon, and failure mode.
- `REP-05B`: replicate selected signals under original-style and corrected
  point-in-time/cost assumptions.
- `REP-05C`: measure decay, turnover, coverage, missingness, correlation clusters,
  and incremental value after existing signals.

Required evidence: signal dossiers, replication differences, trial-family manifest,
decay curves, redundancy clusters, and net incremental contribution.

Advance only if signal value is economically interpretable and not explained by
data cleaning, universe selection, or overlap with existing features.

## R06: normalization and neutralization

**Entry:** R05 signal definitions are frozen for this comparison.

Work packages:

- `REP-06A`: compare raw, winsorized, ranked, z-scored, and other registered
  transforms fitted inside training windows.
- `REP-06B`: measure explicit factor/sector/liquidity/venue neutralization where
  relevant.
- `REP-06C`: test orthogonalization order and quantify alpha removed, risk removed,
  turnover added, and incremental information retained.

Required evidence: transform stability, exposure before/after, ordering sensitivity,
future-perturbation tests, and net portfolio results.

Advance only if the selected transformation has a stated economic/statistical
reason and does not gain from future distribution information.

## R07: predictive-model benchmark matrix

**Entry:** the E05-E06 common model adapters and evaluation controls pass.

Work packages:

- `REP-07A`: compare mean/linear/regularized baselines using identical data,
  features, splits, and seeds.
- `REP-07B`: add tree/forest challengers with predeclared search space and resource
  budget.
- `REP-07C`: add neural or other complex models only if simpler challengers leave a
  documented limitation they can plausibly address.

Required evidence: IC/calibration, turnover, gross/net utility, stability by time
and side, seed/search sensitivity, compute cost, and complete governed trials.

Advance only when the selected model improves locked net utility and stability,
not merely training or validation fit. This is a provisional ranking under the
current cost model; final selection waits for R13-R15 execution and governance
evidence.

## R08: missing data and representation learning

**Entry:** R07 establishes a stable common benchmark.

Work packages:

- `REP-08A`: compare complete-case, indicator, simple imputation, and registered
  model-based missing policies.
- `REP-08B`: test whether missingness itself is predictive and point-in-time
  available rather than a source artifact.
- `REP-08C`: compare any representation-learning challenger with transparent
  factor/model baselines using ablations.

Required evidence: missingness by source/time/asset, imputation leakage tests,
coverage/performance trade-offs, ablations, seed stability, and net utility.

Advance only if gains remain after controlling for coverage changes, source
artifacts, and implicit look-ahead.

## R09: conditional evaluation, regimes, and degradation rules

**Entry:** R03-R08 produce a bounded candidate family.

Work packages:

- `REP-09A`: report predeclared results by volatility, liquidity, trend, funding,
  crowding, venue, and relevant market states.
- `REP-09B`: test structural breaks, calibration drift, feature drift, model age,
  and long/short asymmetry.
- `REP-09C`: propose versioned alert, de-risk, pause, retrain, and kill criteria
  using only observable state; final thresholds freeze in R15 after risk and
  execution evidence.

Required evidence: conditional tables with sample counts, break/drift diagnostics,
threshold rationale, expected response, owner, and false-positive analysis.

Advance only if degradation can be observed using information available at the
time and every response is operationally implementable.

## R10: covariance and risk-model validation

**Entry:** G03 risk-model and covariance contracts pass.

Work packages:

- `REP-10A`: compare sample and shrinkage covariance baselines.
- `REP-10B`: compare factor and sparse-residual covariance where justified.
- `REP-10C`: evaluate forecast versus realized portfolio risk, tails,
  concentration, stability, and optimizer sensitivity.

Required evidence: calibration plots/tables, eigenstructure, factor/residual
reconstruction, tail outcomes, concentration, and runtime/resource cost.

Advance only if risk is validated through realized portfolio behavior and the
selected estimator improves a declared operational decision.

## R11: static portfolio construction

**Entry:** G01-G04 portfolio contracts, optimizer diagnostics, constraints, and
fallback behavior pass.

Work packages:

- `REP-11A`: compare transparent rank/equal-risk baselines with the constrained
  optimizer.
- `REP-11B`: exercise every constraint's sign, unit, boundary, feasibility, and
  comparative statics.
- `REP-11C`: measure transfer coefficient, shadow prices, binding frequency,
  concentration, and incremental signal value after netting.

Required evidence: baseline/optimized comparison, constraint diagnostics,
feasibility failures, registered fallback results, and stress response.

Advance only if the optimizer behaves predictably and adds net value rather than
hiding risk or costs behind constraint interactions.

## R12: dynamic cost-aware trading

**Entry:** R11 selects a stable static reference, G04 limiting tests pass, and F06
supplies the calibrated execution-cost contract used for net comparison.

Work packages:

- `REP-12A`: implement a transparent linear cost-aware trading baseline.
- `REP-12B`: evaluate a multi-period optimizer and verify its one-period limiting
  case.
- `REP-12C`: compare trading speed, turnover, exposures, capacity, and net value
  across alpha decay and cost assumptions.

Required evidence: comparative statics, limiting-case tests, cost attribution,
position paths, and robust net benefit over the static reference.

Advance only if higher costs slow trading, slower decay slows trading, and the
dynamic policy survives reasonable cost/forecast error.

## R13: execution, impact, and capacity

**Entry:** F05-F08 replay, state-machine, cost, scenario, TCA, and parity tests
pass.

Work packages:

- `REP-13A`: reconcile decision, arrival, and fill prices, fees, partial fills,
  delay, opportunity cost, and ledger P&L.
- `REP-13B`: calibrate or bound spread/impact/participation/urgency assumptions and
  document unsupported venue behavior.
- `REP-13C`: produce capacity frontiers across capital, participation, horizon,
  liquidity, and stress with uncertainty.

Required evidence: TCA reconciliation, model calibration/limitations, vector/replay
parity, and net-return/risk capacity curves.

Advance only if the proposed capital is below stressed capacity and the result is
not dependent on an unobservable fill assumption.

## R14: financing, margin, and short-side stress

**Entry:** applicable F03/F06 accounting, funding, margin, and lifecycle state plus
the selected asset certification fixtures pass. Equity borrow is not applicable to
a digital-asset candidate, but exchange/custody credit, liquidation, stablecoin FX,
and venue/chain outage evidence are mandatory under L05.

Work packages:

- `REP-14A`: reconcile funding, financing, margin, liquidation, and collateral
  state across historical regimes.
- `REP-14B`: for supported shortable assets, model historical availability, fees,
  recalls, and forced buy-ins; otherwise mark the evidence not applicable.
- `REP-14C`: run funding jumps, margin changes, liquidity withdrawal, squeeze,
  concentration, and forced-deleveraging stresses.

Required evidence: financing attribution, margin utilization, availability and
source limitations, liquidation paths, concentration, and severe plausible stress.

Advance only if short/financing assumptions are historically available or bounded
conservatively and the candidate survives predeclared operational limits.

## R15: multiple testing, selection freeze, and independent review

**Entry:** the candidate family is closed and E02, E06, E08, and K07 governance and
independent-validation controls are ready.

Work packages:

- `REP-15A`: reconcile the complete governed trial family, search space, abandoned
  branches, and researcher degrees of freedom.
- `REP-15B`: apply dependence-aware uncertainty and multiple-testing corrections
  appropriate to the research design.
- `REP-15C`: freeze candidate, final-OOS inputs, rules, thresholds, model card, and
  independent-review findings.

Required evidence: trial-family manifest, selection rule, corrected uncertainty,
freeze manifest, access policy, model card draft, dissenting findings, and owners.

Advance only if selection would have chosen the same candidate using only evidence
available before final OOS and every blocking review condition is closed.

## R16: final OOS and certification package

**Entry:** R15 freeze is complete; the final-OOS access control is active; and the
applicable E08, F08, G08, H01, and K07 certification gates pass. Paper and shadow
are subsequent operational promotion stages, not prerequisites for opening the
final OOS set.

Work packages:

- `REP-16A`: run the frozen candidate once on untouched final OOS and retain the
  access log and complete outcome, including failure.
- `REP-16B`: run crowding, capital withdrawal, liquidity withdrawal, correlated
  impact, funding/margin, and drawdown scenarios.
- `REP-16C`: reconcile research and deterministic replay from forecast through
  target, simulated order/fill, costs, cash, positions, and P&L; deliver the
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
