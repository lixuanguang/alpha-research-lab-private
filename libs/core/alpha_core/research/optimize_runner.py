"""OptimizeRunner — grid/random parameter sweep over the backtest/evaluate pipeline.

Optimization steps (see :meth:`OptimizeRunner.run`)
-----------------------------------------------------
1. Expand the ``parameter_space`` into a trial list (grid or random).
2. For each trial: run :class:`BacktestRunner` then :class:`EvaluateRunner`.
3. Tag each trial as ``ok``, ``constraint_violation``, or ``failed``.
4. Sort feasible trials by the objective metric; build top-N leaderboard.
5. Persist:
   - ``trial_registry.jsonl``   — one JSON record per trial
   - ``trial_registry.parquet`` — same records in columnar form
   - ``leaderboard.json``       — top-N feasible trials
   - ``best_manifest.json``     — reference to the best trial's run artifacts

Parameter space contract
------------------------
``parameter_space`` maps parameter name to a list of candidate values.

Supported parameter names:
- ``threshold``      — z-score entry threshold passed to the strategy.
- ``target_weight``  — fractional portfolio weight per position.
- ``starting_cash``  — initial notional cash for the simulation.

Grid search: cartesian product of all lists (capped to *max_trials*).
Random search: sample without replacement using *seed* (capped to *max_trials*).
"""

from __future__ import annotations

import itertools
import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.backtest_runner as backtest_runner_mod
import alpha_core.research.evaluate_runner as evaluate_runner_mod
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
from alpha_core.research.artifact_store import FilesystemArtifactStore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REGISTRY_SCHEMA_VERSION: int = 1
_SUPPORTED_PARAMS: frozenset[str] = frozenset({"threshold", "target_weight", "starting_cash"})
_STRATEGY_PARAMS: frozenset[str] = frozenset({"threshold", "target_weight"})

TrialStatus = Literal["ok", "constraint_violation", "failed"]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class OptimizeConfig(BaseModel):
    """Configuration for a parameter-sweep optimization run."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1)
    feature_set_version: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1, description="Base strategy id (e.g. 'zscore_v1').")
    search_mode: Literal["grid", "random"] = Field(
        default="grid",
        description="'grid' expands the full cartesian product; 'random' samples uniformly.",
    )
    parameter_space: dict[str, list[float]] = Field(
        description=(
            "Maps parameter name to candidate values. "
            f"Supported keys: {sorted(_SUPPORTED_PARAMS)}."
        ),
    )
    objective: str = Field(
        default="sharpe_ratio",
        description=(
            "Metric key from the evaluation run to maximise (or minimise). "
            "Example values: 'sharpe_ratio', 'total_return', 'win_rate'."
        ),
    )
    objective_minimize: bool = Field(
        default=False,
        description="Set True to minimise the objective instead of maximising it.",
    )
    constraints: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Minimum acceptable metric values. Trials that violate any constraint are "
            "tagged 'constraint_violation' and excluded from the leaderboard. "
            "Example: {'trade_count': 5.0, 'win_rate': 0.4}."
        ),
    )
    max_trials: int = Field(default=20, gt=0, description="Maximum trials to evaluate.")
    top_n: int = Field(default=5, gt=0, description="Number of top trials to include in leaderboard.")
    seed: int = Field(default=42, description="RNG seed for reproducible random search.")
    starting_cash: float = Field(default=100_000.0, gt=0)
    engine: backtest_runner_mod.EngineType = "event"

    @field_validator("dataset_id", "feature_set_version", "strategy_id", "objective")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must not be blank")
        return cleaned

    @model_validator(mode="after")
    def _validate_parameter_space(self) -> "OptimizeConfig":
        unknown = set(self.parameter_space) - _SUPPORTED_PARAMS
        if unknown:
            raise ValueError(
                f"Unsupported parameter_space keys: {sorted(unknown)}. "
                f"Supported: {sorted(_SUPPORTED_PARAMS)}."
            )
        for key, values in self.parameter_space.items():
            if not values:
                raise ValueError(f"parameter_space['{key}'] must not be empty.")
        return self


# ---------------------------------------------------------------------------
# Trial record
# ---------------------------------------------------------------------------


class TrialRecord(BaseModel):
    """One row in the trial registry."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=_REGISTRY_SCHEMA_VERSION)
    optimize_run_id: str
    trial_index: int
    backtest_run_id: str
    evaluate_run_id: str
    params: dict[str, float]
    metrics: dict[str, float]
    objective_value: float
    constraint_pass: bool
    status: TrialStatus


