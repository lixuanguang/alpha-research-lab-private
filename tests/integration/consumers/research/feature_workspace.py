"""Qualify installed incremental features against the isolated real Feast worker."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.util import find_spec
from pathlib import Path

# third party library imports
from msgspec.structs import replace

# project library imports
from applications.explore import run_served_decision
from financial_units import Dimension, ExactRatio, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from research.features import (
    FeastOfflineWorker,
    FeastServingBridge,
    FeastServingSnapshot,
    FeatureMaterializer,
    FeatureSchema,
    FeatureStoreDefinition,
    RunningMeanFeature,
    VersionedFeatureStore,
)
from research.observations import (
    InputRequirement,
    NamedObservation,
    NumericField,
    NumericHistorySource,
)
from runtime import WorkspaceBackup
from serialization import DomainCodec
from strategies import ConfirmedSignal, DecisionSession


class _FeatureWorkspace:
    """Exercise named multi-entity features, online intents and clean workspace recovery."""

    def __init__(self, root: Path, worker_python: Path) -> None:
        """Select the installed command bytes and independently locked interpreter."""
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=False)
        spec = find_spec("applications.explore.command")
        if spec is None or spec.origin is None:
            raise ValueError("installed feature worker command missing")
        command = (
            str(worker_python.absolute()),
            "-I",
            "-c",
            "from runpy import run_path; "
            f"raise SystemExit(run_path({spec.origin!r})['main'](['feast-serving-worker']))",
        )
        self.bridge = FeastServingBridge(FeastOfflineWorker(command, timeout_seconds=120))
        self.entities = (
            "4476df8e-6342-4417-839e-e41b88f41446",
            "78239923-9ec5-47fa-80df-4b0b8c652cdd",
        )
        self.requirement = InputRequirement(
            name="reference-signal",
            family="non-book",
            clock="authored",
            field=NumericField(name="signal", units="dimensionless"),
            max_age_us=0,
        )
        self.rows = tuple(
            NamedObservation(
                input=self.requirement,
                entity=entity,
                event_at=self.at(second),
                available_at=self.at(second),
                value=ExactRatio(numerator=str(multiplier * value), denominator="1"),
                reason="authored engineering input",
                lineage=f"{entity}:{second}:{value}",
            )
            for entity, multiplier in zip(self.entities, (1, 10), strict=True)
            for second, value in ((1, 1), (2, 3), (3, 5))
        )
        self.source = NumericHistorySource(self.rows, (self.requirement,))
        self.kernel = RunningMeanFeature(
            FeatureSchema(
                implementation="running-mean",
                inputs=(self.requirement,),
                outputs=(self.requirement.field,),
                parameters=(),
                mode="incremental",
                ttl_us=5_000_000,
            )
        )
        self.definition = FeatureStoreDefinition(
            name="reference-expanding-mean",
            entity_type="instrument",
            schema=self.kernel.schema,
            instance="reference-feature-stream",
        )
        self.store = VersionedFeatureStore.open(self.root / "features" / "history.sqlite3")
        self.lineage = hashlib.sha256(DomainCodec().encode_json(self.rows)).hexdigest()
        (self.root / "raw").mkdir()
        (self.root / "snapshots").mkdir()
        (self.root / "raw" / "source.json").write_bytes(DomainCodec().encode_json(self.rows))
        (self.root / "snapshots" / "source.json").write_bytes(
            DomainCodec().encode_json(
                {
                    "source_identity": self.source.identity,
                    "source_sha256": self.lineage,
                }
            )
        )
        (self.root / "features" / "definition.json").write_bytes(
            DomainCodec().encode_json(self.definition)
        )

    @staticmethod
    def at(second: int) -> datetime:
        """Use authored UTC clocks without representing original venue receipt times."""
        return datetime(2026, 9, 24, tzinfo=UTC) + timedelta(seconds=second)

    def materialize(self, seconds: tuple[int, ...], version: str) -> None:
        """Run the real generalized application with exact source and dataset pins."""
        FeatureMaterializer().materialize(
            self.store,
            self.definition,
            source=self.source,
            kernel=self.kernel,
            instance="reference-feature-stream",
            entities=self.entities,
            decisions=tuple(self.at(second) for second in seconds),
            source_version=self.source.identity,
            source_sha256=self.lineage,
            dataset_version="authored-source",
            dataset_sha256=self.lineage,
            version=version,
            bridge=self.bridge,
            serving_root=self.root / "serving",
        )

    def run(self) -> None:
        """Verify exact parity, restart, correction, rollback, staleness and service loss."""
        self.materialize((1, 2), "warm")
        self.store = VersionedFeatureStore.open(self.root / "features" / "history.sqlite3")
        self.materialize((1, 2, 3), "current")
        self.materialize((1, 2, 3), "current")
        for entity, expected in zip(self.entities, ("3", "30"), strict=True):
            offline = self.store.retrieve_offline(self.definition, entity, self.at(3))
            online = self.store.retrieve_online(self.definition, entity, self.at(3))
            assert offline.require_ready().values == (
                ExactRatio(numerator=expected, denominator="1"),
            )
            assert online.require_ready() == offline.require_ready()
        original = self.store.retrieve_offline(
            self.definition, self.entities[0], self.at(3)
        ).feature
        assert original is not None
        correction_definition = replace(
            self.definition,
            name="reference-batch-correction",
            schema=replace(self.kernel.schema, mode="batch"),
            instance=None,
        )
        self.store.register(correction_definition)
        original = replace(
            original,
            definition_identity=correction_definition.identity,
            vector=replace(original.vector, definition=correction_definition.schema.identity),
        )
        self.store.append(correction_definition, original)
        correction = replace(
            original,
            vector=replace(
                original.vector,
                available_at=self.at(4),
                values=(ExactRatio(numerator="4", denominator="1"),),
            ),
            revision_identity=hashlib.sha256(b"late-correction").hexdigest(),
        )
        self.store.append(correction_definition, correction)
        assert (
            self.store.retrieve_offline(correction_definition, self.entities[0], self.at(3)).feature
            == original
        )
        assert (
            self.store.retrieve_offline(correction_definition, self.entities[0], self.at(4)).feature
            == correction
        )
        dimension = Dimension(
            instrument_id=InstrumentId.from_canonical_text(self.entities[1]),
            kind=QuantityKind.BASE_UNIT,
        )
        policy = ConfirmedSignal(
            field=self.kernel.schema.outputs[0],
            quantity=Quantity(value=Decimal("1"), dimension=dimension),
            confirmations=1,
        )
        session = DecisionSession(
            policy,
            run_identity=self.definition.identity,
            instance="online-reference",
            entity=self.entities[1],
        )
        decision = run_served_decision(
            self.store,
            self.definition,
            entity=self.entities[1],
            at=self.at(4),
            session=session,
            bridge=self.bridge,
            serving_root=self.root / "serving",
        )
        assert decision.status == "decided" and decision.decision is not None
        assert decision.decision.at == self.at(4)
        assert (
            decision.feature is not None
            and decision.feature.require_ready().decision_at == self.at(3)
        )
        checkpoint = session.checkpoint()
        expired = run_served_decision(
            self.store,
            self.definition,
            entity=self.entities[1],
            at=self.at(9),
            session=session,
            bridge=self.bridge,
            serving_root=self.root / "serving",
        )
        assert expired.status == "paused" and expired.checkpoint == checkpoint
        absent = run_served_decision(
            self.store,
            self.definition,
            entity=self.entities[1],
            at=self.at(5),
            session=session,
            bridge=self.bridge,
            serving_root=self.root / "unavailable-service",
        )
        assert absent.status == "paused" and absent.checkpoint == checkpoint
        self.store.activate(self.definition, "warm")
        assert self.store.retrieve_online(
            self.definition, self.entities[1], self.at(2)
        ).require_ready().values == (ExactRatio(numerator="20", denominator="1"),)
        self.store.activate(self.definition, "current")
        backup = self.root.parent / (self.root.name + "-backup")
        restored = self.root.parent / (self.root.name + "-restored")
        WorkspaceBackup.create(self.root, backup, components=("features", "serving"))
        WorkspaceBackup.restore(backup, restored)
        reopened = VersionedFeatureStore.open(restored / "features" / "history.sqlite3")
        assert (
            reopened.retrieve_offline(correction_definition, self.entities[0], self.at(3)).feature
            == original
        )
        snapshot = FeastServingSnapshot.from_materialization(
            reopened.get_materialization(self.definition, "current")
        )
        generation = self.bridge.open_generation(snapshot, restored / "serving")
        served = self.bridge.retrieve(snapshot, generation, self.entities[1], self.at(3))
        assert served.values == ("30/1",)
        (self.root / "acceptance.json").write_bytes(
            DomainCodec().encode_json(
                {
                    "definition": self.definition.identity,
                    "source_sha256": self.lineage,
                    "matched_cutoff_exact": True,
                    "incremental_restart": True,
                    "late_correction_pit": True,
                    "rollback": True,
                    "online_intent": True,
                    "stale_service_pause": True,
                    "clean_restore_feast": True,
                }
            )
        )
        print((self.root / "acceptance.json").read_text())


class _Arguments(argparse.Namespace):
    """Narrow the two explicit filesystem selections at the command boundary."""

    output: Path
    worker_python: Path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--worker-python", type=Path, required=True)
    arguments = _Arguments()
    parser.parse_args(namespace=arguments)
    _FeatureWorkspace(arguments.output, arguments.worker_python).run()
