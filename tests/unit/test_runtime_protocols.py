"""Unit tests for alpha_core.runtime_protocols (13.1 — Provider-Agnostic Runtime Protocols).

Covers:
- Protocol interface importability and ``@runtime_checkable`` isinstance checks
- Model construction and field validation
- Serialization round-trips (model → dict → model)
- Field bound enforcement (prices in [0,1], positive sizes, non-empty IDs)
- Stub conformance: minimal classes that satisfy each protocol
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

import alpha_core.runtime_protocols.interfaces as rt_interfaces
import alpha_core.runtime_protocols.models as rt_models

# ---------------------------------------------------------------------------
# Minimal stub implementations satisfying each protocol
# ---------------------------------------------------------------------------


class _StubAccountProvider:
    def get_account_snapshot(self) -> rt_models.AccountSnapshot:
        return rt_models.AccountSnapshot(
            positions={"kalshi:mrkt:yes": Decimal("10")},
            balances={"USD": Decimal("500")},
            buying_power=Decimal("490"),
        )

    def get_buying_power(self) -> Decimal:
        return Decimal("490")


class _StubMarketProvider:
    def get_top_of_book(self, instrument_id: str) -> rt_models.TopOfBook:
        return rt_models.TopOfBook(
            instrument_id=instrument_id,
            best_bid=Decimal("0.45"),
            best_ask=Decimal("0.55"),
            bid_size=Decimal("100"),
            ask_size=Decimal("80"),
        )

    def get_instrument_status(self, instrument_id: str) -> rt_models.InstrumentStatus:
        return rt_models.InstrumentStatus(
            instrument_id=instrument_id,
            lifecycle="active",
            is_tradeable=True,
        )


class _StubOrderRouter:
    def submit_order(self, order: object) -> str:
        return "venue-order-001"

    def cancel_order(self, order_id: str) -> bool:
        return True

    def query_order(self, order_id: str) -> rt_models.OrderStatus:
        return rt_models.OrderStatus(
            order_id=order_id,
            instrument_id="kalshi:mrkt:yes",
            status=rt_models.OrderStatusCode.OPEN,
            filled_size=Decimal("0"),
            remaining_size=Decimal("5"),
        )


class _StubExecutionAcknowledger:
    def __init__(self) -> None:
        self.acks: list[rt_models.OrderAck] = []
        self.rejects: list[rt_models.OrderReject] = []
        self.fills: list[rt_models.OrderFill] = []

    def on_ack(self, ack: rt_models.OrderAck) -> None:
        self.acks.append(ack)

    def on_reject(self, reject: rt_models.OrderReject) -> None:
        self.rejects.append(reject)

    def on_fill(self, fill: rt_models.OrderFill) -> None:
        self.fills.append(fill)


# ---------------------------------------------------------------------------
# 1. Protocol isinstance checks
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_account_provider_isinstance(self) -> None:
        assert isinstance(_StubAccountProvider(), rt_interfaces.AccountStateProvider)

    def test_market_provider_isinstance(self) -> None:
        assert isinstance(_StubMarketProvider(), rt_interfaces.MarketStateProvider)

    def test_order_router_isinstance(self) -> None:
        assert isinstance(_StubOrderRouter(), rt_interfaces.OrderRouter)

    def test_execution_acknowledger_isinstance(self) -> None:
        assert isinstance(_StubExecutionAcknowledger(), rt_interfaces.ExecutionAcknowledger)

    def test_plain_object_fails_account_provider(self) -> None:
        assert not isinstance(object(), rt_interfaces.AccountStateProvider)

    def test_plain_object_fails_order_router(self) -> None:
        assert not isinstance(object(), rt_interfaces.OrderRouter)

    def test_plain_object_fails_execution_acknowledger(self) -> None:
        assert not isinstance(object(), rt_interfaces.ExecutionAcknowledger)


# ---------------------------------------------------------------------------
# 2. AccountSnapshot
# ---------------------------------------------------------------------------


class TestAccountSnapshot:
    def test_construct_minimal(self) -> None:
        snap = rt_models.AccountSnapshot(buying_power=Decimal("100"))
        assert snap.positions == {}
        assert snap.balances == {}
        assert snap.buying_power == Decimal("100")
        assert snap.ts_snapshot.tzinfo is not None

    def test_negative_buying_power_rejected(self) -> None:
        with pytest.raises(ValidationError):
            rt_models.AccountSnapshot(buying_power=Decimal("-1"))

    def test_round_trip(self) -> None:
        snap = rt_models.AccountSnapshot(
            positions={"kalshi:mrkt:yes": Decimal("5")},
            balances={"USD": Decimal("200")},
            buying_power=Decimal("195"),
        )
        restored = rt_models.AccountSnapshot.model_validate(snap.model_dump())
        assert restored.buying_power == snap.buying_power
        assert restored.positions == snap.positions

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            rt_models.AccountSnapshot(buying_power=Decimal("100"), unknown_field="x")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# 3. TopOfBook
# ---------------------------------------------------------------------------


class TestTopOfBook:
    def test_construct_full(self) -> None:
        tob = rt_models.TopOfBook(
            instrument_id="poly:abc:yes",
            best_bid=Decimal("0.48"),
            best_ask=Decimal("0.52"),
            bid_size=Decimal("200"),
            ask_size=Decimal("150"),
        )
        assert tob.instrument_id == "poly:abc:yes"
        assert tob.best_bid == Decimal("0.48")

    def test_price_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            rt_models.TopOfBook(instrument_id="x:y:z", best_bid=Decimal("1.01"))

    def test_price_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            rt_models.TopOfBook(instrument_id="x:y:z", best_ask=Decimal("-0.01"))

    def test_empty_instrument_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            rt_models.TopOfBook(instrument_id="")

    def test_all_none_prices_allowed(self) -> None:
        tob = rt_models.TopOfBook(instrument_id="x:y:z")
        assert tob.best_bid is None
        assert tob.best_ask is None


# ---------------------------------------------------------------------------
# 4. InstrumentStatus
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lifecycle", ["active", "halted", "resolved", "delisted"])
def test_instrument_status_lifecycles(lifecycle: str) -> None:
    status = rt_models.InstrumentStatus(
        instrument_id="kalshi:mrkt:yes",
        lifecycle=lifecycle,
        is_tradeable=lifecycle == "active",
    )
    assert status.lifecycle == lifecycle


def test_instrument_status_round_trip() -> None:
    s = rt_models.InstrumentStatus(
        instrument_id="kalshi:mrkt:yes",
        lifecycle="active",
        is_tradeable=True,
    )
    restored = rt_models.InstrumentStatus.model_validate(s.model_dump())
    assert restored.lifecycle == s.lifecycle
    assert restored.is_tradeable == s.is_tradeable


# ---------------------------------------------------------------------------
# 5. OrderAck / OrderReject
# ---------------------------------------------------------------------------


class TestOrderAck:
    def test_construct_minimal(self) -> None:
        ack = rt_models.OrderAck(
            order_id="venue-001",
            instrument_id="kalshi:mrkt:yes",
        )
        assert ack.client_order_id is None
        assert ack.metadata == {}

    def test_with_metadata(self) -> None:
        ack = rt_models.OrderAck(
            order_id="v-001",
            instrument_id="kalshi:mrkt:yes",
            metadata={"latency_ms": 12},
        )
        assert ack.metadata["latency_ms"] == 12

    def test_empty_order_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            rt_models.OrderAck(order_id="", instrument_id="kalshi:mrkt:yes")


class TestOrderReject:
    def test_construct_with_error_code(self) -> None:
        rej = rt_models.OrderReject(
            instrument_id="kalshi:mrkt:yes",
            reason="market not active",
            error_code="MARKET_HALTED",
        )
        assert rej.error_code == "MARKET_HALTED"
        assert rej.order_id is None

    def test_empty_reason_rejected(self) -> None:
        with pytest.raises(ValidationError):
            rt_models.OrderReject(instrument_id="x:y:z", reason="")


# ---------------------------------------------------------------------------
# 6. OrderFill
# ---------------------------------------------------------------------------


class TestOrderFill:
    def test_construct(self) -> None:
        fill = rt_models.OrderFill(
            order_id="v-001",
            fill_id="fill-001",
            instrument_id="kalshi:mrkt:yes",
            price=Decimal("0.60"),
            size=Decimal("10"),
            side=rt_models.FillSide.BUY,
        )
        assert fill.fee == Decimal("0")
        assert fill.side == rt_models.FillSide.BUY

    def test_price_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            rt_models.OrderFill(
                order_id="v",
                fill_id="f",
                instrument_id="x:y:z",
                price=Decimal("1.01"),
                size=Decimal("1"),
                side=rt_models.FillSide.BUY,
            )

    def test_zero_size_rejected(self) -> None:
        with pytest.raises(ValidationError):
            rt_models.OrderFill(
                order_id="v",
                fill_id="f",
                instrument_id="x:y:z",
                price=Decimal("0.5"),
                size=Decimal("0"),
                side=rt_models.FillSide.SELL,
            )

    @pytest.mark.parametrize("side", list(rt_models.FillSide))
    def test_fill_sides(self, side: rt_models.FillSide) -> None:
        fill = rt_models.OrderFill(
            order_id="v",
            fill_id="f",
            instrument_id="x:y:z",
            price=Decimal("0.5"),
            size=Decimal("1"),
            side=side,
        )
        assert fill.side == side


# ---------------------------------------------------------------------------
# 7. OrderStatus
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", list(rt_models.OrderStatusCode))
def test_order_status_codes(code: rt_models.OrderStatusCode) -> None:
    status = rt_models.OrderStatus(
        order_id="v-001",
        instrument_id="kalshi:mrkt:yes",
        status=code,
    )
    assert status.status == code


def test_order_status_round_trip() -> None:
    s = rt_models.OrderStatus(
        order_id="v-001",
        instrument_id="kalshi:mrkt:yes",
        status=rt_models.OrderStatusCode.PARTIALLY_FILLED,
        filled_size=Decimal("3"),
        remaining_size=Decimal("7"),
        average_fill_price=Decimal("0.62"),
    )
    restored = rt_models.OrderStatus.model_validate(s.model_dump())
    assert restored.status == s.status
    assert restored.filled_size == s.filled_size
    assert restored.average_fill_price == s.average_fill_price


# ---------------------------------------------------------------------------
# 8. Protocol stub integration — full callback cycle
# ---------------------------------------------------------------------------


class TestExecutionAcknowledgerCallbacks:
    def test_ack_callback(self) -> None:
        handler = _StubExecutionAcknowledger()
        ack = rt_models.OrderAck(order_id="v-001", instrument_id="kalshi:mrkt:yes")
        handler.on_ack(ack)
        assert len(handler.acks) == 1
        assert handler.acks[0].order_id == "v-001"

    def test_reject_callback(self) -> None:
        handler = _StubExecutionAcknowledger()
        rej = rt_models.OrderReject(instrument_id="kalshi:mrkt:yes", reason="halted")
        handler.on_reject(rej)
        assert len(handler.rejects) == 1

    def test_fill_callback(self) -> None:
        handler = _StubExecutionAcknowledger()
        fill = rt_models.OrderFill(
            order_id="v",
            fill_id="f",
            instrument_id="x:y:z",
            price=Decimal("0.5"),
            size=Decimal("2"),
            side=rt_models.FillSide.BUY,
        )
        handler.on_fill(fill)
        assert len(handler.fills) == 1


class TestOrderRouterStub:
    def test_submit_returns_id(self) -> None:
        router = _StubOrderRouter()
        # pass any object; stub ignores contents
        result = router.submit_order(object())
        assert isinstance(result, str)

    def test_cancel_returns_bool(self) -> None:
        assert _StubOrderRouter().cancel_order("v-001") is True

    def test_query_returns_status(self) -> None:
        status = _StubOrderRouter().query_order("v-001")
        assert isinstance(status, rt_models.OrderStatus)


# ---------------------------------------------------------------------------
# 9. Module-level importability
# ---------------------------------------------------------------------------


def test_runtime_protocols_importable() -> None:
    import alpha_core.runtime_protocols as rtp

    assert hasattr(rtp, "interfaces")
    assert hasattr(rtp, "models")


def test_alpha_core_all_includes_runtime_protocols() -> None:
    import alpha_core

    assert "runtime_protocols" in alpha_core.__all__


# ---------------------------------------------------------------------------
# 10. Timestamp UTC discipline
# ---------------------------------------------------------------------------


def test_account_snapshot_ts_is_utc() -> None:
    snap = rt_models.AccountSnapshot(buying_power=Decimal("100"))
    assert snap.ts_snapshot.tzinfo is not None
    assert snap.ts_snapshot.tzinfo == UTC or str(snap.ts_snapshot.tzinfo) == "UTC"


def test_order_fill_ts_is_utc() -> None:
    fill = rt_models.OrderFill(
        order_id="v",
        fill_id="f",
        instrument_id="x:y:z",
        price=Decimal("0.5"),
        size=Decimal("1"),
        side=rt_models.FillSide.BUY,
    )
    assert fill.ts_filled.tzinfo is not None


def test_order_ack_ts_is_utc() -> None:
    ack = rt_models.OrderAck(order_id="v", instrument_id="x:y:z")
    assert ack.ts_acked.tzinfo is not None
    assert ack.ts_acked <= datetime.now(tz=UTC)
