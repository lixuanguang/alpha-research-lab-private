# Research program

This page describes the empirical work needed to grow the repository from its current domain libraries into an
institutional, multi-asset, multi-strategy research-to-production platform. It is a human-maintained program,
not an executable package catalog, registry service, or release gate. Acquisition,
publication, bounded queries/replay, EDA, retained price feature/label diagnostics
and collector health are implemented, alongside fitted model workflows and bounded
spot simulation. Broker integration and strategy monitoring remain planned; the
roadmap records exact supported scope.

The immediate operating model is a single founder using the accepted
[bounded saved-data simulation baseline](../research/saved-baseline-acceptance.md).
MRs through 9A are implemented and closed. Future MR data comes from OKX or
Bitfinex where possible; Binance and Tardis are excluded because of availability,
as specified by the [platform data policy](README.md#current-platform).
The [frozen P1 hypothesis](../research/p1-baseline.md) remains deferred and unaccepted,
with historical source evidence unresolved. The single [implementation roadmap](README.md) owns delivery of its library operations and
orchestrator pipelines. The [QR implementation guide](../../examples/README.md#research-activities-and-journey)
owns the activity-based journey and current usage; this page owns methodology and
research records. Candidate research plans do not duplicate the infrastructure backlog.
A production operating target remains a later decision. The long-term model can add asset classes, strategy families, shared
portfolio construction, production execution, monitoring, and recovery. Independent research, model-risk,
risk, release, and activation controls become formal organizational controls when people are hired; they do
not block the founder from implementing and reproducibly testing technical work now.

The workstreams below are candidate hypothesis workstreams selected when a strategy, asset, or observed
failure makes them relevant. Their numbering gives the work a common vocabulary; it does not make every stage
a mandatory sequential prerequisite for every strategy. A simple strategy may use R01, R02, R05, R10, and R15.
A cross-asset or capacity-sensitive strategy may use most of the workstreams. Record why an applicable
workstream was used, deferred, or marked not applicable.

## Rules for every workstream

Before formal comparison, record the economic hypothesis, target or decision variable, decision and fill
timing, universe, horizon, rebalance rule, constraints, cost and financing conventions, primary selection
rule, and no-trade and transparent baselines. A paper or published result is a hypothesis source, not evidence
that the local result replicates it. Record the exact claim, equation, table, source, and differences in data,
universe, timing, and implementation.

Use point-in-time data. Keep raw identity, source event time, publication or availability time, ingestion
time, revisions, historical universe membership, units, timezone, adjustment rules, and deterministic
ordering. A decision may consume only values whose knowledge time is at or before the decision time.
Historical membership and eligibility must be reconstructed as known then; today's survivors cannot define the
past. Gaps, duplicates, stale values, outliers, delistings, corrections, and missingness need explicit
policies.

Fit normalizers, imputers, feature selectors, dimensionality reductions, and all other learned transforms on
training data only. For maximum label or holding horizon `H`, purge a training row when its label interval
overlaps validation or test. Set an embargo from the actual information intervals: exclude observations that
could still share label, feature, publication, or execution information across the split boundary. Use `H` as a
conservative default when those intervals cannot be modeled; an earlier-only walk-forward fold may use no extra
embargo when its intervals prove that no overlap is possible. Record the intervals, effective gap, and rationale
with the split manifest.

Use time-ordered rolling or nested selection for temporal work. An outer fold estimates performance; an inner
earlier-only fold selects transforms, features, hyperparameters, and thresholds. A fixed
train/validation/final holdout is acceptable only with predeclared boundaries and rationale. Do not inspect
final OOS to decide what to try next. When a holdout is consumed, label it evaluated and define new untouched
evidence for a new experiment.

Once a strategy is promoted into the package, use the same versioned strategy logic in formal research,
deterministic replay, paper, shadow, and live operation.
Adapters may supply asset- or venue-specific data, execution, representation, and precision, but economic
semantics and the decision contract remain the same. Test conversion and parity at those boundaries; do not
create a second production implementation merely because runtime representation differs.

Every formal attempt that influences comparison or selection, including failed, rejected, abandoned, or
stopped variants, remains in an append-only trial record. Account for related trials, researcher choices,
search bounds, seeds, transforms, and stopping decisions. Report uncertainty appropriate to repeated and
dependent trials. Prefer net utility, risk-adjusted contribution, drawdown, turnover, capacity, exposure, and
stability over one headline return.

## Notebook research and package promotion

The founder selected long-lived, activity-based notebooks on 2026-09-13.
The 2026-09-14 retention decision versions maintained `.ipynb`, `.py` and `.md`
files under repository-root `examples/`; generated runs and kernel files remain
local and ignored. The 2026-09-19 cleanup keeps two maintained reader journeys:
the [QR workflow](../../examples/research-foundations.ipynb), ordered from research
question through the current data/EDA capabilities and planned later stages, and
[engineering diagnostics](../../examples/infrastructure-diagnostics.ipynb) for
installed infrastructure, failure and recovery observations. Source acquisition
uses the existing commands. The 2026-09-20 follow-up gives each journey an explicit
live and offline version: [QR live](../../examples/research-foundations-live.ipynb) and
[engineer live](../../examples/infrastructure-diagnostics-live.ipynb) acquire bounded
public recordings through those commands; their saved studies reopen offline.
Separate data-fetching, strategy or monitoring
notebooks are conditional on distinct working content that warrants separation.
They are test beds for new ideas and may span many implementation MRs; an MR records the
relevant notebook section and decisive scenario rather than requiring a new file.

Exploratory source calls, transformations, signals, models and visualizations
may be developed locally without first turning every experiment into a package
API. A feature diagnostic or deterministic signal is a concrete research consumer;
choosing a model is not a prerequisite. Use existing instrument, calendar,
provenance and exact financial contracts
where applicable. Source-access permissions and the predeclared experiment's
universe, hypothesis and holdout boundaries continue to apply to notebook work.
Exploration that changes selection must retain its attempts, including failures;
a notebook's overwritten output is not the sole research record.

Notebooks may tailor names and calculations to a particular asset or alpha
hypothesis. Maintained package code follows the
[generalization and activation standard](../coding_standards/README.md#generalized-code-and-configuration-driven-activation):
shared operations use role-based names and explicit inputs, strategy modules own
their formulas, and configuration selects active instances, assets, parameters
and associated pipelines. Asset-specific notebook defaults do not become hidden
package defaults during promotion.

The maintained package owns productionized shared infrastructure and versioned
strategy implementations intended for publication or operation. Promote an idea
when it has a concrete retained consumer or a selected reproducible strategy
contract: extract cohesive logic, move incidental case assumptions into explicit
inputs/configuration, validate its inputs and invariants, retain
decisive regression cases and expose a callable interface. Package development
can proceed in bounded tested slices before a complete strategy is ready.
After promotion, notebooks call that implementation for formal results; they
remain useful for new variants without becoming a second production strategy.

Data-fetching notebooks explore and invoke acquisition APIs; mature acquisition
and storage behavior belongs in the package. EDA notebooks inspect data and
quality. Strategy-research notebooks develop and compare hypotheses. Monitoring
notebooks inspect versioned outputs and runtime observations; persistent metric
collection, alerts and operational controls belong in maintained code when those
capabilities are built. No monitoring service or published strategy exists merely
because a notebook is created, and this workflow does not authorize publication
or activation. Existing release and operating boundaries remain applicable.

## Small records and artifacts

Keep small versioned records as durable research evidence. The
[selected integrations](README.md#selected-research-integrations) add ClearML tracking,
model records and workflow execution from MR 4 onward, followed by versioned dataset
and feature access. These tools index and consume the retained contracts; mutable
dashboard metadata does not replace them. Assign a stable `strategy_id` from the first formal
run. Add a `family_id` when variants or shared selection rules make grouping useful. Keep each record
human-readable and append changes rather than silently renaming history. A strategy record identifies its
implementation, input/parameter contracts, supported capabilities, lifecycle state, version and optional family.
A configured instance links that strategy/version to its selected assets/universe, representation and precision,
horizon, parameters and data bindings, with a distinct instance identity. Reusing the algorithm for another
compatible asset does not require copying its implementation or inventing another algorithm ID. A family record
groups related variants; these records neither approve a strategy nor replace the trial ledger.

Instance identity includes its state namespace; each invocation resolves actual
universe membership, versions, parameters and input dependencies into an immutable
run manifest. Collection jobs may serve several strategies or a wider EDA universe.
Deployment/account/trading authority is added only for the corresponding runtime
consumer and cannot be inferred from a research selection. Historical EDA and
deterministic strategies can use saved data without live capture or fitted models;
the [implementation roadmap](README.md#delivery-order-and-dependencies) owns these dependencies.

| Artifact | Minimum contents | Purpose |
| --- | --- | --- |
| Dataset manifest | Source and rights, raw identity, availability and knowledge times, revisions, universe rule, units, timezone, adjustments, quality policy | Rebuild the point-in-time sample and limitations |
| Split/transform manifest | Train/validation/test intervals, label horizon, purge/embargo, fit rows, feature and imputation versions, seed | Prove selection used permitted information |
| Trial record | Strategy/family/instance IDs, run/attempt identity, state namespace, hypothesis, exact command, commit/lock, resolved universe/config/data/model identities, choices, resources, metrics, uncertainty, outcome | Account for every result influencing a decision without sharing instance state |
| Model/rule artifact | Definition and configured/calibrated/fitted state version, creation attempt, inputs, parameters, transforms, precision, representation, serialization identity, retrievable bytes/digest, expected errors | Reuse decision logic in replay and operation; analytical models require no invented training history |
| Model evaluation record | Exact model version, evaluation attempt, dataset/feature identities, split/window, label availability, metric definition/units, diagnostics and outcome | Keep model performance history separate from model construction and costed strategy performance |
| Portfolio/replay trace | Signals, targets, orders, fills, costs, financing, cash, positions, exposures, risk, timestamps, reconciliation | Compare decisions with executable behavior |
| Selection/OOS manifest | Closed family, selection rule, freeze identity, access record, final result, failures and deviations | Protect and interpret final evidence |
| Handoff/monitoring record | Artifact digest, limits, state compatibility, rollback reference, alerts, stop/reconcile procedure, unresolved assumptions | Carry a result into controlled operation |

Keep small identities, manifests, and summaries in version control. Keep bulk data and run outputs outside Git
with durable references and retention suitable for reproduction. Do not restore synthetic evidence packs,
institutional registries, or fictional approvals to make an experiment look complete.

## Candidate research workstreams

Each workstream states when it is useful, its implementation/research output, and decisive tests. These are
technical research decisions; future staffed review is described below.

### R01 — Define the strategy and transparent baseline

Use for every new family: define the mechanism, target, horizon, tradable universe, decision/fill timestamps,
rebalance, constraints, financing, and rejection rule; run no-trade, equal-weight/rank, and other simple
challengers through common accounting where meaningful. Deliverables: typed strategy contract, reproducible
data-to-report input, baseline configuration, and hand-calculated ledger examples. Decisive tests: sign,
units, timing, no-trade and empty-input behavior, sizing, cash, positions, fees, and gross-to-net P&L. Stop
when the effect depends on hidden selection, corrected timing, or an assumption that cannot be bounded.

### R02 — Audit point-in-time data and the tradable universe

Use when a source, asset class, historical universe, or reference convention changes: rebuild raw-to-canonical
lineage, identifiers, aliases, publication delays, revisions, inactive instruments, delistings, contract
metadata, and historical eligibility; quantify gaps, duplicates, stale periods, outliers, resampling,
adjustments, and source-policy effects. Deliverables: dataset manifest, quality/coverage report,
historical-universe artifact, timestamp audit, and source limitations. Decisive tests delay publication,
revise future values, perturb membership, inject duplicates, and vary stale/gap policies; earlier decisions
must stay unchanged. Founder rebuild is technical evidence now; independent review is added with staffed
scope.

### R03 — Build observable factors, PCA, and residual baselines

Use when the hypothesis is factor/residual based or shared return sources need separating: define observable
factors with units and exposures; compare PCA or other latent dimensions with training-only fitting, rolling
dimension selection, and deterministic sign/basis conventions; measure reconstruction, covariance,
convergence, turnover, costs, and factor contamination. Deliverables: factor definitions,
exposure/reconstruction reports, eigenvalue/dimension diagnostics, residual artifacts, and costed comparisons.
Decisive tests use rolling windows, permuted columns, constant/degenerate inputs, missing factors, future
perturbations, and basis-orientation changes; stop for future normalization, unstable basis selection, or
uncosted turnover.

### R04 — Test conditional and pricing-relevant factors

Use only when a recorded question says unconditional factors are insufficient: compare conditional
exposures, state-dependent factors, pricing-relevant factors, and supervised challengers under R03's data,
splits, costs, and risk budget; measure loading instability, omitted-factor exposure, and incremental net
portfolio contribution. Deliverables: aligned challenger report, loading/exposure stability, omitted-factor
diagnostics, and complexity decision. Decisive tests perturb conditioning states, use out-of-window states,
check decision-time availability, and compare the transparent factor baseline; continue only when extra
complexity improves a predeclared net metric and survives stability/cost.

### R05 — Record economic signals and replicate hypotheses

Give each formal signal a stable `signal_id`, family, formula, direction, units, timing, mechanism, expected
horizon, coverage, and failure mode. Replicate published or internal hypotheses under original-style and
corrected point-in-time, universe, and cost assumptions when those answer different questions; measure decay,
turnover, missingness, redundancy, and incremental value. Deliverables: small signal records, formula/feature
implementations, replication notes, decay curves, coverage reports, correlation clusters, and trial links.
Decisive tests use hand examples, sign reversals, shifted timestamps, unavailable inputs, future
perturbations, and incremental ablations; stop for cleaning, survivor selection, leakage, or duplicate
signals.

### R06 — Compare normalization and neutralization policies

Use when scale, outliers, cross-sectional comparability, or exposure control affects a signal: compare raw,
ranked, winsorized, centered, scaled, and other recorded transforms fitted within each training window;
evaluate factor, sector, liquidity, venue, or other neutralization only with an explicit economic purpose;
quantify alpha removed, risk removed, turnover added, and information retained. Deliverables: transform
manifests, before/after exposures, ordering and neutralization reports, and selected-policy rationale.
Decisive tests fit on training rows only, perturb future distributions, exercise outliers and constant
windows, vary neutralization order, and verify missing/zero-scale behavior; continue only without a
future-distribution advantage.

### R07 — Compare model families under a common benchmark

Use when a predictive model is needed beyond transparent rules. Start with mean, linear, and regularized
baselines; add other challengers only with a predeclared search space, resource budget, and limitation the
simpler model cannot address. Complex families need an explicit hypothesis, ablations, and reproducible seeds.
Deliverables: model matrix, common feature/split manifest, search/resource record, calibration and utility
report, and complete trials. Decisive tests use identical inputs, costs, constraints, rolling or nested
splits, seeds, and asset/time slices; test serialization and repeated inference. Select on locked net utility,
stability, calibration, and operating cost, not training fit.

### R08 — Handle missing data and representation choices

Use when coverage, sparse histories, modality, or structured representation may change the result: compare
complete-case, indicator, simple-imputation, and documented model-based policies; test whether missingness is
available and economically meaningful rather than a source artifact; compare representations through ablations
while preserving strategy-appropriate representation/precision. Deliverables:
missingness-by-source/time/asset report, imputation and representation manifests, coverage/performance
trade-offs, ablations, and seed stability. Decisive tests use missing windows, missing-by-regime fixtures,
late arrivals, constant features, dtype/shape changes, and future perturbations; continue only when gains
survive coverage changes and implicit look-ahead.

### R09 — Measure regimes, drift, and degradation

Use when performance or risk may vary with market, venue, liquidity, funding, or model state: define
observable regimes before final evaluation where possible; report conditional utility, exposure, turnover,
drawdown, and sample counts; test structural breaks, feature/calibration drift, model age, and long/short
asymmetry. Deliverables: regime definitions, conditional reports, drift diagnostics, and versioned alert,
de-risk, pause, retrain, or stop proposals. Decisive tests prove states are observable at decision time,
thresholds are not tuned on future outcomes, and responses work in replay and operation; freeze thresholds
with the selected strategy's risk and execution assumptions.

### R10 — Validate covariance and risk forecasts

Use when sizing or constraints depend on predicted risk: compare sample and shrinkage covariance with
structured or factor/residual alternatives only when justified; evaluate forecast versus realized portfolio
risk, tails, eigenstructure, concentration, stability, and optimizer sensitivity across relevant regimes.
Deliverables: covariance manifests, calibration tables, factor/residual reconstruction, tail/concentration
reports, and resource costs. Decisive tests cover one asset, duplicate assets, singular/near-singular
matrices, empty windows, changing order, non-finite inputs, and held-out risk; continue only when the
estimator improves a declared allocation or risk decision.

### R11 — Construct portfolios and measure cross-strategy contribution

Use for one strategy when constraints shape its outcome and for multiple strategies/assets when capital is
shared. Compare transparent rank, equal-weight, and equal-risk baselines with constrained construction; test
every constraint's sign, unit, boundary, feasibility, fallback, and comparative static. Across strategies
compare total/marginal contribution, incremental P&L, marginal risk, correlation, overlap, turnover, capacity,
drawdown, and diversification by asset, family, and regime. Deliverables: portfolio contract, optimizer
diagnostics, contribution/overlap reports, binding-frequency and shadow-price records, feasible/fallback
traces, and cross-strategy scorecard. Decisive tests vary one constraint and signal, use infeasible and
zero-target fixtures, replay repeated calls, and reconcile contribution to positions and P&L.

### R12 — Model dynamic costs and trading decisions

Use when target changes, alpha decay, turnover, or multi-period execution affects net results. Establish a
transparent linear or one-period trading baseline; compare a dynamic policy with explicit decay, liquidity,
impact, participation, urgency, and inventory assumptions; verify its one-period limiting case and compare
speed, turnover, exposure, capacity, and net utility under uncertainty. Deliverables: trading-policy
contract, comparative statics, target/position paths, cost attribution, and limiting-case report. Decisive
tests check zero target change, zero cost, liquidity bounds, delayed fills, cost-sign errors, and position
continuity. Under a declared fixed scenario, comparative statics should show higher costs slowing trading or
reducing net result; investigate exceptions caused by changed constraints or paths.

### R13 — Reconcile execution, impact, and capacity

Use before an executable-net or capacity claim. Reconcile decision, arrival, and fill prices; delay, spread,
fees, partial fills, opportunity cost, order state, cash, positions, and ledger P&L. Calibrate or
conservatively bound impact, participation, urgency, and venue behavior; produce capacity frontiers across
capital, participation, horizon, liquidity, and stress with uncertainty. Deliverables: execution trace, TCA
reconciliation, cost calibration and limits, replay parity report, and capacity curves. Decisive tests use no,
partial, and duplicate fills, out-of-order events, rejects, stale prices, delayed acknowledgements, and
restart/reconciliation. Any deployed capital and participation must be bounded by a conservative stress-based
capacity estimate and cannot depend on an unobservable fill assumption.

### R14 — Account for financing and the full lifecycle

Use when funding, borrowing, margin, collateral, leverage, liquidation, settlement, or cash lifecycle can
change a decision. Reconcile opening/closing cash, financing, fees, margin, collateral, funding, borrow,
corporate or contract events, forced reductions, and liquidation. For shortable assets model availability,
recalls, fees, and buy-ins; when inapplicable, record that boundary rather than inventing an assumption.
Deliverables: financing conventions, lifecycle transitions, attribution, utilization/availability reports,
severe-stress scenarios, and source limits. Decisive tests cover funding jumps, margin changes, liquidity
withdrawal, missing collateral, zero/negative balances, forced deleveraging, repeated settlement, and restart
from persisted state.

### R15 — Account for trials, select robustly, and freeze

Use whenever variants, transforms, models, assets, or stopping choices can influence selection. Reconcile the
complete family, including abandoned branches, search bounds, researcher choices, seeds, and failures; apply
uncertainty and multiple-testing treatment appropriate to related trials. Use nested or rolling selection and
lock candidate, transforms, data/config identities, decision rules, thresholds, costs, and operating
assumptions before final OOS. Deliverables: closed family manifest, trial accounting, uncertainty and
multiple-testing report, freeze manifest, model/rule card, access policy, and founder decision. Decisive tests
rebuild selection, prevent later trials changing the frozen candidate, and verify purge/embargo intervals.
Formal independent validation and model-risk signoff are added for staffed scope; technical reproducibility is
required now.

### R16 — Run untouched final OOS evidence and prepare handoff

Use after R15 when final OOS informs a real promotion decision. Run the frozen candidate once on untouched
data and retain access history, complete output, failures, and deviations. Evaluate crowding,
capital/liquidity withdrawal, correlated impact, financing, margin, drawdown, and recovery; reconcile research
and deterministic replay from forecast through target, order/fill, costs, cash, positions, risk, and P&L.
Deliverables: untouched-OOS package, attribution and uncertainty, capacity/stress reports, replay
reconciliation, handoff manifest, rollback reference, monitoring conditions, and
continue/de-risk/reject/new-trial decision. Decisive tests prohibit retuning or selection from the holdout;
rerunning the unchanged frozen candidate for reproducibility is allowed. They also check same-logic
research/replay, future perturbation, and stop/recovery paths. This does not authorize live capital; release,
security, limits, risk separation, activation, and operations follow current policies.

## From research to production and monitoring

Research correctness is the immediate bar: point-in-time data, train-only transforms, honest trial accounting,
costed behavior, numerical and lifecycle invariants, reproducible artifacts, and strategy/replay parity. A
founder can review and rerun these records without a committee. An operating target adds build identity,
dependency lock, configuration, model/data references, limits, state compatibility, rollback, secrets
handling, reconciliation, and a tested stop path.

The long-term platform should give each strategy one versioned kernel and contract shared across replay, paper, shadow, canary, and live. Monitoring should surface stale inputs, missing heartbeats, reject/error bursts, position or cash
mismatch, drift, risk and loss limits, and broken reconciliation. Preserve orders, fills, decisions, state,
alerts, and recovery evidence for the operating lifetime. Choose process and computing topology from measured
latency, availability, data, and broker requirements.

Formal independent review, model-risk challenge, portfolio and risk signoff, release approval, dual-control
activation, and separation of duties are future organizational controls. Add them when the corresponding
people and authority exist; they strengthen the handoff and capital boundary without replacing the technical
tests and artifacts the founder produces now.

## Computing scale and implementation status

Run locally while data volume, working set, elapsed time, and trial count fit the existing environment.
Consider a larger or parallel path only after measuring a reproducible bottleneck: local memory no longer
fits, rolling/nested trials exceed a documented time budget, replay needs more throughput, or cross-asset
comparison needs controlled parallelism. Record hardware, environment, seed, input identities, resource
limits, and failure/retry behavior; keep a small reference run and compare scaled results against it.
The roadmap's selected ClearML, data/feature and analytical integrations address
concrete traceability, repeatability and researcher-usability needs from MR 4 onward;
their initial bounded consumers do not depend on a throughput bottleneck. Add larger
or distributed infrastructure when measured workload or actual sharing requires it.
Keep numerical search in Optuna, execution/tracking in ClearML, dataset versions in
lakeFS and feature retrieval in Feast where those consumers are implemented. These
choices do not expand the delivered MR 3 scope or authorize deployment.

There is no research runner command today. Until one exists, use the existing `uv run --frozen` environment and
affected pytest/static checks for iteration. `make check` remains the complete local entrypoint when full
validation is needed; the hosted required lane remains authoritative before merge. Record external analysis
commands explicitly. A future runner must retain the trial and artifact fields above, fail clearly on missing or
stale inputs, and make data, code, configuration, seed, and resource identity visible in results.

## Research-source policy

Papers, specifications, and prior results inform hypotheses, baselines, and diagnostics. Before a replication, record a stable DOI, publisher, arXiv, or official specification link; identify the exact claim; state data,
universe, timing, and implementation differences; define success and failure evidence; and retain
published-style and corrected point-in-time/costed results when they answer different questions. An author/year
citation alone is not a replication. A negative result is a useful completed experiment when its limitations and attempted alternatives are retained.
