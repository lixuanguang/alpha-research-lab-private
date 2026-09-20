"""Connect verified saved inputs to observations, independent risk, fills and accounting."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

# project library imports
from accounting import Ledger, LedgerState
from market_data.query import QueryReader
from market_data.replay import Replay
from research.experiments import (
    AttemptHistory,
    AttemptStore,
    ClearMLDestination,
    ClearMLPublication,
    ExperimentSpec,
    Fingerprint,
    TemporalSplit,
)
from research.observations import Observations
from runtime import ImplementationIdentity
from serialization import DomainCodec
from simulation import (
    BacktestSpec,
    EconomicCheckpoint,
    EconomicResult,
    SpotSimulation,
    VectorbtAdapter,
)
from strategies import Momentum, NoTrade


class _Rules:
    """Resolve only reviewed installed rule implementations for this application."""

    definitions: ClassVar[dict[str, type[Momentum] | type[NoTrade]]] = {
        "completed-price-momentum-v1": Momentum,
        "no-trade-v1": NoTrade,
    }


def run_backtest(
    reader: QueryReader,
    spec: BacktestSpec,
    *,
    batch_size: int = 256,
    checkpoint: EconomicCheckpoint | None = None,
    stop_at: datetime | None = None,
) -> EconomicResult | EconomicCheckpoint:
    """Execute or resume one isolated spot economy using the existing verified replay iterator.

    Args:
        reader: Admitted saved query inputs; this workflow never acquires data implicitly.
        spec: Explicit instance, binding, clocks, size, costs and independent limits.
        batch_size: Query delivery bound, excluded from economic identity.
        checkpoint: Complete economic/source state; a source cursor alone is unsupported.
        stop_at: Optional completed-step checkpoint clock before the terminal; no result claim.

    Returns:
        Reconciled terminal result or complete checkpoint at the explicit stop boundary.

    Raises:
        ValueError: Inputs, rules, state, scope or required valuation are incompatible.
    """
    codec = DomainCodec()
    spec = codec.decode_json(codec.encode_json(spec), BacktestSpec)
    definition = _Rules.definitions.get(spec.rule)
    if definition is None:
        raise ValueError(f"unsupported installed target rule: {spec.rule}")
    if checkpoint is not None:
        checkpoint = codec.decode_json(codec.encode_json(checkpoint), EconomicCheckpoint)
        if checkpoint.spec_identity != spec.identity:
            raise ValueError("checkpoint economic assumptions changed")
    if stop_at is not None:
        BacktestSpec._require_utc(stop_at, field_name="stop_at")
        if not spec.start <= stop_at < spec.end or (
            checkpoint is not None and stop_at <= checkpoint.cursor.clock
        ):
            raise ValueError("checkpoint stop must advance within the sample")
    replay = Replay(
        reader,
        (spec.binding[2],),
        start=spec.start,
        end=spec.end,
        terminal=spec.end,
        config_identity=spec.identity,
        batch_size=batch_size,
        cursor=None if checkpoint is None else checkpoint.cursor,
    )
    state = None if checkpoint is None else checkpoint.state
    observations = Observations(
        spec.binding,
        replay.evidence,
        tick=spec.limits.tick,
        cadence=timedelta(seconds=spec.cadence_seconds),
        max_age=timedelta(seconds=spec.max_age_seconds),
        state=None if state is None else state.observations,
    )
    if any(evidence.request.instrument.product != "spot" for evidence in observations.evidence):
        raise ValueError("economic simulation supports spot inputs only")
    ledger = Ledger(
        LedgerState(initial_cash=spec.initial_cash, dimension=spec.quantity.dimension)
        if state is None
        else state.ledger
    )
    simulation = SpotSimulation(spec, observations, definition(), ledger, state=state)
    while True:
        scheduled = simulation.scheduled_at
        if stop_at is not None:
            scheduled = min(scheduled, stop_at)
        cursor = replay.step(scheduled, simulation.consume)
        if cursor is None:
            completed = replay.cursor
            if completed is None:
                raise ValueError("replay has no completed cursor")
            return simulation.result(completed)
        if stop_at is not None and cursor.clock == stop_at:
            return simulation.checkpoint(cursor)


def compare_vectorbt(
    reader: QueryReader,
    spec: BacktestSpec,
    *,
    family: str,
    split: TemporalSplit,
    attempts: Path,
    tracking: ClearMLDestination,
) -> AttemptHistory:
    """Retain a formal vectorbt comparison and publish through MR 4's recoverable outbox.

    Args:
        reader: Verified immutable reference input, without implicit acquisition.
        spec: Explicit supported economic assumptions and rule.
        family: Declared synthetic study family, distinct from empirical baseline acceptance.
        split: Existing no-fit study partition; this slice permits validation access only.
        attempts: Single-writer attempt store retaining failures and exact/approximate results.
        tracking: Required ClearML destination; unavailable transport leaves recoverable intent.

    Returns:
        Completed retained attempt after acknowledged publication; exact ledger remains separate.

    Raises:
        ValueError: Configuration, study scope, economics or adapter capabilities are invalid.
        Exception: Execution or publication fails; retained outcomes and retry identity survive.
    """
    spec.__post_init__()
    split.__post_init__()
    if (
        split.fit_mode != "none"
        or not split.validation.start <= spec.start < spec.end <= split.validation.end
    ):
        raise ValueError("vectorbt comparison requires an explicit no-fit validation window")
    codec = DomainCodec()
    experiment = ExperimentSpec(
        family=family,
        inputs=(
            Fingerprint(name="snapshot", sha256=reader.identity),
            Fingerprint(name="economics", sha256=spec.identity),
        ),
        components=(Fingerprint(name="implementation", sha256=ImplementationIdentity.sha256()),),
        parameters=(
            ("scope", "synthetic single-instrument spot vectorbt comparison"),
            ("engine", "vectorbt/numba"),
        ),
        seeds=(("deterministic", 0),),
        environment_sha256=ExperimentSpec.installed_environment(),
        split=split,
    )
    with AttemptStore(attempts) as store:
        publication = ClearMLPublication(store, tracking)
        start = store.start(
            experiment,
            at=datetime.now(UTC),
            invocation="applications.backtest.compare_vectorbt",
            request=codec.encode_json(spec),
        )
        publication.enqueue(start.attempt_id)
        try:
            exact = run_backtest(reader, spec)
            if not isinstance(exact, EconomicResult):
                raise ValueError("reference economics did not reach terminal completion")
            store.retain(start.attempt_id, "economic-reference", codec.encode_json(exact))
            approximate = VectorbtAdapter.run(exact)
            payload = codec.encode_json(approximate)
            store.retain(start.attempt_id, "vectorbt-comparison", payload)
            store.finish(
                start.attempt_id,
                status="completed",
                at=datetime.now(UTC),
                reason="Reconciled exact reference and bounded vectorbt comparison",
                result=payload,
            )
        except (Exception, KeyboardInterrupt) as error:
            if store.read(start.attempt_id).status == "incomplete":
                store.finish(
                    start.attempt_id,
                    status="abandoned" if isinstance(error, KeyboardInterrupt) else "failed",
                    at=datetime.now(UTC),
                    reason=f"{type(error).__name__}: {error}",
                )
            publication.publish(start.attempt_id)
            raise
        publication.publish(start.attempt_id)
        return store.read(start.attempt_id)
