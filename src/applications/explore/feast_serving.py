"""Build and read byte-pinned Feast SQLite generations in the isolated worker."""

from __future__ import annotations

# standard library imports
import hashlib
import importlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast


class _EntityFactory(Protocol):
    """Describe the Feast entity constructor used by local materialization."""

    def __call__(self, *, name: str, join_keys: list[str], value_type: object) -> object:
        """Construct a string-keyed entity."""
        ...


class _SourceFactory(Protocol):
    """Describe the Feast local Parquet source constructor."""

    def __call__(
        self,
        *,
        name: str,
        path: str,
        event_timestamp_column: str,
        created_timestamp_column: str,
        timestamp_field: str,
    ) -> object:
        """Construct the immutable source registered in this generation."""
        ...


class _FieldFactory(Protocol):
    """Describe one Feast string field constructor."""

    def __call__(self, *, name: str, dtype: object) -> object:
        """Construct a registered source field."""
        ...


class _ViewFactory(Protocol):
    """Describe one local online Feast feature view constructor."""

    def __call__(
        self,
        *,
        name: str,
        entities: list[object],
        ttl: timedelta,
        schema: list[object],
        source: object,
        online: bool,
        offline: bool,
    ) -> object:
        """Construct the version-specific feature view."""
        ...


class _OnlineResponse(Protocol):
    """Describe Feast's columnar online response conversion."""

    def to_dict(self) -> dict[str, object]:
        """Return feature columns and one requested entity row."""
        ...


class _FeatureStore(Protocol):
    """Describe the SDK calls used for local generation publication and reads."""

    def apply(self, objects: list[object]) -> None:
        """Register the generation source, entity and online feature view."""
        ...

    def write_to_online_store(self, feature_view_name: str, *, df: object) -> None:
        """Copy the admitted immutable source into SQLite through the SDK."""
        ...

    def get_online_features(
        self, *, features: list[str], entity_rows: list[dict[str, str]]
    ) -> _OnlineResponse:
        """Read the latest exact fields for one entity."""
        ...


class _StoreFactory(Protocol):
    """Describe the Feast local FeatureStore constructor."""

    def __call__(self, *, repo_path: str) -> _FeatureStore:
        """Open a local Feast repository."""
        ...


class _FeastModule(Protocol):
    """Describe the selected Feast SDK constructors and installed version."""

    __version__: str
    Entity: _EntityFactory
    FileSource: _SourceFactory
    Field: _FieldFactory
    FeatureView: _ViewFactory
    FeatureStore: _StoreFactory


class _ArrowTableFactory(Protocol):
    """Describe PyArrow's table constructor with an explicit empty-safe schema."""

    def from_pylist(self, records: list[dict[str, object]], *, schema: object) -> object:
        """Build one typed source table."""
        ...


class _ArrowModule(Protocol):
    """Describe the small PyArrow type and table surface in the worker."""

    Table: _ArrowTableFactory

    def string(self) -> object:
        """Return the exact string field type."""
        ...

    def timestamp(self, unit: str, *, tz: str) -> object:
        """Return an aware UTC timestamp field type."""
        ...

    def schema(self, fields: list[tuple[str, object]]) -> object:
        """Construct the explicitly typed Parquet schema."""
        ...


class _ParquetModule(Protocol):
    """Describe the PyArrow Parquet writer."""

    def write_table(self, table: object, where: str) -> None:
        """Persist one immutable source file."""
        ...


class _PandasModule(Protocol):
    """Describe the worker-only Parquet dataframe loader used for SDK ingestion."""

    def read_parquet(self, path: str) -> object:
        """Load exactly the pinned local Parquet source for online ingestion."""
        ...


