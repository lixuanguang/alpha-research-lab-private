"""Check bounded Alphalens diagnostics against independent expected examples."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from typing import cast

# third party library imports
import pytest

# project library imports
from financial_units import ExactRatio
from reference_data.instruments import InstrumentId
from research.experiments.diagnostics import (
    AlphalensDiagnostics,
    AlphalensStudy,
    FactorDirection,
    FeatureLabelPayload,
    PriceConvention,
    QuantileRule,
)
from research.experiments.splits import SampleInterval
from research.features import FeatureValue, PriceWindow, TrailingReturn, WindowPolicy
from research.labels import ForwardReturn, LabelValue
from serialization import DomainCodec

_START = datetime(2024, 1, 1, tzinfo=UTC)
_ASSETS = (
    InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
    InstrumentId.from_canonical_text("22222222-2222-4222-8222-222222222222"),
)
_SELECTION = "a" * 64


def _definitions() -> tuple[TrailingReturn, ForwardReturn]:
    """Build the retained feature and explicit forward-label definitions."""
    policy = WindowPolicy(
        lookback_us=1_000_000,
        min_trades=2,
        max_staleness_us=1_000_000,
    )
    return (
        TrailingReturn(policy=policy, cadence_us=10_000_000, processing_delay_us=0),
        ForwardReturn(policy=policy, horizon_us=10_000_000, availability_delay_us=1_000_000),
    )


def _payload(
    factors: tuple[tuple[int, ...], ...] = ((1, 2), (2, 1)),
    returns: tuple[tuple[int, ...], ...] = ((1, 2), (2, 1)),
    pending: tuple[tuple[int, int], ...] = (),
    assets: tuple[InstrumentId, ...] = _ASSETS,
    decision_step: timedelta = timedelta(seconds=10),
) -> FeatureLabelPayload:
    """Create a tiny retained result whose expected ranks are hand-computable."""
    feature_definition, label_definition = _definitions()
    feature_rows: list[tuple[str, FeatureValue]] = []
    label_rows: list[tuple[str, LabelValue]] = []
    samples: list[SampleInterval] = []
    pending_set = set(pending)
    for date_index, (date_factors, date_returns) in enumerate(zip(factors, returns, strict=True)):
        decision = _START + date_index * decision_step
        outcome = decision + timedelta(seconds=10)
        available = outcome + timedelta(seconds=1)
        for asset_index, (asset, factor, outcome_value) in enumerate(
            zip(assets, date_factors, date_returns, strict=True)
        ):
            row_id = f"{date_index}:{asset_index}"
            binding = ("fixture-source", "trade", asset)
            window = PriceWindow(
                query_identity="b" * 64,
                binding=binding,
                start=decision - timedelta(seconds=1),
                end=decision,
                known_at=decision,
                points=(),
                missing=None,
                evidence=(),
                controls=(),
            )
            feature = FeatureValue(
                definition_identity=feature_definition.identity,
                decision_at=decision,
                available_at=decision,
                window=window,
                value=ExactRatio(numerator=str(factor), denominator="1"),
            )
            is_pending = (date_index, asset_index) in pending_set
            label = LabelValue(
                definition_identity=label_definition.identity,
                decision_at=decision,
                outcome_at=outcome,
                information_start=decision - timedelta(seconds=1),
                information_end=outcome,
                available_at=None if is_pending else available,
                window=None,
                missing="outcome not yet available" if is_pending else None,
                value=(
                    None if is_pending else ExactRatio.from_fraction(Fraction(outcome_value, 10))
                ),
            )
            feature_rows.append((row_id, feature))
            label_rows.append((row_id, label))
            samples.append(
                SampleInterval(
                    row_id=row_id,
                    input_sha256="c" * 64,
                    decision_at=decision,
                    information_start=decision - timedelta(seconds=1),
                    information_end=outcome,
                    features_available_at=decision,
                    label_available_at=None if is_pending else available,
                )
            )
    return FeatureLabelPayload(
        schema_version="feature-study-result-v1",
        selection_identity=_SELECTION,
        feature_definition=feature_definition,
        label_definition=label_definition,
        features=tuple(feature_rows),
        labels=tuple(label_rows),
        samples=tuple(samples),
        split_identity="d" * 64,
        fitting="not applicable: fixed diagnostic",
        scope="exploratory_degraded",
    )


def _study(
    *,
    direction: str = "ascending",
    known_at: datetime | None = _START + timedelta(seconds=31),
    assets: tuple[InstrumentId, ...] = _ASSETS,
    quantile_rule: str = "equal-frequency-qcut-v1",
    price_convention: str = "forward-last-over-frozen-base-v1",
    demeaned: bool = True,
    group_adjust: bool = False,
) -> AlphalensStudy:
    """Build an explicit validation-only study over the fixture universe."""
    names = tuple(str(asset) for asset in assets)
    return AlphalensStudy(
        selection_identity=_SELECTION,
        universe=names,
        factor_direction=cast(FactorDirection, direction),
        horizon_us=10_000_000,
        price_convention=cast(PriceConvention, price_convention),
        groups=tuple((name, "core") for name in names),
        quantiles=2,
        known_at=known_at,
        quantile_rule=cast(QuantileRule, quantile_rule),
        demeaned=demeaned,
        group_adjust=group_adjust,
    )


class TestAlphalensDiagnostics:
    """Use hand-ranked factors and retained publication clocks."""

    def test_real_metrics_and_retention_bytes(self) -> None:
        """Aligned ranks produce IC one and retain the selected evaluation metadata."""
        payload = _payload()
        report = AlphalensDiagnostics().evaluate(
            _study(group_adjust=True, demeaned=True), DomainCodec().encode_json(payload)
        )

        assert report.inapplicable_reason is None
        assert report.horizon_us == 10_000_000
        assert report.eligible_rows == tuple(row_id for row_id, _ in payload.features)
        assert report.information_coefficients
        assert all(metric.value == pytest.approx(1.0) for metric in report.information_coefficients)
        assert tuple(metric.value for metric in report.quantile_returns) == pytest.approx(
            (-0.05, 0.05)
        )
        assert report.turnover and all(metric.value is None for metric in report.turnover)
        assert b'"selection_identity"' in report.json_bytes
        assert b"Alphalens factor diagnostics" in report.html_bytes

    def test_factor_direction_reverses_rank_ic(self) -> None:
        """Descending factors invert the independently aligned rank relationship."""
        report = AlphalensDiagnostics().evaluate(_study(direction="descending"), _payload())

        assert report.information_coefficients
        assert all(
            metric.value == pytest.approx(-1.0) for metric in report.information_coefficients
        )

    def test_pending_label_is_late_and_never_enters_metrics(self) -> None:
        """A label unavailable at the cutoff is retained as late with its expected clock."""
        payload = _payload(pending=((1, 1),))
        report = AlphalensDiagnostics().evaluate(_study(), payload)

        assert tuple(drop.row_id for drop in report.late_labels) == ("1:1",)
        assert report.late_labels[0].available_at == _START + timedelta(seconds=21)
        assert "1:1" not in report.eligible_rows

    def test_qcut_ties_are_bounded_and_invalid_policy_is_rejected(self) -> None:
        """Alphalens qcut drops tied buckets explicitly and rejects unimplemented rules."""
        report = AlphalensDiagnostics().evaluate(_study(), _payload(factors=((1, 1), (1, 1))))

        assert report.inapplicable_reason == "the selected quantile rule produced no eligible rows"
        assert {drop.reason for drop in report.dropped_rows} == {"quantile unavailable"}
        with pytest.raises(ValueError, match="invalid Alphalens"):
            _study(quantile_rule="rank-first-v1")
        with pytest.raises(ValueError, match="invalid Alphalens"):
            _study(price_convention="spot-close-v1")

    def test_daily_membership_swap_has_native_turnover(self) -> None:
        """A daily quantile membership swap produces concrete native turnover values."""
        payload = _payload(decision_step=timedelta(days=1))
        report = AlphalensDiagnostics().evaluate(
            _study(
                known_at=_START + timedelta(days=1, seconds=31),
                group_adjust=True,
                demeaned=True,
            ),
            payload,
        )

        values = tuple(metric.value for metric in report.turnover if metric.value is not None)
        assert values == pytest.approx((1.0, 1.0))

    def test_one_asset_is_inapplicable_without_calling_cross_section_stats(self) -> None:
        """A bounded one-asset payload returns an honest inapplicable report."""
        asset = (_ASSETS[0],)
        payload = _payload(
            factors=((1,), (2,)),
            returns=((1,), (2,)),
            assets=asset,
        )
        report = AlphalensDiagnostics().evaluate(_study(assets=asset), payload)

        assert report.inapplicable_reason == (
            "cross-sectional statistics require at least two assets at one decision"
        )
        assert report.information_coefficients == ()
