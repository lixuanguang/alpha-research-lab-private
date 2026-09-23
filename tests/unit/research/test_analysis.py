"""Verify bounded DuckDB/Polars transformations preserve causal feature records."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from financial_units import ExactRatio
from reference_data.instruments import InstrumentId
from research.experiments import SampleInterval
from research.exploration.analysis import (
    AnalysisQuery,
    BoundedFeatureAnalysis,
    VerifiedFeatureRows,
)
from research.features import (
    FeatureObservation,
    FeatureValue,
    OfflineFeatureDefinition,
    PricePoint,
    PriceWindow,
    TrailingReturn,
    WindowPolicy,
)
from research.studies import FeatureLabelPayload
from serialization import DomainCodec

_START = datetime(2026, 1, 1, tzinfo=UTC)
_SOURCE_SHA256 = hashlib.sha256(b"analysis source").hexdigest()


class TestBoundedFeatureAnalysis:
    """Exercise exact values, nulls, UTC clocks, SQL filters and dataframe parity."""

    @staticmethod
    def _definition() -> OfflineFeatureDefinition:
        """Create one immutable feature manifest shared by all fixture rows."""
        return OfflineFeatureDefinition(
            feature_name="trailing_return",
            feature_ref="price_features:trailing_return",
            entity_type="instrument",
            units="dimensionless",
            ttl_us=60_000_000,
            sdk_version="0.66.0",
            definition_version="trailing-return-v1",
            definition_bytes=b"analysis definition",
            registry_bytes=b"analysis registry",
            source_version="analysis-source-v1",
            source_sha256=_SOURCE_SHA256,
        )

    @staticmethod
    def _row(
        definition: OfflineFeatureDefinition,
        *,
        entity_key: str,
        seconds: int,
        value: str | None,
        revision_identity: str | None = None,
    ) -> FeatureObservation:
        """Build one retained observation with exact ratio text and explicit nulls."""
        decision = _START + timedelta(seconds=seconds)
        return FeatureObservation(
            definition_identity=definition.identity,
            source_version=definition.source_version,
            source_sha256=definition.source_sha256,
            feature_name=definition.feature_name,
            entity_type=definition.entity_type,
            entity_key=entity_key,
            decision_at=decision,
            event_at=decision if value is not None else None,
            available_at=decision if value is not None else None,
            ttl_us=definition.ttl_us,
            units=definition.units,
            value=value,
            revision_identity=revision_identity,
            missing_reason=None if value is not None else "source value is null",
        )

    @classmethod
    def _source(cls) -> VerifiedFeatureRows:
        """Provide two instruments, two decisions and one explicit missing value."""
        definition = cls._definition()
        return VerifiedFeatureRows(
            (
                cls._row(definition, entity_key="ETH", seconds=20, value=None),
                cls._row(
                    definition,
                    entity_key="BTC",
                    seconds=10,
                    value="1/10003",
                    revision_identity="a" * 64,
                ),
                cls._row(
                    definition,
                    entity_key="ETH",
                    seconds=10,
                    value="1/200",
                    revision_identity="b" * 64,
                ),
                cls._row(
                    definition,
                    entity_key="BTC",
                    seconds=20,
                    value="1/10004",
                    revision_identity="c" * 64,
                ),
            )
        )

    def test_duckdb_and_polars_match_native_reference(self) -> None:
        """Both actual adapters preserve order, identities, exact strings and nulls."""
        source = self._source()
        query = AnalysisQuery(start=_START, end=_START + timedelta(seconds=30))
        comparison = BoundedFeatureAnalysis().compare(source, query)

        assert comparison.exact
        assert comparison.duckdb.rows == source.select(query)
        assert comparison.polars.rows == source.select(query)
        assert comparison.duckdb.rows[0].value == "1/10003"
        assert comparison.duckdb.rows[0].revision_identity == "a" * 64
        assert comparison.polars.rows[0].revision_identity == "a" * 64
        assert comparison.duckdb.rows[3].value is None
        assert comparison.duckdb.rows[0].decision_at.tzinfo is not None
        assert comparison.duckdb.rows[0].row_identity == comparison.polars.rows[0].row_identity

    def test_bounded_filters_and_missing_projection(self) -> None:
        """Fixed filters bound rows and allow an explicit non-null projection."""
        source = self._source()
        query = AnalysisQuery(
            entity_type="instrument",
            entity_key="BTC",
            start=_START,
            end=_START + timedelta(seconds=15),
            include_missing=False,
            max_rows=1,
        )
        result = BoundedFeatureAnalysis().polars(source, query)

        assert result.backend == "polars"
        assert len(result.rows) == 1
        assert result.rows[0].entity_key == "BTC"
        assert result.rows[0].value == "1/10003"

    def test_mixed_source_identity_and_unbounded_query_fail(self) -> None:
        """The adapter refuses mixed snapshots and query budgets beyond the contract."""
        source = self._source()
        definition = self._definition()
        changed = FeatureObservation(
            definition_identity=definition.identity,
            source_version=definition.source_version,
            source_sha256=hashlib.sha256(b"other source").hexdigest(),
            feature_name=definition.feature_name,
            entity_type=definition.entity_type,
            entity_key="SOL",
            decision_at=_START,
            event_at=_START,
            available_at=_START,
            ttl_us=definition.ttl_us,
            units=definition.units,
            value="1/3",
        )
        with pytest.raises(ValueError, match="mix immutable"):
            VerifiedFeatureRows((*source.rows, changed))
        with pytest.raises(ValueError, match="max_rows"):
            AnalysisQuery(max_rows=1_025)

    def test_mr3_result_converter_retains_binding_clocks_and_exact_value(self) -> None:
        """MR3 wire bytes become bounded rows without losing binding or revision evidence."""
        decision = _START + timedelta(seconds=10)
        binding = (
            "fixture-source",
            "trade",
            InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        )
        definition = TrailingReturn(
            policy=WindowPolicy(
                lookback_us=1_000_000,
                min_trades=2,
                max_staleness_us=500_000,
            ),
            cadence_us=10_000_000,
            processing_delay_us=0,
        )
        feature = FeatureValue(
            definition_identity=definition.identity,
            decision_at=decision,
            available_at=decision,
            window=PriceWindow(
                query_identity="e" * 64,
                binding=binding,
                start=decision - timedelta(seconds=1),
                end=decision,
                known_at=decision,
                points=(
                    PricePoint(
                        identity="f" * 64,
                        business_at=decision - timedelta(microseconds=1),
                        event_at=decision - timedelta(microseconds=1),
                        available_at=decision,
                        price=Decimal("100"),
                    ),
                ),
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
            split_identity="3" * 64,
            fitting="not applicable: fixed diagnostic",
            scope="exploratory_degraded",
        )
        raw = DomainCodec().encode_json(payload)
        rows = VerifiedFeatureRows.from_result(
            raw,
            hashlib.sha256(raw).hexdigest(),
            ttl_us=10_000_000,
        )

        assert len(rows.rows) == 1
        assert rows.rows[0].entity_key == DomainCodec().encode_json(binding).decode("utf-8")
        assert rows.rows[0].event_at == decision
        assert rows.rows[0].available_at == decision
        assert rows.rows[0].value == "1/100"
        assert rows.rows[0].revision_identity == "f" * 64

        null_payload = replace(
            payload,
            features=(
                (
                    "sample-1",
                    feature._replace(value=None),
                ),
            ),
        )
        null_raw = DomainCodec().encode_json(null_payload)
        null_rows = VerifiedFeatureRows.from_result(
            null_raw,
            hashlib.sha256(null_raw).hexdigest(),
            ttl_us=10_000_000,
        )

        assert null_rows.rows[0].event_at == decision
        assert null_rows.rows[0].available_at == decision
        assert null_rows.rows[0].value is None
        assert null_rows.rows[0].revision_identity == "f" * 64
        assert null_rows.rows[0].missing_reason == "feature value is null"
