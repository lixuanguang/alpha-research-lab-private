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
    PaperTelemetryRetention,
    ReferenceCandidate,
)
from configuration.accounts import InstrumentFeeRate
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
        spot_limits: tuple[SpotLimits, ...] = (
            SpotLimits(maximum=quantity, lot=quantity, tick=price, product="spot"),
        )
        account = AccountConfiguration(
            mode="paper",
            opening_at=datetime(2026, 9, 27, tzinfo=UTC),
            accounts=(OpeningAccount(account_id="shared", cash=(money,)),),
            instruments=spot_limits,
            fee_rates=tuple(
                InstrumentFeeRate(
                    instrument_id=limits.maximum.dimension.instrument_id, rate=Decimal(0)
                )
                for limits in spot_limits
            ),
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
                max_residual_age_us=86_400_000_000,
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
                    candidate=ReferenceCandidate(
                        formula="fixed_clip" if name == "first" else "liquidity_clip",
                        cadence_us=3_000_000,
                        starts_at=datetime(2026, 9, 25, tzinfo=UTC),
                    ),
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
                    replace(
                        before.instances[0],
                        candidate=replace(before.instances[0].candidate, formula="liquidity_clip"),
                    ),
                    before.instances[1],
                ),
                revision=2,
                previous_sha256=before.identity,
            ),
            replace(
                before,
                sources=(replace(before.sources[0], freshness_us=20_000_000),),
                revision=2,
                previous_sha256=before.identity,
            ),
        ):
            with pytest.raises(ValueError, match="immutable"):
                successor.require_successor(before)

    def test_candidate_cadence_is_positive_and_within_freshness_and_capture_idle(self) -> None:
        """A candidate may decide less often than ingestion but never beyond freshness."""
        before = self.configuration()
        first = before.instances[0]
        source = before.sources[0]
        bound = min(source.freshness_us, source.capture.idle_seconds * 1_000_000)
        for cadence in (0, -1):
            with pytest.raises(ValueError, match="invalid reference candidate"):
                replace(first.candidate, cadence_us=cadence)
        with pytest.raises(ValueError, match="exceeds"):
            replace(
                before,
                instances=(
                    replace(first, candidate=replace(first.candidate, cadence_us=bound + 1)),
                    before.instances[1],
                ),
            )
        with pytest.raises(TypeError, match="timezone-aware"):
            replace(first.candidate, starts_at=datetime(2026, 9, 25))
        within = replace(first, candidate=replace(first.candidate, cadence_us=bound))
        assert replace(before, instances=(within, before.instances[1])).instances[0] == within

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

    def test_telemetry_retention_is_optional_and_bounded(self) -> None:
        """Unset retention keeps every existing identity; a declared one stays finite."""
        configuration = self.configuration()
        assert b'telemetry"' not in DomainCodec().encode_json(configuration)
        retained = replace(
            configuration,
            telemetry=PaperTelemetryRetention(max_events=8_000_000, retention_days=7),
        )
        retained.__post_init__()
        assert retained.identity != configuration.identity
        for max_events, days in ((0, 7), (10_000_001, 7), (8_000_000, 0)):
            with pytest.raises(ValueError, match="telemetry retention"):
                PaperTelemetryRetention(max_events=max_events, retention_days=days)
