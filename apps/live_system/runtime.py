"""Live runtime scaffolding built on strategy-framework contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
import alpha_core.strategy_framework.engine as strategy_engine
import alpha_core.strategy_framework.models as strategy_models


@dataclass(slots=True, frozen=True)
class LiveRunRequest:
    instruments: list[str]
    cycles: int
    storage_root: Path
    execute: bool


@dataclass(slots=True, frozen=True)
class LiveRunOutcome:
    run_id: str
    status: str
    cycles: int
    orders_emitted: int
    config_hash: str
    manifest_path: Path | None = None


class _StaticUniverseModel:
    def __init__(self, instruments: list[str]) -> None:
        self._instruments = instruments

    def select(self, state: strategy_models.MarketState) -> list[str]:
        del state
        return list(self._instruments)


class _ConstantAlphaModel:
    def generate(self, state: strategy_models.MarketState) -> list[strategy_models.Signal]:
        return [
            strategy_models.Signal(
                instrument_id=instrument_id,
                direction=strategy_models.SignalDirection.LONG,
                strength=Decimal("0.5"),
                confidence=Decimal("0.5"),
            )
            for instrument_id in state.universe
        ]


class _EqualWeightPortfolioModel:
    def targets(
        self,
        signals: list[strategy_models.Signal],
        state: strategy_models.MarketState,
    ) -> list[strategy_models.Target]:
        del state
        if not signals:
            return []
        target_weight = Decimal("1") / Decimal(len(signals))
        return [
            strategy_models.Target(
                instrument_id=signal.instrument_id,
                target_weight=target_weight,
                direction=signal.direction,
            )
            for signal in signals
        ]


class _PassThroughRiskModel:
    def apply(
        self,
        targets: list[strategy_models.Target],
        state: strategy_models.MarketState,
    ) -> list[strategy_models.Target]:
        del state
        return targets


class _MarketExecutionModel:
    def create_orders(
        self,
        targets: list[strategy_models.Target],
        state: strategy_models.MarketState,
    ) -> list[strategy_models.OrderIntent]:
        del state
        return [
            strategy_models.OrderIntent(
                instrument_id=target.instrument_id,
                order_type=strategy_models.OrderType.MARKET,
                direction=target.direction,
                size=Decimal("1"),
            )
            for target in targets
        ]


def run_live_scaffold(request: LiveRunRequest) -> LiveRunOutcome:
    if request.cycles <= 0:
        raise ValueError("`cycles` must be > 0")
    instruments = _normalize_instruments(request.instruments)
    payload = {"cycles": request.cycles, "instruments": instruments}
    run_context = run_context_mod.make_run_context("live", config_payload=payload)
    orders_emitted = _simulate_orders(instruments=instruments, cycles=request.cycles)
    if not request.execute:
        return LiveRunOutcome(
            run_id=run_context.run_id,
            status="planned",
            cycles=request.cycles,
            orders_emitted=orders_emitted,
            config_hash=run_context.config_hash,
            manifest_path=None,
        )

    completed_context = run_context_mod.close_run_context(run_context)
    run_root = artifact_paths.run_root(request.storage_root, completed_context.run_id)
    run_root.mkdir(parents=True, exist_ok=True)

    config_path = artifact_paths.run_config_path(request.storage_root, completed_context.run_id)
    config_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    summary_path = artifact_paths.artifact_key_path(
        request.storage_root,
        completed_context.run_id,
        "live_summary.json",
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_payload = {
        "cycles": request.cycles,
        "instruments": instruments,
        "orders_emitted": orders_emitted,
    }
    summary_path.write_text(json.dumps(summary_payload, indent=2, sort_keys=True), encoding="utf-8")

    artifacts = {"config": str(config_path), "live_summary": str(summary_path)}
    artifact_paths.write_artifacts_index(request.storage_root, completed_context.run_id, artifacts)

    manifest = manifest_mod.RunManifest(run=completed_context, artifacts=artifacts)
    manifest_path = artifact_paths.run_manifest_path(request.storage_root, completed_context.run_id)
    manifest_mod.write_run_manifest(manifest_path, manifest)
    return LiveRunOutcome(
        run_id=completed_context.run_id,
        status="materialized",
        cycles=request.cycles,
        orders_emitted=orders_emitted,
        config_hash=completed_context.config_hash,
        manifest_path=manifest_path,
    )


def list_recent_live_runs(storage_root: Path, *, limit: int = 5) -> list[LiveRunOutcome]:
    if limit <= 0:
        raise ValueError("`limit` must be > 0")
    manifests = sorted(
        (storage_root / "runs").glob("*/manifest.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    outcomes: list[LiveRunOutcome] = []
    for manifest_path in manifests:
        manifest = manifest_mod.read_run_manifest(manifest_path)
        if manifest.run.run_type != "live":
            continue
        cycles, orders_emitted = _read_live_summary(
            manifest.artifacts.get("live_summary"),
            storage_root=storage_root,
            run_id=manifest.run.run_id,
        )
        outcomes.append(
            LiveRunOutcome(
                run_id=manifest.run.run_id,
                status="materialized",
                cycles=cycles,
                orders_emitted=orders_emitted,
                config_hash=manifest.run.config_hash,
                manifest_path=manifest_path,
            )
        )
        if len(outcomes) >= limit:
            break
    return outcomes


def _simulate_orders(*, instruments: list[str], cycles: int) -> int:
    engine = strategy_engine.StrategyEngine(
        universe=_StaticUniverseModel(instruments),
        alpha=_ConstantAlphaModel(),
        portfolio=_EqualWeightPortfolioModel(),
        risk=_PassThroughRiskModel(),
        execution=_MarketExecutionModel(),
    )
    orders_emitted = 0
    for _ in range(cycles):
        state = strategy_models.MarketState(
            as_of_utc=datetime.now(tz=UTC), universe=list(instruments)
        )
        orders_emitted += len(engine.step(state))
    return orders_emitted


def _normalize_instruments(instruments: list[str]) -> list[str]:
    normalized = [instrument.strip() for instrument in instruments if instrument.strip()]
    return sorted(dict.fromkeys(normalized))


def _read_live_summary(
    summary_path_raw: str | None,
    *,
    storage_root: Path,
    run_id: str,
) -> tuple[int, int]:
    if summary_path_raw is None:
        return (0, 0)
    summary_path = Path(summary_path_raw)
    if not summary_path.exists():
        return (0, 0)

    allowed_root = artifact_paths.run_root(storage_root, run_id).resolve()
    try:
        resolved_summary_path = summary_path.resolve()
        resolved_summary_path.relative_to(allowed_root)
    except (OSError, ValueError):
        return (0, 0)

    try:
        payload = json.loads(resolved_summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (0, 0)
    if not isinstance(payload, dict):
        return (0, 0)
    cycles = payload.get("cycles", 0)
    orders = payload.get("orders_emitted", 0)
    if not isinstance(cycles, int) or not isinstance(orders, int):
        return (0, 0)
    return (cycles, orders)


__all__ = ["LiveRunOutcome", "LiveRunRequest", "list_recent_live_runs", "run_live_scaffold"]
