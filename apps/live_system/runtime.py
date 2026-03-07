"""Live runtime built on strategy-framework contracts.

Public surface:
- ``LiveRuntime`` — startup/shutdown lifecycle; per-cycle event processing.
- ``LiveRuntimeConfig`` — typed configuration injected at construction time.
- ``CycleResult`` — per-cycle output (orders + metrics snapshot).
- ``RuntimeMetrics`` — monotonically-accumulating counters emitted by the runtime.
- ``run_live_scaffold`` / ``list_recent_live_runs`` — retained for backward compat
  with the existing CLI; internally delegate to ``LiveRuntime``.

Default strategy components (``_Static*`` / ``_Constant*``) ship with the
module so the CLI can run without external configuration.  Production usage
should inject custom implementations via ``LiveRuntimeConfig``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
import alpha_core.strategy_framework.engine as strategy_engine
import alpha_core.strategy_framework.interfaces as strategy_interfaces
import alpha_core.strategy_framework.models as strategy_models

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request / outcome dataclasses (preserved for backward compat)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Runtime metrics + per-cycle output
# ---------------------------------------------------------------------------


@dataclass
class RuntimeMetrics:
    """Monotonically-accumulating counters maintained by :class:`LiveRuntime`."""

    cycles_completed: int = 0
    total_signals: int = 0
    total_targets: int = 0
    total_orders: int = 0
    total_errors: int = 0
    started_at: datetime | None = None
    last_cycle_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycles_completed": self.cycles_completed,
            "total_signals": self.total_signals,
            "total_targets": self.total_targets,
            "total_orders": self.total_orders,
            "total_errors": self.total_errors,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
        }


@dataclass(frozen=True)
class CycleResult:
    """Output produced by one :meth:`LiveRuntime.step` call."""

    cycle_index: int
    as_of_utc: datetime
    orders: list[strategy_models.OrderIntent]
    metrics_snapshot: dict[str, Any]


# ---------------------------------------------------------------------------
# LiveRuntimeConfig — typed injection surface
# ---------------------------------------------------------------------------


@dataclass
class LiveRuntimeConfig:
    """Configuration for :class:`LiveRuntime`.

    Every strategy component is optional; defaults are the simple stub
    implementations bundled in this module.
    """

    instruments: list[str] = field(default_factory=list)
    universe_model: strategy_interfaces.UniverseModel | None = None
    alpha_model: strategy_interfaces.AlphaModel | None = None
    portfolio_model: strategy_interfaces.PortfolioConstructionModel | None = None
    risk_model: strategy_interfaces.RiskModel | None = None
    execution_model: strategy_interfaces.ExecutionModel | None = None
    strategy_id: str = "default"
    log_level: int = logging.INFO


# ---------------------------------------------------------------------------
# Default strategy component stubs
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# LiveRuntime — primary class
# ---------------------------------------------------------------------------


class LiveRuntime:
    """Live strategy runtime wired on strategy-framework protocol contracts.

    Lifecycle::

        runtime = LiveRuntime(config)
        runtime.startup()
        try:
            for state in event_feed:
                result = runtime.step(state)
                # hand result.orders to router / venue adapter
        finally:
            runtime.shutdown()

    All strategy components are pluggable via :class:`LiveRuntimeConfig`.
    Defaults are provided so the runtime is runnable without custom code.
    """

    def __init__(self, config: LiveRuntimeConfig | None = None) -> None:
        self._config = config or LiveRuntimeConfig()
        self._metrics = RuntimeMetrics()
        self._engine: strategy_engine.StrategyEngine | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def startup(self) -> None:
        """Initialise components and mark the runtime as running.

        Idempotent — calling twice is a no-op (logs a warning).
        """
        if self._running:
            log.warning("LiveRuntime.startup() called on already-running runtime; ignoring.")
            return

        instruments = self._config.instruments or []
        self._engine = strategy_engine.StrategyEngine(
            universe=self._config.universe_model or _StaticUniverseModel(instruments),
            alpha=self._config.alpha_model or _ConstantAlphaModel(),
            portfolio=self._config.portfolio_model or _EqualWeightPortfolioModel(),
            risk=self._config.risk_model or _PassThroughRiskModel(),
            execution=self._config.execution_model or _MarketExecutionModel(),
        )
        self._metrics.started_at = datetime.now(tz=UTC)
        self._running = True
        log.info(
            "LiveRuntime started: strategy_id=%s instruments=%d",
            self._config.strategy_id,
            len(instruments),
        )

    def shutdown(self) -> None:
        """Tear down components and mark the runtime as stopped.

        Idempotent — calling on a stopped runtime logs a debug message.
        """
        if not self._running:
            log.debug("LiveRuntime.shutdown() called on already-stopped runtime; ignoring.")
            return
        self._running = False
        self._engine = None
        log.info(
            "LiveRuntime stopped: cycles=%d orders=%d errors=%d",
            self._metrics.cycles_completed,
            self._metrics.total_orders,
            self._metrics.total_errors,
        )

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Per-cycle processing
    # ------------------------------------------------------------------

    def step(self, state: strategy_models.MarketState) -> CycleResult:
        """Process one market-state snapshot and return order intents.

        Raises :class:`RuntimeError` if the runtime has not been started.
        Exceptions raised by strategy components are caught, counted in
        ``metrics.total_errors``, and re-raised so callers can decide whether
        to abort or continue cycling.
        """
        if not self._running or self._engine is None:
            raise RuntimeError("LiveRuntime must be started before calling step()")

        cycle_index = self._metrics.cycles_completed
        try:
            orders = self._engine.step(state)
        except Exception:
            self._metrics.total_errors += 1
            log.exception("Error in strategy engine step (cycle=%d)", cycle_index)
            raise

        self._metrics.cycles_completed += 1
        self._metrics.last_cycle_at = datetime.now(tz=UTC)
        self._metrics.total_orders += len(orders)

        log.debug(
            "cycle=%d orders=%d as_of=%s",
            cycle_index,
            len(orders),
            state.as_of_utc.isoformat(),
        )

        return CycleResult(
            cycle_index=cycle_index,
            as_of_utc=state.as_of_utc,
            orders=orders,
            metrics_snapshot=self._metrics.as_dict(),
        )

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @property
    def metrics(self) -> RuntimeMetrics:
        """Read-only view of accumulated runtime metrics."""
        return self._metrics


# ---------------------------------------------------------------------------
# Scaffold helpers (backward-compat CLI helpers)
# ---------------------------------------------------------------------------


def run_live_scaffold(request: LiveRunRequest) -> LiveRunOutcome:
    """Run the live scaffold using :class:`LiveRuntime` and persist artifacts when executing."""
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
    """Run N strategy cycles via LiveRuntime and return total orders emitted."""
    runtime = LiveRuntime(LiveRuntimeConfig(instruments=instruments))
    runtime.startup()
    orders_total = 0
    try:
        for _ in range(cycles):
            state = strategy_models.MarketState(
                as_of_utc=datetime.now(tz=UTC), universe=list(instruments)
            )
            result = runtime.step(state)
            orders_total += len(result.orders)
    finally:
        runtime.shutdown()
    return orders_total


def _normalize_instruments(instruments: list[str]) -> list[str]:
    normalized = [instrument.strip() for instrument in instruments if instrument.strip()]
    return sorted(dict.fromkeys(normalized))


def _read_live_summary(
    summary_path_raw: str | None,
    *,
    storage_root: Path,
    run_id: str,
) -> tuple[int, int]:
    summary_path = artifact_paths.resolve_registered_artifact_path(
        storage_root,
        run_id,
        summary_path_raw,
    )
    if summary_path is None:
        return (0, 0)

    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (0, 0)
    if not isinstance(payload, dict):
        return (0, 0)
    cycles = payload.get("cycles", 0)
    orders = payload.get("orders_emitted", 0)
    if not isinstance(cycles, int) or not isinstance(orders, int):
        return (0, 0)
    return (cycles, orders)


__all__ = [
    "CycleResult",
    "LiveRunOutcome",
    "LiveRunRequest",
    "LiveRuntime",
    "LiveRuntimeConfig",
    "RuntimeMetrics",
    "list_recent_live_runs",
    "run_live_scaffold",
]