# ---------------------------------------------------------------------------
# Optimize manifest
# ---------------------------------------------------------------------------


class OptimizeManifest(BaseModel):
    """Persistent metadata for a completed optimization run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1)
    run_id: str
    dataset_id: str
    feature_set_version: str
    strategy_id: str
    search_mode: str
    objective: str
    objective_minimize: bool
    total_trials: int
    feasible_trials: int
    best_backtest_run_id: str | None
    best_objective_value: float | None
    built_at: datetime
    artifacts: dict[str, str]
    parent_run_id: str | None = None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OptimizeRunError(RuntimeError):
    """Raised when an optimization run cannot proceed."""


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class OptimizeRunner:
    """Sweeps backtest/evaluate over a parameter grid and persists trial artifacts.

    Parameters
    ----------
    storage_root:
        Shared storage root used by all research runners.
    store:
        Optional pre-built :class:`~alpha_core.research.artifact_store.FilesystemArtifactStore`.
        Defaults to a new store backed by *storage_root*.
    """

    def __init__(
        self,
        storage_root: Path,
        store: FilesystemArtifactStore | None = None,
    ) -> None:
        self._storage_root = storage_root
        self._store = store if store is not None else FilesystemArtifactStore(storage_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        config: OptimizeConfig,
        *,
        feature_run_id: str,
        config_payload: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
    ) -> OptimizeManifest:
        """Execute the optimization sweep and persist all artifacts.

        Parameters
        ----------
        config:
            Optimization configuration.
        feature_run_id:
            Run id from a completed ``build-features`` run.  Its
            ``features.parquet`` is consumed by every backtest trial.
        config_payload:
            Optional serialized config dict for run-manifest hashing.
        parent_run_id:
            Optional upstream run id for lineage tracking.

        Returns
        -------
        OptimizeManifest
            Metadata for the completed sweep, also persisted to disk.
        """
        effective_payload = (
            config_payload if config_payload is not None else config.model_dump(mode="json")
        )
        run_context = run_context_mod.make_run_context(
            "optimize", config_payload=effective_payload
        )
        optimize_run_id = run_context.run_id

        trial_params = _expand_parameter_space(config)

        bt_runner = backtest_runner_mod.BacktestRunner(self._storage_root, self._store)
        ev_runner = evaluate_runner_mod.EvaluateRunner(self._storage_root, self._store)

        records: list[TrialRecord] = []
        for index, params in enumerate(trial_params):
            record = _run_trial(
                index=index,
                params=params,
                config=config,
                feature_run_id=feature_run_id,
                optimize_run_id=optimize_run_id,
                bt_runner=bt_runner,
                ev_runner=ev_runner,
            )
            records.append(record)

        feasible = [r for r in records if r.constraint_pass and r.status == "ok"]
        reverse_sort = not config.objective_minimize
        feasible_sorted = sorted(
            feasible,
            key=lambda r: r.objective_value,
            reverse=reverse_sort,
        )
        leaderboard = feasible_sorted[: config.top_n]

        best = leaderboard[0] if leaderboard else None
        artifact_map = self._persist_artifacts(
            optimize_run_id=optimize_run_id,
            records=records,
            leaderboard=leaderboard,
            best_record=best,
        )

        completed_context = run_context_mod.close_run_context(run_context)
        built_at = completed_context.completed_at_utc or datetime.now(tz=UTC)

        manifest = OptimizeManifest(
            run_id=optimize_run_id,
            dataset_id=config.dataset_id,
            feature_set_version=config.feature_set_version,
            strategy_id=config.strategy_id,
            search_mode=config.search_mode,
            objective=config.objective,
            objective_minimize=config.objective_minimize,
            total_trials=len(records),
            feasible_trials=len(feasible),
            best_backtest_run_id=best.backtest_run_id if best else None,
            best_objective_value=best.objective_value if best else None,
            built_at=built_at,
            artifacts=artifact_map,
            parent_run_id=parent_run_id,
        )

        manifest_path = self._store.prepare_path(optimize_run_id, "optimize_manifest.json")
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        artifact_map["optimize_manifest"] = str(manifest_path)

        manifest_mod.persist_run_record(
            storage_root=self._storage_root,
            run_context=completed_context,
            config_payload=effective_payload,
            artifacts=artifact_map,
            parent_run_id=parent_run_id,
        )
        return manifest

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist_artifacts(
        self,
        *,
        optimize_run_id: str,
        records: list[TrialRecord],
        leaderboard: list[TrialRecord],
        best_record: TrialRecord | None,
    ) -> dict[str, str]:
        artifact_map: dict[str, str] = {}

        # Trial registry — JSONL
        jsonl_path = self._store.prepare_path(optimize_run_id, "trial_registry.jsonl")
        with jsonl_path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(record.model_dump_json() + "\n")
        artifact_map["trial_registry_jsonl"] = str(jsonl_path)

        # Trial registry — Parquet
        parquet_path = self._store.prepare_path(optimize_run_id, "trial_registry.parquet")
        pq.write_table(_records_to_arrow(records), parquet_path, compression="zstd")
        artifact_map["trial_registry_parquet"] = str(parquet_path)

        # Leaderboard JSON
        leaderboard_path = self._store.prepare_path(optimize_run_id, "leaderboard.json")
        leaderboard_path.write_text(
            json.dumps(
                [r.model_dump(mode="json") for r in leaderboard],
                indent=2,
                sort_keys=True,
                default=str,
            ),
            encoding="utf-8",
        )
        artifact_map["leaderboard"] = str(leaderboard_path)

        # Best-run manifest reference
        if best_record is not None:
            best_ref_path = self._store.prepare_path(optimize_run_id, "best_manifest.json")
            best_ref_path.write_text(
                json.dumps(
                    {
                        "best_backtest_run_id": best_record.backtest_run_id,
                        "best_evaluate_run_id": best_record.evaluate_run_id,
                        "best_params": best_record.params,
                        "best_objective_value": best_record.objective_value,
                        "trial_index": best_record.trial_index,
                        "best_manifest_path": str(
                            artifact_paths.run_manifest_path(
                                self._storage_root, best_record.backtest_run_id
                            )
                        ),
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            artifact_map["best_manifest"] = str(best_ref_path)

        return artifact_map


# ---------------------------------------------------------------------------
# Trial execution
# ---------------------------------------------------------------------------


def _run_trial(
    *,
    index: int,
    params: dict[str, float],
    config: OptimizeConfig,
    feature_run_id: str,
    optimize_run_id: str,
    bt_runner: backtest_runner_mod.BacktestRunner,
    ev_runner: evaluate_runner_mod.EvaluateRunner,
) -> TrialRecord:
    starting_cash = params.get("starting_cash", config.starting_cash)
    strategy_params = {k: v for k, v in params.items() if k in _STRATEGY_PARAMS}

    bt_config = backtest_runner_mod.BacktestConfig(
        dataset_id=config.dataset_id,
        feature_set_version=config.feature_set_version,
        strategy_id=config.strategy_id,
        engine=config.engine,
        starting_cash=starting_cash,
        strategy_params=strategy_params,
    )

    try:
        bt_manifest = bt_runner.build(
            bt_config,
            config_payload={
                "optimize_run_id": optimize_run_id,
                "trial_index": index,
                **bt_config.model_dump(mode="json"),
            },
            parent_run_id=feature_run_id,
        )
    except Exception:  # noqa: BLE001
        return TrialRecord(
            optimize_run_id=optimize_run_id,
            trial_index=index,
            backtest_run_id="",
            evaluate_run_id="",
            params=params,
            metrics={},
            objective_value=float("-inf"),
            constraint_pass=False,
            status="failed",
        )

    try:
        ev_manifest = ev_runner.build(
            bt_manifest.run_id,
            parent_run_id=optimize_run_id,
        )
    except Exception:  # noqa: BLE001
        return TrialRecord(
            optimize_run_id=optimize_run_id,
            trial_index=index,
            backtest_run_id=bt_manifest.run_id,
            evaluate_run_id="",
            params=params,
            metrics={},
            objective_value=float("-inf"),
            constraint_pass=False,
            status="failed",
        )

    metrics = ev_manifest.metrics
    objective_value = float(metrics.get(config.objective, float("-inf")))

    constraint_pass = all(
        float(metrics.get(metric, float("-inf"))) >= min_value
        for metric, min_value in config.constraints.items()
    )
    status: TrialStatus = "ok" if constraint_pass else "constraint_violation"

    return TrialRecord(
        optimize_run_id=optimize_run_id,
        trial_index=index,
        backtest_run_id=bt_manifest.run_id,
        evaluate_run_id=ev_manifest.run_id,
        params=params,
        metrics=metrics,
        objective_value=objective_value,
        constraint_pass=constraint_pass,
        status=status,
    )


# ---------------------------------------------------------------------------
# Parameter space helpers
# ---------------------------------------------------------------------------


def _expand_parameter_space(config: OptimizeConfig) -> list[dict[str, float]]:
    """Return an ordered list of parameter dicts for all trials."""
    if not config.parameter_space:
        return [{}]

    keys = sorted(config.parameter_space)
    value_lists = [config.parameter_space[k] for k in keys]
    all_combos: list[dict[str, float]] = [
        dict(zip(keys, combo)) for combo in itertools.product(*value_lists)
    ]

    if config.search_mode == "grid":
        return all_combos[: config.max_trials]

    # Random: shuffle with seed, then take max_trials.
    rng = random.Random(config.seed)
    rng.shuffle(all_combos)
    return all_combos[: config.max_trials]


# ---------------------------------------------------------------------------
# Arrow serialization
# ---------------------------------------------------------------------------


def _records_to_arrow(records: list[TrialRecord]) -> pa.Table:
    """Convert trial records to a flat Arrow table for Parquet persistence."""
    if not records:
        schema = pa.schema(
            [
                pa.field("optimize_run_id", pa.string()),
                pa.field("trial_index", pa.int32()),
                pa.field("backtest_run_id", pa.string()),
                pa.field("evaluate_run_id", pa.string()),
                pa.field("objective_value", pa.float64()),
                pa.field("constraint_pass", pa.bool_()),
                pa.field("status", pa.string()),
            ]
        )
        return pa.table({name: [] for name in schema.names}, schema=schema)

    rows = [r.model_dump(mode="json") for r in records]
    # Flatten nested dicts into prefixed columns for Parquet compatibility.
    flat_rows: list[dict[str, Any]] = []
    for row in rows:
        flat: dict[str, Any] = {
            "optimize_run_id": row["optimize_run_id"],
            "trial_index": row["trial_index"],
            "backtest_run_id": row["backtest_run_id"],
            "evaluate_run_id": row["evaluate_run_id"],
            "objective_value": row["objective_value"],
            "constraint_pass": row["constraint_pass"],
            "status": row["status"],
        }
        for k, v in row.get("params", {}).items():
            flat[f"param_{k}"] = float(v)
        for k, v in row.get("metrics", {}).items():
            flat[f"metric_{k}"] = float(v)
        flat_rows.append(flat)

    return pa.Table.from_pandas(pd.DataFrame(flat_rows), preserve_index=False)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "OptimizeConfig",
    "OptimizeManifest",
    "OptimizeRunError",
    "OptimizeRunner",
    "TrialRecord",
    "TrialStatus",
]
