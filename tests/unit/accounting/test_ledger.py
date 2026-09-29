"""Reconcile independent spot ledgers and nonterminating basis without float tolerance."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting import Ledger, LedgerState
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from serialization import DomainCodec
from simulation import SpotCosts


class TestLedger:
    """Use the retained independent hand oracle and a distinct rational-allocation example."""

    currency = Currency(code="TEST", minor_unit=Decimal("0.01"))
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    start = datetime(2024, 6, 1, tzinfo=UTC)

    @classmethod
    def _price(cls, value: str) -> Price:
        """Construct exact oracle prices in explicit units."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Construct signed oracle quantities."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _ledger(cls) -> Ledger:
        """Start with the unchanged 1000-unit hand-ledger capital."""
        return Ledger(
            LedgerState(
                initial_cash=Money(value=Decimal("1000"), currency=cls.currency),
                dimension=cls.dimension,
            )
        )

    def test_hand_ledger_gross_net_duplicate_and_rejection(self) -> None:
        """Check every independent cash/basis/P&L value, including no-trade and failed postings."""
        ledger = self._ledger()
        costs = SpotCosts(
            adverse=self._price("0.50"), fee_rate=Decimal("0.001"), rounding="half_up"
        )
        assert ledger.mark(None).nav.value == Decimal("1000")
        assert ledger.balance.turnover.value == 0
        buy = costs.fill(
            "buy",
            decision_at=self.start,
            filled_at=self.start + timedelta(seconds=1),
            quantity=self._quantity("2"),
            reference=self._price("100"),
        )
        ledger.apply(buy)
        assert ledger.balance.cash.value == Decimal("798.80")
        assert ledger.balance.basis.value == 201
        mark = ledger.mark(self._price("105"))
        assert mark.unrealized.value == 9
        assert mark.net.value == Decimal("8.80")
        assert mark.nav.value == Decimal("1008.80")
        prior = ledger.state
        with pytest.raises(ValueError, match="duplicate"):
            ledger.apply(buy)
        with pytest.raises(ValueError, match="insufficient"):
            ledger.apply(replace(buy, identity="oversized", quantity=self._quantity("100")))
        with pytest.raises(ValueError, match="overselling"):
            ledger.apply(
                costs.fill(
                    "oversell",
                    decision_at=self.start,
                    filled_at=self.start + timedelta(seconds=2),
                    quantity=self._quantity("-3"),
                    reference=self._price("110"),
                )
            )
        assert ledger.state == prior
        ledger.apply(
            costs.fill(
                "sell",
                decision_at=self.start,
                filled_at=self.start + timedelta(seconds=2),
                quantity=self._quantity("-2"),
                reference=self._price("110"),
            )
        )
        assert ledger.balance.cash.value == Decimal("1017.58")
        assert ledger.balance.realized.value == 18
        assert ledger.balance.fees.value == Decimal("0.42")
        assert ledger.balance.slippage.value == Decimal("2")
        assert ledger.mark(None).gross.value == 20
        assert ledger.mark(None).net.value == Decimal("17.58")

    def test_reused_state_matches_validated_rebuild_and_copies_post_independently(
        self,
    ) -> None:
        """State built from applied fills equals a validated rebuild; copies stay separate."""
        costs = SpotCosts(
            adverse=self._price("0.50"), fee_rate=Decimal("0.001"), rounding="half_up"
        )
        fills = [
            costs.fill(
                f"trade-{index}",
                decision_at=self.start,
                filled_at=self.start + timedelta(seconds=index + 1),
                quantity=self._quantity("1" if index % 2 == 0 else "-1"),
                reference=self._price("100"),
            )
            for index in range(6)
        ]
        ledger = self._ledger()
        for fill in fills[:4]:
            ledger.apply(fill)
        state = ledger.state
        validated = LedgerState(
            initial_cash=Money(value=Decimal("1000"), currency=self.currency),
            dimension=self.dimension,
            fills=tuple(fills[:4]),
        )
        codec = DomainCodec()
        assert state == validated
        assert codec.encode_json(state) == codec.encode_json(validated)
        rebuilt = Ledger(codec.decode_json(codec.encode_json(state), LedgerState))
        assert (rebuilt.state, rebuilt.balance) == (state, ledger.balance)
        duplicate = ledger.copy()
        duplicate.apply(fills[4])
        assert ledger.state == state and len(duplicate.state.fills) == 5
        with pytest.raises(ValueError, match="duplicate"):
            duplicate.apply(fills[0])
        ledger.apply(fills[4])
        assert (ledger.state, ledger.balance) == (duplicate.state, duplicate.balance)

    def test_fee_tie_and_rational_basis_under_changed_context(self) -> None:
        """Retain 302/3 released basis and distinguish the oracle's half-up from half-even."""
        for precision in (2, 7, 28):
            with localcontext() as context:
                context.prec = precision
                costs = SpotCosts(
                    adverse=self._price("0"), fee_rate=Decimal("0.001"), rounding="half_up"
                )
                fill = costs.fill(
                    "tie",
                    decision_at=self.start,
                    filled_at=self.start + timedelta(seconds=1),
                    quantity=self._quantity("1"),
                    reference=self._price("205"),
                )
                assert fill.fee.value == Decimal("0.21")
                assert replace(costs, rounding="half_even").fill(
                    "tie",
                    decision_at=self.start,
                    filled_at=self.start + timedelta(seconds=1),
                    quantity=self._quantity("1"),
                    reference=self._price("205"),
                ).fee.value == Decimal("0.20")
                ledger = self._ledger()
                for i, (quantity, price) in enumerate((("1", "100"), ("2", "101"), ("-1", "103"))):
                    ledger.apply(
                        costs.fill(
                            str(i),
                            decision_at=self.start,
                            filled_at=self.start + timedelta(seconds=i + 1),
                            quantity=self._quantity(quantity),
                            reference=self._price(price),
                        )
                    )
                assert ledger.balance.basis.value == Fraction(604, 3)
                assert ledger.balance.realized.value == Fraction(7, 3)
                codec = DomainCodec()
                restored = Ledger(codec.decode_json(codec.encode_json(ledger.state), LedgerState))
                assert restored.balance == ledger.balance
                assert restored.mark(self._price("104")) == ledger.mark(self._price("104"))
