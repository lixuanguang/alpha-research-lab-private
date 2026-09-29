"""Check independent exact spot-account posting and correction outcomes."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting.accounts import AccountLedger, AccountPosting, AccountState
from financial_units import Currency, DecimalGrid, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from serialization import DomainCodec


class TestAccountLedger:
    """Retain hand-calculated multi-currency balances and failure boundaries."""

    usd = Currency(code="QUSD", minor_unit=Decimal("0.01"))
    eur = Currency(code="QEUR", minor_unit=Decimal("0.01"))
    asset_a = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    asset_b = Dimension(
        instrument_id=InstrumentId.from_canonical_text("22222222-2222-4222-8222-222222222222"),
        kind=QuantityKind.BASE_UNIT,
    )
    start = datetime(2025, 1, 1, tzinfo=UTC)

    @classmethod
    def _cash(cls, value: str, currency: Currency | None = None) -> Money:
        """Create authored exact cash without changing its decimal representation."""
        return Money(value=Decimal(value), currency=currency or cls.usd)

    @classmethod
    def _fill(
        cls,
        identity: str,
        *,
        seconds: int,
        quantity: str,
        price: str,
        dimension: Dimension | None = None,
        currency: Currency | None = None,
        instance_id: str = "alpha",
        order_id: str = "order-a",
    ) -> AccountPosting:
        """Construct a signed, independently calculated fill cash movement."""
        selected_dimension = dimension or cls.asset_a
        selected_currency = currency or cls.usd
        return AccountPosting(
            identity=identity,
            account_id="physical",
            event_at=cls.start + timedelta(seconds=seconds),
            known_at=cls.start + timedelta(seconds=seconds),
            kind="fill",
            cash=Money(
                value=DecimalGrid.exact_decimal(
                    -Fraction(Decimal(price)) * Fraction(Decimal(quantity))
                ),
                currency=selected_currency,
            ),
            quantity=Quantity(value=Decimal(quantity), dimension=selected_dimension),
            price=Price(value=Decimal(price), currency=selected_currency, per=selected_dimension),
            instance_id=instance_id,
            order_id=order_id,
        )

    @classmethod
    def _transfer(
        cls, identity: str, *, seconds: int, value: str, currency: Currency | None = None
    ) -> AccountPosting:
        """Create an account-level capital movement with its own identity."""
        return AccountPosting(
            identity=identity,
            account_id="physical",
            event_at=cls.start + timedelta(seconds=seconds),
            known_at=cls.start + timedelta(seconds=seconds),
            kind="transfer",
            cash=cls._cash(value, currency),
        )

    @classmethod
    def _ledger(cls) -> AccountLedger:
        """Create an unfunded two-currency account."""
        return AccountLedger(AccountState(account_id="physical", currencies=(cls.usd, cls.eur)))

    def test_multi_instrument_cash_fees_rebates_transfers_and_instance_views(self) -> None:
        """Reconcile hand-calculated balances and separate physical from attributed cash."""
        ledger = self._ledger()
        ledger.post(self._transfer("capital-usd", seconds=0, value="1000"))
        ledger.post(self._transfer("capital-eur", seconds=1, value="50", currency=self.eur))
        ledger.post(self._fill("buy-a", seconds=2, quantity="2", price="100"))
        ledger.post(
            AccountPosting(
                identity="fee-a",
                account_id="physical",
                event_at=self.start + timedelta(seconds=3),
                known_at=self.start + timedelta(seconds=3),
                kind="fee",
                cash=self._cash("-0.50"),
                instance_id="alpha",
                order_id="order-a",
            )
        )
        ledger.post(
            AccountPosting(
                identity="rebate-a",
                account_id="physical",
                event_at=self.start + timedelta(seconds=4),
                known_at=self.start + timedelta(seconds=4),
                kind="rebate",
                cash=self._cash("0.10"),
                instance_id="alpha",
                order_id="order-a",
            )
        )
        ledger.post(
            self._fill(
                "sell-a",
                seconds=5,
                quantity="-0.5",
                price="110",
                order_id="order-sell",
            )
        )
        ledger.post(self._transfer("withdraw", seconds=6, value="-20"))
        ledger.post(
            self._fill(
                "buy-b",
                seconds=7,
                quantity="1",
                price="40",
                dimension=self.asset_b,
                currency=self.eur,
                instance_id="beta",
                order_id="order-b",
            )
        )
        aggregate = ledger.snapshot()
        assert tuple(amount.value for amount in aggregate.cash) == (
            Decimal("834.60"),
            Decimal("10"),
        )
        assert tuple(position.value for position in aggregate.positions) == (
            Decimal("1.5"),
            Decimal("1"),
        )
        assert tuple(amount.value for amount in aggregate.fees) == (Decimal("0.50"), Decimal(0))
        assert tuple(amount.value for amount in aggregate.rebates) == (Decimal("0.10"), Decimal(0))
        assert tuple(amount.value for amount in aggregate.transfers) == (
            Decimal("980"),
            Decimal("50"),
        )
        assert aggregate.fill_ids == ("buy-a", "sell-a", "buy-b")
        assert aggregate.posting_ids == (
            "capital-usd",
            "capital-eur",
            "buy-a",
            "fee-a",
            "rebate-a",
            "sell-a",
            "withdraw",
            "buy-b",
        )
        alpha = ledger.snapshot("alpha")
        beta = ledger.snapshot("beta")
        assert tuple(amount.value for amount in alpha.cash) == (Decimal("-145.40"), Decimal(0))
        assert alpha.fill_ids == ("buy-a", "sell-a")
        assert tuple(amount.value for amount in alpha.transfers) == (Decimal(0), Decimal(0))
        assert tuple(amount.value for amount in beta.cash) == (Decimal(0), Decimal("-40"))
        assert tuple(position.dimension for position in beta.positions) == (self.asset_b,)
        codec = DomainCodec()
        restored = AccountLedger(codec.decode_json(codec.encode_json(ledger.state), AccountState))
        assert restored.snapshot() == aggregate
        assert restored.snapshot("alpha") == alpha

    def test_base_denomination_changes_inventory_without_spurious_cash(self) -> None:
        """Hand-reconcile a 2-unit buy with a base fee and later base rebate."""
        base = Currency(code="BASE", minor_unit=Decimal("0.00000001"))
        ledger = AccountLedger(AccountState(account_id="physical", currencies=(self.usd, base)))
        ledger.post(self._transfer("capital", seconds=0, value="1000"))
        ledger.post(self._fill("buy", seconds=1, quantity="2", price="100"))
        ledger.post(
            AccountPosting(
                identity="base-fee",
                account_id="physical",
                event_at=self.start + timedelta(seconds=2),
                known_at=self.start + timedelta(seconds=2),
                kind="fee",
                cash=self._cash("-0.01", base),
                asset_change=Quantity(value=Decimal("-0.01"), dimension=self.asset_a),
                instance_id="alpha",
                order_id="order-a",
            )
        )
        ledger.post(
            AccountPosting(
                identity="base-rebate",
                account_id="physical",
                event_at=self.start + timedelta(seconds=3),
                known_at=self.start + timedelta(seconds=3),
                kind="rebate",
                cash=self._cash("0.002", base),
                asset_change=Quantity(value=Decimal("0.002"), dimension=self.asset_a),
                instance_id="alpha",
                order_id="order-a",
            )
        )
        snapshot = ledger.snapshot()
        assert tuple(amount.value for amount in snapshot.cash) == (Decimal("800"), Decimal(0))
        assert snapshot.positions[0].value == Decimal("1.992")
        assert tuple(amount.value for amount in snapshot.fees) == (Decimal(0), Decimal("0.01"))
        assert tuple(amount.value for amount in snapshot.rebates) == (
            Decimal(0),
            Decimal("0.002"),
        )
        restored = AccountLedger(
            DomainCodec().decode_json(DomainCodec().encode_json(ledger.state), AccountState)
        )
        assert restored.snapshot() == snapshot
        before = ledger.state
        with pytest.raises(ValueError, match="spot inventory cannot be short"):
            ledger.post(
                AccountPosting(
                    identity="excess-base-fee",
                    account_id="physical",
                    event_at=self.start + timedelta(seconds=4),
                    known_at=self.start + timedelta(seconds=4),
                    kind="fee",
                    cash=self._cash("-3", base),
                    asset_change=Quantity(value=Decimal("-3"), dimension=self.asset_a),
                    instance_id="alpha",
                    order_id="order-a",
                )
            )
        assert ledger.state == before

    def test_retry_revisions_and_favorable_price_preserve_original_fill_identity(self) -> None:
        """Replace effects atomically while retaining all source and revision IDs."""
        ledger = self._ledger()
        ledger.post(self._transfer("capital", seconds=0, value="300"))
        buy = self._fill("buy", seconds=1, quantity="2", price="100")
        ledger.post(buy)
        ledger.post(self._fill("sell", seconds=2, quantity="-1", price="110"))
        before = ledger.state
        assert ledger.post(buy) == ledger.snapshot()
        assert ledger.state == before
        with pytest.raises(ValueError, match="conflicting posting retry"):
            ledger.post(
                replace(
                    buy, price=Price(value=Decimal("100.0"), currency=self.usd, per=self.asset_a)
                )
            )
        assert ledger.state == before
        correction = AccountPosting(
            identity="correct-buy",
            account_id="physical",
            event_at=self.start + timedelta(seconds=3),
            known_at=self.start + timedelta(seconds=3),
            kind="correction",
            corrects="buy",
            replacement_kind="fill",
            cash=self._cash("-198"),
            quantity=Quantity(value=Decimal("2"), dimension=self.asset_a),
            price=Price(value=Decimal("99"), currency=self.usd, per=self.asset_a),
            instance_id="alpha",
            order_id="order-a",
        )
        snapshot = ledger.post(correction)
        assert snapshot.cash[0].value == Decimal("212")
        assert snapshot.positions[0].value == 1
        assert snapshot.fill_ids == ("buy", "sell")
        assert snapshot.posting_ids == ("capital", "buy", "sell", "correct-buy")
        active = ledger.effective_postings()
        assert active[1].identity == "buy"
        assert active[1].revision_id == "correct-buy"
        assert active[1].price is not None and active[1].price.value == 99
        with pytest.raises(ValueError, match="current revision"):
            ledger.post(
                replace(
                    correction,
                    identity="stale",
                    corrects="buy",
                    known_at=self.start + timedelta(seconds=4),
                )
            )
        assert ledger.state.postings[-1] == correction
        second = replace(
            correction,
            identity="correct-again",
            corrects="correct-buy",
            known_at=self.start + timedelta(seconds=4),
            event_at=self.start + timedelta(seconds=4),
            cash=self._cash("-196"),
            price=Price(value=Decimal("98"), currency=self.usd, per=self.asset_a),
        )
        assert ledger.post(second).cash[0].value == Decimal("214")
        assert ledger.effective_postings()[1].identity == "buy"

    def test_rejected_short_cash_clock_and_correction_leave_state_unchanged(self) -> None:
        """Fail closed before committing unfunded trades or revisions that expose shorts."""
        ledger = self._ledger()
        with pytest.raises(ValueError, match="insufficient account cash"):
            ledger.post(self._fill("unfunded", seconds=1, quantity="1", price="1"))
        assert ledger.state.postings == ()
        ledger.post(self._transfer("capital", seconds=1, value="100"))
        ledger.post(self._fill("buy", seconds=2, quantity="1", price="50"))
        ledger.post(self._fill("sell", seconds=3, quantity="-1", price="60"))
        before = ledger.state
        with pytest.raises(ValueError, match="spot inventory cannot be short"):
            ledger.post(self._fill("oversell", seconds=4, quantity="-1", price="70"))
        with pytest.raises(ValueError, match="out of order"):
            ledger.post(self._transfer("late", seconds=0, value="1"))
        with pytest.raises(ValueError, match="ownership or units"):
            ledger.post(
                AccountPosting(
                    identity="wrong-owner",
                    account_id="physical",
                    event_at=self.start + timedelta(seconds=4),
                    known_at=self.start + timedelta(seconds=4),
                    kind="correction",
                    corrects="buy",
                    replacement_kind="fill",
                    cash=self._cash("-50"),
                    quantity=Quantity(value=Decimal("1"), dimension=self.asset_a),
                    price=Price(value=Decimal("50"), currency=self.usd, per=self.asset_a),
                    instance_id="beta",
                    order_id="order-a",
                )
            )
        with pytest.raises(ValueError, match="spot inventory cannot be short"):
            ledger.post(
                AccountPosting(
                    identity="void-buy",
                    account_id="physical",
                    event_at=self.start + timedelta(seconds=4),
                    known_at=self.start + timedelta(seconds=4),
                    kind="correction",
                    corrects="buy",
                    cash=self._cash("0"),
                    instance_id="alpha",
                    order_id="order-a",
                )
            )
        assert ledger.state == before
        with pytest.raises(ValueError, match="exact signed cash"):
            replace(
                self._fill("bad-cash", seconds=4, quantity="1", price="1"), cash=self._cash("-2")
            )

    def test_fee_rebate_transfer_corrections_and_delayed_source_events(self) -> None:
        """Reconcile revised cost and cashflow totals without erasing an earlier fact."""
        ledger = self._ledger()
        ledger.post(self._transfer("capital", seconds=0, value="100"))
        ledger.post(self._fill("buy", seconds=1, quantity="1", price="20"))
        fee = AccountPosting(
            identity="fee",
            account_id="physical",
            event_at=self.start + timedelta(seconds=2),
            known_at=self.start + timedelta(seconds=4),
            kind="fee",
            cash=self._cash("-1"),
            instance_id="alpha",
            order_id="order-a",
        )
        ledger.post(fee)
        rebate = AccountPosting(
            identity="rebate",
            account_id="physical",
            event_at=self.start + timedelta(seconds=3),
            known_at=self.start + timedelta(seconds=5),
            kind="rebate",
            cash=self._cash("0.50"),
            instance_id="alpha",
            order_id="order-a",
        )
        ledger.post(rebate)
        withdrawal = replace(
            self._transfer("withdraw", seconds=6, value="-10"),
            event_at=self.start + timedelta(seconds=3),
        )
        ledger.post(withdrawal)
        assert ledger.snapshot().cash[0].value == Decimal("69.50")
        ledger.post(
            AccountPosting(
                identity="fee-revision",
                account_id="physical",
                event_at=self.start + timedelta(seconds=7),
                known_at=self.start + timedelta(seconds=7),
                kind="correction",
                corrects="fee",
                replacement_kind="fee",
                cash=self._cash("-0.75"),
                instance_id="alpha",
                order_id="order-a",
            )
        )
        ledger.post(
            AccountPosting(
                identity="rebate-void",
                account_id="physical",
                event_at=self.start + timedelta(seconds=8),
                known_at=self.start + timedelta(seconds=8),
                kind="correction",
                corrects="rebate",
                cash=self._cash("0"),
                instance_id="alpha",
                order_id="order-a",
            )
        )
        ledger.post(
            AccountPosting(
                identity="withdraw-revision",
                account_id="physical",
                event_at=self.start + timedelta(seconds=9),
                known_at=self.start + timedelta(seconds=9),
                kind="correction",
                corrects="withdraw",
                replacement_kind="transfer",
                cash=self._cash("-8"),
            )
        )
        snapshot = ledger.snapshot()
        assert snapshot.cash[0].value == Decimal("71.25")
        assert snapshot.fees[0].value == Decimal("0.75")
        assert snapshot.rebates[0].value == 0
        assert snapshot.transfers[0].value == 92
        assert snapshot.fill_ids == ("buy",)
        assert snapshot.posting_ids[-3:] == (
            "fee-revision",
            "rebate-void",
            "withdraw-revision",
        )
        assert tuple(effect.identity for effect in ledger.effective_postings()) == (
            "capital",
            "buy",
            "fee",
            "withdraw",
        )
        assert ledger.effective_postings()[2].revision_id == "fee-revision"
        with pytest.raises(ValueError, match="spot inventory cannot be short"):
            ledger.post(
                self._fill(
                    "other-instance-sell",
                    seconds=10,
                    quantity="-1",
                    price="21",
                    instance_id="beta",
                )
            )

    def test_incremental_postings_match_a_full_rebuild_after_every_step(self) -> None:
        """Posting one fact at a time equals replaying the stored history from scratch."""
        base = Currency(code="BASE", minor_unit=Decimal("0.00000001"))
        ledger = AccountLedger(AccountState(account_id="physical", currencies=(self.usd, base)))
        codec = DomainCodec()
        fee = AccountPosting(
            identity="fee",
            account_id="physical",
            event_at=self.start + timedelta(seconds=4),
            known_at=self.start + timedelta(seconds=4),
            kind="fee",
            cash=self._cash("-1"),
            instance_id="alpha",
            order_id="order-a",
        )
        steps: tuple[tuple[AccountPosting, str | None], ...] = (
            (self._transfer("capital", seconds=0, value="1000"), None),
            (self._fill("buy-a", seconds=1, quantity="2", price="100"), None),
            (
                self._fill(
                    "buy-b", seconds=2, quantity="3", price="50", instance_id="beta", order_id="b"
                ),
                None,
            ),
            (fee, None),
            (fee, None),
            (replace(fee, cash=self._cash("-2")), "conflicting posting retry"),
            (
                AccountPosting(
                    identity="base-fee",
                    account_id="physical",
                    event_at=self.start + timedelta(seconds=5),
                    known_at=self.start + timedelta(seconds=5),
                    kind="fee",
                    cash=self._cash("-0.01", base),
                    asset_change=Quantity(value=Decimal("-0.01"), dimension=self.asset_a),
                    instance_id="alpha",
                    order_id="order-a",
                ),
                None,
            ),
            (
                AccountPosting(
                    identity="rebate",
                    account_id="physical",
                    event_at=self.start + timedelta(seconds=6),
                    known_at=self.start + timedelta(seconds=6),
                    kind="rebate",
                    cash=self._cash("0.25"),
                    instance_id="beta",
                    order_id="b",
                ),
                None,
            ),
            (
                AccountPosting(
                    identity="fee-revision",
                    account_id="physical",
                    event_at=self.start + timedelta(seconds=7),
                    known_at=self.start + timedelta(seconds=7),
                    kind="correction",
                    corrects="fee",
                    replacement_kind="fee",
                    cash=self._cash("-0.5"),
                    instance_id="alpha",
                    order_id="order-a",
                ),
                None,
            ),
            (
                AccountPosting(
                    identity="stale-revision",
                    account_id="physical",
                    event_at=self.start + timedelta(seconds=8),
                    known_at=self.start + timedelta(seconds=8),
                    kind="correction",
                    corrects="fee",
                    cash=self._cash("0"),
                    instance_id="alpha",
                    order_id="order-a",
                ),
                "current revision",
            ),
            (
                AccountPosting(
                    identity="rebate-void",
                    account_id="physical",
                    event_at=self.start + timedelta(seconds=8),
                    known_at=self.start + timedelta(seconds=8),
                    kind="correction",
                    corrects="rebate",
                    cash=self._cash("0"),
                    instance_id="beta",
                    order_id="b",
                ),
                None,
            ),
            (self._fill("oversell", seconds=9, quantity="-3", price="100"), "short"),
            (self._transfer("overdraft", seconds=9, value="-10000"), "insufficient"),
            (self._fill("sell-a", seconds=9, quantity="-1", price="120"), None),
            (self._transfer("late", seconds=1, value="5"), "out of order"),
            (self._transfer("withdraw", seconds=10, value="-100"), None),
        )
        for posting, refusal in steps:
            before = (ledger.state, ledger.effective_postings(), ledger.snapshot())
            if refusal is not None:
                with pytest.raises(ValueError, match=refusal):
                    ledger.post(posting)
                assert (ledger.state, ledger.effective_postings(), ledger.snapshot()) == before
                continue
            ledger.post(posting)
            rebuilt = AccountLedger(
                codec.decode_json(codec.encode_json(ledger.state), AccountState)
            )
            assert rebuilt.state == ledger.state
            assert rebuilt.effective_postings() == ledger.effective_postings()
            for instance_id in (None, "alpha", "beta"):
                assert rebuilt.snapshot(instance_id) == ledger.snapshot(instance_id)

    def test_exact_balances_survive_low_decimal_precision(self) -> None:
        """Avoid ambient Decimal rounding in cumulative multi-posting balances."""
        with localcontext() as context:
            context.prec = 2
            ledger = self._ledger()
            ledger.post(self._transfer("capital", seconds=0, value="1000.00"))
            ledger.post(self._fill("buy", seconds=1, quantity="1", price="123.45"))
            assert ledger.snapshot().cash[0].value == Decimal("876.55")
