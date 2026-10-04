"""Compose causal incremental materialization and strict online intent consumption."""

from __future__ import annotations

# standard library imports
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

# project library imports
from research.features import (
    FeastServingBridge,
    FeastServingSnapshot,
    FeatureAccessError,
    FeatureKernel,
    FeatureMaterialization,
    FeatureSession,
    FeatureStoreDefinition,
    FeatureStoreResult,
    FittedTransform,
    StoredFeature,
    TransformVersion,
    VersionedFeatureStore,
)
from research.observations import DecisionSource
from serialization import DomainCodec, WireRecord
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


def materialize_features(
    store: VersionedFeatureStore,
    definition: FeatureStoreDefinition,
    *,
    source: DecisionSource,
    kernel: FeatureKernel,
    instance: str,
    entities: tuple[str, ...],
    decisions: tuple[datetime, ...],
    source_version: str,
    source_sha256: str,
    dataset_version: str,
    dataset_sha256: str,
    version: str,
    bridge: FeastServingBridge,
    serving_root: Path,
    transform: FittedTransform | None = None,
    transform_version: TransformVersion | None = None,
) -> FeatureMaterialization:
    """Commit each vector with its successor state, then publish and activate verified Feast.

    The caller supplies admitted immutable source/dataset identities. Every row
    retains the source's actual input lineage. A retry resumes committed cutoffs.
    The snapshot at the last decision is prepared, its Feast generation published
    and read back, and only then appended, so a reader of the version's stream
    never finds a snapshot without its generation. Calling again with the same
    version and later decisions extends that stream; an interrupted publication
    leaves the preceding snapshot and active version intact.
    A fitted definition (one with ``transform_identity``) is materialized with
    the study's ``FittedTransform`` and its retained ``TransformVersion``: each raw
    vector is transformed with that state, never refitted, and stored under the
    definition's output fields. A decision before the version's availability is
    refused by the transform itself.
    """
    if (
        not entities
        or len(set(entities)) != len(entities)
        or not decisions
        or tuple(sorted(set(decisions))) != decisions
        or kernel.schema != definition.schema
        or (definition.transform_identity is None) != (transform_version is None)
        or (transform is None) != (transform_version is None)
        or (
            transform is not None
            and transform_version is not None
            and (
                definition.transform_identity != transform_version.identity
                or definition.output_fields != transform_version.output_fields
                or transform.identity != transform_version.implementation
            )
        )
        or (definition.schema.mode == "incremental" and definition.instance != instance)
        or source.requirements != kernel.schema.inputs
        or source_version != source.identity
    ):
        raise ValueError("materialization requires matching source/schema and ordered unique scope")
    store.register(definition)
    expected_active = store.active_version(definition)
    codec = DomainCodec()
    for entity in entities:
        checkpoint = store.get_checkpoint(
            definition,
            instance,
            entity,
            source_version=source_version,
            source_sha256=source_sha256,
            dataset_version=dataset_version,
            dataset_sha256=dataset_sha256,
        )
        session = FeatureSession(kernel, instance=instance, entity=entity, checkpoint=checkpoint)
        for at in decisions:
            if (
                checkpoint is not None
                and checkpoint.last_at is not None
                and at <= checkpoint.last_at
            ):
                continue
            vector = session.evaluate(source.read(entity, at))
            if transform is not None and transform_version is not None:
                vector = transform.apply(transform_version, vector)
            row = StoredFeature(
                definition_identity=definition.identity,
                vector=vector,
                source_version=source_version,
                source_sha256=source_sha256,
                dataset_version=dataset_version,
                dataset_sha256=dataset_sha256,
                revision_identity=hashlib.sha256(
                    codec.encode_json((vector.identity, source_version, dataset_version))
                ).hexdigest(),
            )
            store.append(definition, row, checkpoint=session.checkpoint())
    prepared = store.prepare(definition, version, decisions[-1], entities)
    snapshot = FeastServingSnapshot.from_materialization(prepared)
    generation = bridge.materialize(snapshot, serving_root)
    for entity in entities:
        bridge.retrieve(snapshot, generation, entity, decisions[-1])
    materialization = store.materialize(
        definition, version, decisions[-1], entities, expected_identity=prepared.identity
    )
    store.activate_if_current(definition, version, expected_active)
    return materialization


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
