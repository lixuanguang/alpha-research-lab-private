"""Persist exact feature history and publish immutable, causal serving versions.

The store owns authoritative point-in-time selection. A serving adapter may copy a
materialization into another system, but that system does not infer revision or
availability eligibility. A version is a stream: an append-only sequence of complete
snapshots at strictly increasing cutoffs. SQLite transactions keep each snapshot and
the active version pointer separate, so a failed publication never exposes a partial
snapshot.
"""

from __future__ import annotations

# standard library imports
import hashlib
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, cast

# project library imports
from research.features.contracts import FeatureCheckpoint, FeatureSchema, FeatureVector
from research.observations import NumericField
from serialization import DomainCodec, WireRecord

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
FeatureQuality = Literal[
    "ready", "partial", "missing", "expired", "stale", "future", "unmaterialized"
]


class FeatureStoreError(ValueError):
    """Report an incompatible, ambiguous or corrupt feature-store operation."""


class FeatureStoreDefinition(WireRecord, frozen=True, kw_only=True):
    """Bind a named entity domain to one schema and optional fitted-state version."""

    name: str
    entity_type: str
    schema: FeatureSchema
    instance: str | None = None
    transform_identity: str | None = None
    output_fields: tuple[NumericField, ...] | None = None
    schema_version: Literal["feature-store-definition"] = "feature-store-definition"

    def __post_init__(self) -> None:
        """Refuse unnamed, unversioned or incompatible serving definitions."""
        if self.schema_version != "feature-store-definition":
            raise ValueError("unsupported feature-store definition schema")
        for value in (self.name, self.entity_type):
            if type(value) is not str or not value or value != value.strip():
                raise ValueError("feature-store definition requires trimmed names")
        if type(self.schema) is not FeatureSchema:
            raise TypeError("feature-store definition requires FeatureSchema")
        self.schema.__post_init__()
        if self.instance is not None and (
            type(self.instance) is not str
            or not self.instance
            or self.instance != self.instance.strip()
        ):
            raise ValueError("feature-store instance must be a trimmed name")
        if self.schema.mode == "incremental" and self.instance is None:
            raise ValueError("incremental feature store requires an isolated instance")
        if self.transform_identity is not None and (
            type(self.transform_identity) is not str
            or _SHA256.fullmatch(self.transform_identity) is None
        ):
            raise ValueError("fitted transform identity must be a SHA-256 digest")
        if self.output_fields is not None:
            if type(self.output_fields) is not tuple or not self.output_fields:
                raise ValueError("transformed output signature must be nonempty")
            for field in self.output_fields:
                if type(field) is not NumericField:
                    raise TypeError("transformed outputs require NumericField")
                field.__post_init__()
            if len({field.name for field in self.output_fields}) != len(self.output_fields):
                raise ValueError("transformed output names must be unique")
            if self.transform_identity is None and self.output_fields != self.schema.outputs:
                raise ValueError("changed output signature requires a fitted transform")

    @property
    def fields(self) -> tuple[NumericField, ...]:
        """Return the exact ordered served signature, after any fitted transform."""
        return self.schema.outputs if self.output_fields is None else self.output_fields

    @property
    def identity(self) -> str:
        """Identify the complete immutable serving definition."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class StoredFeature(WireRecord, frozen=True, kw_only=True):
    """Retain a vector and the actual source, dataset and correction revisions."""

    definition_identity: str
    vector: FeatureVector
    source_version: str
    source_sha256: str
    dataset_version: str
    dataset_sha256: str
    revision_identity: str
    schema_version: Literal["stored-feature"] = "stored-feature"

    def __post_init__(self) -> None:
        """Keep immutable lineage, exact values and source clocks verifiable."""
        if self.schema_version != "stored-feature":
            raise ValueError("unsupported stored-feature schema")
        for digest in (
            self.definition_identity,
            self.source_sha256,
            self.dataset_sha256,
            self.revision_identity,
        ):
            if type(digest) is not str or _SHA256.fullmatch(digest) is None:
                raise ValueError("stored feature requires SHA-256 lineage identities")
        for version in (self.source_version, self.dataset_version):
            if type(version) is not str or not version or version != version.strip():
                raise ValueError("stored feature requires named source and dataset versions")
        if type(self.vector) is not FeatureVector:
            raise TypeError("stored feature requires FeatureVector")
        self.vector.__post_init__()

    @property
    def identity(self) -> str:
        """Pin the exact vector, correction and source lineage for retry comparison."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class FeatureStoreResult(WireRecord, frozen=True, kw_only=True):
    """Return one exact feature and quality state at a requested knowledge cutoff."""

    definition_identity: str
    entity_type: str
    entity: str
    requested_at: datetime
    status: FeatureQuality
    feature: StoredFeature | None
    version: str | None = None
    materialized_at: datetime | None = None
    schema_version: Literal["feature-store-result"] = "feature-store-result"

    def __post_init__(self) -> None:
        """Reject result metadata that could disguise incompatible or future values."""
        if self.schema_version != "feature-store-result":
            raise ValueError("unsupported feature-store result schema")
        if (
            type(self.definition_identity) is not str
            or _SHA256.fullmatch(self.definition_identity) is None
        ):
            raise ValueError("feature-store result requires definition identity")
        for value in (self.entity_type, self.entity):
            if type(value) is not str or not value or value != value.strip():
                raise ValueError("feature-store result requires entity identity")
        self._require_utc(self.requested_at, field_name="requested_at")
        if self.status not in (
            "ready",
            "partial",
            "missing",
            "expired",
            "stale",
            "future",
            "unmaterialized",
        ):
            raise ValueError("unsupported feature-store quality")
        if (self.version is None) != (self.materialized_at is None):
            raise ValueError("serving version and cutoff must be supplied together")
        if self.version is not None and (
            type(self.version) is not str
            or not self.version
            or self.version != self.version.strip()
        ):
            raise ValueError("feature-store version must be a trimmed name")
        if self.materialized_at is not None:
            self._require_utc(self.materialized_at, field_name="materialized_at")
        if self.status == "unmaterialized" and self.version is not None:
            raise ValueError("unmaterialized result cannot name a serving version")
        if self.status == "future" and (
            self.materialized_at is None or self.materialized_at <= self.requested_at
        ):
            raise ValueError("future result requires a later materialization cutoff")
        if self.status == "stale" and (
            self.materialized_at is None or self.materialized_at > self.requested_at
        ):
            raise ValueError("stale result requires an earlier serving version")
        if self.feature is not None:
            if type(self.feature) is not StoredFeature:
                raise TypeError("feature-store result requires StoredFeature")
            self.feature.__post_init__()
            if (
                self.feature.definition_identity != self.definition_identity
                or self.feature.vector.entity != self.entity
            ):
                raise ValueError("feature-store result carries incompatible feature")
            if self.feature.vector.decision_at > self.requested_at:
                raise ValueError("feature-store result carries a future decision")
            if self.feature.vector.available_at > self.requested_at:
                raise ValueError("feature-store result carries unavailable feature")
            if self.status not in ("stale", "future", "unmaterialized"):
                vector = self.feature.vector
                if vector.expires_at < self.requested_at:
                    expected: FeatureQuality = "expired"
                else:
                    present = sum(value is not None for value in vector.values)
                    if present == 0:
                        expected = "missing"
                    elif present == len(vector.values):
                        expected = "ready"
                    else:
                        expected = "partial"
                if self.status != expected:
                    raise ValueError("feature-store quality differs from exact values")
        if self.status in ("future", "unmaterialized") and self.feature is not None:
            raise ValueError("unavailable serving result cannot expose a feature")
        if self.feature is None and self.status not in (
            "missing",
            "stale",
            "future",
            "unmaterialized",
        ):
            raise ValueError("feature-store quality requires a feature")

    @property
    def vector(self) -> FeatureVector | None:
        """Expose the exact vector while retaining its source and dataset lineage."""
        return None if self.feature is None else self.feature.vector

    def require_ready(self) -> FeatureVector:
        """Return only a complete fresh vector for a strict consuming strategy."""
        if self.status != "ready" or self.feature is None:
            raise FeatureStoreError(f"feature is {self.status}")
        return self.feature.vector


