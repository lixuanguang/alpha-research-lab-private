"""Verify exact Feast serving admission and immutable local SDK generations."""

from __future__ import annotations

# standard library imports
import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import cast

# third party library imports
import pytest

# project library imports
from financial_units import ExactRatio
from research.features import FeatureSchema, FeatureVector
from research.features.offline import FeastOfflineWorker, FeatureAccessError
from research.features.serving import (
    FeastGeneration,
    FeastServingBridge,
    FeastServingRow,
    FeastServingSnapshot,
)
from research.features.store import FeatureStoreDefinition, StoredFeature, VersionedFeatureStore
from research.observations import InputRequirement, NumericField
from serialization import DomainCodec


class _OnlineWorker:
    """Return one controlled online row for core admission tests."""

    def __init__(self, row: FeastServingRow, *, value: str | None = None) -> None:
        """Bind the authoritative row and optional corrupt Feast value."""
        self._row = row
        self._value = value

    def __call__(self, request: bytes) -> bytes:
        """Answer one serving request with a versioned worker payload."""
        decoded = cast(object, json.loads(request))
        if not isinstance(decoded, dict):
            raise ValueError("serving test worker requires a JSON object")
        payload = cast(dict[str, object], cast(object, decoded))
        values = [self._row.values[0] if self._value is None else self._value]
        response: dict[str, object] = {
            "schema_version": "feast-online-response-v1",
            "snapshot_identity": payload["snapshot_identity"],
            "entity": payload["entity"],
            "row_identity": self._row.identity,
            "values": values,
        }
        return DomainCodec().encode_json(response)


