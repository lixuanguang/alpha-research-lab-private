"""Check exact paper valuation against independent spot cash-flow examples."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# third party library imports
import pytest

# project library imports
from accounting import (
    AccountLedger,
    AccountPosting,
    AccountState,
    AttributedPaperFill,
    Fill,
    PaperAccountReporter,
    PaperCostEvidence,
    PaperGasPolicy,
    PaperPositionMark,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from serialization import DomainCodec


class TestPaperAccountReporter:
    """Prove posted fees, adverse fills and marked values reconcile once."""

    usd = Currency(code="QUSD", minor_unit=Decimal("0.01"))
    eur = Currency(code="QEUR", minor_unit=Decimal("0.01"))
    base = Currency(code="BASE", minor_unit=Decimal("0.00000001"))
    asset_a = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    asset_b = Dimension(
        instrument_id=InstrumentId.from_canonical_text("22222222-2222-4222-8222-222222222222"),
        kind=QuantityKind.BASE_UNIT,
    )
    start = datetime(2025, 1, 1, tzinfo=UTC)
    gas = PaperGasPolicy(
        scenario_id="off-chain-spot-scenario",
        applicable=False,
        reason="spot matching uses no on-chain transaction or transfer",
    )

    @classmethod
    def _money(cls, value: str, currency: Currency | None = None) -> Money:
        """Create an authored native-currency amount."""
        return Money(value=Decimal(value), currency=currency or cls.usd)

    @classmethod
    def _price(
        cls, value: str, dimension: Dimension | None = None, currency: Currency | None = None
    ) -> Price:
        """Create an authored currency-per-unit price."""
        return Price(
            value=Decimal(value),
            currency=currency or cls.usd,
            per=dimension or cls.asset_a,
        )

    @classmethod
    def _fill(
        cls,
        identity: str,
        *,
        at_seconds: int,
        quantity: str,
        reference: str,
        effective: str,
        fee: str,
        dimension: Dimension | None = None,
        currency: Currency | None = None,
    ) -> Fill:
        """Create a retained signed fill with independent reference economics."""
        selected_dimension = dimension or cls.asset_a
        selected_currency = currency or cls.usd
        return Fill(
            identity=identity,
            decision_at=cls.start,
            filled_at=cls.start + timedelta(seconds=at_seconds),
            quantity=Quantity(value=Decimal(quantity), dimension=selected_dimension),
            reference=cls._price(reference, selected_dimension, selected_currency),
            effective=cls._price(effective, selected_dimension, selected_currency),
            fee=cls._money(fee, selected_currency),
        )

    @classmethod
    def _fund(
        cls, ledger: AccountLedger, identity: str, value: str, currency: Currency | None = None
    ) -> None:
        """Post explicit external funding at the initial knowledge time."""
        ledger.post(
            AccountPosting(
                identity=identity,
                account_id="physical",
                event_at=cls.start,
                known_at=cls.start,
                kind="transfer",
                cash=cls._money(value, currency),
            )
        )

    @classmethod
    def _post_fill(
        cls,
        ledger: AccountLedger,
        fill: Fill,
        *,
        instance_id: str,
        order_id: str,
    ) -> tuple[AttributedPaperFill, PaperCostEvidence]:
        """Post the exact execution cash and separately identified quote fee."""
        ledger.post(
            AccountPosting(
                identity=fill.identity,
                account_id="physical",
                event_at=fill.filled_at,
                known_at=fill.filled_at,
                kind="fill",
                cash=Money(
                    value=-fill.effective.amount(fill.quantity).value,
                    currency=fill.effective.currency,
                ),
                instance_id=instance_id,
                order_id=order_id,
                quantity=fill.quantity,
                price=fill.effective,
            )
        )
        posting_id: str | None = None
        amount = cls._money("0", fill.fee.currency)
        if fill.fee.value:
            posting_id = f"fee:{fill.identity}"
            amount = fill.fee
            ledger.post(
                AccountPosting(
                    identity=posting_id,
                    account_id="physical",
                    event_at=fill.filled_at,
                    known_at=fill.filled_at,
                    kind="fee",
                    cash=Money(value=-amount.value, currency=amount.currency),
                    instance_id=instance_id,
                    order_id=order_id,
                )
            )
        return (
            AttributedPaperFill(instance_id=instance_id, order_id=order_id, fill=fill),
            PaperCostEvidence(source_fill_id=fill.identity, posting_id=posting_id, amount=amount),
        )

    @classmethod
    def _mark(
        cls,
        identity: str,
        *,
        at_seconds: int,
        value: str,
        dimension: Dimension | None = None,
        currency: Currency | None = None,
    ) -> PaperPositionMark:
        """Create one current mark available at the stated time."""
        return PaperPositionMark(
            identity=identity,
            available_at=cls.start + timedelta(seconds=at_seconds),
            price=cls._price(value, dimension, currency),
        )

    def test_no_trade_funding_has_zero_pnl_in_each_currency(self) -> None:
        """External transfers do not masquerade as paper trading gains."""
        ledger = AccountLedger(AccountState(account_id="physical", currencies=(self.usd, self.eur)))
        self._fund(ledger, "usd-capital", "1000")
        self._fund(ledger, "eur-capital", "50", self.eur)
        report = PaperAccountReporter().build(
            ledger.state,
            cutoff=self.start + timedelta(seconds=10),
            max_mark_age=timedelta(seconds=2),
            marks=(),
            fills=(),
            costs=(),
            gas_policy=self.gas,
        )
        assert report.schema_version == "paper-account-report"
        assert report.instances == ()
        assert tuple(item.nav.value for item in report.account.currencies) == (
            Decimal("1000"),
            Decimal("50"),
        )
        assert tuple(item.net_pnl.value for item in report.account.currencies) == (
            Decimal(0),
            Decimal(0),
        )
        assert tuple(item.slippage.value for item in report.account.currencies) == (
            Decimal(0),
            Decimal(0),
        )
        codec = DomainCodec()
        assert codec.decode_json(codec.encode_json(report), type(report)) == report

    def test_losing_round_trip_reconciles_fees_and_slippage_once(self) -> None:
        """A buy, partial sale and lower mark lose 23 after 3 fees and 5 slippage."""
        ledger = AccountLedger(AccountState(account_id="physical", currencies=(self.usd,)))
        self._fund(ledger, "capital", "1000")
        buy = self._fill(
            "buy", at_seconds=1, quantity="2", reference="100", effective="102", fee="2"
        )
        sell = self._fill(
            "sell", at_seconds=2, quantity="-1", reference="95", effective="94", fee="1"
        )
        buy_link, buy_fee = self._post_fill(ledger, buy, instance_id="alpha", order_id="buy-order")
        sell_link, sell_fee = self._post_fill(
            ledger, sell, instance_id="alpha", order_id="sell-order"
        )
        report = PaperAccountReporter().build(
            ledger.state,
            cutoff=self.start + timedelta(seconds=4),
            max_mark_age=timedelta(seconds=2),
            marks=(self._mark("close", at_seconds=3, value="90"),),
            fills=(buy_link, sell_link),
            costs=(buy_fee, sell_fee),
            gas_policy=self.gas,
        )
        result = report.account.currencies[0]
        assert report.account.snapshot.cash[0].value == Decimal("887")
        assert report.account.snapshot.fees[0].value == Decimal("3")
        assert report.account.snapshot.transfers[0].value == Decimal("1000")
        assert report.account.positions[0].position.value == Decimal("1")
        assert result.position_value.value == Decimal("90")
        assert result.nav.value == Decimal("977")
        assert result.net_pnl.value == Decimal("-23")
        assert result.slippage.value == Decimal("5")
        assert report.instances[0].currencies[0].net_pnl.value == Decimal("-23")
        assert report.instances[0].snapshot.cash[0].value == Decimal("-113")

    def test_more_adverse_execution_reduces_net_without_double_charge(self) -> None:
        """The added three per unit reduces NAV by six and increases slippage by six."""
        results = []
        for effective in ("102", "105"):
            ledger = AccountLedger(AccountState(account_id="physical", currencies=(self.usd,)))
            self._fund(ledger, "capital", "1000")
            fill = self._fill(
                "buy", at_seconds=1, quantity="2", reference="100", effective=effective, fee="2"
            )
            link, cost = self._post_fill(ledger, fill, instance_id="alpha", order_id="buy-order")
            report = PaperAccountReporter().build(
                ledger.state,
                cutoff=self.start + timedelta(seconds=3),
                max_mark_age=timedelta(seconds=1),
                marks=(self._mark("close", at_seconds=2, value="90"),),
                fills=(link,),
                costs=(cost,),
                gas_policy=self.gas,
            )
            results.append(report.account.currencies[0])
        assert tuple(item.net_pnl.value for item in results) == (
            Decimal("-26"),
            Decimal("-32"),
        )
        assert tuple(item.slippage.value for item in results) == (Decimal("4"), Decimal("10"))

    def test_strategy_currency_and_native_asset_fee_remain_distinct(self) -> None:
        """Value two isolated holdings while a base fee reduces inventory, not quote cash."""
        ledger = AccountLedger(
            AccountState(account_id="physical", currencies=(self.usd, self.eur, self.base))
        )
        self._fund(ledger, "usd-capital", "1000")
        self._fund(ledger, "eur-capital", "100", self.eur)
        alpha_fill = self._fill(
            "alpha-buy", at_seconds=1, quantity="2", reference="100", effective="100", fee="1"
        )
        beta_fill = self._fill(
            "beta-buy",
            at_seconds=2,
            quantity="1",
            reference="40",
            effective="40",
            fee="0",
            dimension=self.asset_b,
            currency=self.eur,
        )
        alpha, alpha_cost = self._post_fill(
            ledger, alpha_fill, instance_id="alpha", order_id="alpha-order"
        )
        beta, _ = self._post_fill(ledger, beta_fill, instance_id="beta", order_id="beta-order")
        ledger.post(
            AccountPosting(
                identity="base-fee",
                account_id="physical",
                event_at=self.start + timedelta(seconds=3),
                known_at=self.start + timedelta(seconds=3),
                kind="fee",
                cash=self._money("-0.1", self.base),
                asset_change=Quantity(value=Decimal("-0.1"), dimension=self.asset_b),
                instance_id="beta",
                order_id="beta-order",
            )
        )
        report = PaperAccountReporter().build(
            ledger.state,
            cutoff=self.start + timedelta(seconds=5),
            max_mark_age=timedelta(seconds=1),
            marks=(
                self._mark("a-close", at_seconds=4, value="110"),
                self._mark(
                    "b-close",
                    at_seconds=4,
                    value="35",
                    dimension=self.asset_b,
                    currency=self.eur,
                ),
            ),
            fills=(alpha, beta),
            costs=(
                alpha_cost,
                PaperCostEvidence(
                    source_fill_id="beta-buy",
                    posting_id="base-fee",
                    amount=self._money("0.1", self.base),
                ),
            ),
            gas_policy=self.gas,
        )
        assert tuple(item.net_pnl.value for item in report.account.currencies) == (
            Decimal("19"),
            Decimal("-8.5"),
            Decimal(0),
        )
        assert tuple(item.snapshot.instance_id for item in report.instances) == ("alpha", "beta")
        assert report.instances[0].currencies[0].net_pnl.value == Decimal("19")
        assert report.instances[1].currencies[1].net_pnl.value == Decimal("-8.5")
        assert report.account.snapshot.cash[2].value == Decimal(0)
        assert report.account.snapshot.fees[2].value == Decimal("0.1")
        assert report.account.positions[1].position.value == Decimal("0.9")

    def test_fee_correction_uses_current_posting_and_retains_original_fill(self) -> None:
        """A corrected fee changes net P&L without changing reference slippage."""
        ledger = AccountLedger(AccountState(account_id="physical", currencies=(self.usd,)))
        self._fund(ledger, "capital", "1000")
        fill = self._fill(
            "buy", at_seconds=1, quantity="2", reference="100", effective="102", fee="2"
        )
        link, _ = self._post_fill(ledger, fill, instance_id="alpha", order_id="buy-order")
        ledger.post(
            AccountPosting(
                identity="correct-fee",
                account_id="physical",
                event_at=self.start + timedelta(seconds=1),
                known_at=self.start + timedelta(seconds=2),
                kind="correction",
                corrects="fee:buy",
                replacement_kind="fee",
                cash=self._money("-1"),
                instance_id="alpha",
                order_id="buy-order",
            )
        )
        report = PaperAccountReporter().build(
            ledger.state,
            cutoff=self.start + timedelta(seconds=4),
            max_mark_age=timedelta(seconds=1),
            marks=(self._mark("close", at_seconds=3, value="90"),),
            fills=(link,),
            costs=(
                PaperCostEvidence(
                    source_fill_id="buy", posting_id="fee:buy", amount=self._money("1")
                ),
            ),
            gas_policy=self.gas,
        )
        assert report.account.snapshot.fees[0].value == Decimal("1")
        assert report.account.currencies[0].net_pnl.value == Decimal("-25")
        assert report.account.currencies[0].slippage.value == Decimal("4")
        ledger.post(
            AccountPosting(
                identity="void-fee",
                account_id="physical",
                event_at=self.start + timedelta(seconds=1),
                known_at=self.start + timedelta(seconds=5),
                kind="correction",
                corrects="correct-fee",
                replacement_kind=None,
                cash=self._money("0"),
                instance_id="alpha",
                order_id="buy-order",
            )
        )
        voided = PaperAccountReporter().build(
            ledger.state,
            cutoff=self.start + timedelta(seconds=7),
            max_mark_age=timedelta(seconds=1),
            marks=(self._mark("later-close", at_seconds=6, value="90"),),
            fills=(link,),
            costs=(
                PaperCostEvidence(source_fill_id="buy", posting_id=None, amount=self._money("0")),
            ),
            gas_policy=self.gas,
        )
        assert voided.account.snapshot.fees[0].value == Decimal(0)
        assert voided.account.currencies[0].net_pnl.value == Decimal("-24")
        assert voided.account.currencies[0].slippage.value == Decimal("4")

    def test_incomplete_marks_fills_costs_and_gas_fail_closed(self) -> None:
        """A report cannot silently accept missing economics or unsupported on-chain gas."""
        ledger = AccountLedger(AccountState(account_id="physical", currencies=(self.usd,)))
        self._fund(ledger, "capital", "1000")
        fill = self._fill(
            "buy", at_seconds=1, quantity="2", reference="100", effective="102", fee="2"
        )
        link, cost = self._post_fill(ledger, fill, instance_id="alpha", order_id="buy-order")
        cutoff = self.start + timedelta(seconds=4)
        maximum_age = timedelta(seconds=1)
        current_mark = self._mark("close", at_seconds=3, value="90")
        reporter = PaperAccountReporter()
        with pytest.raises(ValueError, match="complete current position marks"):
            reporter.build(
                ledger.state,
                cutoff=cutoff,
                max_mark_age=maximum_age,
                marks=(),
                fills=(link,),
                costs=(cost,),
                gas_policy=self.gas,
            )
        with pytest.raises(ValueError, match="stale"):
            reporter.build(
                ledger.state,
                cutoff=cutoff,
                max_mark_age=maximum_age,
                marks=(self._mark("old", at_seconds=2, value="90"),),
                fills=(link,),
                costs=(cost,),
                gas_policy=self.gas,
            )
        with pytest.raises(ValueError, match="future"):
            reporter.build(
                ledger.state,
                cutoff=cutoff,
                max_mark_age=maximum_age,
                marks=(self._mark("future", at_seconds=5, value="90"),),
                fills=(link,),
                costs=(cost,),
                gas_policy=self.gas,
            )
        with pytest.raises(ValueError, match="knowledge after cutoff"):
            reporter.build(
                ledger.state,
                cutoff=self.start,
                max_mark_age=maximum_age,
                marks=(current_mark,),
                fills=(link,),
                costs=(cost,),
                gas_policy=self.gas,
            )
        with pytest.raises(ValueError, match="every current direct or child fill"):
            reporter.build(
                ledger.state,
                cutoff=cutoff,
                max_mark_age=maximum_age,
                marks=(current_mark,),
                fills=(),
                costs=(cost,),
                gas_policy=self.gas,
            )
        with pytest.raises(ValueError, match="every current fee and rebate"):
            reporter.build(
                ledger.state,
                cutoff=cutoff,
                max_mark_age=maximum_age,
                marks=(current_mark,),
                fills=(link,),
                costs=(),
                gas_policy=self.gas,
            )
        with pytest.raises(ValueError, match="applicable gas"):
            PaperGasPolicy(scenario_id="on-chain", applicable=True, reason="gas required")
