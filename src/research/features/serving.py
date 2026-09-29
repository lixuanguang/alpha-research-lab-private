"""Serve admitted exact features through isolated, immutable Feast generations.

The core runtime owns causal selection and version activation.  This bridge sends
one already admitted snapshot to the separately locked Feast worker and admits
only a byte-pinned, exact online response from that snapshot.
"""

from __future__ import annotations

# standard library imports
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

# project library imports
from research.features.offline import (
    FeastWorker,
    FeatureAccessError,
    OfflineFeatureDefinition,
)
from research.features.store import FeatureMaterialization
from serialization import DomainCodec, WireRecord

_MAX_ROWS = 4_096
_MAX_BYTES = 16 * 1024 * 1024


class FeastServingRow(WireRecord, frozen=True, kw_only=True):
    """Retain one authoritative entity row without approximating feature values."""

    entity: str
    event_at: datetime | None
    available_at: datetime | None
    expires_at: datetime | None
    values: tuple[str | None, ...]
    reasons: tuple[str, ...]
    source_version: str | None = None
    source_sha256: str | None = None
    dataset_version: str | None = None
    dataset_sha256: str | None = None
    revision_identity: str | None = None
    schema_version: Literal["feast-serving-row"] = "feast-serving-row"

    def __post_init__(self) -> None:
        """Validate exact values, nullable clocks and per-field quality reasons."""
        if self.schema_version != "feast-serving-row":
            raise ValueError("unsupported Feast serving row schema")
        OfflineFeatureDefinition._text(self.entity, "entity")
        if not self.values or len(self.values) != len(self.reasons):
            raise ValueError("Feast serving row fields and quality reasons differ")
        for value, reason in zip(self.values, self.reasons, strict=True):
            if value is not None:
                OfflineFeatureDefinition._ratio(value, "feature value")
            OfflineFeatureDefinition._text(reason, "quality reason")
        has_value = any(value is not None for value in self.values)
        clocks = (self.event_at, self.available_at, self.expires_at)
        if has_value and any(clock is None for clock in clocks):
            raise ValueError("non-null Feast serving row lacks source clocks")
        if any(clock is not None for clock in clocks):
            if any(clock is None for clock in clocks):
                raise ValueError("Feast serving row has partial source clocks")
            for name, clock in zip(("event_at", "available_at", "expires_at"), clocks, strict=True):
                if clock is not None:
                    self._require_utc(clock, field_name=name)
            if (
                self.event_at is not None
                and self.available_at is not None
                and self.expires_at is not None
                and not self.event_at <= self.available_at <= self.expires_at
            ):
                raise ValueError("Feast serving row clocks are out of order")
        lineage = (
            self.source_version,
            self.source_sha256,
            self.dataset_version,
            self.dataset_sha256,
        )
        if has_value and any(value is None for value in lineage):
            raise ValueError("non-null Feast serving row lacks source lineage")
        if any(value is not None for value in lineage):
            if any(value is None for value in lineage):
                raise ValueError("Feast serving row has partial source lineage")
            for name, value in (
                ("source_version", self.source_version),
                ("dataset_version", self.dataset_version),
            ):
                OfflineFeatureDefinition._text(value, name)
            for name, value in (
                ("source_sha256", self.source_sha256),
                ("dataset_sha256", self.dataset_sha256),
            ):
                OfflineFeatureDefinition._digest(value, name)
        if self.revision_identity is not None:
            OfflineFeatureDefinition._digest(self.revision_identity, "revision_identity")

    @property
    def identity(self) -> str:
        """Hash exact values, clocks and lineage for the worker's online parity check."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class FeastServingSnapshot(WireRecord, frozen=True, kw_only=True):
    """Bind a named version to one complete, causally admitted entity snapshot."""

    definition_identity: str
    schema_identity: str
    materialization_identity: str
    version: str
    cutoff: datetime
    field_names: tuple[str, ...]
    rows: tuple[FeastServingRow, ...]
    sdk_version: str = "0.66.0"
    schema_version: Literal["feast-serving-snapshot"] = "feast-serving-snapshot"

    def __post_init__(self) -> None:
        """Require one bounded, unique, exact snapshot with no future source row."""
        if self.schema_version != "feast-serving-snapshot":
            raise ValueError("unsupported Feast serving snapshot schema")
        OfflineFeatureDefinition._digest(self.definition_identity, "definition_identity")
        OfflineFeatureDefinition._digest(self.schema_identity, "schema_identity")
        OfflineFeatureDefinition._digest(self.materialization_identity, "materialization_identity")
        OfflineFeatureDefinition._text(self.version, "version")
        OfflineFeatureDefinition._text(self.sdk_version, "sdk_version")
        self._require_utc(self.cutoff, field_name="cutoff")
        if not self.field_names or len(set(self.field_names)) != len(self.field_names):
            raise ValueError("Feast serving feature signature is empty or duplicated")
        for name in self.field_names:
            OfflineFeatureDefinition._text(name, "feature name")
        if not self.rows or len(self.rows) > _MAX_ROWS:
            raise ValueError("Feast serving snapshot exceeds the bounded entity grid")
        seen: set[str] = set()
        for row in self.rows:
            if type(row) is not FeastServingRow:
                raise TypeError("Feast serving snapshot requires exact row records")
            row.__post_init__()
            if row.entity in seen or len(row.values) != len(self.field_names):
                raise ValueError(
                    "Feast serving snapshot has duplicate entities or mismatched fields"
                )
            seen.add(row.entity)
            if row.event_at is not None and row.event_at > self.cutoff:
                raise ValueError("Feast serving snapshot contains a future event")
            if row.available_at is not None and row.available_at > self.cutoff:
                raise ValueError("Feast serving snapshot contains a late unavailable row")
            if (
                any(value is not None for value in row.values)
                and row.expires_at is not None
                and row.expires_at < self.cutoff
            ):
                raise ValueError("Feast serving snapshot contains an expired value")

    @property
    def identity(self) -> str:
        """Return the content identity of the admitted online generation."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    @classmethod
    def from_materialization(
        cls, materialization: FeatureMaterialization, *, sdk_version: str = "0.66.0"
    ) -> FeastServingSnapshot:
        """Project the authoritative version into exact Feast source strings.

        Args:
            materialization: Immutable causal snapshot from ``VersionedFeatureStore``.
            sdk_version: Separately locked Feast SDK version required by the worker.

        Returns:
            A versioned snapshot preserving per-field missingness and source lineage.
        """
        materialization.__post_init__()
        field_names = tuple(field.name for field in materialization.definition.fields)
        rows: list[FeastServingRow] = []
        for result in materialization.rows:
            feature = result.feature
            if feature is None:
                rows.append(
                    FeastServingRow(
                        entity=result.entity,
                        event_at=None,
                        available_at=None,
                        expires_at=None,
                        values=tuple(None for _ in field_names),
                        reasons=tuple(result.status for _ in field_names),
                    )
                )
                continue
            vector = feature.vector
            if vector.fields != materialization.definition.fields:
                raise FeatureAccessError("materialized vector signature differs from schema")
            rows.append(
                FeastServingRow(
                    entity=result.entity,
                    event_at=vector.event_at,
                    available_at=vector.available_at,
                    expires_at=vector.expires_at,
                    values=tuple(
                        None if value is None else f"{value.numerator}/{value.denominator}"
                        for value in vector.values
                    ),
                    reasons=vector.reasons,
                    source_version=feature.source_version,
                    source_sha256=feature.source_sha256,
                    dataset_version=feature.dataset_version,
                    dataset_sha256=feature.dataset_sha256,
                    revision_identity=feature.revision_identity,
                )
            )
        return cls(
            definition_identity=materialization.definition.identity,
            schema_identity=materialization.definition.schema.identity,
            materialization_identity=materialization.identity,
            version=materialization.version,
            cutoff=materialization.at,
            field_names=field_names,
            rows=tuple(rows),
            sdk_version=sdk_version,
        )

    def row(self, entity: str) -> FeastServingRow:
        """Select an explicitly materialized entity from this generation.

        Args:
            entity: Complete entity key retained in the snapshot.

        Returns:
            Authoritative row, including explicit missing values and reasons.

        Raises:
            FeatureAccessError: The entity was not part of the named generation.
        """
        for row in self.rows:
            if row.entity == entity:
                return row
        raise FeatureAccessError("entity is not present in the Feast serving generation")


