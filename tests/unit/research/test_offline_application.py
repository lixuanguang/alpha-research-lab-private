"""Verify formal offline feature parity retains MR3 and worker evidence."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

# project library imports
from applications.explore import compare_offline_features
from financial_units import ExactRatio
from market_data.query import InputBinding
from reference_data.instruments import InstrumentId
from research.experiments import (
    AttemptStore,
    ClearMLDestination,
    ExperimentSpec,
    FeatureLabelPayload,
    Fingerprint,
    ResultManifest,
    SampleInterval,
    TemporalSplit,
    TimeWindow,
)
from research.features import (
    FeatureEntity,
    FeatureObservation,
    FeatureValue,
    OfflineFeatureAccess,
    OfflineFeatureBridge,
    OfflineFeatureDefinition,
    OfflineFeatureRequest,
    OfflineFeatureResult,
    PricePoint,
    PriceWindow,
    TrailingReturn,
    WindowPolicy,
)
from serialization import DomainCodec

_CODEC = DomainCodec()
_START = datetime(2026, 1, 1, tzinfo=UTC)
_INSTRUMENT = InstrumentId(UUID("11111111-1111-4111-8111-111111111111"))
_BINDING: InputBinding = ("fixture-source", "trade", _INSTRUMENT)
_SOURCE_BYTES = b"offline-source-v1"


class _Worker:
    """Return one worker result while retaining every formal request."""

    def __init__(self, *, value: str = "1/100") -> None:
        """Bind one exact feature value returned for the source entity."""
        self.value = value
        self.requests: list[OfflineFeatureRequest] = []

    def __call__(self, request: bytes) -> bytes:
        """Decode the formal request and return its source row plus an omitted entity."""
        decoded = _CODEC.decode_json(request, OfflineFeatureRequest)
        self.requests.append(decoded)
        decision = decoded.decisions[0]
        row = FeatureObservation(
            definition_identity=decoded.definition.identity,
            source_version=decoded.definition.source_version,
            source_sha256=decoded.definition.source_sha256,
            feature_name=decoded.definition.feature_name,
            entity_type=decoded.definition.entity_type,
            entity_key=_CODEC.encode_json(_BINDING).decode(),
            decision_at=decision,
            event_at=decision,
            available_at=decision,
            ttl_us=decoded.definition.ttl_us,
            units=decoded.definition.units,
            value=self.value,
        )
        return _CODEC.encode_json(
            OfflineFeatureResult(
                request_identity=decoded.identity,
                definition_identity=decoded.definition.identity,
                registry_sha256=decoded.definition.registry_sha256,
                sdk_version=decoded.definition.sdk_version,
                source_version=decoded.definition.source_version,
                source_sha256=decoded.definition.source_sha256,
                rows=(row,),
            )
        )


class TestFormalOfflineFeatureComparison:
    """Exercise retained MR3 source, request rebinding and terminal parity outcomes."""

    @staticmethod
    def _split() -> TemporalSplit:
        """Declare one validation decision before the untouched final holdout."""
        return TemporalSplit(
            training=None,
            fit_cutoff=None,
            fit_mode="none",
            samples=(),
            embargo_us=0,
            rationale="Offline parity has no fitted state",
            validation=TimeWindow(start=_START, end=_START + timedelta(seconds=20)),
            holdout=TimeWindow(
                start=_START + timedelta(seconds=30), end=_START + timedelta(seconds=40)
            ),
        )

    @staticmethod
    def _payload(split: TemporalSplit) -> bytes:
        """Create one valid MR3 result with exact trailing-return evidence."""
        definition = TrailingReturn(
            policy=WindowPolicy(lookback_us=1_000_000, min_trades=2, max_staleness_us=500_000),
            cadence_us=10_000_000,
            processing_delay_us=0,
        )
        decision = _START + timedelta(seconds=10)
        point = PricePoint(
            identity="f" * 64,
            business_at=decision,
            event_at=decision,
            available_at=decision,
            price=Decimal("100"),
        )
        feature = FeatureValue(
            definition_identity=definition.identity,
            decision_at=decision,
            available_at=decision,
            window=PriceWindow(
                query_identity="e" * 64,
                binding=_BINDING,
                start=decision - timedelta(seconds=1),
                end=decision,
                known_at=decision,
                points=(point,),
                missing=None,
                evidence=(),
                controls=(),
            ),
            value=ExactRatio(numerator="1", denominator="100"),
        )
        payload = FeatureLabelPayload(
            schema_version="feature-study-result-v1",
            selection_identity="1" * 64,
            feature_definition=definition,
            label_definition=None,
            features=(("sample-1", feature),),
            labels=(),
            samples=(
                SampleInterval(
                    row_id="sample-1",
                    input_sha256="2" * 64,
                    decision_at=decision,
                    information_start=decision - timedelta(seconds=1),
                    information_end=decision,
                    features_available_at=decision,
                    label_available_at=None,
                ),
            ),
            split_identity=split.identity,
            fitting="not applicable: fixed diagnostic",
            scope="exploratory_degraded",
        )
        return _CODEC.encode_json(payload)

    @classmethod
    def _request(cls) -> OfflineFeatureRequest:
        """Declare one source entity and one explicitly missing entity."""
        definition = OfflineFeatureDefinition(
            feature_name="trailing_return",
            feature_ref="trailing_return:trailing_return",
            entity_type="instrument",
            units="dimensionless",
            ttl_us=10_000_000,
            sdk_version="0.66.0",
            definition_version="trailing-return-v1",
            definition_bytes=b"offline definition",
            registry_bytes=b"offline registry",
            source_version="offline-source-v1",
            source_sha256=hashlib.sha256(_SOURCE_BYTES).hexdigest(),
        )
        return OfflineFeatureRequest(
            definition=definition,
            entities=(
                FeatureEntity(
                    entity_type="instrument", entity_key=_CODEC.encode_json(_BINDING).decode()
                ),
                FeatureEntity(entity_type="instrument", entity_key="missing-entity"),
            ),
            decisions=(_START + timedelta(seconds=10),),
        )

    @classmethod
    def _source(cls, attempts: Path, split: TemporalSplit, payload: bytes) -> str:
        """Retain the completed MR3 payload in the shared family attempt store."""
        spec = ExperimentSpec(
            family="offline-formal",
            inputs=(Fingerprint(name="source", sha256="3" * 64),),
            components=(Fingerprint(name="implementation", sha256="a" * 64),),
            parameters=(("scope", "mr3"),),
            seeds=(),
            environment_sha256="b" * 64,
            split=split,
        )
        with AttemptStore(attempts) as store:
            start = store.start(
                spec,
                at=_START,
                invocation="test-mr3-source",
                request=b"source-request",
            )
            store.finish(
                start.attempt_id,
                status="completed",
                at=_START + timedelta(seconds=1),
                reason="completed MR3 fixture",
                result=payload,
            )
            return start.attempt_id

    @staticmethod
    def _tracking() -> ClearMLDestination:
        """Use non-secret local endpoints while publication is patched in this unit test."""
        return ClearMLDestination(
            project="unit",
            api_uri="http://127.0.0.1:18008",
            files_uri="http://127.0.0.1:18081",
        )

    def test_matching_grid_retains_manifest_and_one_worker_result(self, tmp_path: Path) -> None:
        """Retain request, SDK result, exact comparison, reference and source payload."""
        split = self._split()
        payload = self._payload(split)
        attempts = tmp_path / "attempts"
        source_attempt = self._source(attempts, split, payload)
        request = self._request()
        worker = _Worker()
        with (
            patch(
                "applications.explore.offline.ImplementationIdentity.sha256",
                return_value="a" * 64,
            ),
            patch(
                "applications.explore.offline.ExperimentSpec.installed_environment",
                return_value="b" * 64,
            ),
            patch("applications.explore.offline.ClearMLPublication.publish"),
        ):
            history = compare_offline_features(
                request,
                OfflineFeatureAccess(OfflineFeatureBridge(worker)),
                family="offline-formal",
                source_attempt=source_attempt,
                source_sha256=hashlib.sha256(payload).hexdigest(),
                split=split,
                attempts=attempts,
                tracking=self._tracking(),
            )
        assert history.status == "completed"
        assert len(worker.requests) == 1
        store = AttemptStore(attempts)
        names = store.artifacts(history.start.attempt_id)
        assert {
            "offline-feature-request",
            "offline-feature-result",
            "offline-feature-reference",
            "offline-feature-comparison",
            "mr3-feature-result",
        } <= set(names)
        manifest = ResultManifest.read(store, history.start.attempt_id)
        assert {item.name for item in manifest.artifacts} >= {
            "offline-feature-request",
            "offline-feature-result",
            "offline-feature-comparison",
            "mr3-feature-result",
        }

    def test_mismatch_is_rejected_with_retained_evidence(self, tmp_path: Path) -> None:
        """A value mismatch becomes a terminal rejection while all comparison evidence remains."""
        split = self._split()
        payload = self._payload(split)
        attempts = tmp_path / "attempts"
        source_attempt = self._source(attempts, split, payload)
        worker = _Worker(value="1/50")
        with (
            patch(
                "applications.explore.offline.ImplementationIdentity.sha256",
                return_value="a" * 64,
            ),
            patch(
                "applications.explore.offline.ExperimentSpec.installed_environment",
                return_value="b" * 64,
            ),
            patch("applications.explore.offline.ClearMLPublication.publish"),
        ):
            history = compare_offline_features(
                self._request(),
                OfflineFeatureAccess(OfflineFeatureBridge(worker)),
                family="offline-formal",
                source_attempt=source_attempt,
                source_sha256=hashlib.sha256(payload).hexdigest(),
                split=split,
                attempts=attempts,
                tracking=self._tracking(),
            )
        assert history.status == "rejected"
        assert "offline-feature-comparison" in AttemptStore(attempts).artifacts(
            history.start.attempt_id
        )