class FeastServingWorkerCommand:
    """Run real Feast materialization and serving over immutable local generations."""

    _MAX_ROWS = 4_096

    def run(self, payload: bytes) -> bytes:
        """Dispatch one bounded serving request through the installed Feast SDK.

        Args:
            payload: Versioned JSON from the core serving bridge.

        Returns:
            UTF-8 JSON for an immutable generation or one exact online row.

        Raises:
            ValueError: The request, SDK, source, registry or online bytes are invalid.
        """
        decoded: object = json.loads(payload.decode("utf-8"))
        request = self._mapping(decoded, "serving request")
        schema_version = request.get("schema_version")
        if schema_version == "feast-materialize-request":
            result = self._materialize(request)
        elif schema_version == "feast-serve-request":
            result = self._serve(request)
        else:
            raise ValueError("unsupported Feast serving worker request")
        return json.dumps(result, separators=(",", ":"), sort_keys=True).encode("utf-8")

    def _materialize(self, request: Mapping[str, object]) -> dict[str, object]:
        """Build a complete generation in staging before atomic directory publication."""
        snapshot = self._mapping(request.get("snapshot"), "snapshot")
        if snapshot.get("schema_version") != "feast-serving-snapshot":
            raise ValueError("unsupported Feast serving snapshot")
        snapshot_identity = self._digest(request.get("snapshot_identity"), "snapshot_identity")
        sdk = self._sdk(self._text(snapshot.get("sdk_version"), "sdk_version"))
        root = Path(self._text(request.get("root"), "root"))
        if not root.is_absolute():
            raise ValueError("Feast serving root must be absolute")
        rows = self._sequence(snapshot.get("rows"), "rows")
        names = self._sequence(snapshot.get("field_names"), "field_names")
        if not rows or len(rows) > self._MAX_ROWS or not names:
            raise ValueError("Feast serving source is empty or oversized")
        row_identities = self._sequence(request.get("row_identities"), "row_identities")
        if len(row_identities) != len(rows):
            raise ValueError("Feast serving row identities differ from source rows")
        cutoff = self._utc(snapshot.get("cutoff"), "cutoff")
        root.mkdir(parents=True, exist_ok=True)
        target = root / snapshot_identity
        if target.exists():
            receipt = self._verify_generation(target, snapshot_identity, sdk.__version__, None)
            self._check_snapshot(
                sdk.FeatureStore(repo_path=str(target)), rows, row_identities, len(names)
            )
            return receipt
        stage = Path(tempfile.mkdtemp(prefix=".feast-staging-", dir=root))
        try:
            self._create_repository(
                sdk, stage, snapshot_identity, rows, row_identities, names, cutoff
            )
            receipt = self._receipt(stage, snapshot_identity, sdk.__version__)
            (stage / "generation.json").write_text(
                json.dumps(receipt, separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )
            self._verify_generation(
                stage, snapshot_identity, sdk.__version__, receipt, allow_staging=True
            )
            try:
                os.rename(stage, target)
            except OSError:
                if not target.is_dir():
                    raise
                receipt = self._verify_generation(target, snapshot_identity, sdk.__version__, None)
                self._check_snapshot(
                    sdk.FeatureStore(repo_path=str(target)), rows, row_identities, len(names)
                )
                return receipt
            return {**receipt, "repository_path": str(target)}
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def _create_repository(
        self,
        sdk: _FeastModule,
        stage: Path,
        identity: str,
        rows: list[object],
        row_identities: list[object],
        names: list[object],
        cutoff: datetime,
    ) -> None:
        """Author an explicit source and registry, materialize, then verify every row."""
        data = stage / "data"
        data.mkdir()
        config = (
            f"project: feature_generation_{identity[:16]}\n"
            "provider: local\n"
            "registry: data/registry.db\n"
            "online_store:\n"
            "  type: sqlite\n"
            "  path: data/online.db\n"
        )
        (stage / "feature_store.yaml").write_text(config, encoding="utf-8")
        arrow = cast(_ArrowModule, importlib.import_module("pyarrow"))
        parquet = cast(_ParquetModule, importlib.import_module("pyarrow.parquet"))
        source_rows: list[dict[str, object]] = []
        expected: list[tuple[str, str | None, tuple[str | None, ...]]] = []
        seen: set[str] = set()
        for item, row_digest in zip(rows, row_identities, strict=True):
            row = self._mapping(item, "source row")
            entity = self._text(row.get("entity"), "entity")
            if entity in seen:
                raise ValueError("Feast serving source contains duplicate entities")
            seen.add(entity)
            values = tuple(
                self._optional_text(value, "feature value")
                for value in self._sequence(row.get("values"), "values")
            )
            if len(values) != len(names):
                raise ValueError("Feast serving source signature differs")
            digest = self._digest(row_digest, "row identity")
            live = any(value is not None for value in values)
            expected.append((entity, digest if live else None, values))
            if not live:
                continue
            event = self._utc(row.get("event_at"), "event_at")
            available = self._utc(row.get("available_at"), "available_at")
            if event > available or available > cutoff:
                raise ValueError("Feast serving source has a future or late row")
            record: dict[str, object] = {
                "entity_key": entity,
                "event_timestamp": event,
                "created_timestamp": available,
                "row_identity": digest,
            }
            for index, value in enumerate(values):
                record[f"value_{index}"] = value
            source_rows.append(record)
        schema_fields: list[tuple[str, object]] = [
            ("entity_key", arrow.string()),
            ("event_timestamp", arrow.timestamp("us", tz="UTC")),
            ("created_timestamp", arrow.timestamp("us", tz="UTC")),
            ("row_identity", arrow.string()),
        ]
        schema_fields.extend((f"value_{index}", arrow.string()) for index in range(len(names)))
        table = arrow.Table.from_pylist(source_rows, schema=arrow.schema(schema_fields))
        parquet.write_table(table, str(data / "features.parquet"))
        value_type = self._attribute(importlib.import_module("feast.value_type"), "ValueType")
        string_type = self._attribute(value_type, "STRING")
        feast_string = self._attribute(importlib.import_module("feast.types"), "String")
        feast_entity = sdk.Entity(name="entity", join_keys=["entity_key"], value_type=string_type)
        feast_source = sdk.FileSource(
            name="generation_source",
            path="data/features.parquet",
            event_timestamp_column="event_timestamp",
            created_timestamp_column="created_timestamp",
            timestamp_field="event_timestamp",
        )
        fields = [sdk.Field(name="row_identity", dtype=feast_string)]
        fields.extend(
            sdk.Field(name=f"value_{index}", dtype=feast_string) for index in range(len(names))
        )
        feast_view = sdk.FeatureView(
            name="versioned_features",
            entities=[feast_entity],
            ttl=timedelta(0),
            schema=fields,
            source=feast_source,
            online=True,
            offline=True,
        )
        store = sdk.FeatureStore(repo_path=str(stage))
        store.apply([feast_entity, feast_source, feast_view])
        if source_rows:
            pandas = cast(_PandasModule, importlib.import_module("pandas"))
            store.write_to_online_store(
                "versioned_features", df=pandas.read_parquet(str(data / "features.parquet"))
            )
        for entity_key, expected_digest, values in expected:
            actual_digest, actual_values = self._online(store, entity_key, len(names))
            if actual_digest != expected_digest or actual_values != values:
                raise ValueError("Feast materialization differs from admitted source rows")

    def _check_snapshot(
        self,
        store: _FeatureStore,
        rows: list[object],
        identities: list[object],
        count: int,
    ) -> None:
        """Verify an existing generation against the exact retry source grid."""
        for item, identity in zip(rows, identities, strict=True):
            row = self._mapping(item, "source row")
            entity = self._text(row.get("entity"), "entity")
            values = tuple(
                self._optional_text(value, "feature value")
                for value in self._sequence(row.get("values"), "values")
            )
            if len(values) != count:
                raise ValueError("Feast retry source signature differs")
            expected_identity = (
                self._digest(identity, "row identity")
                if any(value is not None for value in values)
                else None
            )
            actual_identity, actual_values = self._online(store, entity, count)
            if actual_identity != expected_identity or actual_values != values:
                raise ValueError("Feast retry generation differs from admitted source")

    def _serve(self, request: Mapping[str, object]) -> dict[str, object]:
        """Verify pinned generation files and read an exact Feast online record."""
        generation = self._mapping(request.get("generation"), "generation")
        if generation.get("schema_version") != "feast-generation":
            raise ValueError("unsupported Feast generation")
        identity = self._digest(request.get("snapshot_identity"), "snapshot_identity")
        if identity != generation.get("snapshot_identity"):
            raise ValueError("Feast serve request generation differs")
        sdk = self._sdk(self._text(generation.get("sdk_version"), "sdk_version"))
        path = Path(self._text(generation.get("repository_path"), "repository_path"))
        self._verify_generation(path, identity, sdk.__version__, generation)
        entity = self._text(request.get("entity"), "entity")
        fields = self._sequence(request.get("field_names"), "field_names")
        if not fields:
            raise ValueError("Feast serve request requires fields")
        store = sdk.FeatureStore(repo_path=str(path))
        row_identity, values = self._online(store, entity, len(fields))
        self._verify_generation(path, identity, sdk.__version__, generation)
        return {
            "schema_version": "feast-online-response",
            "snapshot_identity": identity,
            "entity": entity,
            "row_identity": row_identity,
            "values": values,
        }

    def _online(
        self, store: _FeatureStore, entity: str, count: int
    ) -> tuple[str | None, tuple[str | None, ...]]:
        """Read the actual SQLite feature view without coercing exact strings."""
        names = ["row_identity", *(f"value_{index}" for index in range(count))]
        response = store.get_online_features(
            features=[f"versioned_features:{name}" for name in names],
            entity_rows=[{"entity_key": entity}],
        )
        payload = self._mapping(response.to_dict(), "Feast online response")
        values: list[str | None] = []
        for name in names:
            column = self._sequence(payload.get(name), f"Feast online {name}")
            if len(column) != 1:
                raise ValueError("Feast online response omitted the requested entity")
            values.append(self._optional_text(column[0], name))
        row_identity = values.pop(0)
        if row_identity is not None:
            self._digest(row_identity, "online row identity")
        return row_identity, tuple(values)

    def _receipt(self, repository: Path, identity: str, sdk_version: str) -> dict[str, object]:
        """Hash exactly the local registry, source and SQLite bytes Feast uses."""
        return {
            "schema_version": "feast-generation",
            "snapshot_identity": identity,
            "sdk_version": sdk_version,
            "config_sha256": self._file_digest(repository / "feature_store.yaml"),
            "registry_sha256": self._file_digest(repository / "data" / "registry.db"),
            "source_sha256": self._file_digest(repository / "data" / "features.parquet"),
            "online_sha256": self._file_digest(repository / "data" / "online.db"),
        }

    def _verify_generation(
        self,
        repository: Path,
        identity: str,
        sdk_version: str,
        expected: Mapping[str, object] | None,
        *,
        allow_staging: bool = False,
    ) -> dict[str, object]:
        """Reject incomplete, substituted or modified published Feast generations."""
        if not repository.is_absolute() or (
            repository.name != identity
            and not (allow_staging and repository.name.startswith(".feast-staging-"))
        ):
            raise ValueError("Feast generation path is incompatible")
        manifest_path = repository / "generation.json"
        try:
            decoded: object = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError("Feast generation manifest is unavailable") from error
        manifest = self._mapping(decoded, "generation manifest")
        actual = self._receipt(repository, identity, sdk_version)
        if any(manifest.get(key) != value for key, value in actual.items()):
            raise ValueError("Feast generation bytes differ from pinned manifest")
        if expected is not None and any(
            expected.get(key) != value for key, value in actual.items()
        ):
            raise ValueError("Feast generation bytes differ from pinned request")
        return {**actual, "repository_path": str(repository)}

    def _sdk(self, expected_version: str) -> _FeastModule:
        """Import Feast only inside this separately locked process."""
        sdk = cast(_FeastModule, importlib.import_module("feast"))
        if sdk.__version__ != expected_version:
            raise ValueError("Feast serving SDK differs from pinned version")
        return sdk

    @staticmethod
    def _file_digest(path: Path) -> str:
        """Hash one required local generation file without accepting directories."""
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise ValueError("Feast generation file is unavailable") from error

    @staticmethod
    def _attribute(value: object, name: str) -> object:
        """Read one dynamic SDK attribute behind an explicit object boundary."""
        try:
            return cast(object, getattr(value, name))
        except AttributeError as error:
            raise ValueError(f"Feast SDK lacks {name}") from error

    @staticmethod
    def _mapping(value: object, field_name: str) -> Mapping[str, object]:
        """Narrow a decoded JSON object without allowing dynamic values to escape."""
        if not isinstance(value, dict) or any(type(key) is not str for key in value):
            raise ValueError(f"{field_name} must be a JSON object")
        return cast(Mapping[str, object], value)

    @staticmethod
    def _sequence(value: object, field_name: str) -> list[object]:
        """Require a JSON list at this worker boundary."""
        if not isinstance(value, list):
            raise ValueError(f"{field_name} must be a JSON list")
        return cast(list[object], value)

    @staticmethod
    def _text(value: object, field_name: str) -> str:
        """Require one nonempty trimmed protocol string."""
        if type(value) is not str or not value or value != value.strip():
            raise ValueError(f"{field_name} must be a nonempty trimmed string")
        return value

    @classmethod
    def _optional_text(cls, value: object, field_name: str) -> str | None:
        """Retain a nullable exact SDK string without numerical conversion."""
        return None if value is None else cls._text(value, field_name)

    @classmethod
    def _digest(cls, value: object, field_name: str) -> str:
        """Validate one lowercase SHA-256 identity at the process boundary."""
        result = cls._text(value, field_name)
        if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
            raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        return result

    @classmethod
    def _utc(cls, value: object, field_name: str) -> datetime:
        """Decode one aware UTC source or cutoff timestamp."""
        if isinstance(value, datetime):
            result = value
        elif type(value) is str:
            try:
                result = datetime.fromisoformat(value)
            except ValueError as error:
                raise ValueError(f"{field_name} is not an ISO timestamp") from error
        else:
            raise ValueError(f"{field_name} must be an aware UTC timestamp")
        if result.tzinfo is None or result.utcoffset() != timedelta(0):
            raise ValueError(f"{field_name} must use UTC")
        return result.astimezone(UTC)
