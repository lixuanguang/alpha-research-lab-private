"""Unit tests for the execution layer (LA-012).

Covers:
- order_models.py: ValidatedOrder, ExecutionReport, enums, schema serialisation
- pretrade.py: PreTradeValidator accept/reject paths with deterministic codes
- simulator.py: FillSimulator fill price, fee, slippage, partial-fill, rejected input
- order_router.py: validator integration, pretrade_rejected counters
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from apps.live_system.order_router import OrderRouter, SubmissionResult

import alpha_core.strategy_framework.models as strategy_models
from alpha_core.execution.order_models import (
    ExecutionReport,
    OrderLifecycleStatus,
    RejectReasonCode,
    ValidatedOrder,
)
from alpha_core.execution.pretrade import PreTradeConfig, PreTradeValidator
from alpha_core.execution.simulator import FillConfig, FillSimulator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INST = "p:mkt1:yes"
_INST_B = "p:mkt1:no"


def _limit_order(
    instrument_id: str = _INST,
    price: str = "0.50",
    size: str = "1",
    direction: strategy_models.SignalDirection = strategy_models.SignalDirection.LONG,
) -> strategy_models.OrderIntent:
    return strategy_models.OrderIntent(
        instrument_id=instrument_id,
        order_type=strategy_models.OrderType.LIMIT,
        direction=direction,
        size=Decimal(size),
        price_limit=Decimal(price),
    )


def _market_order(
    instrument_id: str = _INST,
    size: str = "1",
) -> strategy_models.OrderIntent:
    return strategy_models.OrderIntent(
        instrument_id=instrument_id,
        order_type=strategy_models.OrderType.MARKET,
        direction=strategy_models.SignalDirection.LONG,
        size=Decimal(size),
    )


def _cancel_order(instrument_id: str = _INST) -> strategy_models.OrderIntent:
    return strategy_models.OrderIntent(
        instrument_id=instrument_id,
        order_type=strategy_models.OrderType.CANCEL,
        direction=strategy_models.SignalDirection.FLAT,
        size=Decimal("1"),
    )


def _market_state() -> strategy_models.MarketState:
    return strategy_models.MarketState(as_of_utc=datetime.now(tz=UTC), universe=[_INST])


# ---------------------------------------------------------------------------
# order_models — enums
# ---------------------------------------------------------------------------


class TestRejectReasonCode:
    def test_all_codes_are_strings(self) -> None:
        for code in RejectReasonCode:
            assert isinstance(code.value, str)
            assert code.value == str(code)

    def test_known_codes_present(self) -> None:
        expected = {
            "limit_order_no_price",
            "market_order_not_allowed",
            "price_out_of_range",
            "size_too_large",
            "notional_too_large",
            "instrument_not_allowed",
            "unknown",
        }
        actual = {code.value for code in RejectReasonCode}
        assert expected.issubset(actual)


class TestOrderLifecycleStatus:
    def test_terminal_statuses_present(self) -> None:
        for value in ("new", "validated", "rejected", "submitted", "filled",
                      "partial_fill", "cancelled", "expired"):
            assert OrderLifecycleStatus(value) is not None


# ---------------------------------------------------------------------------
# order_models — ValidatedOrder
# ---------------------------------------------------------------------------


class TestValidatedOrder:
    def test_is_valid_true_when_validated(self) -> None:
        vo = ValidatedOrder(
            intent=_limit_order(),
            status=OrderLifecycleStatus.VALIDATED,
        )
        assert vo.is_valid

    def test_is_valid_false_when_rejected(self) -> None:
        vo = ValidatedOrder(
            intent=_limit_order(),
            status=OrderLifecycleStatus.REJECTED,
            reject_reason_code=RejectReasonCode.SIZE_TOO_LARGE,
            reject_reason_detail="size=9999 > max=10",
        )
        assert not vo.is_valid

    def test_validated_at_set_by_default(self) -> None:
        before = datetime.now(tz=UTC)
        vo = ValidatedOrder(intent=_limit_order(), status=OrderLifecycleStatus.VALIDATED)
        after = datetime.now(tz=UTC)
        assert before <= vo.validated_at <= after

    def test_serialisation_round_trip(self) -> None:
        vo = ValidatedOrder(
            intent=_limit_order(),
            status=OrderLifecycleStatus.REJECTED,
            reject_reason_code=RejectReasonCode.PRICE_OUT_OF_RANGE,
            reject_reason_detail="price=1.5 > max=0.99",
        )
        payload = vo.model_dump(mode="json")
        _ = json.dumps(payload)  # must not raise
        assert payload["status"] == "rejected"
        assert payload["reject_reason_code"] == "price_out_of_range"

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(Exception):
            ValidatedOrder(  # type: ignore[call-arg]
                intent=_limit_order(),
                status=OrderLifecycleStatus.VALIDATED,
                unknown_field="oops",
            )


# ---------------------------------------------------------------------------
# order_models — ExecutionReport schema stability
# ---------------------------------------------------------------------------


class TestExecutionReportSchema:
    def _make_report(self) -> ExecutionReport:
        return ExecutionReport(
            order_id="ord001",
            instrument_id=_INST,
            status=OrderLifecycleStatus.FILLED,
            fill_price=Decimal("0.62"),
            fill_size=Decimal("5"),
            fee=Decimal("0.0031"),
            slippage=Decimal("0.0005"),
            source_intent=_limit_order(price="0.62"),
        )

    def test_required_fields_present(self) -> None:
        r = self._make_report()
        assert r.order_id == "ord001"
        assert r.instrument_id == _INST
        assert r.status == OrderLifecycleStatus.FILLED
        assert r.fill_price == Decimal("0.62")
        assert r.fill_size == Decimal("5")

    def test_serialisation_produces_stable_json(self) -> None:
        payload = self._make_report().model_dump(mode="json")
        raw = json.dumps(payload, sort_keys=True)  # must not raise
        assert "order_id" in payload
        assert "instrument_id" in payload
        assert "fill_price" in payload
        assert "fill_size" in payload
        assert "fee" in payload
        assert "slippage" in payload
        assert "status" in payload
        assert "source_intent" in payload
        _ = raw  # side-effect check

    def test_fill_price_clamped_to_probability_space(self) -> None:
        # Pydantic enforces ge=0/le=1 on fill_price
        with pytest.raises(Exception):
            ExecutionReport(
                order_id="x",
                instrument_id=_INST,
                status=OrderLifecycleStatus.FILLED,
                fill_price=Decimal("1.5"),
                source_intent=_limit_order(),
            )

    def test_fee_non_negative(self) -> None:
        with pytest.raises(Exception):
            ExecutionReport(
                order_id="x",
                instrument_id=_INST,
                status=OrderLifecycleStatus.FILLED,
                fee=Decimal("-0.01"),
                source_intent=_limit_order(),
            )


# ---------------------------------------------------------------------------
# PreTradeValidator — accept paths
# ---------------------------------------------------------------------------


class TestPreTradeValidatorAccept:
    def test_valid_limit_order_accepted(self) -> None:
        v = PreTradeValidator()
        order = _limit_order(price="0.50", size="1")
        result = v.validate(order)
        assert result.is_valid
        assert result.reject_reason_code is None

    def test_market_order_accepted_when_allowed(self) -> None:
        v = PreTradeValidator(PreTradeConfig(allow_market_orders=True))
        result = v.validate(_market_order())
        assert result.is_valid

    def test_cancel_order_bypasses_all_checks(self) -> None:
        cfg = PreTradeConfig(
            allow_market_orders=False,
            max_size_per_order=Decimal("0.001"),  # would reject any real order
        )
        v = PreTradeValidator(cfg)
        result = v.validate(_cancel_order())
        assert result.is_valid

    def test_state_parameter_is_optional(self) -> None:
        v = PreTradeValidator()
        result = v.validate(_limit_order(), state=None)
        assert result.is_valid

    def test_state_accepted_when_supplied(self) -> None:
        v = PreTradeValidator()
        result = v.validate(_limit_order(), state=_market_state())
        assert result.is_valid

    def test_validate_batch_all_valid(self) -> None:
        v = PreTradeValidator()
        orders = [_limit_order(price="0.40"), _limit_order(price="0.60")]
        results = v.validate_batch(orders)
        assert len(results) == 2
        assert all(r.is_valid for r in results)


# ---------------------------------------------------------------------------
# PreTradeValidator — reject paths
# ---------------------------------------------------------------------------


class TestPreTradeValidatorReject:
    def test_market_order_not_allowed(self) -> None:
        v = PreTradeValidator(PreTradeConfig(allow_market_orders=False))
        result = v.validate(_market_order())
        assert not result.is_valid
        assert result.reject_reason_code == RejectReasonCode.MARKET_ORDER_NOT_ALLOWED

    def test_limit_order_no_price(self) -> None:
        order = strategy_models.OrderIntent(
            instrument_id=_INST,
            order_type=strategy_models.OrderType.LIMIT,
            direction=strategy_models.SignalDirection.LONG,
            size=Decimal("1"),
            price_limit=None,
        )
        v = PreTradeValidator()
        result = v.validate(order)
        assert not result.is_valid
        assert result.reject_reason_code == RejectReasonCode.LIMIT_ORDER_NO_PRICE

    def test_price_too_low(self) -> None:
        v = PreTradeValidator(PreTradeConfig(min_price=Decimal("0.05")))
        result = v.validate(_limit_order(price="0.001"))
        assert not result.is_valid
        assert result.reject_reason_code == RejectReasonCode.PRICE_OUT_OF_RANGE

    def test_price_too_high(self) -> None:
        v = PreTradeValidator(PreTradeConfig(max_price=Decimal("0.95")))
        result = v.validate(_limit_order(price="0.99"))
        assert not result.is_valid
        assert result.reject_reason_code == RejectReasonCode.PRICE_OUT_OF_RANGE

    def test_size_too_large(self) -> None:
        v = PreTradeValidator(PreTradeConfig(max_size_per_order=Decimal("5")))
        result = v.validate(_limit_order(size="6"))
        assert not result.is_valid
        assert result.reject_reason_code == RejectReasonCode.SIZE_TOO_LARGE

    def test_notional_too_large(self) -> None:
        # size=100, price=0.70 → notional=70 > max_notional=50
        v = PreTradeValidator(PreTradeConfig(max_notional_per_order=Decimal("50")))
        result = v.validate(_limit_order(price="0.70", size="100"))
        assert not result.is_valid
        assert result.reject_reason_code == RejectReasonCode.NOTIONAL_TOO_LARGE

    def test_instrument_not_allowed(self) -> None:
        v = PreTradeValidator(
            PreTradeConfig(allowed_instruments=frozenset([_INST_B]))
        )
        result = v.validate(_limit_order(instrument_id=_INST))
        assert not result.is_valid
        assert result.reject_reason_code == RejectReasonCode.INSTRUMENT_NOT_ALLOWED

    def test_reject_reason_detail_populated(self) -> None:
        v = PreTradeValidator(PreTradeConfig(max_size_per_order=Decimal("5")))
        result = v.validate(_limit_order(size="10"))
        assert result.reject_reason_detail is not None
        assert "size=10" in result.reject_reason_detail

    def test_validate_batch_mixed(self) -> None:
        v = PreTradeValidator(PreTradeConfig(allow_market_orders=False))
        orders = [_limit_order(), _market_order(), _limit_order(price="0.30")]
        results = v.validate_batch(orders)
        assert len(results) == 3
        assert results[0].is_valid
        assert not results[1].is_valid
        assert results[1].reject_reason_code == RejectReasonCode.MARKET_ORDER_NOT_ALLOWED
        assert results[2].is_valid


# ---------------------------------------------------------------------------
# PreTradeValidator — determinism
# ---------------------------------------------------------------------------


class TestPreTradeValidatorDeterminism:
    def test_same_intent_same_result(self) -> None:
        v = PreTradeValidator(PreTradeConfig(allow_market_orders=False))
        order = _market_order()
        r1 = v.validate(order)
        r2 = v.validate(order)
        assert r1.reject_reason_code == r2.reject_reason_code
        assert r1.is_valid == r2.is_valid

    def test_check_ordering_instrument_takes_precedence(self) -> None:
        """Instrument not-allowed fires before any price/size checks."""
        v = PreTradeValidator(
            PreTradeConfig(
                allowed_instruments=frozenset([_INST_B]),
                allow_market_orders=False,
            )
        )
        # Market order + disallowed instrument → should get INSTRUMENT_NOT_ALLOWED
        result = v.validate(_market_order(instrument_id=_INST))
        assert result.reject_reason_code == RejectReasonCode.INSTRUMENT_NOT_ALLOWED


# ---------------------------------------------------------------------------
# FillSimulator
# ---------------------------------------------------------------------------


class TestFillSimulatorAccepted:
    def _accept(self, order: strategy_models.OrderIntent) -> ValidatedOrder:
        return ValidatedOrder(intent=order, status=OrderLifecycleStatus.VALIDATED)

    def test_long_limit_fill_price_includes_slippage(self) -> None:
        """LONG LIMIT: fill price > limit price by slippage fraction."""
        sim = FillSimulator(FillConfig(slippage_bps=Decimal("100"), fee_bps=Decimal("0")))
        order = _limit_order(price="0.50", size="1")
        report = sim.simulate(self._accept(order))
        # 100 bps = 1% of 0.50 = 0.005 → expected fill = 0.505
        assert report.fill_price is not None
        assert report.fill_price > Decimal("0.50")
        assert report.slippage > Decimal("0")

    def test_short_limit_fill_price_below_limit(self) -> None:
        """SHORT LIMIT: fill price < limit price (adverse slippage)."""
        sim = FillSimulator(FillConfig(slippage_bps=Decimal("100"), fee_bps=Decimal("0")))
        order = _limit_order(price="0.50", size="1",
                             direction=strategy_models.SignalDirection.SHORT)
        report = sim.simulate(self._accept(order))
        assert report.fill_price is not None
        assert report.fill_price < Decimal("0.50")
        assert report.slippage < Decimal("0")

    def test_fee_calculated_correctly(self) -> None:
        # 200 bps = 2% fee on notional (size=10, price=0.50 → notional=5 → fee=0.10)
        sim = FillSimulator(FillConfig(slippage_bps=Decimal("0"), fee_bps=Decimal("200")))
        order = _limit_order(price="0.50", size="10")
        report = sim.simulate(self._accept(order))
        assert report.fee is not None
        assert report.fee > Decimal("0")
        # fee ≈ 5 * 0.02 = 0.10
        assert abs(report.fee - Decimal("0.10")) < Decimal("0.001")

    def test_no_slippage_no_fee_config(self) -> None:
        sim = FillSimulator(FillConfig(slippage_bps=Decimal("0"), fee_bps=Decimal("0")))
        order = _limit_order(price="0.62", size="3")
        report = sim.simulate(self._accept(order))
        assert report.fill_price == Decimal("0.62")
        assert report.fee == Decimal("0")
        assert report.slippage == Decimal("0")

    def test_full_fill_status(self) -> None:
        sim = FillSimulator(FillConfig(fill_ratio=Decimal("1")))
        report = sim.simulate(self._accept(_limit_order()))
        assert report.status == OrderLifecycleStatus.FILLED

    def test_partial_fill_status(self) -> None:
        sim = FillSimulator(FillConfig(fill_ratio=Decimal("0.5")))
        report = sim.simulate(self._accept(_limit_order(size="4")))
        assert report.status == OrderLifecycleStatus.PARTIAL_FILL
        assert report.fill_size == Decimal("2")

    def test_fill_price_clamped_below_one(self) -> None:
        """Very high slippage on a high-priced LONG should not exceed 1."""
        sim = FillSimulator(FillConfig(slippage_bps=Decimal("10000"), fee_bps=Decimal("0")))
        order = _limit_order(price="0.99", size="1")
        report = sim.simulate(self._accept(order))
        assert report.fill_price is not None
        assert report.fill_price <= Decimal("1")

    def test_market_order_uses_market_price_arg(self) -> None:
        sim = FillSimulator(FillConfig(slippage_bps=Decimal("0"), fee_bps=Decimal("0")))
        order = _market_order(size="1")
        report = sim.simulate(self._accept(order), market_price=Decimal("0.70"))
        assert report.fill_price == Decimal("0.70")

    def test_market_order_fallback_price_when_none(self) -> None:
        """MARKET order with no price supplied → falls back to 0.5."""
        sim = FillSimulator(FillConfig(slippage_bps=Decimal("0"), fee_bps=Decimal("0")))
        report = sim.simulate(self._accept(_market_order()))
        assert report.fill_price is not None
        # Should be approximately 0.5 (exact if no slippage)
        assert report.fill_price > Decimal("0")
        assert report.fill_price <= Decimal("1")

    def test_order_id_auto_generated(self) -> None:
        sim = FillSimulator()
        r1 = sim.simulate(self._accept(_limit_order()))
        r2 = sim.simulate(self._accept(_limit_order()))
        assert r1.order_id != r2.order_id

    def test_explicit_order_id_used(self) -> None:
        sim = FillSimulator()
        report = sim.simulate(self._accept(_limit_order()), order_id="my-ord-123")
        assert report.order_id == "my-ord-123"

    def test_source_intent_preserved(self) -> None:
        order = _limit_order(price="0.45")
        sim = FillSimulator()
        report = sim.simulate(self._accept(order))
        assert report.source_intent.instrument_id == _INST
        assert report.source_intent.price_limit == Decimal("0.45")


class TestFillSimulatorRejected:
    def test_rejected_order_produces_cancelled_report(self) -> None:
        vo = ValidatedOrder(
            intent=_limit_order(),
            status=OrderLifecycleStatus.REJECTED,
            reject_reason_code=RejectReasonCode.SIZE_TOO_LARGE,
            reject_reason_detail="too big",
        )
        sim = FillSimulator()
        report = sim.simulate(vo)
        assert report.status == OrderLifecycleStatus.CANCELLED
        assert report.fill_price is None
        assert report.fill_size is None
        assert "pre-trade rejected" in (report.notes or "")

    def test_cancelled_report_has_correct_instrument(self) -> None:
        vo = ValidatedOrder(
            intent=_limit_order(instrument_id=_INST_B),
            status=OrderLifecycleStatus.REJECTED,
            reject_reason_code=RejectReasonCode.MARKET_ORDER_NOT_ALLOWED,
            reject_reason_detail="n/a",
        )
        sim = FillSimulator()
        report = sim.simulate(vo)
        assert report.instrument_id == _INST_B


class TestFillSimulatorSerialisation:
    def test_execution_report_json_stable(self) -> None:
        vo = ValidatedOrder(
            intent=_limit_order(),
            status=OrderLifecycleStatus.VALIDATED,
        )
        report = FillSimulator(
            FillConfig(slippage_bps=Decimal("0"), fee_bps=Decimal("0"))
        ).simulate(vo)
        payload = report.model_dump(mode="json")
        _ = json.dumps(payload)  # must not raise
        for key in ("order_id", "instrument_id", "status", "fill_price", "fill_size",
                    "fee", "slippage", "source_intent"):
            assert key in payload, f"missing key: {key}"


# ---------------------------------------------------------------------------
# OrderRouter — validator integration
# ---------------------------------------------------------------------------


class _AlwaysAcceptAdapter:
    def __init__(self) -> None:
        self.submitted: list[strategy_models.OrderIntent] = []

    def submit(self, order: strategy_models.OrderIntent) -> SubmissionResult:
        self.submitted.append(order)
        return SubmissionResult(order_id=f"ord_{order.instrument_id}", accepted=True)

    def cancel(self, order_id: str) -> bool:
        return True

    def adapter_id(self) -> str:
        return "test_accept"


class TestOrderRouterValidatorIntegration:
    def test_router_without_validator_routes_all(self) -> None:
        adapter = _AlwaysAcceptAdapter()
        router = OrderRouter(adapter)
        result = router.route([_limit_order(), _market_order()], _market_state())
        assert result.accepted == 2
        assert result.pretrade_rejected == 0

    def test_router_with_validator_blocks_market_orders(self) -> None:
        adapter = _AlwaysAcceptAdapter()
        validator = PreTradeValidator(PreTradeConfig(allow_market_orders=False))
        router = OrderRouter(adapter, validator=validator)
        result = router.route(
            [_limit_order(), _market_order(), _limit_order(price="0.30")],
            _market_state(),
        )
        assert result.accepted == 2
        assert result.pretrade_rejected == 1
        assert result.rejected == 1

    def test_pretrade_rejected_order_does_not_reach_adapter(self) -> None:
        adapter = _AlwaysAcceptAdapter()
        validator = PreTradeValidator(PreTradeConfig(allow_market_orders=False))
        router = OrderRouter(adapter, validator=validator)
        router.route([_market_order()], _market_state())
        assert adapter.submitted == []

    def test_routing_record_pretrade_rejected_flag(self) -> None:
        adapter = _AlwaysAcceptAdapter()
        validator = PreTradeValidator(PreTradeConfig(allow_market_orders=False))
        router = OrderRouter(adapter, validator=validator)
        result = router.route([_market_order()], _market_state())
        assert result.details[0].pretrade_rejected is True
        assert "pretrade:" in (result.details[0].reject_reason or "")

    def test_cumulative_pretrade_rejected_counter(self) -> None:
        adapter = _AlwaysAcceptAdapter()
        validator = PreTradeValidator(PreTradeConfig(allow_market_orders=False))
        router = OrderRouter(adapter, validator=validator)
        router.route([_market_order()], _market_state())
        router.route([_market_order()], _market_state())
        assert router.total_pretrade_rejected == 2

    def test_legitimate_orders_pass_through_after_validator(self) -> None:
        adapter = _AlwaysAcceptAdapter()
        validator = PreTradeValidator(PreTradeConfig(allow_market_orders=False))
        router = OrderRouter(adapter, validator=validator)
        router.route([_limit_order(), _limit_order(price="0.70")], _market_state())
        assert len(adapter.submitted) == 2

    def test_router_routing_result_all_accepted_false_when_pretrade_rejects(self) -> None:
        adapter = _AlwaysAcceptAdapter()
        validator = PreTradeValidator(PreTradeConfig(allow_market_orders=False))
        router = OrderRouter(adapter, validator=validator)
        result = router.route([_market_order()], _market_state())
        assert not result.all_accepted


# ---------------------------------------------------------------------------
# PreTradeValidator + FillSimulator pipeline
# ---------------------------------------------------------------------------


class TestEndToEndValidateAndSimulate:
    def test_valid_order_produces_filled_report(self) -> None:
        validator = PreTradeValidator()
        sim = FillSimulator(FillConfig(slippage_bps=Decimal("0"), fee_bps=Decimal("0")))
        order = _limit_order(price="0.62", size="2")
        validated = validator.validate(order)
        report = sim.simulate(validated)
        assert report.status == OrderLifecycleStatus.FILLED
        assert report.fill_price == Decimal("0.62")

    def test_rejected_order_produces_cancelled_report(self) -> None:
        validator = PreTradeValidator(PreTradeConfig(allow_market_orders=False))
        sim = FillSimulator()
        validated = validator.validate(_market_order())
        report = sim.simulate(validated)
        assert report.status == OrderLifecycleStatus.CANCELLED

    def test_validator_code_propagated_into_report_notes(self) -> None:
        validator = PreTradeValidator(PreTradeConfig(allow_market_orders=False))
        sim = FillSimulator()
        validated = validator.validate(_market_order())
        report = sim.simulate(validated)
        assert "market_order_not_allowed" in (report.notes or "")
