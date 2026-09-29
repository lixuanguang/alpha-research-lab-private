"""Exercise causal feature history, atomic serving versions and durable restart state."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path

# third party library imports
import pytest

# project library imports
from financial_units import ExactRatio
from research.features import (
    FeatureCheckpoint,
    FeatureSchema,
    FeatureSession,
    FeatureStoreDefinition,
    FeatureStoreError,
    FeatureVector,
    RunningMeanFeature,
    StoredFeature,
    VersionedFeatureStore,
)
from research.observations import DecisionInputs, InputRequirement, NamedObservation, NumericField


class TestVersionedFeatureStore:
    """Check the exact history and serving boundaries at independent cutoffs."""

    @staticmethod
    def _time(minutes: int) -> datetime:
        """Return one deterministic UTC clock for hand-checked history."""
        return datetime(2025, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes)

    @staticmethod
    def _schema(*, mode: str = "batch") -> FeatureSchema:
        """Define a named exact ratio with an explicit ten-minute TTL."""
        field = NumericField(name="mid", units="quote/base")
        requirement = InputRequirement(
            name="mid-source", family="book", clock="event", field=field, max_age_us=600_000_000
        )
        return FeatureSchema(
            implementation="named-projection" if mode == "batch" else "running-mean",
            inputs=(requirement,),
            outputs=(NumericField(name="signal", units="quote/base"),),
            parameters=(),
            mode="batch" if mode == "batch" else "incremental",
            ttl_us=600_000_000,
        )

    @classmethod
    def _definition(cls, *, mode: str = "batch") -> FeatureStoreDefinition:
        """Select one reusable entity domain without venue-specific logic."""
        return FeatureStoreDefinition(
            name="book-signal",
            entity_type="instrument",
            schema=cls._schema(mode=mode),
            instance="strategy-one" if mode == "incremental" else None,
        )

    @classmethod
    def _feature(
        cls,
        definition: FeatureStoreDefinition,
        *,
        entity: str = "instrument-a",
        decision_minute: int = 0,
        available_minute: int = 0,
        numerator: int | None = 1,
        revision: str = "1",
        dataset_version: str = "dataset-one",
    ) -> StoredFeature:
        """Author independent exact values and real correction availability clocks."""
        vector = FeatureVector(
            entity=entity,
            decision_at=cls._time(decision_minute),
            event_at=cls._time(decision_minute),
            information_start=cls._time(decision_minute),
            available_at=cls._time(available_minute),
            expires_at=cls._time(decision_minute + 10),
            definition=definition.schema.identity,
            fields=definition.fields,
            values=(
                None if numerator is None else ExactRatio.from_fraction(Fraction(numerator, 3)),
            ),
            reasons=("missing" if numerator is None else "observed",),
            input_identity="a" * 64,
            transform_identity=definition.transform_identity,
        )
        return StoredFeature(
            definition_identity=definition.identity,
            vector=vector,
            source_version="source-one",
            source_sha256="b" * 64,
            dataset_version=dataset_version,
            dataset_sha256="c" * 64,
            revision_identity=revision * 64,
        )

    def test_late_correction_preserves_earlier_cutoff_and_expiry(self, tmp_path: Path) -> None:
        """A 3-minute correction cannot change a 2-minute decision."""
        definition = self._definition()
        store = VersionedFeatureStore.open(tmp_path / "features.sqlite")
        store.register(definition)
        first = self._feature(definition)
        store.append(definition, first)
        store.append(definition, first)
        correction = self._feature(
            definition, available_minute=3, numerator=5, revision="2", dataset_version="dataset-two"
        )
        store.append(definition, correction)

        early = store.retrieve_offline(definition, "instrument-a", self._time(2))
        late = store.retrieve_offline(definition, "instrument-a", self._time(3))
        expired = store.retrieve_offline(definition, "instrument-a", self._time(11))
        absent = store.retrieve_offline(definition, "instrument-b", self._time(3))
        assert early.require_ready().values == (ExactRatio(numerator="1", denominator="3"),)
        assert late.require_ready().values == (ExactRatio(numerator="5", denominator="3"),)
        assert late.feature is not None
        assert late.feature.dataset_version == "dataset-two"
        assert expired.status == "expired"
        assert expired.feature == correction
        assert absent.status == "missing" and absent.feature is None

        backdated = self._feature(definition, available_minute=2, numerator=7, revision="3")
        with pytest.raises(FeatureStoreError, match="advance availability"):
            store.append(definition, backdated)
        with pytest.raises(FeatureStoreError, match="different bytes"):
            store.append(
                definition,
                self._feature(definition, available_minute=4, numerator=8, revision="2"),
            )

    def test_staging_activation_restart_rollback_and_restore(self, tmp_path: Path) -> None:
        """Only a complete active version is visible, including after process restart."""
        definition = self._definition()
        path = tmp_path / "features.sqlite"
        store = VersionedFeatureStore.open(path)
        store.register(definition)
        store.append(definition, self._feature(definition))
        original = store.materialize(
            definition, "release-one", self._time(2), ("instrument-a", "instrument-b")
        )
        assert (
            store.materialize(
                definition, "release-one", self._time(2), ("instrument-a", "instrument-b")
            ).identity
            == original.identity
        )
        assert store.retrieve_online(definition, "instrument-a", self._time(2)).status == (
            "unmaterialized"
        )
        store.activate(definition, "release-one")
        assert store.retrieve_online(definition, "instrument-b", self._time(2)).status == "missing"

        store.append(
            definition, self._feature(definition, available_minute=3, numerator=5, revision="2")
        )
        newer = store.materialize(definition, "release-two", self._time(3), ("instrument-a",))
        assert newer.rows[0].require_ready().values == (ExactRatio(numerator="5", denominator="3"),)
        assert store.retrieve_online(definition, "instrument-a", self._time(3)).version == (
            "release-one"
        )
        with pytest.raises(FeatureStoreError, match="different bytes"):
            store.materialize(definition, "release-one", self._time(3), ("instrument-a",))
        assert store.active_version(definition) == "release-one"
        store.activate(definition, "release-two")
        assert store.retrieve_online(definition, "instrument-a", self._time(3)).feature == (
            newer.rows[0].feature
        )

        reopened = VersionedFeatureStore.open(path)
        assert reopened.get_materialization(definition, "release-two") == newer
        assert reopened.active_version(definition) == "release-two"
        reopened.activate(definition, "release-one")
        assert reopened.retrieve_online(definition, "instrument-a", self._time(3)).version == (
            "release-one"
        )
        backup = tmp_path / "features.backup.sqlite"
        reopened.backup(backup)
        restored = VersionedFeatureStore.restore(backup, tmp_path / "restored.sqlite")
        assert restored.active_version(definition) == "release-one"
        assert restored.get_materialization(definition, "release-two") == newer

    def test_online_quality_and_fitted_schema_validation(self, tmp_path: Path) -> None:
        """Missing, future, expired and stale states stay explicit at serving time."""
        base = self._definition()
        transformed = FeatureStoreDefinition(
            name=base.name,
            entity_type=base.entity_type,
            schema=base.schema,
            transform_identity="d" * 64,
            output_fields=(NumericField(name="centered", units="quote/base"),),
        )
        store = VersionedFeatureStore.open(tmp_path / "features.sqlite")
        store.register(transformed)
        with pytest.raises(FeatureStoreError, match="schema"):
            store.append(transformed, self._feature(base))
        missing = self._feature(transformed, numerator=None)
        store.append(transformed, missing)
        store.materialize(transformed, "fitted-one", self._time(1), ("instrument-a",))
        store.activate(transformed, "fitted-one")
        assert store.retrieve_online(transformed, "instrument-a", self._time(0)).status == (
            "future"
        )
        assert store.retrieve_online(transformed, "instrument-a", self._time(1)).status == (
            "missing"
        )
        assert store.retrieve_online(
            transformed, "instrument-a", self._time(3), max_materialization_age_us=0
        ).status == ("stale")
        assert store.retrieve_online(transformed, "instrument-a", self._time(11)).status == (
            "expired"
        )

    def test_prepared_worker_cannot_implicitly_roll_back_newer_publication(
        self, tmp_path: Path
    ) -> None:
        """Interleaved workers publish by compare-and-swap, while retry is idempotent."""
        definition = self._definition()
        store = VersionedFeatureStore.open(tmp_path / "features.sqlite")
        store.register(definition)
        store.append(definition, self._feature(definition))
        store.materialize(definition, "base", self._time(0), ("instrument-a",))
        store.activate_if_current(definition, "base", expected_version=None)
        observed = store.active_version(definition)
        store.materialize(definition, "slow-worker", self._time(0), ("instrument-a",))
        store.materialize(definition, "fast-worker", self._time(0), ("instrument-a",))

        store.activate_if_current(definition, "fast-worker", expected_version=observed)
        with pytest.raises(FeatureStoreError, match="changed during publication"):
            store.activate_if_current(definition, "slow-worker", expected_version=observed)
        assert store.active_version(definition) == "fast-worker"
        store.activate_if_current(definition, "fast-worker", expected_version=observed)
        assert store.active_version(definition) == "fast-worker"
        store.activate(definition, "base")
        assert store.active_version(definition) == "base"

    def test_incremental_checkpoint_commits_with_vector(self, tmp_path: Path) -> None:
        """A failed row does not advance state; restart consumes the committed state."""
        definition = self._definition(mode="incremental")
        store = VersionedFeatureStore.open(tmp_path / "features.sqlite")
        store.register(definition)
        kernel = RunningMeanFeature(definition.schema)
        session = FeatureSession(kernel, instance="strategy-one", entity="instrument-a")
        first_inputs = self._inputs(definition.schema, self._time(0), 2)
        first = session.evaluate(first_inputs)
        committed = self._from_vector(definition, first, "1")
        checkpoint = session.checkpoint()
        with pytest.raises(FeatureStoreError, match="checkpoint"):
            store.append(definition, committed)
        assert self._checkpoint(store, definition) is None
        store.append(definition, committed, checkpoint=checkpoint)
        store.append(definition, committed, checkpoint=checkpoint)
        with pytest.raises(ValueError, match="isolated instance"):
            FeatureStoreDefinition(
                name=definition.name, entity_type=definition.entity_type, schema=definition.schema
            )
        other = FeatureStoreDefinition(
            name=definition.name,
            entity_type=definition.entity_type,
            schema=definition.schema,
            instance="strategy-two",
        )
        store.register(other)
        independent = FeatureSession(kernel, instance="strategy-two", entity="instrument-a")
        other_vector = independent.evaluate(self._inputs(definition.schema, self._time(0), 8))
        store.append(
            other,
            self._from_vector(other, other_vector, "1"),
            checkpoint=independent.checkpoint(),
        )
        assert store.retrieve_offline(
            other, "instrument-a", self._time(0)
        ).require_ready().values == (ExactRatio(numerator="8", denominator="1"),)
        assert store.retrieve_offline(
            definition, "instrument-a", self._time(0)
        ).require_ready().values == (ExactRatio(numerator="2", denominator="1"),)
        invalid_state = b"different-successor"
        incompatible = FeatureCheckpoint(
            definition=checkpoint.definition,
            instance=checkpoint.instance,
            entity=checkpoint.entity,
            last_at=checkpoint.last_at,
            information_start=checkpoint.information_start,
            state=invalid_state,
            sha256=FeatureCheckpoint.digest(
                checkpoint.definition,
                checkpoint.instance,
                checkpoint.entity,
                checkpoint.last_at,
                checkpoint.information_start,
                invalid_state,
            ),
        )
        corrected = self._feature(definition, available_minute=1, numerator=9, revision="3")
        with pytest.raises(FeatureStoreError, match="different state"):
            store.append(definition, corrected, checkpoint=incompatible)
        assert self._checkpoint(store, definition) == checkpoint
        assert store.retrieve_offline(definition, "instrument-a", self._time(1)).feature == (
            committed
        )

        resumed = FeatureSession(
            kernel,
            instance="strategy-one",
            entity="instrument-a",
            checkpoint=self._checkpoint(store, definition),
        )
        second = resumed.evaluate(self._inputs(definition.schema, self._time(1), 4))
        assert second.values == (ExactRatio(numerator="3", denominator="1"),)
        store.append(
            definition, self._from_vector(definition, second, "2"), checkpoint=resumed.checkpoint()
        )
        assert self._checkpoint(store, definition) == resumed.checkpoint()
        with pytest.raises(FeatureStoreError, match="lineage changed"):
            store.get_checkpoint(
                definition,
                "strategy-one",
                "instrument-a",
                source_version="source-one",
                source_sha256="b" * 64,
                dataset_version="dataset-two",
                dataset_sha256="c" * 64,
            )
        assert store.retrieve_offline(
            definition, "instrument-a", self._time(1)
        ).require_ready().values == (ExactRatio(numerator="3", denominator="1"),)

    @staticmethod
    def _inputs(schema: FeatureSchema, at: datetime, numerator: int) -> DecisionInputs:
        """Construct a then-known named observation for the real incremental kernel."""
        return DecisionInputs(
            entity="instrument-a",
            decision_at=at,
            observations=(
                NamedObservation(
                    input=schema.inputs[0],
                    entity="instrument-a",
                    event_at=at,
                    available_at=at,
                    value=ExactRatio.from_fraction(Fraction(numerator)),
                    reason="observed",
                    lineage="source-row",
                ),
            ),
        )

    @staticmethod
    def _from_vector(
        definition: FeatureStoreDefinition, vector: FeatureVector, revision: str
    ) -> StoredFeature:
        """Bind a real FeatureSession result to explicit source and dataset bytes."""
        return StoredFeature(
            definition_identity=definition.identity,
            vector=vector,
            source_version="source-one",
            source_sha256="b" * 64,
            dataset_version="dataset-one",
            dataset_sha256="c" * 64,
            revision_identity=revision * 64,
        )

    @staticmethod
    def _checkpoint(
        store: VersionedFeatureStore, definition: FeatureStoreDefinition
    ) -> FeatureCheckpoint | None:
        """Read restart state only under the source and dataset that produced it."""
        return store.get_checkpoint(
            definition,
            "strategy-one",
            "instrument-a",
            source_version="source-one",
            source_sha256="b" * 64,
            dataset_version="dataset-one",
            dataset_sha256="c" * 64,
        )