class FeastGeneration(WireRecord, frozen=True, kw_only=True):
    """Pin an immutable local Feast registry, source and SQLite online store."""

    snapshot_identity: str
    repository_path: str
    registry_sha256: str
    source_sha256: str
    online_sha256: str
    config_sha256: str
    sdk_version: str
    schema_version: Literal["feast-generation"] = "feast-generation"

    def __post_init__(self) -> None:
        """Reject unpinned or relative Feast generation paths."""
        if self.schema_version != "feast-generation":
            raise ValueError("unsupported Feast generation schema")
        for name, digest in (
            ("snapshot_identity", self.snapshot_identity),
            ("registry_sha256", self.registry_sha256),
            ("source_sha256", self.source_sha256),
            ("online_sha256", self.online_sha256),
            ("config_sha256", self.config_sha256),
        ):
            OfflineFeatureDefinition._digest(digest, name)
        OfflineFeatureDefinition._text(self.sdk_version, "sdk_version")
        if not Path(self.repository_path).is_absolute():
            raise ValueError("Feast generation repository must be an absolute path")


class FeastServedRow(WireRecord, frozen=True, kw_only=True):
    """Expose an exact online value with named version and explicit freshness state."""

    snapshot_identity: str
    version: str
    entity: str
    requested_at: datetime
    status: Literal["ready", "missing", "expired"]
    values: tuple[str | None, ...]
    reasons: tuple[str, ...]
    row_identity: str | None
    event_at: datetime | None
    available_at: datetime | None
    expires_at: datetime | None
    source_version: str | None
    source_sha256: str | None
    dataset_version: str | None
    dataset_sha256: str | None
    revision_identity: str | None
    schema_version: Literal["feast-served-row"] = "feast-served-row"

    def __post_init__(self) -> None:
        """Validate served status, exact values and retained source quality metadata."""
        if self.schema_version != "feast-served-row":
            raise ValueError("unsupported Feast served row schema")
        OfflineFeatureDefinition._digest(self.snapshot_identity, "snapshot_identity")
        OfflineFeatureDefinition._text(self.version, "version")
        OfflineFeatureDefinition._text(self.entity, "entity")
        self._require_utc(self.requested_at, field_name="requested_at")
        if self.status not in ("ready", "missing", "expired"):
            raise ValueError("unsupported Feast served status")
        if len(self.values) != len(self.reasons):
            raise ValueError("served values and quality reasons differ")
        for value, reason in zip(self.values, self.reasons, strict=True):
            if value is not None:
                OfflineFeatureDefinition._ratio(value, "served value")
            OfflineFeatureDefinition._text(reason, "served reason")
        if self.status != "ready" and any(value is not None for value in self.values):
            raise ValueError("missing or expired Feast rows cannot expose values")
        if self.status == "ready" and not any(value is not None for value in self.values):
            raise ValueError("ready Feast row requires an exact value")
        for name, clock in (
            ("event_at", self.event_at),
            ("available_at", self.available_at),
            ("expires_at", self.expires_at),
        ):
            if clock is not None:
                self._require_utc(clock, field_name=name)
        if self.status == "ready" and (
            self.available_at is None
            or self.expires_at is None
            or self.available_at > self.requested_at
            or self.expires_at < self.requested_at
        ):
            raise ValueError("ready Feast row is unavailable or expired")
        if self.status == "expired" and (
            self.expires_at is None or self.expires_at >= self.requested_at
        ):
            raise ValueError("expired Feast row lacks a past expiry")
        if self.row_identity is not None:
            OfflineFeatureDefinition._digest(self.row_identity, "row_identity")
        for name, digest in (
            ("source_sha256", self.source_sha256),
            ("dataset_sha256", self.dataset_sha256),
            ("revision_identity", self.revision_identity),
        ):
            if digest is not None:
                OfflineFeatureDefinition._digest(digest, name)


