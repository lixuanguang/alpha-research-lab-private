"""Verify the isolated Feast bridge and bounded causal feature admission."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta

# third party library imports
import pandas as pd
import pytest

# project library imports
from applications.explore.command import FeastWorkerCommand
from research.features.offline import (
    FeatureAccessError,
    FeatureEntity,
    FeatureObservation,
    OfflineFeatureAccess,
    OfflineFeatureBridge,
    OfflineFeatureDefinition,
    OfflineFeatureRequest,
    OfflineFeatureResult,
)
from serialization import DomainCodec

_CODEC = DomainCodec()
_START = datetime(2026, 1, 1, tzinfo=UTC)
_SOURCE_BYTES = b"immutable source fixture v1"
_SOURCE_SHA256 = hashlib.sha256(_SOURCE_BYTES).hexdigest()


class _ResultWorker:
    """Return a predeclared result through the same JSON bridge as a worker process."""

    def __init__(self, rows: tuple[FeatureObservation, ...]) -> None:
        """Bind immutable fixture rows for one worker invocation."""
        self.rows = rows
        self.requests: list[OfflineFeatureRequest] = []

    def __call__(self, request: bytes) -> bytes:
        """Decode the request and emit the fixture result with its actual identity."""
        decoded = _CODEC.decode_json(request, OfflineFeatureRequest)
        self.requests.append(decoded)
        return _CODEC.encode_json(
            OfflineFeatureResult(
                request_identity=decoded.identity,
                definition_identity=decoded.definition.identity,
                registry_sha256=decoded.definition.registry_sha256,
                sdk_version=decoded.definition.sdk_version,
                source_version=decoded.definition.source_version,
                source_sha256=decoded.definition.source_sha256,
                rows=self.rows,
            )
        )


class TestOfflineFeatureAccess:
    """Exercise worker identity, availability, missingness and TTL boundaries."""

    @staticmethod
    def _definition(*, ttl_us: int = 10_000_000) -> OfflineFeatureDefinition:
        """Create a pinned ratio feature view over the independent source fixture."""
        return OfflineFeatureDefinition(
            feature_name="trailing_return",
            feature_ref="price_features:trailing_return",
            entity_type="instrument",
            units="dimensionless",
            ttl_us=ttl_us,
            sdk_version="0.66.0",
            definition_version="trailing-return-v1",
            definition_bytes=b"feature definition bytes v1",
            registry_bytes=b"registry bytes v1",
            source_version="source-snapshot-v1",
            source_sha256=_SOURCE_SHA256,
        )

    @classmethod
    def _request(
        cls,
        definition: OfflineFeatureDefinition,
        *,
        entities: tuple[FeatureEntity, ...] = (
            FeatureEntity(entity_type="instrument", entity_key="BTC"),
        ),
        decisions: tuple[datetime, ...] = (_START + timedelta(seconds=5),),
    ) -> OfflineFeatureRequest:
        """Create a bounded one-feature entity/decision grid."""
        return OfflineFeatureRequest(definition=definition, entities=entities, decisions=decisions)

    @staticmethod
    def _row(
        definition: OfflineFeatureDefinition,
        *,
        entity_key: str = "BTC",
        decision_at: datetime = _START + timedelta(seconds=5),
        event_at: datetime | None = _START,
        available_at: datetime | None = _START,
        value: str | None = "1/100",
    ) -> FeatureObservation:
        """Build one exact source row with explicit nullable clocks."""
        return FeatureObservation(
            definition_identity=definition.identity,
            source_version=definition.source_version,
            source_sha256=definition.source_sha256,
            feature_name=definition.feature_name,
            entity_type=definition.entity_type,
            entity_key=entity_key,
            decision_at=decision_at,
            event_at=event_at,
            available_at=available_at,
            ttl_us=definition.ttl_us,
            units=definition.units,
            value=value,
        )

    def test_retrieval_round_trip_pins_worker_and_exact_ratio(self) -> None:
        """A worker result retains the request, registry, source and exact value identities."""
        definition = self._definition()
        request = self._request(definition)
        row = self._row(definition)
        worker = _ResultWorker((row,))
        result = OfflineFeatureAccess(OfflineFeatureBridge(worker)).retrieve(request)

        assert result.rows == (row,)
        assert result.rows[0].value == "1/100"
        assert worker.requests[0].definition_identity == definition.identity
        assert worker.requests[0].request_identity == request.identity

    def test_late_correction_is_rejected_at_earlier_decision(self) -> None:
        """A value whose revision becomes available after the decision cannot enter the grid."""
        definition = self._definition()
        request = self._request(definition)
        late = self._row(
            definition,
            value="9/10",
            available_at=_START + timedelta(seconds=6),
        )
        with pytest.raises(FeatureAccessError, match="unavailable"):
            OfflineFeatureAccess(OfflineFeatureBridge(_ResultWorker((late,)))).retrieve(request)

    def test_missing_entity_is_explicit_nullable_row(self) -> None:
        """An omitted Feast entity is retained as a visible null rather than imputed."""
        definition = self._definition()
        request = self._request(
            definition,
            entities=(
                FeatureEntity(entity_type="instrument", entity_key="BTC"),
                FeatureEntity(entity_type="instrument", entity_key="ETH"),
            ),
        )
        btc = self._row(definition)
        result = OfflineFeatureAccess(OfflineFeatureBridge(_ResultWorker((btc,)))).retrieve(request)

        assert len(result.rows) == 2
        missing = result.rows[1]
        assert missing.entity_key == "ETH"
        assert missing.value is None
        assert missing.event_at is None and missing.available_at is None
        assert missing.missing_reason is not None

    def test_ttl_expiry_fails_closed(self) -> None:
        """A stale non-null value is an SDK contract failure, never an implicit null."""
        definition = self._definition(ttl_us=1_000_000)
        request = self._request(definition)
        stale = self._row(
            definition,
            event_at=_START,
            available_at=_START,
            decision_at=_START + timedelta(seconds=5),
        )
        with pytest.raises(FeatureAccessError, match="TTL"):
            OfflineFeatureAccess(OfflineFeatureBridge(_ResultWorker((stale,)))).retrieve(request)

    @pytest.mark.parametrize("bad_value", ("2/4", "01/2", "1/0", "0/2"))
    def test_noncanonical_exact_values_are_rejected(self, bad_value: str) -> None:
        """No decimal or unreduced ratio can cross the retained feature boundary."""
        definition = self._definition()
        with pytest.raises(ValueError):
            self._row(definition, value=bad_value)

    def test_bridge_rejects_changed_registry_or_sdk_metadata(self) -> None:
        """Worker metadata cannot silently substitute another SDK or registry."""
        definition = self._definition()
        request = self._request(definition)
        row = self._row(definition)

        class WrongRegistry(_ResultWorker):
            """Return a result bound to an unrelated registry digest."""

            def __call__(self, request: bytes) -> bytes:
                """Change only the registry metadata to exercise bridge admission."""
                decoded = _CODEC.decode_json(request, OfflineFeatureRequest)
                return _CODEC.encode_json(
                    OfflineFeatureResult(
                        request_identity=decoded.identity,
                        definition_identity=decoded.definition.identity,
                        registry_sha256="f" * 64,
                        sdk_version=decoded.definition.sdk_version,
                        source_version=decoded.definition.source_version,
                        source_sha256=decoded.definition.source_sha256,
                        rows=(row,),
                    )
                )

        with pytest.raises(FeatureAccessError, match="registry"):
            OfflineFeatureAccess(OfflineFeatureBridge(WrongRegistry((row,)))).retrieve(request)


class TestFeastWorkerRows:
    """Exercise pandas null normalization at the isolated SDK boundary."""

    @staticmethod
    def _nullish(value: object) -> bool:
        """Recognize the scalar nulls emitted by pandas in a retrieval frame."""
        return value is None or value is pd.NaT or (type(value) is float and value != value)

    @staticmethod
    def _definition() -> dict[str, object]:
        """Return the minimal feature metadata accepted by the row aligner."""
        return {
            "feature_name": "trailing_return",
            "feature_ref": "trailing_return:trailing_return",
            "source_version": "source-v1",
            "source_sha256": "a" * 64,
            "ttl_us": 1_000_000,
            "units": "dimensionless",
        }

    def test_missing_entity_nat_clocks_become_explicit_null(self) -> None:
        """Feast's all-null entity row is skipped and represented by the requested grid."""
        decision = _START + timedelta(seconds=5)
        records: list[dict[str, object]] = [
            {
                "instrument": "missing",
                "event_timestamp": decision,
                "trailing_return": float("nan"),
                "feature_event_timestamp": pd.NaT,
                "created_timestamp": pd.NaT,
            }
        ]
        rows = FeastWorkerCommand()._rows(
            records,
            definition=self._definition(),
            definition_identity="b" * 64,
            entities=[{"entity_type": "instrument", "entity_key": "missing"}],
            decisions=(decision,),
            join_column="instrument",
            is_nullish=self._nullish,
        )

        assert rows == [
            {
                "schema_version": "feature-observation-v1",
                "definition_identity": "b" * 64,
                "source_version": "source-v1",
                "source_sha256": "a" * 64,
                "feature_name": "trailing_return",
                "entity_type": "instrument",
                "entity_key": "missing",
                "decision_at": decision.isoformat(),
                "event_at": None,
                "available_at": None,
                "ttl_us": 1_000_000,
                "units": "dimensionless",
                "value": None,
                "revision_identity": None,
                "missing_reason": "missing entity or no eligible source row",
            }
        ]

    @pytest.mark.parametrize("missing_clock", ("feature_event_timestamp", "created_timestamp"))
    def test_partial_nat_clock_is_rejected(self, missing_clock: str) -> None:
        """A matched value with only one source clock cannot cross the worker boundary."""
        decision = _START + timedelta(seconds=5)
        records: list[dict[str, object]] = [
            {
                "instrument": "BTC",
                "event_timestamp": decision,
                "trailing_return": "1/100",
                "feature_event_timestamp": decision,
                "created_timestamp": decision,
            }
        ]
        records[0][missing_clock] = pd.NaT

        with pytest.raises(ValueError, match="partial source clocks"):
            FeastWorkerCommand()._rows(
                records,
                definition=self._definition(),
                definition_identity="b" * 64,
                entities=[{"entity_type": "instrument", "entity_key": "BTC"}],
                decisions=(decision,),
                join_column="instrument",
                is_nullish=self._nullish,
            )
