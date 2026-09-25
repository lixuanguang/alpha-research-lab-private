"""Bind a candidate session to pinned offline or isolated online features."""

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
    VersionedFeatureStore,
)
from runtime.candidates import CandidateSession, CandidateStep


class CandidateFeatureFeed:
    """Consume a pinned feature version without advancing state on serving failure.

    Offline reads compare the selected immutable materialization with
    authoritative point-in-time retrieval. Online reads also verify the actual
    isolated Feast generation and active version. Already fitted transforms in
    the store are never reapplied.
    """

    def __init__(
        self,
        store: VersionedFeatureStore,
        *,
        bridge: FeastServingBridge | None = None,
        serving_root: Path | None = None,
    ) -> None:
        """Bind authoritative store and optional isolated Feast serving access."""
        self._store = store
        self._bridge = bridge
        self._serving_root = serving_root

    def evaluate(self, session: CandidateSession, at: datetime) -> CandidateStep:
        """Evaluate one cutoff against the deployment's exact feature binding.

        A changed active version, missing or stale value, or unavailable serving
        dependency yields a pause without committing the candidate checkpoint.
        Invalid deployment bindings, cutoffs and inconsistent store data raise.
        """
        loaded = session.loaded
        deployment, definition = loaded.deployment, loaded.store_definition
        if (
            definition is None
            or deployment.feature_version is None
            or deployment.input_mode == "source"
        ):
            raise ValueError("candidate deployment has no feature-store binding")
        if deployment.input_mode == "online_features" and (
            self._bridge is None or self._serving_root is None
        ):
            raise ValueError("online candidate requires its isolated Feast bridge")
        session.admit_cutoff(at)
        try:
            materialization = self._store.get_materialization(
                definition, deployment.feature_version
            )
            if materialization.identity != deployment.source_identity:
                raise ValueError("candidate materialization differs from pinned deployment")
            if deployment.input_mode == "offline_features":
                if at != materialization.at:
                    raise ValueError("offline candidate cutoff differs from pinned materialization")
                result = self._store.retrieve_offline(definition, deployment.entity, at)
                pinned = next(
                    (row for row in materialization.rows if row.entity == deployment.entity),
                    None,
                )
                if (
                    pinned is None
                    or pinned.feature != result.feature
                    or pinned.status != result.status
                ):
                    raise ValueError("candidate PIT retrieval differs from pinned materialization")
            else:
                result = self._store.retrieve_online(
                    definition,
                    deployment.entity,
                    at,
                    max_materialization_age_us=min(
                        *(item.max_age_us for item in loaded.manifest.inputs),
                        *(
                            requirement.max_freshness_us
                            for requirement in loaded.manifest.requirements
                            if requirement.name in {item.name for item in loaded.manifest.inputs}
                            and requirement.max_freshness_us is not None
                        ),
                    ),
                )
                if result.version != deployment.feature_version:
                    return session.pause(at, "feature-version-changed")
                if result.status != "ready":
                    return session.pause(at, result.status)
                if self._bridge is None or self._serving_root is None:
                    raise ValueError("online candidate requires its isolated Feast bridge")
                snapshot = FeastServingSnapshot.from_materialization(materialization)
                generation = self._bridge.open_generation(snapshot, self._serving_root)
                served = self._bridge.retrieve(snapshot, generation, deployment.entity, at)
                if served.status != "ready":
                    return session.pause(at, served.status)
            if result.status != "ready":
                return session.pause(at, result.status)
        except FeatureAccessError, OSError, sqlite3.Error:
            return session.pause(at, "feature-service-unavailable")
        return session.evaluate_feature(result.require_ready(), at)
