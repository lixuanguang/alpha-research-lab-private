"""Exercise installed feature/label studies over saved, evidenced synthetic archive revisions."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
import research.features
from applications.explore import evaluate_model, inspect_experiment, publish_experiments
from configuration import Configuration
from financial_units import ExactRatio
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import SourceRequest
from market_data.datasets import DatasetPublication
from market_data.storage import RawFiles, RawStore
from market_data.validation import Correction, QualityPolicy, TradeRevision
from reference_data.catalogs import CatalogSnapshot
from reference_data.eligibility import EligibilityAssertions
from research.experiments import (
    AttemptStore,
    ClearMLDestination,
    ClearMLPublication,
    EvaluationRecord,
    SampleInterval,
    TemporalSplit,
    TimeWindow,
)
from research.exploration import EdaQuery, FeatureStudy, ResearchSelection, TradeSelection
from research.features import TrailingReturn, WindowPolicy
from research.labels import ForwardReturn
from research.models import LinearDefinition, ModelDataset, ModelStudy, ModelVersion, RetainedResult
from serialization import DomainCodec

_START = datetime(2024, 6, 1, tzinfo=UTC)
_CODEC = DomainCodec()
_LIMIT = 262_144
_RETAIN = AttemptStore.retain


class _StudyFixture:
    """Bind actual native archive decoding, correction evidence and retained stores."""

    def __init__(self, inputs: Path, output: Path) -> None:
        """Bind copied fixture configuration and a fresh outside-checkout output directory."""
        self.inputs, self.output = inputs, output
        self.raw = RawStore(output / "raw")

    def publish(self) -> ResearchSelection:
        """Publish two independent instruments with explicit synthetic revision availability."""
        config = Configuration.read(self.inputs / "binance-archive.json")
        catalog = _CODEC.decode_json(
            (self.inputs / "binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        run = config.resolve("spot-comparison", catalog, implementation_identity="a" * 64)
        descriptors = []
        publisher = DatasetPublication(SourceAdapters(), "a" * 64)
        for instrument, prices in zip(
            run.instruments,
            (
                ("100.03", "100.04", "100.05", "100.06", "100.08", "100.09"),
                ("20", "22", "24", "26", "29", "31"),
            ),
            strict=True,
        ):
            request = SourceRequest.partition(replace(run, instruments=(instrument,)))[0]
            rows = b""
            for trade_id, (second, price) in enumerate(
                zip((0, 9, 19, 30, 39, 49), prices, strict=True)
            ):
                event_ms = 1717200000000 + second * 1000
                for value in ("1.00", price):
                    rows += f"{trade_id},{value},2.0,2,{event_ms},true,true\n".encode()
            source = self.output / f"{instrument.symbol}.zip"
            member = ZipInfo(f"{instrument.symbol}-trades-2024-06-01.csv")
            member.compress_type = ZIP_DEFLATED
            with ZipFile(source, "w") as archive:
                archive.writestr(member, rows)
            origin = RawFiles.describe(
                source,
                request=request.binding,
                retrieval_reference="synthetic:diagnostic-revisions",
                ts_received=_START + timedelta(days=1),
                ts_ingested=_START + timedelta(days=1),
            )
            self.raw.publish(source, descriptor=origin, request=request.binding)
            descriptors.append(origin)
        acquisition = AcquisitionManifest(run=run, completed=tuple(descriptors))
        corrections: list[Correction] = []
        for partition in acquisition.partitions():
            occurrences = tuple(publisher.occurrences(partition, self.raw, max_bytes=_LIMIT))
            for index, second in enumerate((0, 9, 19, 30, 39, 49)):
                corrections.append(
                    Correction(
                        supersedes=TradeRevision(occurrences=(occurrences[2 * index],)).identity,
                        replacement=TradeRevision(
                            occurrences=(occurrences[2 * index + 1],)
                        ).identity,
                        ts_published=_START + timedelta(seconds=second + 1),
                        ts_available=_START + timedelta(seconds=second + 1),
                        evidence_reference="synthetic:diagnostic-correction-availability",
                    )
                )
        identity = publisher.publish(
            (acquisition,),
            self.raw,
            self.output / "snapshots",
            max_bytes=_LIMIT,
            policy=QualityPolicy(use="exploratory", known_at=_START, max_gap=timedelta(hours=1)),
            eligibility=EligibilityAssertions.read(
                self.inputs / "membership-corrections.json", catalog=catalog
            ),
            corrections={run.identity: tuple(corrections)},
        )
        return ResearchSelection(
            inputs=(
                TradeSelection(
                    name="prices",
                    query=EdaQuery(
                        snapshot_id=identity,
                        precedence=tuple(
                            (item.source, "trade", item.instrument_id) for item in run.instruments
                        ),
                        instruments=tuple(item.instrument_id for item in run.instruments),
                        start=_START,
                        end=_START + timedelta(seconds=30),
                        known_at=_START + timedelta(seconds=30),
                        columns=("revision",),
                        mode="cutoff",
                        batch_size=1,
                        max_bytes=_LIMIT,
                    ),
                ),
            )
        )

    def study(self, selection: ResearchSelection) -> FeatureStudy:
        """Configure one decision, two instruments and independently delayed forward outcomes."""
        return FeatureStudy(
            family="price-diagnostic",
            question="Inspect exact trailing and forward observed returns",
            selection=selection,
            partition="validation",
            decisions=TimeWindow(
                start=_START + timedelta(seconds=10), end=_START + timedelta(seconds=11)
            ),
            split=TemporalSplit(
                training=None,
                fit_cutoff=None,
                fit_mode="none",
                samples=(),
                embargo_us=0,
                rationale="Fixed diagnostic; label information ends before the holdout.",
                validation=TimeWindow(start=_START, end=_START + timedelta(minutes=1)),
                holdout=TimeWindow(
                    start=_START + timedelta(minutes=2), end=_START + timedelta(minutes=3)
                ),
            ),
            feature=TrailingReturn(
                policy=WindowPolicy(
                    lookback_us=10_000_000, min_trades=2, max_staleness_us=2_000_000
                ),
                cadence_us=10_000_000,
                processing_delay_us=0,
            ),
            label=ForwardReturn(
                horizon_us=10_000_000,
                availability_delay_us=1_000_000,
                policy=WindowPolicy(
                    lookback_us=10_000_000, min_trades=1, max_staleness_us=2_000_000
                ),
            ),
        )


class _ModelAcceptance:
    """Exercise installed models with ClearML or an explicitly unavailable transport."""

    @staticmethod
    def _configure_server() -> bool:
        """Load private local test credentials without putting them in retained manifests."""
        location = os.environ.get("ALPHA_CLEARML_LOCAL_ENV")
        if location is None:
            return False
        values = dict(line.split("=", 1) for line in Path(location).read_text().splitlines())
        os.environ.update(
            CLEARML_API_HOST="http://127.0.0.1:18008",
            CLEARML_WEB_HOST="http://127.0.0.1:18080",
            CLEARML_FILES_HOST="http://127.0.0.1:18081",
            CLEARML_API_ACCESS_KEY=values["CLEARML_LOCAL_ACCESS_KEY"],
            CLEARML_API_SECRET_KEY=values["CLEARML_LOCAL_SECRET_KEY"],
            CLEARML_CACHE_DIR=str(Path(location).parent / "alpha-clearml-cache"),
        )
        return True

    @staticmethod
    def _interrupt_receipt(store: AttemptStore, attempt_id: str, name: str, payload: bytes) -> str:
        """Simulate interruption after remote success but before durable local acknowledgement."""
        if name == "clearml-receipt":
            raise ConnectionError("injected receipt interruption")
        return _RETAIN(store, attempt_id, name, payload)

    @staticmethod
    def _selection_item(item: TradeSelection) -> TradeSelection:
        """Extend the same pinned input envelope to include the independent validation window."""
        return replace(
            item,
            query=replace(
                item.query,
                end=_START + timedelta(seconds=60),
                known_at=_START + timedelta(seconds=60),
            ),
        )

    @classmethod
    def run(cls, inputs: Path, output: Path) -> None:
        """Exercise installed models, terminal retention and optional actual server recovery."""
        is_server = cls._configure_server()
        output.mkdir()
        (output / "raw").mkdir()
        (output / "snapshots").mkdir()
        fixture = _StudyFixture(inputs, output)
        selection = fixture.publish()
        expanded = ResearchSelection(
            inputs=tuple(
                cls._selection_item(item)
                for item in selection.inputs
                if isinstance(item, TradeSelection)
            )
        )
        original = fixture.study(expanded)
        feature_study = replace(
            original,
            family="model-feature-inputs",
            decisions=TimeWindow(
                start=_START + timedelta(seconds=10), end=_START + timedelta(seconds=41)
            ),
            feature=replace(original.feature, cadence_us=30_000_000),
        )
        request = output / "features.json"
        request.write_bytes(_CODEC.encode_json(feature_study))
        attempts = output / "attempts"
        destination = ClearMLDestination(
            project="alpha-local-integration",
            api_uri="http://127.0.0.1:18008",
            files_uri="http://127.0.0.1:18081",
        )
        history = inspect_experiment(
            request,
            output / "snapshots",
            fixture.raw,
            attempts=attempts,
            tracking=destination if is_server else None,
        )
        payload = history.events[-1].result
        assert payload is not None
        dataset = ModelDataset.from_results((payload,))
        assert len(dataset.rows) == 4
        split = TemporalSplit(
            training=TimeWindow(start=_START, end=_START + timedelta(seconds=11)),
            fit_cutoff=_START + timedelta(seconds=22),
            fit_mode="labels",
            validation=TimeWindow(
                start=_START + timedelta(seconds=40), end=_START + timedelta(seconds=41)
            ),
            holdout=original.split.holdout,
            samples=tuple(row.sample for row in dataset.rows),
            embargo_us=0,
            rationale="Separate synthetic windows, no empirical selection claim",
        )
        study = ModelStudy(
            family="linear-construction",
            question="Verify exact fitted state and delayed error",
            sources=(
                RetainedResult(
                    attempt_id=history.start.attempt_id, sha256=hashlib.sha256(payload).hexdigest()
                ),
            ),
            split=split,
            partition="validation",
            known_at=_START + timedelta(seconds=60),
            max_mse=ExactRatio(numerator="100", denominator="1"),
            selection_reason="Fixed synthetic software threshold; no quality claim",
            definition=LinearDefinition(
                mode="least-squares", assumptions="Pooled dimensionless return diagnostic"
            ),
            available_at=_START + timedelta(seconds=23),
        )
        config = output / "model.json"
        config.write_bytes(_CODEC.encode_json(study))
        if is_server:
            with patch.object(AttemptStore, "retain", new=cls._interrupt_receipt):
                try:
                    evaluate_model(config, attempts=attempts, tracking=destination)
                except ConnectionError as error:
                    assert str(error) == "injected receipt interruption"
                else:
                    raise AssertionError("publication interruption was not reached")
        else:
            with patch.object(
                ClearMLPublication, "publish", side_effect=ConnectionError("unavailable transport")
            ):
                try:
                    evaluate_model(config, attempts=attempts, tracking=destination)
                except ConnectionError:
                    pass
                else:
                    raise AssertionError("unavailable publication must be visible")
        retained = AttemptStore(attempts)
        models = tuple(h for h in retained.histories() if h.start.spec.family == study.family)
        assert len(models) == 1 and models[0].status == "completed"
        model_id = models[0].start.attempt_id
        model = _CODEC.decode_json(retained.artifact(model_id, "model-version"), ModelVersion)
        assert len(model.fit_rows) == 2
        before = tuple(_CODEC.encode_json(h) for h in retained.histories())
        if is_server:
            receipts = publish_experiments(attempts)
            assert len(receipts) == 2
            assert publish_experiments(attempts) == receipts
            assert tuple(_CODEC.encode_json(h) for h in retained.histories()) == before
        # Reload never calls construct, even when the state was rejected by selection.
        reload_study = replace(
            study,
            definition=None,
            available_at=None,
            models=(RetainedResult(attempt_id=model_id, sha256=model.identity),),
        )
        config.write_bytes(_CODEC.encode_json(reload_study))
        with patch(
            "research.models.LinearModel.construct", side_effect=AssertionError("implicit refit")
        ):
            if is_server:
                reloaded = evaluate_model(config, attempts=attempts, tracking=destination)
                assert reloaded.events[-1].result == models[0].events[-1].result
            else:
                with patch.object(
                    ClearMLPublication, "publish", side_effect=ConnectionError("offline")
                ):
                    try:
                        evaluate_model(config, attempts=attempts, tracking=destination)
                    except ConnectionError:
                        pass
        if is_server:
            # A newly configured state is retained even when selection rejects it.
            rejected_study = replace(
                study,
                family="configured-rejection",
                split=replace(split, training=None, fit_cutoff=None, fit_mode="none"),
                definition=LinearDefinition(
                    mode="configured",
                    assumptions="Fixed zero-return analytical comparator",
                    intercept=ExactRatio(numerator="0", denominator="1"),
                    slope=ExactRatio(numerator="0", denominator="1"),
                ),
                available_at=_START,
                max_mse=ExactRatio(numerator="0", denominator="1"),
            )
            config.write_bytes(_CODEC.encode_json(rejected_study))
            rejected = evaluate_model(config, attempts=attempts, tracking=destination)
            assert rejected.status == "rejected"
            assert "model-version" in retained.artifacts(rejected.start.attempt_id)
            # A failed calibration has diagnostics but no invented usable state.
            failed_study = replace(rejected_study, definition=study.definition, family="failed-fit")
            config.write_bytes(_CODEC.encode_json(failed_study))
            try:
                evaluate_model(config, attempts=attempts, tracking=destination)
            except ValueError as error:
                assert "supervised label fitting" in str(error)
            else:
                raise AssertionError("forbidden calibration succeeded")
            failure = tuple(h for h in retained.histories() if h.start.spec.family == "failed-fit")
            assert len(failure) == 1 and failure[0].status == "failed"
            assert "model-version" not in retained.artifacts(failure[0].start.attempt_id)
            config.write_bytes(_CODEC.encode_json(replace(study, family="aborted-fit")))
            with patch("research.models.LinearModel.construct", side_effect=KeyboardInterrupt):
                try:
                    evaluate_model(config, attempts=attempts, tracking=destination)
                except KeyboardInterrupt:
                    pass
                else:
                    raise AssertionError("interruption was not propagated")
            aborted = tuple(h for h in retained.histories() if h.start.spec.family == "aborted-fit")
            assert len(aborted) == 1 and aborted[0].status == "abandoned"
            publish_experiments(attempts)
            assert all(
                "clearml-receipt" in retained.artifacts(h.start.attempt_id)
                for h in retained.histories()
            )
        (output / "dataset.json").write_bytes(_CODEC.encode_json(dataset))
        (output / "model-attempt.txt").write_text(model_id)
        backup = output / "backup"
        shutil.copytree(attempts, backup)
        restored = AttemptStore(backup)
        restored_model = _CODEC.decode_json(
            restored.artifact(model_id, "model-version"), ModelVersion
        )
        assert restored_model == model
        for row in dataset.rows:
            if row.sample.decision_at < model.available_at:
                continue
            assert restored_model.predict(row, dataset.signature) == model.predict(
                row, dataset.signature
            )
        assert restored.histories() == AttemptStore(attempts).histories()
        subprocess.run(
            [
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                str(inputs),
                str(output),
                "model-reopen",
            ],
            check=True,
            timeout=60,
        )
        print(
            "Installed saved-input model fit/reload, immutable history and backup bytes verified."
        )
        print(
            "ClearML server publication/reconciliation verified."
            if is_server
            else "ClearML transport unavailable by test design; no server claim."
        )

    @staticmethod
    def reopen(output: Path) -> None:
        """Reopen backup metadata and actual model bytes in a fresh installed interpreter."""
        store = AttemptStore(output / "backup")
        model_id = (output / "model-attempt.txt").read_text()
        model = _CODEC.decode_json(store.artifact(model_id, "model-version"), ModelVersion)
        dataset = _CODEC.decode_json((output / "dataset.json").read_bytes(), ModelDataset)
        evaluation = _CODEC.decode_json(store.artifact(model_id, "evaluation"), EvaluationRecord)
        predictions = {name: value for name, _, value, _, _ in evaluation.predictions}
        for row in dataset.rows:
            if row.sample.row_id in predictions:
                assert model.predict(row, dataset.signature) == predictions[row.sample.row_id]
        print("Fresh-process backup reload reproduces exact predictions.")


def main() -> None:
    """Publish real saved fixtures or reproduce the completed study in a fresh installed process.

    Raises:
        AssertionError: Numeric, causal, identity, installed or retained-attempt behavior differs.
    """
    inputs, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    if len(sys.argv) == 4 and sys.argv[3] == "model-reopen":
        _ModelAcceptance.reopen(output)
        return
    assert "site-packages" in Path(research.features.__file__).parts
    if len(sys.argv) == 3:
        output.mkdir()
        (output / "raw").mkdir()
        (output / "snapshots").mkdir()
        fixture = _StudyFixture(inputs, output)
        study = fixture.study(fixture.publish())
        (output / "study.json").write_bytes(_CODEC.encode_json(study))
    history = inspect_experiment(
        output / "study.json",
        output / "snapshots",
        RawStore(output / "raw"),
        attempts=output / "attempts",
    )
    assert history.status == "completed"
    payload = history.events[-1].result
    assert payload is not None
    result = msgspec.json.decode(payload, type=dict[str, msgspec.Raw])
    # NamedTuple result rows are arrays. Independent JSON checks avoid importing formula logic.
    features = msgspec.json.decode(
        result["features"], type=tuple[tuple[str, tuple[msgspec.Raw, ...]], ...]
    )
    labels = msgspec.json.decode(
        result["labels"], type=tuple[tuple[str, tuple[msgspec.Raw, ...]], ...]
    )
    assert [msgspec.json.decode(item[1][-1], type=dict[str, str]) for item in features] == [
        {"numerator": "1", "denominator": "10003"},
        {"numerator": "1", "denominator": "10"},
    ]
    assert [msgspec.json.decode(item[1][-1], type=dict[str, str]) for item in labels] == [
        {"numerator": "1", "denominator": "10004"},
        {"numerator": "1", "denominator": "11"},
    ]
    samples = msgspec.json.decode(result["samples"], type=tuple[SampleInterval, ...])
    assert len(samples) == 2 and all(
        sample.label_available_at == _START + timedelta(seconds=21) for sample in samples
    )
    assert tuple(item[0] for item in features) == tuple(item[0] for item in labels)
    if len(sys.argv) == 3:
        subprocess.run(
            [
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                str(inputs),
                str(output),
                "reopen",
            ],
            check=True,
            timeout=60,
        )
    else:
        retained = AttemptStore(output / "attempts").histories()
        assert len(retained) == 2
        assert retained[0].start.run_identity == retained[1].start.run_identity
        assert retained[0].events[-1].result == retained[1].events[-1].result
    (output / "result.json").write_bytes(payload)
    print("Installed two-instrument feature/label study and fresh-process parity verified.")
    if len(sys.argv) == 3:
        _ModelAcceptance.run(inputs, output / "models")


if __name__ == "__main__":
    main()
