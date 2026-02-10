WEEK 2 DONE CHECKLIST - Multi-Asset Systematic Macro Allocator (L/S) + Stable Reporting

Purpose
Week 2 is "done" when the macro allocator is genuinely multi-asset, long/short with explicit gross/net constraints, evaluated with rolling walk-forward splits, and produces a stable results.json + report bundle that can be compared across runs without breaking downstream reporting.

A. Repository and reproducibility

A1. Deterministic run identity

- [ ] Running `make run EXP=macro_allocator_ls CONFIG=...` creates `runs/<run_id>/`.
- [ ] `runs/<run_id>/meta.json` exists and includes:
  - run_id
  - exp_name
  - start_time, end_time
  - config_path + config_hash
  - git_commit (or "unknown" if not in repo)
  - python_version, rust_version (optional)
- [ ] Two runs with same code commit + same config + same data snapshot produce identical:
  - config_hash
  - strategy results hash (store `results_hash` in results.json)

A2. Data stays out of git

- [ ] `data/` and `runs/` are gitignored.
- [ ] No secrets in repo (run secret scan or grep patterns, e.g. "API_KEY", "SECRET", ".env").

A3. One-command execution

- [ ] `make ingest_prices CONFIG=experiments/macro/configs/universe.yaml` completes successfully.
- [ ] `make run EXP=macro_allocator_ls CONFIG=experiments/macro/configs/macro_allocator_ls.yaml` completes successfully.
- [ ] `make report RUN=<run_id>` completes successfully.

B. Data contracts (multi-asset panel + metadata)

B1. Price panel integrity

- [ ] `LAB_DATA_ROOT/prices/close.parquet` exists.
- [ ] The close price table satisfies:
  - monotone increasing date index
  - no duplicate dates
  - columns are unique tickers
  - at least N trading days (define N in config; e.g. > 1000)
- [ ] Returns computed from prices contain no NaN beyond the first row after alignment.

B2. Asset metadata integrity

- [ ] `LAB_DATA_ROOT/prices/meta.(csv|parquet)` exists.
- [ ] Every ticker in the price panel has metadata including:
  - bucket (equities/rates/commodities/credit/fx)
  - per_asset_cap (max abs weight)
  - cost_bps
- [ ] Bucket caps and portfolio constraints exist in config:
  - gross_cap
  - net_target
  - net_band
  - bucket_gross_caps

C. Evaluation hygiene (walk-forward, no leakage)

C1. Rolling walk-forward splits used

- [ ] The experiment uses multiple folds (not a single train/test split), with parameters:
  - train_days (or years)
  - test_days (or months)
  - step_days
  - embargo_days
- [ ] Each fold satisfies:
  - train end < test start - embargo
  - no overlap between train and test
  - time-ordered splits only

C2. No-lookahead checks exist and are enforced

- [ ] There is an explicit assertion that signals at time t only use information <= t (or <= t-1).
- [ ] There is a unit test that intentionally injects lookahead and confirms the assertion fails.
- [ ] Macro regime indicator (if used) is lagged by a fixed number of days (e.g. 30) and documented.

D. Portfolio construction (L/S with constrained gross and net)

D1. Constraints are enforced at each rebalance

- [ ] At each rebalance date:
  - sum(|w|) <= gross_cap + eps
  - net in [net_target - net_band, net_target + net_band]
  - |w_i| <= per_asset_cap_i + eps for all i
  - bucket gross <= bucket_gross_cap_bucket + eps for each bucket
- [ ] There is a test that builds weights from synthetic scores and verifies all constraints.

D2. Exposure diagnostics are recorded

- [ ] Time series are saved (either in results.json summary or as artifact files):
  - gross exposure
  - net exposure
  - bucket exposures (gross by bucket)
- [ ] Plots exist for gross/net over time.

E. Cost model (asset-aware) + cost stress

E1. Asset-aware costs applied

- [ ] Costs use per-asset cost_bps from metadata (or explicitly documented override).
- [ ] Costs scale with turnover:
  - if turnover increases, costs increase
  - if cost_bps is 0, net == gross performance
- [ ] Total costs paid is reported.

E2. Cost stress table produced

- [ ] The report contains performance under cost multipliers [1, 2, 4].
- [ ] results.json contains net metrics for each multiplier.

F. Baselines (always-on, comparable)

F1. Baselines run every time

- [ ] At least three baselines are included:
  - Equal-weight (define whether long-only or L/S neutral, but consistent)
  - 60/40 proxy (SPY + IEF/TLT, long-only is fine)
  - Trend-only without regime overlay (if regime overlay exists in main strategy)
- [ ] Baseline metrics appear in results.json and report.

G. Reporting and artifacts

G1. results.json schema stability

- [ ] results.json includes:
  - schema_version
  - run metadata
  - universe summary (tickers + buckets)
  - per-fold metrics
  - aggregated metrics (overall)
  - baselines section
  - cost stress section
- [ ] Reporting code reads results.json without relying on ad-hoc keys.

G2. Minimum plots produced

- [ ] Equity curve (net, post-cost)
- [ ] Drawdown
- [ ] Turnover
- [ ] Gross and net exposure
- [ ] Bucket exposure
- [ ] (Optional but recommended) Risk contribution by bucket

H. Sanity checks ("does it behave like macro?")

H1. Cross-asset rotation evidence

- [ ] There exists at least one period where:
  - equity bucket exposure decreases while rates or gold exposure increases (or vice versa),
    based on your signal/regime rules.
- [ ] This behavior is visible in bucket exposure plots and explained in report notes.

H2. Risk characteristics documented

- [ ] Report includes:
  - correlation vs SPY
  - max drawdown vs SPY baseline
  - volatility and Sharpe (post-cost)
  - commentary on limitations and assumptions
