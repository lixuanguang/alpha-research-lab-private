Suggested results.json schema (stable, report-friendly)

1. JSON Schema-style definition (practical subset)

Use this as a contract; you don't need to validate strictly on day one, but keep the structure stable.

```json
{
  "schema_version": "1.0",
  "run": {
    "run_id": "string",
    "exp_name": "string",
    "timestamp_utc": "string",
    "git_commit": "string",
    "config_path": "string",
    "config_hash": "string",
    "data_snapshot_id": "string",
    "results_hash": "string"
  },
  "universe": {
    "tickers": ["string"],
    "ticker_meta": [
      {
        "ticker": "string",
        "bucket": "string",
        "cost_bps": "number",
        "per_asset_cap": "number"
      }
    ],
    "constraints": {
      "gross_cap": "number",
      "net_target": "number",
      "net_band": "number",
      "bucket_gross_caps": {
        "equities": "number",
        "rates": "number",
        "commodities": "number",
        "credit": "number",
        "fx": "number"
      }
    }
  },
  "evaluation": {
    "frequency": "string",
    "rebalance_rule": "string",
    "calendar": "string",
    "folds": [
      {
        "fold_id": "string",
        "train_start": "string",
        "train_end": "string",
        "test_start": "string",
        "test_end": "string",
        "embargo_days": "integer"
      }
    ]
  },
  "strategy": {
    "name": "string",
    "params": { "any": "json" },
    "assumptions": {
      "macro_lag_days": "integer",
      "financing_included": "boolean",
      "short_borrow_included": "boolean"
    }
  },
  "results": {
    "overall": {
      "metrics_net": {
        "cagr": "number",
        "vol_annual": "number",
        "sharpe": "number",
        "sortino": "number",
        "max_drawdown": "number",
        "calmar": "number"
      },
      "metrics_gross": {
        "cagr": "number",
        "vol_annual": "number",
        "sharpe": "number",
        "max_drawdown": "number"
      },
      "turnover": {
        "avg_daily": "number",
        "avg_rebalance": "number",
        "annualized": "number"
      },
      "costs": {
        "total_cost_return": "number",
        "avg_daily_cost_return": "number",
        "assumed_costs": {
          "use_meta_costs": "boolean",
          "cost_multiplier": "number"
        }
      },
      "exposure": {
        "gross_avg": "number",
        "gross_p95": "number",
        "net_avg": "number",
        "net_p95_abs": "number"
      }
    },
    "by_fold": [
      {
        "fold_id": "string",
        "metrics_net": {
          "cagr": "number",
          "vol_annual": "number",
          "sharpe": "number",
          "max_drawdown": "number"
        },
        "turnover_annualized": "number",
        "gross_avg": "number",
        "net_avg": "number"
      }
    ],
    "cost_stress": [
      {
        "multiplier": "number",
        "metrics_net": {
          "cagr": "number",
          "vol_annual": "number",
          "sharpe": "number",
          "max_drawdown": "number"
        },
        "total_cost_return": "number"
      }
    ],
    "baselines": [
      {
        "name": "string",
        "params": { "any": "json" },
        "metrics_net": {
          "cagr": "number",
          "vol_annual": "number",
          "sharpe": "number",
          "max_drawdown": "number"
        }
      }
    ],
    "diagnostics": {
      "correlation_to": {
        "SPY": "number"
      },
      "risk_contrib_by_bucket_avg": {
        "equities": "number",
        "rates": "number",
        "commodities": "number",
        "credit": "number",
        "fx": "number"
      }
    }
  },
  "artifacts": {
    "figures": [
      { "name": "string", "path": "string" }
    ],
    "tables": [
      { "name": "string", "path": "string" }
    ]
  }
}
```

2. Example results.json payload (template)