class TestFeastServing:
    """Check causal source projection, exact online values and SDK recovery."""

    @staticmethod
    def _time(minutes: int) -> datetime:
        """Return one deterministic UTC decision or availability clock."""
        return datetime(2025, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes)

    @staticmethod
    def _definition() -> FeatureStoreDefinition:
        """Describe a reusable named exact signal and its source requirement."""
        field = NumericField(name="mid", units="quote/base")
        schema = FeatureSchema(
            implementation="named-projection-v1",
            inputs=(
                InputRequirement(
                    name="mid-source",
                    family="book",
                    clock="event",
                    field=field,
                    max_age_us=600_000_000,
                ),
            ),
            outputs=(NumericField(name="signal", units="quote/base"),),
            parameters=(),
            mode="batch",
            ttl_us=600_000_000,
        )
        return FeatureStoreDefinition(name="book-signal", entity_type="instrument", schema=schema)

    @classmethod
    def _feature(
        cls,
        definition: FeatureStoreDefinition,
        *,
        numerator: int,
        available_minute: int,
        revision: str,
    ) -> StoredFeature:
        """Author an exact correction whose availability may follow its event."""
        vector = FeatureVector(
            entity="instrument-a",
            decision_at=cls._time(0),
            event_at=cls._time(0),
            information_start=cls._time(0),
            available_at=cls._time(available_minute),
            expires_at=cls._time(10),
            definition=definition.schema.identity,
            fields=definition.fields,
            values=(ExactRatio.from_fraction(Fraction(numerator, 3)),),
            reasons=("observed",),
            input_identity="a" * 64,
        )
        return StoredFeature(
            definition_identity=definition.identity,
            vector=vector,
            source_version="source-one",
            source_sha256="b" * 64,
            dataset_version="dataset-one",
            dataset_sha256="c" * 64,
            revision_identity=revision * 64,
        )

    @classmethod
    def _snapshot(
        cls, root: Path
    ) -> tuple[VersionedFeatureStore, FeatureStoreDefinition, FeastServingSnapshot]:
        """Create one authoritative version with a present and a missing entity."""
        definition = cls._definition()
        store = VersionedFeatureStore.open(root / "features.sqlite")
        store.register(definition)
        store.append(
            definition, cls._feature(definition, numerator=1, available_minute=0, revision="1")
        )
        materialization = store.materialize(
            definition, "release-one", cls._time(2), ("instrument-a", "instrument-b")
        )
        return store, definition, FeastServingSnapshot.from_materialization(materialization)

    def test_exact_value_clock_and_missing_admission(self, tmp_path: Path) -> None:
        """The bridge refuses a changed rational, a future read and an altered source row."""
        _, _, snapshot = self._snapshot(tmp_path)
        row = snapshot.row("instrument-a")
        assert row.values == ("1/3",)
        assert snapshot.row("instrument-b").values == (None,)
        generation = FeastGeneration(
            snapshot_identity=snapshot.identity,
            repository_path=str(tmp_path / snapshot.identity),
            config_sha256="1" * 64,
            registry_sha256="2" * 64,
            source_sha256="3" * 64,
            online_sha256="4" * 64,
            sdk_version="0.66.0",
        )
        bridge = FeastServingBridge(_OnlineWorker(row))
        served = bridge.retrieve(snapshot, generation, "instrument-a", self._time(2))
        assert served.values == ("1/3",)
        assert served.version == "release-one"
        assert served.revision_identity == "1" * 64
        assert bridge.retrieve(snapshot, generation, "instrument-a", self._time(11)).status == (
            "expired"
        )
        with pytest.raises(FeatureAccessError, match="cannot replay"):
            bridge.retrieve(snapshot, generation, "instrument-a", self._time(1))
        with pytest.raises(FeatureAccessError, match="values or source identity"):
            FeastServingBridge(_OnlineWorker(row, value="2/3")).retrieve(
                snapshot, generation, "instrument-a", self._time(2)
            )

        late = FeastServingRow(
            entity=row.entity,
            event_at=row.event_at,
            available_at=self._time(3),
            expires_at=row.expires_at,
            values=row.values,
            reasons=row.reasons,
            source_version=row.source_version,
            source_sha256=row.source_sha256,
            dataset_version=row.dataset_version,
            dataset_sha256=row.dataset_sha256,
            revision_identity=row.revision_identity,
        )
        with pytest.raises(ValueError, match="late unavailable"):
            FeastServingSnapshot(
                definition_identity=snapshot.definition_identity,
                schema_identity=snapshot.schema_identity,
                materialization_identity=snapshot.materialization_identity,
                version=snapshot.version,
                cutoff=snapshot.cutoff,
                field_names=snapshot.field_names,
                rows=(late,),
            )

    @pytest.mark.integration
    def test_real_feast_retry_relocation_and_rollback(self, tmp_path: Path) -> None:
        """The pinned SDK reopens copied generations and keeps older values intact."""
        worker_path = os.environ.get("ALPHA_FEAST_WORKER_PYTHON")
        if worker_path is None:
            pytest.skip("set ALPHA_FEAST_WORKER_PYTHON to the pinned Feast worker interpreter")
        worker_python = Path(worker_path).absolute()
        if not worker_python.is_file():
            pytest.skip("pinned Feast worker interpreter is unavailable")
        command_file = (
            Path(__file__).resolve().parents[3] / "src" / "applications" / "explore" / "command.py"
        )
        code = (
            "from runpy import run_path; "
            f"raise SystemExit(run_path({str(command_file)!r})"
            "['main'](['feast-serving-worker']))"
        )
        bridge = FeastServingBridge(
            FeastOfflineWorker([str(worker_python), "-c", code], timeout_seconds=120)
        )
        store, definition, first = self._snapshot(tmp_path)
        generation_root = tmp_path / "serving"
        original = bridge.materialize(first, generation_root)
        assert bridge.materialize(first, generation_root) == original
        assert bridge.open_generation(first, generation_root) == original
        assert bridge.retrieve(first, original, "instrument-a", self._time(2)).values == ("1/3",)
        assert bridge.retrieve(first, original, "instrument-b", self._time(2)).status == "missing"
        assert bridge.retrieve(first, original, "instrument-a", self._time(11)).status == (
            "expired"
        )
        store.activate(definition, "release-one")
        store.append(
            definition, self._feature(definition, numerator=5, available_minute=3, revision="2")
        )
        second = FeastServingSnapshot.from_materialization(
            store.materialize(definition, "release-two", self._time(3), ("instrument-a",))
        )
        assert store.active_version(definition) == "release-one"
        corrected = bridge.materialize(second, generation_root)
        assert bridge.retrieve(second, corrected, "instrument-a", self._time(3)).values == ("5/3",)
        assert bridge.retrieve(first, original, "instrument-a", self._time(3)).values == ("1/3",)
        store.activate(definition, "release-two")
        restored_root = tmp_path / "restored" / "serving"
        restored_root.mkdir(parents=True)
        shutil.copytree(Path(original.repository_path), restored_root / first.identity)
        restored = bridge.open_generation(first, restored_root)
        assert bridge.retrieve(first, restored, "instrument-a", self._time(3)).values == ("1/3",)
        store.activate(definition, "release-one")
        assert store.active_version(definition) == "release-one"
        (Path(corrected.repository_path) / "data" / "features.parquet").write_bytes(
            b"corrupt-source"
        )
        with pytest.raises(FeatureAccessError, match="pinned receipt"):
            bridge.open_generation(second, generation_root)
        assert bridge.retrieve(first, original, "instrument-a", self._time(3)).values == ("1/3",)
