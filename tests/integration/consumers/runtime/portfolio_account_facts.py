"""Provide typed policies and independent economic checks for portfolio evidence."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

# project library imports
from accounting import AccountLedger, AccountSnapshot, Fill
from applications.execute import AccountExecutionResult
from configuration import AccountConfiguration, InstrumentFeeRate, OpeningAccount
from execution import (
    AccountDecision,
    AccountQuote,
    MarketTouch,
    OrderDecision,
    OrderEvent,
    PortfolioBatch,
    PortfolioContext,
    PortfolioDecision,
)
from financial_units import Currency, Dimension, Money, Price, Quantity
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent, TargetIntent


class ReferenceTargetPolicy:
    """Produce a configured absolute inventory target for one strategy instance."""

    def __init__(self, target: Quantity) -> None:
        """Bind an exact target without holding journal or account authority."""
        target.model_copy()
        self.target = target

    def decide(self) -> TargetIntent:
        """Return the portable target consumed by independent risk admission."""
        return TargetIntent(quantity=self.target)


class ReferenceLimitPolicy:
    """Produce a configured spot order intent for a different active strategy."""

    def __init__(self, side: Literal["buy", "sell"], quantity: Quantity, limit: Price) -> None:
        """Bind explicit side, base quantity and quote-currency limit."""
        quantity.model_copy()
        limit.model_copy()
        self.side, self.quantity, self.limit = side, quantity, limit

    def decide(self) -> OrderIntent:
        """Return a portable IOC order with no submission privilege."""
        return OrderIntent(
            side=self.side,
            quantity=self.quantity,
            limit=self.limit,
            time_in_force="ioc",
        )


class PortfolioAccountFacts:
    """Author typed portfolio inputs and check their independent exact outcomes."""

    def __init__(
        self,
        currency: Currency,
        dimension: Dimension,
        codec: DomainCodec,
        venue: str,
        opening_at: datetime,
    ) -> None:
        """Bind the selected fixture units and canonical identity codec."""
        self.currency = currency
        self.dimension = dimension
        self.codec = codec
        self.venue = venue
        self.opening_at = opening_at

    def money(self, amount: str) -> Money:
        """Construct exact local quote-currency money."""
        return Money(value=Decimal(amount), currency=self.currency)

    def quantity(self, amount: str) -> Quantity:
        """Construct exact spot base inventory."""
        return Quantity(value=Decimal(amount), dimension=self.dimension)

    def price(self, amount: str = "100") -> Price:
        """Construct an exact cash-spot valuation or limit."""
        return Price(value=Decimal(amount), currency=self.currency, per=self.dimension)

    def config(self) -> AccountConfiguration:
        """Fund a paper account with two authorized strategy instances."""
        spot_limits: tuple[SpotLimits, ...] = (
            SpotLimits(
                maximum=self.quantity("200"),
                lot=self.quantity("1"),
                tick=self.price("0.01"),
                product="spot",
            ),
        )
        return AccountConfiguration(
            mode="paper",
            opening_at=self.opening_at,
            accounts=(OpeningAccount(account_id="shared", cash=(self.money("50000"),)),),
            instruments=spot_limits,
            fee_rates=tuple(
                InstrumentFeeRate(
                    instrument_id=limits.maximum.dimension.instrument_id, rate=Decimal(0)
                )
                for limits in spot_limits
            ),
            budgets=BudgetPolicy(
                valuation_currency=self.currency,
                firm_maximum=self.money("10000"),
                accounts=(AccountLimit(account_id="shared", maximum=self.money("10000")),),
                instances=(
                    InstanceLimit(
                        instance_id="alpha",
                        account_id="shared",
                        maximum=self.money("9000"),
                        instruments=(self.dimension.instrument_id,),
                    ),
                    InstanceLimit(
                        instance_id="beta",
                        account_id="shared",
                        maximum=self.money("9000"),
                        instruments=(self.dimension.instrument_id,),
                    ),
                ),
                max_quote_age_us=1_000_000,
                max_state_age_us=86_400_000_000,
                max_price_deviation_bps=100,
                max_order_notional=self.money("9000"),
            ),
        )

    def snapshot(
        self,
        *,
        instance_id: str | None,
        cash: str,
        position: str | None,
        fees: str,
        transfers: str,
        fill_ids: tuple[str, ...],
        posting_ids: tuple[str, ...],
    ) -> AccountSnapshot:
        """State independently authored account or strategy expectations."""
        return AccountSnapshot(
            account_id="shared",
            instance_id=instance_id,
            cash=(self.money(cash),),
            positions=() if position is None else (self.quantity(position),),
            fees=(self.money(fees),),
            rebates=(self.money("0"),),
            transfers=(self.money(transfers),),
            fill_ids=fill_ids,
            posting_ids=posting_ids,
        )

    def opening(self) -> AccountSnapshot:
        """Specify the cash-funded account before strategy activity."""
        return self.snapshot(
            instance_id=None,
            cash="50000",
            position=None,
            fees="0",
            transfers="50000",
            fill_ids=(),
            posting_ids=(f"opening:{self.currency.code}",),
        )

    def decision(
        self,
        *,
        instance_id: Literal["alpha", "beta"],
        identity: str,
        at: datetime,
        intent: TargetIntent | OrderIntent,
        bucket: str = "spot",
    ) -> PortfolioDecision:
        """Bind one intent to complete strategy and account ownership."""
        strategy_id = "inventory-target" if instance_id == "alpha" else "limit-order"
        return PortfolioDecision(
            request=AccountDecision(
                account_id="shared",
                instance_id=instance_id,
                decision=OrderDecision(identity=identity, at=at, intent=intent),
                quote=AccountQuote(price=self.price(), at=at),
                maximum_fee=self.money("1"),
                checkpoint=f"{strategy_id}:{identity}".encode(),
                touch=MarketTouch(bid=self.price("99.99"), ask=self.price()),
            ),
            context=PortfolioContext(
                portfolio_id="reference-portfolio",
                strategy_id=strategy_id,
                model_revision="reference",
                config_revision="paper",
                horizon="one-minute",
                reason="authored-fixture",
                venue=self.venue,
                settlement="spot-immediate",
                risk_bucket=bucket,
                authority_scope="paper",
            ),
        )

    def batch(
        self,
        identity: str,
        at: datetime,
        decisions: tuple[PortfolioDecision, ...],
        crossing: Literal["reject", "internal_at_quote"],
    ) -> PortfolioBatch:
        """Give independently timed decisions one atomic boundary."""
        return PortfolioBatch(
            identity=identity,
            at=at + timedelta(microseconds=1),
            decisions=decisions,
            crossing=crossing,
        )

    def physical_fill(
        self,
        *,
        identity: str,
        order_id: str,
        decision_at: datetime,
        at: datetime,
        quantity: str,
        fee: str,
    ) -> OrderEvent:
        """Supply one explicitly modeled physical paper fill and cost."""
        return OrderEvent(
            identity=f"receipt:{identity}",
            order_id=order_id,
            at=at,
            kind="fill",
            fill=Fill(
                identity=identity,
                decision_at=decision_at,
                filled_at=at,
                quantity=self.quantity(quantity),
                reference=self.price(),
                effective=self.price(),
                fee=self.money(fee),
            ),
        )

    def allocated_fill_id(self, physical_id: str, child_id: str) -> str:
        """Derive the documented child lineage for an observation."""
        return hashlib.sha256(
            self.codec.encode_json(("allocated-physical-fill", physical_id, child_id))
        ).hexdigest()

    def verify_balances(
        self,
        result: AccountExecutionResult,
        *,
        physical_cash: str,
        physical_position: str | None,
        physical_fee: str,
        alpha_cash: str,
        alpha_position: str | None,
        alpha_fee: str,
        beta_cash: str,
        beta_position: str | None,
        beta_fee: str,
    ) -> None:
        """Compare all three balances to independently calculated values."""
        assert len(result.accounts) == 1
        ledger = AccountLedger(result.accounts[0].ledger)
        physical = ledger.snapshot()
        alpha = ledger.snapshot(instance_id="alpha")
        beta = ledger.snapshot(instance_id="beta")
        assert physical.cash == (self.money(physical_cash),)
        assert physical.positions == (
            () if physical_position is None else (self.quantity(physical_position),)
        )
        assert physical.fees == (self.money(physical_fee),)
        assert alpha.cash == (self.money(alpha_cash),)
        assert alpha.positions == (
            () if alpha_position is None else (self.quantity(alpha_position),)
        )
        assert alpha.fees == (self.money(alpha_fee),)
        assert beta.cash == (self.money(beta_cash),)
        assert beta.positions == (() if beta_position is None else (self.quantity(beta_position),))
        assert beta.fees == (self.money(beta_fee),)
        assert physical.transfers == (self.money("50000"),)
        assert alpha.transfers == beta.transfers == (self.money("0"),)
        assert physical.rebates == alpha.rebates == beta.rebates == (self.money("0"),)
        assert physical.cash[0] == self.money("50000") + alpha.cash[0] + beta.cash[0]
        assert physical.fees[0] == alpha.fees[0] + beta.fees[0]
