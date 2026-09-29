"""Run the isolated Feast SDK worker over the versioned JSON bridge."""

from __future__ import annotations

# standard library imports
import argparse
import base64
import hashlib
import importlib
import json
import runpy
import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO, Protocol, cast


class _Frame(Protocol):
    """Describe the small pandas frame surface consumed by the worker."""

    def to_dict(self, *, orient: str) -> list[dict[str, object]]:
        """Return records from the actual SDK result without coercion here."""
        ...


class _RetrievalJob(Protocol):
    """Describe the Feast retrieval job's materialization method."""

    def to_df(self) -> _Frame:
        """Materialize the local offline result as a dataframe."""
        ...


class _BatchSource(Protocol):
    """Describe the local source path retained in a Feast feature view."""

    path: str


class _FeatureField(Protocol):
    """Describe a registered feature field name used for source clocks."""

    name: str


class _FeatureView(Protocol):
    """Describe the source binding used to verify the pinned feature bytes."""

    batch_source: _BatchSource
    schema: list[_FeatureField]


class _Store(Protocol):
    """Describe the Feast FeatureStore calls used by this worker."""

    config: object

    repo_path: Path

    def get_feature_view(self, name: str) -> _FeatureView:
        """Resolve one registered feature view from the local registry."""
        ...

    def get_historical_features(
        self,
        *,
        entity_df: _Frame,
        features: list[str],
        filter_by_created_timestamp: bool,
    ) -> _RetrievalJob:
        """Request a point-in-time offline feature join."""
        ...


class _Pandas(Protocol):
    """Describe the pandas constructor available in the worker environment."""

    def DataFrame(self, records: list[dict[str, object]]) -> _Frame:
        """Construct the entity dataframe passed to Feast."""
        ...

    def isna(self, value: object) -> bool:
        """Identify one scalar pandas null, including ``NaT``."""
        ...


class _StoreFactory(Protocol):
    """Describe the Feast FeatureStore constructor."""

    def __call__(self, *, repo_path: str) -> _Store:
        """Open the pinned local feature repository."""
        ...


class _JsonDumper(Protocol):
    """Describe the stdlib JSON encoder call used at the worker boundary."""

    def __call__(self, value: object, *, separators: tuple[str, str]) -> str:
        """Encode one JSON-compatible object."""
        ...


class _ServingWorker(Protocol):
    """Describe the isolated Feast generation worker loaded beside this command."""

    def run(self, payload: bytes) -> bytes:
        """Execute one versioned online materialization or retrieval request."""
        ...


class _ServingWorkerFactory(Protocol):
    """Describe the installed sibling worker constructor."""

    def __call__(self) -> _ServingWorker:
        """Create one stateless serving request worker."""
        ...


_MAX_WORKER_INPUT_BYTES = 16 * 1024 * 1024


