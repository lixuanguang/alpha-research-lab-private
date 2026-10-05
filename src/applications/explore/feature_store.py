"""Compose causal incremental materialization and strict online intent consumption."""

from __future__ import annotations

# standard library imports
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

# project library imports
from research.features import (
    FeastServingBridge,
    FeastServingSnapshot,
    FeatureAccessError,
    FeatureStoreDefinition,
    FeatureStoreResult,
    VersionedFeatureStore,
)
from serialization import WireRecord
from strategies import DecisionContext, DecisionRecord, DecisionSession, DecisionState


class ServedDecision(WireRecord, frozen=True, kw_only=True):
    """Retain an intent or explicit pause with unchanged policy state on serving failure."""

    status: Literal["decided", "paused"]
    reason: str
    feature: FeatureStoreResult | None
    decision: DecisionRecord | None
    checkpoint: DecisionState

    def __post_init__(self) -> None:
        """Prevent a pause from masquerading as an executable decision."""
        if self.status not in ("decided", "paused") or not self.reason:
            raise ValueError("served decision requires a status and reason")
        if (self.status == "decided") != (self.decision is not None):
            raise ValueError("served decision status differs from its intent")
        self.checkpoint.__post_init__()
        if self.feature is not None:
            self.feature.__post_init__()
        if self.decision is not None:
            self.decision.__post_init__()
            if self.feature is None or self.feature.status != "ready":
                raise ValueError("served decision requires a ready feature")


def run_served_decision(
    store: VersionedFeatureStore,
    definition: FeatureStoreDefinition,
    *,
    entity: str,
    at: datetime,
    session: DecisionSession,
    bridge: FeastServingBridge,
    serving_root: Path,
) -> ServedDecision:
    """Read the pinned active Feast generation and pause on missing, stale or lost service.

    Exact feature clocks and lineage remain unchanged while the decision records
    its own consuming time. This MR05/MR07 prerequisite emits intents only; it
    does not grant account authority, reserve risk or submit orders. Incompatible
    definitions and malformed strategy transitions fail explicitly.
    """
    result: FeatureStoreResult | None = None
    try:
        result = store.retrieve_online(definition, entity, at)
        if result.status != "ready" or result.version is None:
            return ServedDecision(
                status="paused",
                reason=result.status,
                feature=result,
                decision=None,
                checkpoint=session.checkpoint(),
            )
        if result.materialized_at is None:
            raise FeatureAccessError("ready online feature lacks its snapshot cutoff")
        materialization = store.get_materialization(
            definition, result.version, result.materialized_at
        )
        snapshot = FeastServingSnapshot.from_materialization(materialization)
        generation = bridge.open_generation(snapshot, serving_root)
        served = bridge.retrieve(snapshot, generation, entity, at)
        if served.status != "ready":
            return ServedDecision(
                status="paused",
                reason=served.status,
                feature=result,
                decision=None,
                checkpoint=session.checkpoint(),
            )
    except FeatureAccessError, OSError, sqlite3.Error:
        return ServedDecision(
            status="paused",
            reason="feature-service-unavailable",
            feature=result,
            decision=None,
            checkpoint=session.checkpoint(),
        )
    decision = session.evaluate(
        DecisionContext(features=result.require_ready(), prediction=None, evaluated_at=at)
    )
    return ServedDecision(
        status="decided",
        reason="verified-online-feature",
        feature=result,
        decision=decision,
        checkpoint=session.checkpoint(),
    )
