"""Exercise separate test-venue scope and installed application admission."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from applications.execute.accounts import AccountExecutionApplication, AccountExecutionRequest
from applications.execute.venue import VenueExecutionApplication
from configuration import (
    AccountConfiguration,
    OpeningAccount,
    VenueAuthorization,
    VenueCredentialReferences,
    VenueExecutionConfiguration,
    VenueInstrument,
)
from execution import AccountQuote
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.catalogs import InstrumentDefinition, ReferenceHistory, VenueSpecification
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec
from telemetry.events import MonitoringQuery
from telemetry.store import TelemetryStore


class TestVenueExecutionApplication:
    """Check executable account isolation without external venue access."""

    at = datetime(2026, 9, 26, 12, tzinfo=UTC)
    instrument_id = InstrumentId.from_canonical_text("33333333-3333-4333-8333-333333333333")
    dimension = Dimension(instrument_id=instrument_id, kind=QuantityKind.BASE_UNIT)
    base_currency = Currency(code="ETH", minor_unit=Decimal("0.00000001"))

    @classmethod
    def _money(cls, value: str, currency: Currency) -> Money:
        """Construct an exact scoped currency amount."""
        return Money(value=Decimal(value), currency=currency)

    @classmethod
    def _config(cls, venue: Literal["okx", "bitfinex"] = "okx") -> VenueExecutionConfiguration:
        """Build one venue-bound test account with independently authored limits."""
        if venue == "okx":
            quote = Currency.from_code("USDT")
            symbol = "ETH-USDT"
            environment: Literal["okx_demo", "bitfinex_paper"] = "okx_demo"
            credentials = VenueCredentialReferences(
                api_key_env="TEST_OKX_KEY",
                api_secret_env="TEST_OKX_SECRET",
                passphrase_env="TEST_OKX_PASSPHRASE",
            )
        elif venue == "bitfinex":
            quote = Currency.from_code("USD")
            symbol = "tETHUSD"
            environment = "bitfinex_paper"
            credentials = VenueCredentialReferences(
                api_key_env="TEST_BITFINEX_KEY", api_secret_env="TEST_BITFINEX_SECRET"
            )
        else:
            raise ValueError("unsupported test venue")
        maximum = Quantity(value=Decimal("10"), dimension=cls.dimension)
        account = AccountConfiguration(
            mode="venue_test",
            opening_at=cls.at,
            accounts=(
                OpeningAccount(account_id="test-account", cash=(cls._money("10000", quote),)),
            ),
            instruments=(
                SpotLimits(
                    maximum=maximum,
                    lot=Quantity(value=Decimal("0.01"), dimension=cls.dimension),
                    tick=Price(value=Decimal("0.01"), currency=quote, per=cls.dimension),
                    product="spot",
                ),
            ),
            budgets=BudgetPolicy(
                valuation_currency=quote,
                firm_maximum=cls._money("10000", quote),
                accounts=(
                    AccountLimit(account_id="test-account", maximum=cls._money("10000", quote)),
                ),
                instances=(
                    InstanceLimit(
                        instance_id="reference-instance",
                        account_id="test-account",
                        maximum=cls._money("5000", quote),
                        instruments=(cls.instrument_id,),
                    ),
                ),
                max_quote_age_us=1_000_000,
                max_state_age_us=86_400_000_000,
                max_price_deviation_bps=100,
                max_order_notional=cls._money("5000", quote),
            ),
        )
        reference = ReferenceHistory(
            specifications=(
                VenueSpecification(
                    instrument=InstrumentDefinition(
                        instrument_id=cls.instrument_id,
                        venue=venue,
                        symbol=symbol,
                        product="spot",
                        base_currency="ETH",
                        quote_currency=quote.code,
                        calendar="24x7",
                    ),
                    valid_from=cls.at,
                    valid_to=None,
                    ts_knowledge=cls.at,
                    source_digest="a" * 64,
                    basis="current_observation",
                    price_tick=Decimal("0.01"),
                    quantity_step=Decimal("0.01"),
                    minimum_quantity=Decimal("0.01"),
                    status="live",
                ),
            ),
        )
        return VenueExecutionConfiguration(
            account=account,
            account_id="test-account",
            venue_account_id="42",
            venue=venue,
            environment=environment,
            instruments=(
                VenueInstrument(
                    dimension=cls.dimension,
                    base_currency=cls.base_currency,
                    quote_currency=quote,
                    native_symbol=symbol,
                ),
            ),
            reference=reference,
            max_reference_age_us=60_000_000,
            credentials=credentials,
        )

    @classmethod
    def _authorization(
        cls, config: VenueExecutionConfiguration, *, enabled: bool
    ) -> VenueAuthorization:
        """Create a separate envelope pinned to one exact configuration."""
        return VenueAuthorization(
            config_sha256=config.identity,
            account_id=config.account_id,
            environment=config.environment,
            instrument_ids=(cls.instrument_id,),
            valid_from=cls.at,
            valid_until=cls.at + timedelta(hours=1),
            maximum_order_notional=cls._money("100", config.account.budgets.valuation_currency),
            submit_enabled=enabled,
        )

    @pytest.mark.parametrize("venue", ["okx", "bitfinex"])
    def test_config_round_trip_keeps_test_venue_scope(
        self, venue: Literal["okx", "bitfinex"]
    ) -> None:
        """Both venue configurations retain exact account and reference identities."""
        config = self._config(venue)
        decoded = DomainCodec().decode_json(
            DomainCodec().encode_json(config), VenueExecutionConfiguration
        )
        assert decoded == config
        assert decoded.identity == config.identity

    def test_rejects_unmapped_symbol_and_non_test_account(self) -> None:
        """Native symbols and executable mode cannot drift from owning contracts."""
        config = self._config()
        wrong_symbol = replace(config.instruments[0], native_symbol="ETH-USD")
        with pytest.raises(ValueError, match="reference definition"):
            replace(config, instruments=(wrong_symbol,)).__post_init__()
        with pytest.raises(ValueError, match="venue_test"):
            replace(config, account=replace(config.account, mode="paper")).__post_init__()

    def test_authorization_is_separate_bounded_and_cancellation_survives_expiry(self) -> None:
        """A stopped submit envelope cannot widen order value or venue scope."""
        config = self._config()
        disabled = self._authorization(config, enabled=False)
        with pytest.raises(ValueError, match="disabled"):
            disabled.authorize(
                config,
                self.at,
                self.instrument_id,
                self._money("10", config.account.budgets.valuation_currency),
            )
        enabled = self._authorization(config, enabled=True)
        with pytest.raises(ValueError, match="notional"):
            enabled.authorize(
                config,
                self.at,
                self.instrument_id,
                self._money("100.01", config.account.budgets.valuation_currency),
            )
        with pytest.raises(ValueError, match="expired"):
            enabled.authorize(
                config,
                self.at + timedelta(hours=1),
                self.instrument_id,
                self._money("10", config.account.budgets.valuation_currency),
            )
        enabled.authorize(
            config, self.at + timedelta(hours=2), self.instrument_id, None, cancel=True
        )
        with pytest.raises(ValueError, match="scope"):
            enabled.authorize(
                self._config("bitfinex"), self.at, self.instrument_id, None, cancel=True
            )

    def test_inspect_needs_no_credentials_and_old_account_command_rejects(
        self, tmp_path: Path
    ) -> None:
        """Installed inspection creates pinned state without reading secret values."""
        config = self._config()
        config_path = tmp_path / "venue.json"
        config_path.write_bytes(DomainCodec().encode_json(config))
        account_path = tmp_path / "account.json"
        account_path.write_bytes(DomainCodec().encode_json(config.account))
        journal_path = tmp_path / "account.sqlite3"
        inspected = VenueExecutionApplication().run(
            config_path=config_path, journal_path=journal_path, action="inspect"
        )
        assert journal_path.exists()
        assert len(inspected.accounts) == 1
        assert inspected.accounts[0].ledger.account_id == config.account_id
        with pytest.raises(ValueError, match="separate venue command"):
            AccountExecutionApplication().run(
                config_path=account_path, journal_path=tmp_path / "paper.sqlite3"
            )

    def test_local_quote_action_requires_typed_matching_request(self, tmp_path: Path) -> None:
        """Installed venue admission accepts a mapped quote without secret access."""
        config = self._config()
        config_path = tmp_path / "venue.json"
        config_path.write_bytes(DomainCodec().encode_json(config))
        request_path = tmp_path / "quote.json"
        request_path.write_bytes(
            DomainCodec().encode_json(
                AccountExecutionRequest(
                    action="quote",
                    quote=AccountQuote(
                        price=Price(
                            value=Decimal("100"),
                            currency=config.account.budgets.valuation_currency,
                            per=self.dimension,
                        ),
                        at=self.at + timedelta(seconds=1),
                    ),
                )
            )
        )
        result = VenueExecutionApplication().run(
            config_path=config_path,
            journal_path=tmp_path / "account.sqlite3",
            action="quote",
            request_path=request_path,
        )
        assert result.quote_observed
        assert result.gateway.config_sha256 == config.identity
        with pytest.raises(ValueError, match="differs"):
            VenueExecutionApplication().run(
                config_path=config_path,
                journal_path=tmp_path / "account.sqlite3",
                action="admit",
                request_path=request_path,
            )

    def test_monitoring_inspection_projects_retained_venue_state(self, tmp_path: Path) -> None:
        """Read venue recovery state and exact cash through an opt-in monitor store."""
        config_path = tmp_path / "venue.json"
        config_path.write_bytes(DomainCodec().encode_json(self._config()))
        monitor_path = tmp_path / "monitor.sqlite3"
        with patch("applications.execute.venue.InstalledIdentity.sha256", return_value="a" * 64):
            result = VenueExecutionApplication().run(
                config_path=config_path,
                journal_path=tmp_path / "account.sqlite3",
                action="inspect",
                telemetry_path=monitor_path,
            )
        assert result.telemetry_error is None
        end = datetime.now(UTC) + timedelta(seconds=1)
        events = TelemetryStore(monitor_path).query(
            MonitoringQuery(
                scope="account:test-account",
                mode="venue_test",
                start=end - timedelta(minutes=1),
                end=end,
                as_of=end,
            )
        )
        assert {event.name for event in events} >= {
            "risk.blocked",
            "account.cash.USDT",
            "execution.venue_recovery_required",
            "execution.receipts",
        }
        assert all(event.context.release == "a" * 64 for event in events)