class FeastServingBridge:
    """Admit a real Feast worker generation and exact online response."""

    def __init__(self, worker: FeastWorker) -> None:
        """Bind the isolated worker selected by the application composition root.

        Args:
            worker: Separately locked subprocess callable accepting bounded JSON.
        """
        self._worker = worker
        self._codec = DomainCodec()

    def materialize(self, snapshot: FeastServingSnapshot, root: Path) -> FeastGeneration:
        """Publish an immutable Feast SQLite generation for admitted source rows.

        Args:
            snapshot: Causal, exact snapshot supplied by the authoritative store.
            root: Absolute local directory for immutable Feast generations.

        Returns:
            Registry, source, SQLite and snapshot bindings of the published generation.

        Raises:
            FeatureAccessError: The worker fails or returns a different generation.
        """
        snapshot.__post_init__()
        if not root.is_absolute():
            raise ValueError("Feast generation root must be absolute")
        payload = self._codec.encode_json(
            {
                "schema_version": "feast-materialize-request",
                "snapshot": snapshot,
                "snapshot_identity": snapshot.identity,
                "root": str(root),
                "row_identities": tuple(row.identity for row in snapshot.rows),
            }
        )
        raw = self._call(payload)
        try:
            result = self._codec.decode_json(raw, FeastGeneration)
        except (TypeError, ValueError) as error:
            raise FeatureAccessError("Feast worker returned invalid generation JSON") from error
        if (
            result.snapshot_identity != snapshot.identity
            or result.sdk_version != snapshot.sdk_version
        ):
            raise FeatureAccessError("Feast generation differs from admitted snapshot")
        if Path(result.repository_path) != root / snapshot.identity:
            raise FeatureAccessError("Feast generation path differs from admitted snapshot")
        return result

    def open_generation(self, snapshot: FeastServingSnapshot, root: Path) -> FeastGeneration:
        """Reopen a published receipt for serving after process restart.

        Args:
            snapshot: Authoritative materialization selected by the active store version.
            root: Absolute parent directory used for immutable Feast generations.

        Returns:
            Pinned generation receipt after local source, registry and SQLite checks.

        Raises:
            FeatureAccessError: The generation is absent, malformed or modified.
        """
        snapshot.__post_init__()
        if not root.is_absolute():
            raise ValueError("Feast generation root must be absolute")
        repository = root / snapshot.identity
        try:
            manifest: object = json.loads(
                (repository / "generation.json").read_text(encoding="utf-8")
            )
            manifest_map = self._mapping(manifest, "generation manifest")
            encoded = self._codec.encode_json({**manifest_map, "repository_path": str(repository)})
            result = self._codec.decode_json(encoded, FeastGeneration)
        except (OSError, TypeError, ValueError) as error:
            raise FeatureAccessError("Feast serving generation is unavailable") from error
        if (
            result.snapshot_identity != snapshot.identity
            or result.sdk_version != snapshot.sdk_version
        ):
            raise FeatureAccessError("Feast generation differs from active snapshot")
        for name, expected in (
            ("registry.db", result.registry_sha256),
            ("features.parquet", result.source_sha256),
            ("online.db", result.online_sha256),
        ):
            try:
                actual = hashlib.sha256((repository / "data" / name).read_bytes()).hexdigest()
            except OSError as error:
                raise FeatureAccessError("Feast generation file is unavailable") from error
            if actual != expected:
                raise FeatureAccessError("Feast generation file differs from pinned receipt")
        try:
            actual_config = hashlib.sha256(
                (repository / "feature_store.yaml").read_bytes()
            ).hexdigest()
        except OSError as error:
            raise FeatureAccessError("Feast generation configuration is unavailable") from error
        if actual_config != result.config_sha256:
            raise FeatureAccessError("Feast generation configuration differs from pinned receipt")
        return result

    @staticmethod
    def _mapping(value: object, name: str) -> dict[str, object]:
        """Narrow a decoded local receipt before binding it to a typed generation."""
        if not isinstance(value, dict) or any(type(key) is not str for key in value):
            raise ValueError(f"{name} must be a JSON object")
        return {str(key): cast(object, item) for key, item in value.items()}

    def retrieve(
        self,
        snapshot: FeastServingSnapshot,
        generation: FeastGeneration,
        entity: str,
        at: datetime,
    ) -> FeastServedRow:
        """Read one named generation and refuse stale or mismatched Feast values.

        Args:
            snapshot: Exact source snapshot for this named version.
            generation: Previously verified immutable Feast generation receipt.
            entity: Explicit entity key in the snapshot.
            at: UTC serving time at or after the materialization cutoff.

        Returns:
            Exact, quality-bearing online value or explicit missing/expired row.

        Raises:
            FeatureAccessError: Version, bytes, entity, clocks or values differ.
        """
        snapshot.__post_init__()
        generation.__post_init__()
        snapshot._require_utc(at, field_name="serving time")
        if at < snapshot.cutoff:
            raise FeatureAccessError(
                "online latest-value retrieval cannot replay an earlier cutoff"
            )
        if (
            generation.snapshot_identity != snapshot.identity
            or generation.sdk_version != snapshot.sdk_version
        ):
            raise FeatureAccessError("Feast generation differs from requested snapshot")
        source = snapshot.row(entity)
        payload = self._codec.encode_json(
            {
                "schema_version": "feast-serve-request",
                "generation": generation,
                "snapshot_identity": snapshot.identity,
                "entity": entity,
                "field_names": snapshot.field_names,
            }
        )
        raw = self._call(payload)
        try:
            response = self._codec.decode_json(raw, _FeastOnlineResponse)
        except (TypeError, ValueError) as error:
            raise FeatureAccessError("Feast worker returned invalid online JSON") from error
        if response.snapshot_identity != snapshot.identity or response.entity != entity:
            raise FeatureAccessError("Feast online response entity or generation differs")
        expected_identity = (
            source.identity if any(value is not None for value in source.values) else None
        )
        if expected_identity != response.row_identity or source.values != response.values:
            raise FeatureAccessError("Feast online values or source identity differ")
        if source.values == tuple(None for _ in source.values):
            status: Literal["ready", "missing", "expired"] = "missing"
            values = source.values
            reasons = source.reasons
        elif source.expires_at is not None and at > source.expires_at:
            status = "expired"
            values = tuple(None for _ in source.values)
            reasons = tuple(
                "expired" if value is not None else reason
                for value, reason in zip(source.values, source.reasons, strict=True)
            )
        else:
            status = "ready"
            values = source.values
            reasons = source.reasons
        return FeastServedRow(
            snapshot_identity=snapshot.identity,
            version=snapshot.version,
            entity=entity,
            requested_at=at,
            status=status,
            values=values,
            reasons=reasons,
            row_identity=source.identity if status != "missing" else None,
            event_at=source.event_at,
            available_at=source.available_at,
            expires_at=source.expires_at,
            source_version=source.source_version,
            source_sha256=source.source_sha256,
            dataset_version=source.dataset_version,
            dataset_sha256=source.dataset_sha256,
            revision_identity=source.revision_identity,
        )

    def _call(self, payload: bytes) -> bytes:
        """Enforce one bounded worker exchange and convert subprocess failures."""
        if not payload or len(payload) > _MAX_BYTES:
            raise FeatureAccessError("Feast serving request exceeds the bounded JSON budget")
        try:
            raw = self._worker(payload)
        except FeatureAccessError:
            raise
        except Exception as error:
            raise FeatureAccessError("Feast serving worker failed") from error
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BYTES:
            raise FeatureAccessError("Feast serving worker returned invalid bytes")
        return raw


class _FeastOnlineResponse(WireRecord, frozen=True, kw_only=True):
    """Carry the worker's unadmitted exact online payload for source comparison."""

    snapshot_identity: str
    entity: str
    row_identity: str | None
    values: tuple[str | None, ...]
    schema_version: Literal["feast-online-response"] = "feast-online-response"

    def __post_init__(self) -> None:
        """Reject malformed, approximate or unpinned online values."""
        if self.schema_version != "feast-online-response":
            raise ValueError("unsupported Feast online response schema")
        OfflineFeatureDefinition._digest(self.snapshot_identity, "snapshot_identity")
        OfflineFeatureDefinition._text(self.entity, "entity")
        if self.row_identity is not None:
            OfflineFeatureDefinition._digest(self.row_identity, "row_identity")
        for value in self.values:
            if value is not None:
                OfflineFeatureDefinition._ratio(value, "online value")
