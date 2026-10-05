"""Serve candidates their pinned feature-store streams, offline or through isolated Feast."""

from __future__ import annotations

# standard library imports
import sqlite3
from datetime import datetime
from pathlib import Path

# project library imports
from research.features import (
    FeastServingBridge,
    FeastServingSnapshot,
    FeatureAccessError,
    FeatureVector,
    VersionedFeatureStore,
)
from runtime.candidates import CandidateSession, CandidateStep, LoadedCandidate
from serialization import WireRecord


class ServedFeature(WireRecord, frozen=True):
    """Carry one served, already transformed vector and the exact snapshot that served it.

    ``stream`` is the pinned version stream's identity; ``materialization`` is the
    snapshot's identity at ``materialized_at``. Replay reopens that snapshot.
    """

    vector: FeatureVector
    stream: str
    version: str
    materialized_at: datetime
    materialization: str
    served_at: datetime

    def __post_init__(self) -> None:
        """Bind the vector and snapshot to one serving cutoff."""
        if type(self.vector) is not FeatureVector:
            raise TypeError("served feature requires a feature vector")
        self.vector.__post_init__()
        self._require_utc(self.materialized_at, field_name="materialized_at")
        self._require_utc(self.served_at, field_name="served_at")
        for value in (self.stream, self.materialization):
            if type(value) is not str or len(value) != 64:
                raise ValueError("served feature requires stream and snapshot identities")
        if type(self.version) is not str or not self.version.strip():
            raise ValueError("served feature requires a version")
        if self.materialized_at > self.served_at or self.vector.available_at > self.served_at:
            raise ValueError("served feature cannot come from a later snapshot or value")

    @property
    def entity(self) -> str:
        """Return the served entity."""
        return self.vector.entity


class ServedFeatures:
    """Read a candidate's pinned stream at a cutoff, or name why it cannot serve.

    Both input modes serve only the pinned version's snapshot exactly at the
    cutoff, so a decision at t reads what research reads at t. Offline serving
    also compares it with authoritative point-in-time retrieval and refuses a
    missing snapshot. Online serving requires the pinned version to be active,
    reads the snapshot's immutable Feast generation, and names a snapshot not yet
    published ``feature-pending``, which a caller may wait for; so is a stream whose
    publisher has not yet published at all. A changed active
    version, a missing, expired or future value, or an unavailable store or Feast
    worker is a reason, never a substitute value. Already fitted transforms are
    never reapplied.
    """

    def __init__(
        self,
        store: VersionedFeatureStore,
        *,
        bridge: FeastServingBridge | None = None,
        serving_root: Path | None = None,
    ) -> None:
        """Bind the authoritative store and optional isolated Feast serving access."""
        self._store = store
        self._bridge = bridge
        self._serving_root = serving_root

    def serve(self, loaded: LoadedCandidate, at: datetime) -> ServedFeature | str:
        """Return the candidate's served feature exactly at ``at``, or the pause reason.

        Raises:
            ValueError: The deployment's binding or the store's data are invalid, or
                an offline cutoff has no snapshot.
        """
        deployment, definition = loaded.deployment, loaded.store_definition
        version = deployment.feature_version
        if definition is None or version is None or deployment.input_mode == "source":
            raise ValueError("candidate deployment has no feature-store binding")
        stream = VersionedFeatureStore.stream_identity(definition, version)
        if deployment.source_identity != stream:
            raise ValueError("candidate deployment differs from its pinned feature stream")
        online = deployment.input_mode == "online_features"
        if online and (self._bridge is None or self._serving_root is None):
            raise ValueError("online candidate requires its isolated Feast bridge")
        try:
            if online:
                published = self._store.published_version(definition)
                if published is None:
                    return "feature-pending"
                if published != version:
                    return "feature-version-changed"
            snapshot = self._store.exact_materialization(definition, version, at)
            if snapshot is None:
                if not online:
                    raise ValueError("offline candidate cutoff has no snapshot in its stream")
                return "feature-pending"
            pinned = next((row for row in snapshot.rows if row.entity == deployment.entity), None)
            if pinned is None:
                raise ValueError("candidate entity is absent from its stream snapshot")
            if not online:
                result = self._store.retrieve_offline(definition, deployment.entity, at)
                if pinned.feature != result.feature or pinned.status != result.status:
                    raise ValueError("candidate PIT retrieval differs from its stream snapshot")
            if pinned.status != "ready":
                return pinned.status
            if online and self._bridge is not None and self._serving_root is not None:
                serving = FeastServingSnapshot.from_materialization(snapshot)
                generation = self._bridge.open_generation(serving, self._serving_root)
                served = self._bridge.retrieve(serving, generation, deployment.entity, at)
                if served.status != "ready":
                    return served.status
        except FeatureAccessError, OSError, sqlite3.Error:
            return "feature-service-unavailable"
        return ServedFeature(
            vector=pinned.require_ready(),
            stream=stream,
            version=version,
            materialized_at=snapshot.at,
            materialization=snapshot.identity,
            served_at=at,
        )

    def verify(self, loaded: LoadedCandidate, served: ServedFeature) -> None:
        """Reopen the exact snapshot a retained served feature names and compare its value.

        Raises:
            ValueError: The stream, snapshot or value differs from the store.
        """
        served.__post_init__()
        deployment, definition = loaded.deployment, loaded.store_definition
        version = deployment.feature_version
        if (
            definition is None
            or version is None
            or served.version != version
            or served.stream != VersionedFeatureStore.stream_identity(definition, version)
            or served.entity != deployment.entity
        ):
            raise ValueError("served feature differs from the candidate's pinned stream")
        snapshot = self._store.get_materialization(definition, version, served.materialized_at)
        row = next((item for item in snapshot.rows if item.entity == deployment.entity), None)
        if (
            served.materialized_at != served.served_at
            or snapshot.at != served.materialized_at
            or snapshot.identity != served.materialization
            or row is None
            or row.vector != served.vector
        ):
            raise ValueError("served feature differs from its retained snapshot")


class CandidateFeatureFeed:
    """Consume a pinned feature stream without advancing state on serving failure."""

    def __init__(
        self,
        store: VersionedFeatureStore,
        *,
        bridge: FeastServingBridge | None = None,
        serving_root: Path | None = None,
    ) -> None:
        """Bind authoritative store and optional isolated Feast serving access."""
        self._served = ServedFeatures(store, bridge=bridge, serving_root=serving_root)

    def evaluate(self, session: CandidateSession, at: datetime) -> CandidateStep:
        """Evaluate one cutoff against the deployment's exact feature stream.

        A changed active version, missing or stale value, or unavailable serving
        dependency yields a pause without committing the candidate checkpoint.
        Invalid deployment bindings, cutoffs and inconsistent store data raise.
        """
        session.admit_cutoff(at)
        served = self._served.serve(session.loaded, at)
        if isinstance(served, str):
            return session.pause(at, served)
        return session.evaluate_feature(served.vector, at)