class FeatureMaterialization(WireRecord, frozen=True, kw_only=True):
    """Retain a complete immutable named snapshot before active-version publication."""

    definition: FeatureStoreDefinition
    version: str
    at: datetime
    rows: tuple[FeatureStoreResult, ...]
    schema_version: Literal["feature-materialization"] = "feature-materialization"

    def __post_init__(self) -> None:
        """Require a complete, unique entity set at one causal cutoff."""
        if self.schema_version != "feature-materialization":
            raise ValueError("unsupported feature materialization schema")
        if type(self.definition) is not FeatureStoreDefinition:
            raise TypeError("materialization requires FeatureStoreDefinition")
        self.definition.__post_init__()
        if (
            type(self.version) is not str
            or not self.version
            or self.version != self.version.strip()
        ):
            raise ValueError("materialization requires a trimmed version name")
        self._require_utc(self.at, field_name="at")
        if type(self.rows) is not tuple or not self.rows:
            raise ValueError("materialization requires explicit entity rows")
        seen: set[str] = set()
        for row in self.rows:
            if type(row) is not FeatureStoreResult:
                raise TypeError("materialization rows must be FeatureStoreResult")
            row.__post_init__()
            if (
                row.definition_identity != self.definition.identity
                or row.entity_type != self.definition.entity_type
                or row.requested_at != self.at
                or row.version != self.version
                or row.materialized_at != self.at
                or row.status not in ("ready", "partial", "missing", "expired")
                or row.entity in seen
            ):
                raise ValueError("materialization contains incompatible or duplicate rows")
            seen.add(row.entity)

    @property
    def identity(self) -> str:
        """Pin every published entity, exact value, revision and missing result."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class VersionedFeatureStore:
    """Own durable causal history, immutable snapshots and atomic activation."""

    def __init__(self, path: Path) -> None:
        """Bind a store path; use :meth:`open` to initialize durable state."""
        if not isinstance(path, Path):
            raise TypeError("feature-store path must be Path")
        self._path = path
        self._codec = DomainCodec()

    @classmethod
    def open(cls, path: Path) -> VersionedFeatureStore:
        """Create or reopen the SQLite store and its transactional schema."""
        store = cls(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(store._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS definitions (
                    identity TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    payload BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feature_rows (
                    definition_identity TEXT NOT NULL,
                    entity TEXT NOT NULL,
                    decision_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    revision_identity TEXT NOT NULL,
                    identity TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    PRIMARY KEY (definition_identity, entity, decision_at, revision_identity),
                    FOREIGN KEY (definition_identity) REFERENCES definitions(identity)
                );
                CREATE INDEX IF NOT EXISTS feature_rows_cutoff ON feature_rows
                    (definition_identity, entity, decision_at DESC, available_at DESC);
                CREATE TABLE IF NOT EXISTS versions (
                    definition_identity TEXT NOT NULL,
                    version TEXT NOT NULL,
                    PRIMARY KEY (definition_identity, version),
                    FOREIGN KEY (definition_identity) REFERENCES definitions(identity)
                );
                CREATE TABLE IF NOT EXISTS materializations (
                    definition_identity TEXT NOT NULL,
                    version TEXT NOT NULL,
                    at TEXT NOT NULL,
                    identity TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    PRIMARY KEY (definition_identity, version, at),
                    FOREIGN KEY (definition_identity, version)
                        REFERENCES versions(definition_identity, version)
                );
                CREATE TABLE IF NOT EXISTS active_versions (
                    definition_identity TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    FOREIGN KEY (definition_identity, version)
                        REFERENCES versions(definition_identity, version)
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    definition_identity TEXT NOT NULL,
                    instance TEXT NOT NULL,
                    entity TEXT NOT NULL,
                    last_at TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    source_version TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    dataset_sha256 TEXT NOT NULL,
                    PRIMARY KEY (definition_identity, instance, entity),
                    FOREIGN KEY (definition_identity) REFERENCES definitions(identity)
                );
                """
            )
        return store

    def _connect(self) -> sqlite3.Connection:
        """Open one bounded transaction with foreign-key checks and a wait timeout."""
        connection = sqlite3.connect(self._path, timeout=10.0)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @staticmethod
    def _clock(at: datetime) -> str:
        """Index UTC timestamps with fixed-width, lexically ordered microseconds."""
        FeatureStoreDefinition._require_utc(at, field_name="feature-store cutoff")
        return at.isoformat(timespec="microseconds")

    @staticmethod
    def _text(value: object, name: str) -> str:
        """Check caller-supplied entity and version keys before SQL access."""
        if type(value) is not str or not value or value != value.strip():
            raise ValueError(f"{name} must be a trimmed nonempty string")
        return value

    def _require_registered(
        self, connection: sqlite3.Connection, definition: FeatureStoreDefinition
    ) -> None:
        """Reject unpublished or corrupted definition bindings."""
        row = cast(
            tuple[object, ...] | None,
            connection.execute(
                "SELECT payload FROM definitions WHERE identity = ?", (definition.identity,)
            ).fetchone(),
        )
        if row is None:
            raise FeatureStoreError("feature-store definition is not registered")
        payload = cast(bytes, row[0])
        if self._codec.decode_json(payload, FeatureStoreDefinition) != definition:
            raise FeatureStoreError("feature-store definition bytes differ")

    def register(self, definition: FeatureStoreDefinition) -> None:
        """Idempotently register one immutable schema without replacing older versions."""
        definition.__post_init__()
        payload = self._codec.encode_json(definition)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = cast(
                tuple[object, ...] | None,
                connection.execute(
                    "SELECT payload FROM definitions WHERE identity = ?", (definition.identity,)
                ).fetchone(),
            )
            if row is None:
                connection.execute(
                    "INSERT INTO definitions (identity, name, payload) VALUES (?, ?, ?)",
                    (definition.identity, definition.name, payload),
                )
            elif cast(bytes, row[0]) != payload:
                raise FeatureStoreError("registered definition identity has different bytes")

    def append(
        self,
        definition: FeatureStoreDefinition,
        feature: StoredFeature,
        *,
        checkpoint: FeatureCheckpoint | None = None,
    ) -> None:
        """Commit one immutable revision and its incremental successor state together."""
        definition.__post_init__()
        feature.__post_init__()
        if (
            feature.definition_identity != definition.identity
            or feature.vector.definition != definition.schema.identity
            or feature.vector.fields != definition.fields
            or feature.vector.transform_identity != definition.transform_identity
        ):
            raise FeatureStoreError("feature vector differs from its registered schema")
        if definition.schema.mode == "incremental" and checkpoint is None:
            raise FeatureStoreError("incremental materialization requires a checkpoint")
        if checkpoint is not None:
            checkpoint.__post_init__()
            if (
                checkpoint.definition != definition.schema.identity
                or (definition.instance is not None and checkpoint.instance != definition.instance)
                or checkpoint.entity != feature.vector.entity
                or checkpoint.last_at != feature.vector.decision_at
                or checkpoint.information_start != feature.vector.information_start
            ):
                raise FeatureStoreError("checkpoint differs from committed feature vector")
        payload = self._codec.encode_json(feature)
        vector = feature.vector
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_registered(connection, definition)
            key = (
                definition.identity,
                vector.entity,
                self._clock(vector.decision_at),
                feature.revision_identity,
            )
            row = cast(
                tuple[object, ...] | None,
                connection.execute(
                    """SELECT identity, payload FROM feature_rows
                       WHERE definition_identity = ? AND entity = ?
                         AND decision_at = ? AND revision_identity = ?""",
                    key,
                ).fetchone(),
            )
            if row is None:
                previous = cast(
                    tuple[object, ...] | None,
                    connection.execute(
                        """SELECT MAX(available_at) FROM feature_rows
                           WHERE definition_identity = ? AND entity = ? AND decision_at = ?""",
                        (key[0], key[1], key[2]),
                    ).fetchone(),
                )
                if (
                    previous is not None
                    and previous[0] is not None
                    and self._clock(vector.available_at) <= cast(str, previous[0])
                ):
                    raise FeatureStoreError("feature correction must advance availability")
                connection.execute(
                    """INSERT INTO feature_rows
                       (definition_identity, entity, decision_at, available_at,
                        revision_identity, identity, payload)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        key[0],
                        key[1],
                        key[2],
                        self._clock(vector.available_at),
                        key[3],
                        feature.identity,
                        payload,
                    ),
                )
            elif cast(str, row[0]) != feature.identity or cast(bytes, row[1]) != payload:
                raise FeatureStoreError("feature revision retry has different bytes")
            if checkpoint is not None:
                self._commit_checkpoint(
                    connection, definition, feature, checkpoint, row is not None
                )

    def _commit_checkpoint(
        self,
        connection: sqlite3.Connection,
        definition: FeatureStoreDefinition,
        feature: StoredFeature,
        checkpoint: FeatureCheckpoint,
        exact_retry: bool,
    ) -> None:
        """Advance checkpoint only with its vector in the same SQL transaction."""
        row = cast(
            tuple[object, ...] | None,
            connection.execute(
                """SELECT last_at, sha256, payload, source_version, source_sha256,
                          dataset_version, dataset_sha256 FROM checkpoints
                   WHERE definition_identity = ? AND instance = ? AND entity = ?""",
                (definition.identity, checkpoint.instance, checkpoint.entity),
            ).fetchone(),
        )
        encoded = self._codec.encode_json(checkpoint)
        last_at = checkpoint.last_at
        if last_at is None:
            raise FeatureStoreError("committed checkpoint requires a decision cutoff")
        at = self._clock(last_at)
        if row is not None:
            if (
                cast(str, row[3]),
                cast(str, row[4]),
                cast(str, row[5]),
                cast(str, row[6]),
            ) != (
                feature.source_version,
                feature.source_sha256,
                feature.dataset_version,
                feature.dataset_sha256,
            ):
                raise FeatureStoreError("checkpoint source or dataset lineage changed")
            current_at = cast(str, row[0])
            if current_at == at:
                if cast(str, row[1]) != checkpoint.sha256 or cast(bytes, row[2]) != encoded:
                    raise FeatureStoreError("checkpoint retry has different state")
                return
            if current_at > at:
                if exact_retry:
                    return
                raise FeatureStoreError("incremental checkpoint cannot regress")
        connection.execute(
            """INSERT INTO checkpoints
               (definition_identity, instance, entity, last_at, sha256, payload,
                source_version, source_sha256, dataset_version, dataset_sha256)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(definition_identity, instance, entity)
               DO UPDATE SET last_at = excluded.last_at, sha256 = excluded.sha256,
                             payload = excluded.payload,
                             source_version = excluded.source_version,
                             source_sha256 = excluded.source_sha256,
                             dataset_version = excluded.dataset_version,
                             dataset_sha256 = excluded.dataset_sha256""",
            (
                definition.identity,
                checkpoint.instance,
                checkpoint.entity,
                at,
                checkpoint.sha256,
                encoded,
                feature.source_version,
                feature.source_sha256,
                feature.dataset_version,
                feature.dataset_sha256,
            ),
        )

    def get_checkpoint(
        self,
        definition: FeatureStoreDefinition,
        instance: str,
        entity: str,
        *,
        source_version: str,
        source_sha256: str,
        dataset_version: str,
        dataset_sha256: str,
    ) -> FeatureCheckpoint | None:
        """Reopen successor state only for unchanged source and dataset revisions."""
        definition.__post_init__()
        self._text(instance, "instance")
        self._text(entity, "entity")
        if definition.instance is not None and instance != definition.instance:
            raise FeatureStoreError("checkpoint instance differs from feature definition")
        self._text(source_version, "source_version")
        self._text(dataset_version, "dataset_version")
        if (
            type(source_sha256) is not str
            or _SHA256.fullmatch(source_sha256) is None
            or type(dataset_sha256) is not str
            or _SHA256.fullmatch(dataset_sha256) is None
        ):
            raise ValueError("checkpoint lookup requires source and dataset SHA-256")
        with closing(self._connect()) as connection:
            self._require_registered(connection, definition)
            row = cast(
                tuple[object, ...] | None,
                connection.execute(
                    """SELECT last_at, sha256, payload, source_version, source_sha256,
                              dataset_version, dataset_sha256 FROM checkpoints
                       WHERE definition_identity = ? AND instance = ? AND entity = ?""",
                    (definition.identity, instance, entity),
                ).fetchone(),
            )
            if row is None:
                return None
            if (
                cast(str, row[3]),
                cast(str, row[4]),
                cast(str, row[5]),
                cast(str, row[6]),
            ) != (source_version, source_sha256, dataset_version, dataset_sha256):
                raise FeatureStoreError("checkpoint source or dataset lineage changed")
            checkpoint = self._codec.decode_json(cast(bytes, row[2]), FeatureCheckpoint)
            if (
                checkpoint.definition != definition.schema.identity
                or checkpoint.instance != instance
                or checkpoint.entity != entity
                or checkpoint.last_at is None
                or self._clock(checkpoint.last_at) != cast(str, row[0])
                or checkpoint.sha256 != cast(str, row[1])
            ):
                raise FeatureStoreError("stored feature checkpoint bytes differ")
            return checkpoint

    def _select(
        self,
        connection: sqlite3.Connection,
        definition: FeatureStoreDefinition,
        entity: str,
        at: datetime,
    ) -> FeatureStoreResult:
        """Select latest then-known decision/revision without stale fallback."""
        candidates = cast(
            list[tuple[object, ...]],
            connection.execute(
                """SELECT decision_at, available_at, identity, payload FROM feature_rows
                   WHERE definition_identity = ? AND entity = ?
                     AND decision_at <= ? AND available_at <= ?
                   ORDER BY decision_at DESC, available_at DESC LIMIT 2""",
                (definition.identity, entity, self._clock(at), self._clock(at)),
            ).fetchall(),
        )
        if not candidates:
            return FeatureStoreResult(
                definition_identity=definition.identity,
                entity_type=definition.entity_type,
                entity=entity,
                requested_at=at,
                status="missing",
                feature=None,
            )
        chosen = candidates[0]
        if len(candidates) > 1 and chosen[:2] == candidates[1][:2]:
            raise FeatureStoreError("ambiguous feature revisions share a causal clock")
        payload = cast(bytes, chosen[3])
        feature = self._codec.decode_json(payload, StoredFeature)
        if (
            feature.identity != cast(str, chosen[2])
            or feature.definition_identity != definition.identity
            or feature.vector.definition != definition.schema.identity
            or feature.vector.fields != definition.fields
            or feature.vector.transform_identity != definition.transform_identity
            or feature.vector.entity != entity
            or self._clock(feature.vector.decision_at) != cast(str, chosen[0])
            or self._clock(feature.vector.available_at) != cast(str, chosen[1])
        ):
            raise FeatureStoreError("stored feature bytes or schema differ")
        status = self._quality(feature.vector, at)
        return FeatureStoreResult(
            definition_identity=definition.identity,
            entity_type=definition.entity_type,
            entity=entity,
            requested_at=at,
            status=status,
            feature=feature,
        )

    @staticmethod
    def _quality(vector: FeatureVector, at: datetime) -> FeatureQuality:
        """Classify complete, partial, missing and expired exact vectors."""
        if vector.expires_at < at:
            return "expired"
        present = sum(value is not None for value in vector.values)
        if present == 0:
            return "missing"
        return "ready" if present == len(vector.values) else "partial"

    def retrieve_offline(
        self, definition: FeatureStoreDefinition, entity: str, at: datetime
    ) -> FeatureStoreResult:
        """Read the value eligible at one historical decision and knowledge time."""
        definition.__post_init__()
        self._text(entity, "entity")
        self._clock(at)
        with closing(self._connect()) as connection:
            self._require_registered(connection, definition)
            return self._select(connection, definition, entity, at)

    def prepare(
        self,
        definition: FeatureStoreDefinition,
        version: str,
        at: datetime,
        entities: tuple[str, ...],
    ) -> FeatureMaterialization:
        """Compute the snapshot :meth:`materialize` would append, without writing it.

        A publisher prepares a snapshot, publishes its serving generation, then
        appends it with ``expected_identity`` so readers never find a snapshot whose
        generation is absent.
        """
        self._scope(definition, version, at, entities)
        with closing(self._connect()) as connection:
            self._require_registered(connection, definition)
            return self._snapshot(connection, definition, version, at, entities)

    def materialize(
        self,
        definition: FeatureStoreDefinition,
        version: str,
        at: datetime,
        entities: tuple[str, ...],
        *,
        expected_identity: str | None = None,
    ) -> FeatureMaterialization:
        """Append one complete snapshot to a version's stream atomically.

        Cutoffs within a version strictly increase; an exact retry of the latest
        snapshot is accepted. With ``expected_identity`` the snapshot must equal the
        prepared one. Publication of the version uses :meth:`activate`.

        Raises:
            FeatureStoreError: The cutoff regresses, names other bytes, or the snapshot
                changed after preparation.
        """
        self._scope(definition, version, at, entities)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_registered(connection, definition)
            snapshot = self._snapshot(connection, definition, version, at, entities)
            if expected_identity is not None and snapshot.identity != expected_identity:
                raise FeatureStoreError("materialization changed after preparation")
            payload = self._codec.encode_json(snapshot)
            latest = cast(
                tuple[object, ...] | None,
                connection.execute(
                    """SELECT at, identity, payload FROM materializations
                       WHERE definition_identity = ? AND version = ?
                       ORDER BY at DESC LIMIT 1""",
                    (definition.identity, version),
                ).fetchone(),
            )
            if latest is not None and cast(str, latest[0]) == self._clock(at):
                if cast(str, latest[1]) != snapshot.identity or cast(bytes, latest[2]) != payload:
                    raise FeatureStoreError("materialization cutoff already names different bytes")
                return snapshot
            if latest is not None and cast(str, latest[0]) > self._clock(at):
                raise FeatureStoreError("materialization stream cutoffs must increase")
            connection.execute(
                """INSERT OR IGNORE INTO versions (definition_identity, version) VALUES (?, ?)""",
                (definition.identity, version),
            )
            connection.execute(
                """INSERT INTO materializations
                   (definition_identity, version, at, identity, payload) VALUES (?, ?, ?, ?, ?)""",
                (definition.identity, version, self._clock(at), snapshot.identity, payload),
            )
            return snapshot

    def _scope(
        self,
        definition: FeatureStoreDefinition,
        version: str,
        at: datetime,
        entities: tuple[str, ...],
    ) -> None:
        """Validate a snapshot's definition, version, cutoff and unique entities."""
        definition.__post_init__()
        self._text(version, "version")
        self._clock(at)
        if type(entities) is not tuple or not entities:
            raise ValueError("materialization requires entities")
        for entity in entities:
            self._text(entity, "entity")
        if len(set(entities)) != len(entities):
            raise ValueError("materialization entities must be unique")

    def _snapshot(
        self,
        connection: sqlite3.Connection,
        definition: FeatureStoreDefinition,
        version: str,
        at: datetime,
        entities: tuple[str, ...],
    ) -> FeatureMaterialization:
        """Select every entity's then-known value at the cutoff as one snapshot."""
        rows = tuple(self._select(connection, definition, entity, at) for entity in entities)
        snapshot = FeatureMaterialization(
            definition=definition,
            version=version,
            at=at,
            rows=tuple(
                FeatureStoreResult(
                    definition_identity=row.definition_identity,
                    entity_type=row.entity_type,
                    entity=row.entity,
                    requested_at=at,
                    status=row.status,
                    feature=row.feature,
                    version=version,
                    materialized_at=at,
                )
                for row in rows
            ),
        )
        snapshot.__post_init__()
        return snapshot

    def get_materialization(
        self, definition: FeatureStoreDefinition, version: str, at: datetime | None = None
    ) -> FeatureMaterialization:
        """Reopen a version's latest snapshot, or its latest at or before ``at``.

        Raises:
            FeatureStoreError: The version has no snapshot by that cutoff, or bytes differ.
        """
        definition.__post_init__()
        self._text(version, "version")
        if at is not None:
            self._clock(at)
        with closing(self._connect()) as connection:
            snapshot = self._require_materialization(connection, definition, version, at)
            if snapshot is None:
                raise FeatureStoreError("materialization version has no snapshot by cutoff")
            return snapshot

    def exact_materialization(
        self, definition: FeatureStoreDefinition, version: str, at: datetime
    ) -> FeatureMaterialization | None:
        """Reopen a version's snapshot exactly at ``at``, or None when it has none there yet.

        Raises:
            FeatureStoreError: The version is unknown or the snapshot's bytes differ.
        """
        definition.__post_init__()
        self._text(version, "version")
        self._clock(at)
        with closing(self._connect()) as connection:
            snapshot = self._require_materialization(connection, definition, version, at)
        return snapshot if snapshot is not None and snapshot.at == at else None

    @staticmethod
    def stream_identity(definition: FeatureStoreDefinition, version: str) -> str:
        """Identify one version's snapshot stream, as a feature deployment pins it."""
        return hashlib.sha256(
            DomainCodec().encode_json(("feature-stream", definition.identity, version))
        ).hexdigest()

    def _require_materialization(
        self,
        connection: sqlite3.Connection,
        definition: FeatureStoreDefinition,
        version: str,
        at: datetime | None = None,
    ) -> FeatureMaterialization | None:
        """Verify a version's latest snapshot at or before ``at``; None if it has none yet.

        Raises:
            FeatureStoreError: The version is unknown or the snapshot's bytes differ.
        """
        self._require_registered(connection, definition)
        known = cast(
            tuple[object, ...] | None,
            connection.execute(
                "SELECT 1 FROM versions WHERE definition_identity = ? AND version = ?",
                (definition.identity, version),
            ).fetchone(),
        )
        if known is None:
            raise FeatureStoreError("materialization version is unknown")
        query = (
            """SELECT at, identity, payload FROM materializations
               WHERE definition_identity = ? AND version = ?
               ORDER BY at DESC LIMIT 1"""
            if at is None
            else """SELECT at, identity, payload FROM materializations
               WHERE definition_identity = ? AND version = ? AND at <= ?
               ORDER BY at DESC LIMIT 1"""
        )
        parameters = (
            (definition.identity, version)
            if at is None
            else (definition.identity, version, self._clock(at))
        )
        row = cast(tuple[object, ...] | None, connection.execute(query, parameters).fetchone())
        if row is None:
            return None
        snapshot = self._codec.decode_json(cast(bytes, row[2]), FeatureMaterialization)
        if (
            snapshot.identity != cast(str, row[1])
            or snapshot.definition != definition
            or snapshot.version != version
            or self._clock(snapshot.at) != cast(str, row[0])
        ):
            raise FeatureStoreError("materialization bytes or definition differ")
        return snapshot

    def activate(self, definition: FeatureStoreDefinition, version: str) -> None:
        """Atomically switch serving to a complete staged version or roll back."""
        definition.__post_init__()
        self._text(version, "version")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._require_materialization(connection, definition, version) is None:
                raise FeatureStoreError("feature version has no materialized snapshot")
            connection.execute(
                """INSERT INTO active_versions (definition_identity, version) VALUES (?, ?)
                   ON CONFLICT(definition_identity) DO UPDATE SET version = excluded.version""",
                (definition.identity, version),
            )

    def activate_if_current(
        self,
        definition: FeatureStoreDefinition,
        version: str,
        expected_version: str | None,
    ) -> None:
        """Publish a prepared version only if no competing worker changed the pointer.

        An exact retry succeeds when the requested version is already active.
        Rollback is an explicit :meth:`activate` call, never an implicit stale
        worker retry.
        """
        definition.__post_init__()
        self._text(version, "version")
        if expected_version is not None:
            self._text(expected_version, "expected_version")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._require_materialization(connection, definition, version) is None:
                raise FeatureStoreError("feature version has no materialized snapshot")
            row = cast(
                tuple[object, ...] | None,
                connection.execute(
                    "SELECT version FROM active_versions WHERE definition_identity = ?",
                    (definition.identity,),
                ).fetchone(),
            )
            current = None if row is None else cast(str, row[0])
            if current == version:
                return
            if current != expected_version:
                raise FeatureStoreError("active feature version changed during publication")
            connection.execute(
                """INSERT INTO active_versions (definition_identity, version) VALUES (?, ?)
                   ON CONFLICT(definition_identity) DO UPDATE SET version = excluded.version""",
                (definition.identity, version),
            )

    def active_version(self, definition: FeatureStoreDefinition) -> str | None:
        """Return the currently published version for one exact definition."""
        definition.__post_init__()
        with closing(self._connect()) as connection:
            self._require_registered(connection, definition)
            row = cast(
                tuple[object, ...] | None,
                connection.execute(
                    "SELECT version FROM active_versions WHERE definition_identity = ?",
                    (definition.identity,),
                ).fetchone(),
            )
            return None if row is None else cast(str, row[0])

    def retrieve_online(
        self,
        definition: FeatureStoreDefinition,
        entity: str,
        at: datetime,
        *,
        max_materialization_age_us: int | None = None,
    ) -> FeatureStoreResult:
        """Serve the active version's latest snapshot at or before ``at``.

        A version whose first snapshot is later than ``at`` is ``future``; a snapshot
        older than the maximum age is ``stale``. Missingness stays explicit.
        """
        definition.__post_init__()
        self._text(entity, "entity")
        self._clock(at)
        if max_materialization_age_us is not None and (
            type(max_materialization_age_us) is not int
            or not 0 <= max_materialization_age_us <= 31_536_000_000_000
        ):
            raise ValueError("invalid maximum materialization age")
        with closing(self._connect()) as connection:
            self._require_registered(connection, definition)
            active = cast(
                tuple[object, ...] | None,
                connection.execute(
                    "SELECT version FROM active_versions WHERE definition_identity = ?",
                    (definition.identity,),
                ).fetchone(),
            )
            if active is None:
                return FeatureStoreResult(
                    definition_identity=definition.identity,
                    entity_type=definition.entity_type,
                    entity=entity,
                    requested_at=at,
                    status="unmaterialized",
                    feature=None,
                )
            version = cast(str, active[0])
            current = self._require_materialization(connection, definition, version, at)
            first = (
                current
                if current is not None
                else self._first_materialization(connection, definition, version)
            )
            if first is None:
                raise FeatureStoreError("active feature version is corrupt")
            snapshot = first
        if at < snapshot.at:
            status: FeatureQuality = "future"
            feature = None
        else:
            selected = next((entry for entry in snapshot.rows if entry.entity == entity), None)
            feature = None if selected is None else selected.feature
            status = "missing" if selected is None else selected.status
            if feature is not None:
                status = self._quality(feature.vector, at)
            if max_materialization_age_us is not None and at - snapshot.at > timedelta(
                microseconds=max_materialization_age_us
            ):
                status = "stale"
        return FeatureStoreResult(
            definition_identity=definition.identity,
            entity_type=definition.entity_type,
            entity=entity,
            requested_at=at,
            status=status,
            feature=feature,
            version=snapshot.version,
            materialized_at=snapshot.at,
        )

    def _first_materialization(
        self,
        connection: sqlite3.Connection,
        definition: FeatureStoreDefinition,
        version: str,
    ) -> FeatureMaterialization | None:
        """Read a version's earliest snapshot, which a cutoff before it finds in the future."""
        row = cast(
            tuple[object, ...] | None,
            connection.execute(
                """SELECT identity, payload FROM materializations
                   WHERE definition_identity = ? AND version = ? ORDER BY at LIMIT 1""",
                (definition.identity, version),
            ).fetchone(),
        )
        if row is None:
            return None
        snapshot = self._codec.decode_json(cast(bytes, row[1]), FeatureMaterialization)
        if snapshot.identity != cast(str, row[0]) or snapshot.definition != definition:
            raise FeatureStoreError("materialization bytes or definition differ")
        return snapshot

    def backup(self, destination: Path) -> None:
        """Copy one transactionally consistent store to a new backup path."""
        if not isinstance(destination, Path) or destination == self._path:
            raise ValueError("backup requires a separate Path")
        if destination.exists():
            raise FileExistsError("feature-store backup already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".incomplete")
        if temporary.exists():
            raise FileExistsError("feature-store backup staging path already exists")
        try:
            with closing(self._connect()) as source, closing(sqlite3.connect(temporary)) as target:
                source.backup(target)
                checked = cast(
                    tuple[object, ...] | None,
                    target.execute("PRAGMA integrity_check").fetchone(),
                )
                if checked is None or cast(str, checked[0]) != "ok":
                    raise FeatureStoreError("feature-store backup failed integrity check")
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()

    @classmethod
    def restore(cls, source: Path, destination: Path) -> VersionedFeatureStore:
        """Restore a checked backup to a new independent store path."""
        if not isinstance(source, Path) or not source.is_file():
            raise FileNotFoundError("feature-store backup does not exist")
        if not isinstance(destination, Path) or destination.exists():
            raise FileExistsError("feature-store restore destination already exists")
        source_uri = f"{source.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True)) as connection:
            checked = cast(
                tuple[object, ...] | None,
                connection.execute("PRAGMA integrity_check").fetchone(),
            )
            if checked is None or cast(str, checked[0]) != "ok":
                raise FeatureStoreError("feature-store backup is corrupt")
        restored = cls.open(destination)
        try:
            with closing(sqlite3.connect(source_uri, uri=True)) as original:
                with closing(restored._connect()) as target:
                    original.backup(target)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return restored