class FeastWorkerCommand:
    """Validate the bridge request and execute one real Feast local retrieval."""

    def run(self, payload: bytes) -> bytes:
        """Execute one request from stdin and encode its strict JSON result.

        Args:
            payload: UTF-8 JSON produced by ``OfflineFeatureBridge``.

        Returns:
            UTF-8 JSON matching ``offline-feature-result``.

        Raises:
            ValueError: The request, registry bytes or SDK result cannot prove the
                declared immutable-source contract.
        """
        decoded: object = json.loads(payload.decode("utf-8"))
        request = self._mapping(decoded, "request")
        if request.get("schema_version") != "offline-feature-request":
            raise ValueError("unsupported offline worker request schema")
        definition = self._mapping(request.get("definition"), "definition")
        if definition.get("eligibility") != "immutable-source":
            raise ValueError("Feast worker requires an eligibility-filtered immutable source")
        sdk_version = self._text(definition.get("sdk_version"), "sdk_version")
        feast_module = importlib.import_module("feast")
        actual_version = self._text(self._attribute(feast_module, "__version__"), "feast version")
        if actual_version != sdk_version:
            raise ValueError("worker Feast SDK version differs from the pinned request")
        registry_bytes = self._bytes(definition.get("registry_bytes"), "registry_bytes")
        expected_registry = hashlib.sha256(registry_bytes).hexdigest()
        repository = self._text(definition.get("repository_path"), "repository_path")
        repository_path = Path(repository)
        if not repository_path.is_dir():
            raise ValueError("worker feature repository is unavailable")
        feature_store_factory = cast(_StoreFactory, self._attribute(feast_module, "FeatureStore"))
        store = feature_store_factory(repo_path=repository)
        self._verify_registry(store, registry_bytes)
        source_sha256 = self._digest(definition.get("source_sha256"), "source_sha256")
        feature_view = self._verify_source(store, definition, source_sha256)
        pandas_module = cast(_Pandas, importlib.import_module("pandas"))
        join_key = definition.get("join_key") or definition.get("entity_type")
        join_column = self._text(join_key, "join_key")
        entities = self._sequence(request.get("entities"), "entities")
        decisions = tuple(
            self._utc(item, "decision")
            for item in self._sequence(request.get("decisions"), "decisions")
        )
        entity_records: list[dict[str, object]] = []
        for entity_item in entities:
            entity = self._mapping(entity_item, "entity")
            key = self._text(entity.get("entity_key"), "entity_key")
            if self._text(entity.get("entity_type"), "entity_type") != definition.get(
                "entity_type"
            ):
                raise ValueError("worker entity type differs from feature definition")
            for decision in decisions:
                entity_records.append({join_column: key, "event_timestamp": decision})
        entity_frame = pandas_module.DataFrame(entity_records)
        feature_ref = self._text(definition.get("feature_ref"), "feature_ref")
        feature_view_name = feature_ref.split(":", 1)[0]
        source_clock_names = {
            "feature_event_timestamp",
            "event_at",
            "feature_timestamp",
            "created_timestamp",
            "available_at",
            "created_at",
        }
        feature_refs = [feature_ref]
        for field in feature_view.schema:
            field_name = self._text(field.name, "feature field name")
            if field_name in source_clock_names:
                feature_refs.append(f"{feature_view_name}:{field_name}")
        job = store.get_historical_features(
            entity_df=entity_frame,
            features=feature_refs,
            filter_by_created_timestamp=True,
        )
        records = job.to_df().to_dict(orient="records")
        rows = self._rows(
            records,
            definition=definition,
            definition_identity=self._text(
                request.get("definition_identity"), "definition_identity"
            ),
            entities=entities,
            decisions=decisions,
            join_column=join_column,
            is_nullish=pandas_module.isna,
        )
        dumper = cast(_JsonDumper, self._attribute(json, "dumps"))
        return dumper(
            {
                "schema_version": "offline-feature-result",
                "request_identity": self._text(request.get("request_identity"), "request_identity"),
                "definition_identity": self._text(
                    request.get("definition_identity"), "definition_identity"
                ),
                "registry_sha256": expected_registry,
                "sdk_version": actual_version,
                "source_version": self._text(definition.get("source_version"), "source_version"),
                "source_sha256": source_sha256,
                "eligibility": "immutable-source",
                "rows": rows,
            },
            separators=(",", ":"),
        ).encode("utf-8")

    def _verify_registry(self, store: _Store, expected: bytes) -> None:
        """Verify the actual FeatureStore registry file before the SDK call."""
        config = store.config
        registry_config = self._attribute_or_none(config, "registry")
        registry_path = self._attribute_or_none(registry_config, "path")
        repo_path = self._attribute_or_none(store, "repo_path")
        if not isinstance(repo_path, Path) or not isinstance(registry_path, str):
            raise ValueError("worker cannot resolve the FeatureStore registry path")
        path = Path(registry_path)
        if not path.is_absolute():
            path = repo_path / path
        try:
            actual = path.read_bytes()
        except OSError as error:
            raise ValueError("worker registry bytes are unavailable") from error
        if actual != expected:
            raise ValueError("FeatureStore registry bytes differ from the pinned request")

    def _verify_source(
        self,
        store: _Store,
        definition: Mapping[str, object],
        expected_sha256: str,
    ) -> _FeatureView:
        """Verify the local immutable source bytes bound to the registered feature view."""
        feature_ref = self._text(definition.get("feature_ref"), "feature_ref")
        feature_view_name = feature_ref.split(":", 1)[0]
        feature_view = store.get_feature_view(feature_view_name)
        source = feature_view.batch_source
        source_path = Path(self._text(source.path, "source_path"))
        if not source_path.is_absolute():
            source_path = store.repo_path / source_path
        try:
            actual = source_path.read_bytes()
        except OSError as error:
            raise ValueError("worker immutable source bytes are unavailable") from error
        if hashlib.sha256(actual).hexdigest() != expected_sha256:
            raise ValueError("worker immutable source bytes differ from the pinned request")
        return feature_view

    def _rows(
        self,
        records: list[dict[str, object]],
        *,
        definition: Mapping[str, object],
        definition_identity: str,
        entities: list[object],
        decisions: tuple[datetime, ...],
        join_column: str,
        is_nullish: Callable[[object], bool],
    ) -> list[dict[str, object]]:
        """Align actual Feast records to the requested grid without inventing values.

        Args:
            records: Scalar records materialized by the Feast retrieval job.
            definition: Versioned feature metadata from the bridge request.
            definition_identity: Identity of the request's feature definition.
            entities: Requested entity objects from the bridge request.
            decisions: Requested UTC decision clocks.
            join_column: Feast entity join-key column.
            is_nullish: Worker-environment scalar null predicate, including ``NaT``.

        Returns:
            One JSON-compatible observation per requested entity and decision.

        Raises:
            ValueError: A matched row has partial clocks, malformed values or a
                duplicate entity/decision key.
        """
        feature_name = self._text(definition.get("feature_name"), "feature_name")
        source_version = self._text(definition.get("source_version"), "source_version")
        source_sha256 = self._text(definition.get("source_sha256"), "source_sha256")
        ttl_us = definition.get("ttl_us")
        if type(ttl_us) is not int:
            raise ValueError("worker TTL is malformed")
        units = self._text(definition.get("units"), "units")
        feature_field = feature_name
        if ":" in self._text(definition.get("feature_ref"), "feature_ref"):
            feature_field = self._text(definition["feature_ref"], "feature_ref").split(":", 1)[1]
        indexed: dict[tuple[str, datetime], Mapping[str, object]] = {}
        for record in records:
            key = self._text(record.get(join_column), join_column)
            event_timestamp = self._utc(record.get("event_timestamp"), "event_timestamp")
            feature_present = feature_field in record
            feature_raw = record.get(feature_field)
            feature_missing = not feature_present or self._nullish(feature_raw, is_nullish)
            event_present = self._has_clock(
                record,
                ("feature_event_timestamp", "event_at", "feature_timestamp"),
                is_nullish,
            )
            available_present = self._has_clock(
                record,
                ("created_timestamp", "available_at", "created_at"),
                is_nullish,
            )
            if feature_missing and not event_present and not available_present:
                # Feast materializes a missing entity as a row with the requested
                # entity/decision and pandas NaN/NaT feature columns. It is the
                # same absence as an omitted row, so leave it for the explicit
                # nullable grid row below.
                continue
            if feature_missing and not feature_present:
                raise ValueError("Feast worker omitted the registered feature field")
            if event_present != available_present:
                raise ValueError("Feast worker returned partial source clocks")
            if not feature_missing and not event_present:
                raise ValueError("Feast worker returned a value without source clocks")
            if (key, event_timestamp) in indexed:
                raise ValueError("Feast worker returned duplicate entity/decision rows")
            indexed[(key, event_timestamp)] = record
        result: list[dict[str, object]] = []
        for entity_item in entities:
            entity = self._mapping(entity_item, "entity")
            key = self._text(entity.get("entity_key"), "entity_key")
            for decision in decisions:
                matched = indexed.get((key, decision))
                value_raw = None if matched is None else matched.get(feature_field)
                value = (
                    None if value_raw is None or self._nullish(value_raw, is_nullish) else value_raw
                )
                if value is not None and type(value) is not str:
                    raise ValueError("Feast worker changed the exact feature string type")
                event_at = (
                    None
                    if matched is None
                    else self._feature_event_at(matched, is_nullish=is_nullish)
                )
                available_at = (
                    None if matched is None else self._created_at(matched, is_nullish=is_nullish)
                )
                result.append(
                    {
                        "schema_version": "feature-observation",
                        "definition_identity": definition_identity,
                        "source_version": source_version,
                        "source_sha256": source_sha256,
                        "feature_name": feature_name,
                        "entity_type": self._text(entity.get("entity_type"), "entity_type"),
                        "entity_key": key,
                        "decision_at": decision.isoformat(),
                        "event_at": None if event_at is None else event_at.isoformat(),
                        "available_at": (
                            None if available_at is None else available_at.isoformat()
                        ),
                        "ttl_us": ttl_us,
                        "units": units,
                        "value": value,
                        "revision_identity": None,
                        "missing_reason": (
                            "source feature value is null"
                            if matched is not None and value is None
                            else (
                                None
                                if matched is not None
                                else "missing entity or no eligible source row"
                            )
                        ),
                    }
                )
        return result

    def _created_at(
        self, record: Mapping[str, object], *, is_nullish: Callable[[object], bool]
    ) -> datetime:
        """Require a truthful non-null source availability timestamp."""
        for name in ("created_timestamp", "available_at", "created_at"):
            if name in record and not self._nullish(record[name], is_nullish):
                return self._utc(record[name], name)
        raise ValueError("Feast result lacks a truthful source availability timestamp")

    def _feature_event_at(
        self, record: Mapping[str, object], *, is_nullish: Callable[[object], bool]
    ) -> datetime:
        """Require a source event clock rather than treating the entity clock as one."""
        for name in ("feature_event_timestamp", "event_at", "feature_timestamp"):
            if name in record and not self._nullish(record[name], is_nullish):
                return self._utc(record[name], name)
        raise ValueError("Feast result lacks a truthful source event timestamp")

    @staticmethod
    def _has_clock(
        record: Mapping[str, object],
        names: tuple[str, ...],
        is_nullish: Callable[[object], bool],
    ) -> bool:
        """Report whether one registered source clock has a non-null scalar."""
        return any(
            name in record and not FeastWorkerCommand._nullish(record[name], is_nullish)
            for name in names
        )

    @staticmethod
    def _nullish(value: object, is_nullish: Callable[[object], bool]) -> bool:
        """Recognize scalar pandas nulls without admitting array truth values."""
        try:
            result = is_nullish(value)
        except TypeError, ValueError:
            return False
        return type(result) is bool and result

    @staticmethod
    def _mapping(value: object, field_name: str) -> dict[str, object]:
        """Narrow one decoded JSON object without dynamic typing."""
        if not isinstance(value, dict) or any(type(key) is not str for key in value):
            raise ValueError(f"{field_name} must be a JSON object")
        return cast(dict[str, object], value)

    @staticmethod
    def _attribute(value: object, name: str) -> object:
        """Read a dynamic SDK attribute as an object before narrowing it."""
        try:
            return object.__getattribute__(value, name)  # type: ignore[misc]  # [owner=research; rationale=bridge dynamic SDK attributes through one narrowed boundary; expires=2027-03-20]
        except AttributeError as error:
            raise ValueError(f"worker object lacks {name}") from error

    @classmethod
    def _attribute_or_none(cls, value: object, name: str) -> object | None:
        """Read an optional SDK attribute without allowing dynamic values to escape."""
        try:
            return cls._attribute(value, name)
        except ValueError:
            return None

    @staticmethod
    def _sequence(value: object, field_name: str) -> list[object]:
        """Narrow one decoded JSON list without accepting strings as sequences."""
        if not isinstance(value, list):
            raise ValueError(f"{field_name} must be a JSON list")
        return value

    @staticmethod
    def _text(value: object, field_name: str) -> str:
        """Require one nonempty worker protocol text field."""
        if type(value) is not str or not value or value != value.strip():
            raise ValueError(f"{field_name} must be a nonempty trimmed string")
        return value

    @classmethod
    def _digest(cls, value: object, field_name: str) -> str:
        """Require one lowercase SHA-256 digest in the worker protocol."""
        result = cls._text(value, field_name)
        if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
            raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        return result

    @classmethod
    def _utc(cls, value: object, field_name: str) -> datetime:
        """Parse one UTC timestamp from JSON or pandas without normalizing it."""
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
        return result

    @classmethod
    def _bytes(cls, value: object, field_name: str) -> bytes:
        """Decode one base64 wire byte field."""
        encoded = cls._text(value, field_name)
        try:
            return base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise ValueError(f"{field_name} is not valid base64") from error


