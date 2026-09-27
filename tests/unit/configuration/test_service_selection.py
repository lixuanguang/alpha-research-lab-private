"""Verify controlled service selection without reinterpreting installed economic identities."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from configuration import (
    AccountConfiguration,
    CaptureConfig,
    OpeningAccount,
    PaperExecutionScenario,
    PaperServiceAccount,
    PaperServiceConfiguration,
    PaperServiceInstance,
    PaperServiceSource,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec


class TestServiceSelection:
    """Keep active selection distinct from immutable funding and strategy definitions."""

    @staticmethod
    def configuration() -> PaperServiceConfiguration:
        """Provision two definitions but initially schedule only one instance."""
        capture = CaptureConfig.read(Path("configs/live/okx-btc-usdt.json"))
        currency = Currency.from_code("USDT")
        dimension = Dimension(instrument_id=capture.instrument_id, kind=QuantityKind.BASE_UNIT)
        money = Money(value=Decimal("1000"), currency=currency)
        quantity = Quantity(value=Decimal("1"), dimension=dimension)
        price = Price(value=Decimal("0.01"), currency=currency, per=dimension)
        account = AccountConfiguration(
            mode="paper",
            opening_at=datetime(2026, 9, 27, tzinfo=UTC),
            accounts=(OpeningAccount(account_id="shared", cash=(money,)),),
            instruments=(SpotLimits(maximum=quantity, lot=quantity, tick=price, product="spot"),),
            budgets=BudgetPolicy(
                valuation_currency=currency,
                firm_maximum=money,
                accounts=(AccountLimit(account_id="shared", maximum=money),),
                instances=tuple(
                    InstanceLimit(
                        instance_id=name,
                        account_id="shared",
                        maximum=money,
                        instruments=(capture.instrument_id,),
                    )
                    for name in ("first", "second")
                ),
                max_quote_age_us=30_000_000,
                max_state_age_us=30_000_000,
                max_price_deviation_bps=100,
                max_order_notional=money,
            ),
        )
        source = PaperServiceSource(
            name="book",
            capture=capture,
            freshness_us=30_000_000,
            scenario=PaperExecutionScenario(
                venue="okx",
                instrument_id=capture.instrument_id,
                entry_delay_us=1000,
                cancel_delay_us=2000,
                adverse=price,
                fee_rate=Decimal("0.001"),
                take_fraction=Decimal("0.5"),
                gas_inapplicable_reason="Off-chain spot without blockchain transfers.",
            ),
        )
        return PaperServiceConfiguration(
            accounts=(
                PaperServiceAccount(
                    account_id="shared",
                    configuration=account,
                    socket_path="/private/tmp/selection-test.sock",
                ),
            ),
            sources=(source,),
            instances=tuple(
                PaperServiceInstance(
                    instance_id=name,
                    account_id="shared",
                    source="book",
                    policy="fixed_clip" if name == "first" else "liquidity_clip",
                    quantity=quantity,
                    lot=quantity,
                    maximum_fee=Money(value=Decimal("1"), currency=currency),
                )
                for name in ("first", "second")
            ),
            active=("first",),
            revision=1,
        )

    def test_add_active_instance_preserves_exact_definitions(self) -> None:
        """A successor selects the installed spare without changing economics or policy identity."""
        before = self.configuration()
        after = replace(
            before, active=("first", "second"), revision=2, previous_sha256=before.identity
        )
        after.require_successor(before)
        assert after.accounts == before.accounts
        assert after.instances == before.instances
        assert after.identity != before.identity
        assert (
            DomainCodec().decode_json(DomainCodec().encode_json(after), PaperServiceConfiguration)
            == after
        )
        with pytest.raises(ValueError, match="ancestry"):
            before.require_successor(after)

    def test_revision_cannot_change_budget_or_existing_policy(self) -> None:
        """New selection ancestry cannot authorize different funding or reinterpret a checkpoint."""
        before = self.configuration()
        account = before.accounts[0]
        changed = replace(account.configuration, opening_at=datetime(2026, 9, 26, tzinfo=UTC))
        for successor in (
            replace(
                before,
                accounts=(replace(account, configuration=changed),),
                revision=2,
                previous_sha256=before.identity,
            ),
            replace(
                before,
                instances=(
                    replace(before.instances[0], policy="liquidity_clip"),
                    before.instances[1],
                ),
                revision=2,
                previous_sha256=before.identity,
            ),
            replace(
                before,
                sources=(replace(before.sources[0], market_interval_us=1_000_000),),
                revision=2,
                previous_sha256=before.identity,
            ),
        ):
            with pytest.raises(ValueError, match="immutable"):
                successor.require_successor(before)

    def test_market_interval_is_positive_and_within_freshness_and_capture_idle(self) -> None:
        """An account may admit less often than ingestion but never beyond freshness."""
        source = self.configuration().sources[0]
        assert source.market_interval_us == 3_000_000
        bound = min(source.freshness_us, source.capture.idle_seconds * 1_000_000)
        for interval in (0, -1, bound + 1):
            with pytest.raises(ValueError, match="incompatible"):
                replace(source, market_interval_us=interval)
        assert replace(source, market_interval_us=bound).market_interval_us == bound

    def test_unprovisioned_instance_currency_and_instrument_rejected(self) -> None:
        """Selection never implies a new budget, source identity or currency conversion."""
        before = self.configuration()
        with pytest.raises(ValueError, match="unknown"):
            replace(before, active=("unprovisioned",))
        with pytest.raises(ValueError, match="exceeds"):
            replace(
                before,
                instances=(
                    replace(
                        before.instances[0],
                        maximum_fee=Money(value=Decimal("1"), currency=Currency.from_code("USD")),
                    ),
                    before.instances[1],
                ),
            )
        with pytest.raises(ValueError, match="incompatible"):
            replace(
                before.sources[0],
                capture=replace(
                    before.sources[0].capture,
                    instrument_id=CaptureConfig.read(
                        Path("configs/live/bitfinex-btc-usd.json")
                    ).instrument_id,
                ),
            )