```json
{
  "schema_version": "1.0",
  "run": {
    "run_id": "2026-02-10T153012Z_a13f2c",
    "exp_name": "macro_allocator_ls",
    "timestamp_utc": "2026-02-10T15:30:12Z",
    "git_commit": "3f9c1e2",
    "config_path": "experiments/macro/configs/macro_allocator_ls.yaml",
    "config_hash": "b1b6c4d9",
    "data_snapshot_id": "prices_close_20260210",
    "results_hash": "9d22fa0a"
  },
  "universe": {
    "tickers": ["SPY", "EFA", "EEM", "IEF", "TLT", "GLD", "DBC", "LQD"],
    "ticker_meta": [
      { "ticker": "SPY", "bucket": "equities", "cost_bps": 3.0, "per_asset_cap": 0.35 },
      { "ticker": "IEF", "bucket": "rates", "cost_bps": 2.0, "per_asset_cap": 0.35 }
    ],
    "constraints": {
      "gross_cap": 1.5,
      "net_target": 0.0,
      "net_band": 0.15,
      "bucket_gross_caps": {
        "equities": 0.8,
        "rates": 0.9,
        "commodities": 0.4,
        "credit": 0.3,
        "fx": 0.2
      }
    }
  },
  "evaluation": {
    "frequency": "daily",
    "rebalance_rule": "W-FRI",
    "calendar": "XNYS",
    "folds": [
      {
        "fold_id": "fold_0",
        "train_start": "2016-01-01",
        "train_end": "2020-12-31",
        "test_start": "2021-01-08",
        "test_end": "2021-12-31",
        "embargo_days": 5
      }
    ]
  },
  "strategy": {
    "name": "ts_trend_ls",
    "params": { "method": "ma_cross", "fast": 20, "slow": 120, "vol_scale_lookback": 63 },
    "assumptions": { "macro_lag_days": 30, "financing_included": false, "short_borrow_included": false }
  },
  "results": {
    "overall": {
      "metrics_net": {
        "cagr": 0.11,
        "vol_annual": 0.10,
        "sharpe": 1.05,
        "sortino": 1.35,
        "max_drawdown": -0.12,
        "calmar": 0.92
      },
      "metrics_gross": {
        "cagr": 0.14,
        "vol_annual": 0.10,
        "sharpe": 1.30,
        "max_drawdown": -0.11
      },
      "turnover": { "avg_daily": 0.012, "avg_rebalance": 0.18, "annualized": 3.0 },
      "costs": {
        "total_cost_return": -0.03,
        "avg_daily_cost_return": -0.00012,
        "assumed_costs": { "use_meta_costs": true, "cost_multiplier": 1.0 }
      },
      "exposure": { "gross_avg": 1.45, "gross_p95": 1.50, "net_avg": 0.02, "net_p95_abs": 0.12 }
    },
    "by_fold": [
      {
        "fold_id": "fold_0",
        "metrics_net": { "cagr": 0.10, "vol_annual": 0.10, "sharpe": 0.98, "max_drawdown": -0.13 },
        "turnover_annualized": 3.1,
        "gross_avg": 1.46,
        "net_avg": 0.01
      }
    ],
    "cost_stress": [
      { "multiplier": 1.0, "metrics_net": { "cagr": 0.11, "vol_annual": 0.10, "sharpe": 1.05, "max_drawdown": -0.12 }, "total_cost_return": -0.03 },
      { "multiplier": 2.0, "metrics_net": { "cagr": 0.09, "vol_annual": 0.10, "sharpe": 0.85, "max_drawdown": -0.13 }, "total_cost_return": -0.06 },
      { "multiplier": 4.0, "metrics_net": { "cagr": 0.06, "vol_annual": 0.10, "sharpe": 0.55, "max_drawdown": -0.15 }, "total_cost_return": -0.12 }
    ],
    "baselines": [
      { "name": "equal_weight_long_only", "params": {}, "metrics_net": { "cagr": 0.07, "vol_annual": 0.12, "sharpe": 0.55, "max_drawdown": -0.20 } },
      { "name": "60_40_proxy", "params": { "equity": "SPY", "bond": "IEF" }, "metrics_net": { "cagr": 0.08, "vol_annual": 0.09, "sharpe": 0.75, "max_drawdown": -0.15 } },
      { "name": "trend_only_no_regime", "params": { "method": "ma_cross", "fast": 20, "slow": 120 }, "metrics_net": { "cagr": 0.10, "vol_annual": 0.10, "sharpe": 0.95, "max_drawdown": -0.12 } }
    ],
    "diagnostics": {
      "correlation_to": { "SPY": 0.15 },
      "risk_contrib_by_bucket_avg": { "equities": 0.35, "rates": 0.40, "commodities": 0.15, "credit": 0.08, "fx": 0.02 }
    }
  },
  "artifacts": {
    "figures": [
      { "name": "equity_curve_net", "path": "figures/equity_curve_net.png" },
      { "name": "gross_net_exposure", "path": "figures/gross_net_exposure.png" }
    ],
    "tables": [
      { "name": "cost_stress", "path": "tables/cost_stress.csv" }
    ]
  }
}
```

Notes on keeping reporting stable

- Never rename top-level keys once you publish v1.0.
- Add new fields under `results.diagnostics` or as new objects (non-breaking).
- Keep metrics names stable; add new metrics rather than replacing.
- Store any heavy time series (weights, exposures) as artifact files (Parquet/CSV) referenced under `artifacts`, not embedded in results.json.
