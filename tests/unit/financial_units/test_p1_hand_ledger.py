"""Retain the independent P1 hand ledger as foundation monetary arithmetic evidence."""

from __future__ import annotations

# standard library imports
from decimal import Decimal
from uuid import UUID

# project library imports
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId


class TestHandLedger:
    """Reconcile a hand-calculated ledger exactly."""

    def test_hand_ledger_reconciles_exact_cash_open_mark_and_round_trip(self) -> None:
        """Match independent goldens without claiming an implemented ledger or fee engine."""
        currency = Currency(code="QXX", minor_unit=Decimal("0.01"))
        dimension = Dimension(
            instrument_id=InstrumentId(UUID("33333333-3333-4333-8333-333333333333")),
            kind=QuantityKind.BASE_UNIT,
        )
        quantity = Quantity(value=Decimal("2"), dimension=dimension)
        initial = Money(value=Decimal("1000.00"), currency=currency)
        buy_notional = Price(value=Decimal("100.50"), currency=currency, per=dimension).amount(
            quantity
        )
        sell_notional = Price(value=Decimal("109.50"), currency=currency, per=dimension).amount(
            quantity
        )
        # Independently hand-rounded half-up fees: 201 * .001 and 219 * .001.
        buy_fee = Money(value=Decimal("0.20"), currency=currency)
        sell_fee = Money(value=Decimal("0.22"), currency=currency)
        cash_after_buy = initial - buy_notional - buy_fee
        mark = Price(value=Decimal("105.00"), currency=currency, per=dimension).amount(quantity)
        final_cash = cash_after_buy + sell_notional - sell_fee

        assert cash_after_buy.value == Decimal("798.80")
        assert (cash_after_buy + mark).value == Decimal("1008.80")
        assert (mark - buy_notional - buy_fee).value == Decimal("8.80")
        assert final_cash.value == Decimal("1017.58")
        assert (final_cash - initial).value == Decimal("17.58")
        assert (buy_fee + sell_fee).value == Decimal("0.42")
        reference_gross = Money(value=Decimal("20.00"), currency=currency)
        slippage = Money(value=Decimal("2.00"), currency=currency)
        assert final_cash - initial == reference_gross - slippage - buy_fee - sell_fee
        zero_holding = Quantity(value=Decimal("0"), dimension=dimension)
        zero_mark = Price(value=Decimal("105.00"), currency=currency, per=dimension).amount(
            zero_holding
        )
        assert initial + zero_mark == initial