def main(argv: list[str] | None = None) -> int:
    """Dispatch one bounded explore action.

    Args:
        argv: Optional command arguments; ``None`` reads the process arguments.

    Returns:
        Zero after a successful worker response, or two after a worker error.

    Raises:
        SystemExit: ``argparse`` reports ``--help`` or invalid action arguments.
    """
    parser = argparse.ArgumentParser(prog="alpha-explore")
    parser.add_argument("action", choices=("feast-worker", "feast-serving-worker"))
    arguments = parser.parse_args(argv)
    action = cast(object, arguments.action)
    if action not in ("feast-worker", "feast-serving-worker"):
        parser.error("unsupported explore action")
    try:
        input_stream = cast(BinaryIO, getattr(sys.stdin, "buffer"))
        output_stream = cast(BinaryIO, getattr(sys.stdout, "buffer"))
        payload = input_stream.read(_MAX_WORKER_INPUT_BYTES + 1)
        if not payload or len(payload) > _MAX_WORKER_INPUT_BYTES:
            raise ValueError("feast worker request exceeds the bounded JSON budget")
        if action == "feast-worker":
            output = FeastWorkerCommand().run(payload)
        else:
            sibling = Path(__file__).with_name("feast_serving.py")
            serving_module = cast(Mapping[str, object], runpy.run_path(str(sibling)))
            factory = cast(_ServingWorkerFactory, serving_module["FeastServingWorkerCommand"])
            output = factory().run(payload)
        output_stream.write(output)
        output_stream.write(b"\n")
        return 0
    except (EOFError, OSError, ValueError, TypeError, ImportError) as error:
        print(f"feast worker failed: {error}", file=sys.stderr)
        return 2
