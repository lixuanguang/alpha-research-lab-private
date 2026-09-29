"""Bind one test-venue account to canonical spot units and separate order authority."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from datetime import datetime
from typing import Literal

# project library imports
from configuration.accounts import AccountConfiguration
from financial_units import Currency, Dimension, Money, QuantityKind
from reference_data.catalogs import ReferenceHistory
from reference_data.instruments import InstrumentId
from serialization import DomainCodec, WireRecord


class VenueInstrument(WireRecord, frozen=True, kw_only=True):
    """Map a canonical spot quantity to one native symbol and exact currencies."""

    dimension: Dimension
    base_currency: Currency
    quote_currency: Currency
    native_symbol: str

    def __post_init__(self) -> None:
        """Reject malformed native identifiers and incompatible native quantities."""
        if (
            type(self.dimension) is not Dimension
            or type(self.base_currency) is not Currency
            or type(self.quote_currency) is not Currency
        ):
            raise TypeError("venue instrument requires exact financial units")
        self.dimension.model_copy()
        self.base_currency.validate_currency()
        self.quote_currency.validate_currency()
        if self.dimension.kind is not QuantityKind.BASE_UNIT:
            raise ValueError("venue spot instrument requires base-unit quantity")
        if self.base_currency == self.quote_currency:
            raise ValueError("venue spot base and quote currencies must differ")
        if (
            type(self.native_symbol) is not str
            or re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", self.native_symbol) is None
        ):
            raise ValueError("invalid native venue symbol")


class VenueCredentialReferences(WireRecord, frozen=True, kw_only=True):
    """Name environment variables while keeping secret material outside config."""

    api_key_env: str
    api_secret_env: str
    passphrase_env: str | None = None

    def __post_init__(self) -> None:
        """Permit distinct, explicit environment variable references only."""
        values: tuple[str, ...] = (self.api_key_env, self.api_secret_env)
        if self.passphrase_env is not None:
            values += (self.passphrase_env,)
        if any(
            type(value) is not str or re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", value) is None
            for value in values
        ) or len(set(values)) != len(values):
            raise ValueError("invalid or duplicate venue credential environment reference")


class VenueExecutionConfiguration(WireRecord, frozen=True, kw_only=True):
    """Pin one test environment and its account, reference and native spot mapping.

    The configuration is operational scope, not submission authority. It contains
    environment variable names but never credential bytes or arbitrary endpoints.
    """

    account: AccountConfiguration
    account_id: str
    venue_account_id: str
    venue: Literal["okx", "bitfinex"]
    environment: Literal["okx_demo", "bitfinex_paper"]
    instruments: tuple[VenueInstrument, ...]
    reference: ReferenceHistory
    max_reference_age_us: int
    credentials: VenueCredentialReferences
    schema_version: Literal["venue-execution"] = "venue-execution"

    def __post_init__(self) -> None:
        """Reject venue, account, reference or currency ambiguity before dispatch."""
        if type(self.account) is not AccountConfiguration:
            raise TypeError("venue execution requires an account configuration")
        self.account.__post_init__()
        if self.account.mode != "venue_test":
            raise ValueError("venue execution requires venue_test account state")
        if (
            self.schema_version != "venue-execution"
            or (self.venue, self.environment)
            not in (("okx", "okx_demo"), ("bitfinex", "bitfinex_paper"))
            or type(self.account_id) is not str
            or self.account_id not in {account.account_id for account in self.account.accounts}
            or type(self.venue_account_id) is not str
            or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", self.venue_account_id) is None
        ):
            raise ValueError("unsupported venue execution account or environment")
        if (
            type(self.instruments) is not tuple
            or not self.instruments
            or type(self.reference) is not ReferenceHistory
            or type(self.max_reference_age_us) is not int
            or self.max_reference_age_us <= 0
            or type(self.credentials) is not VenueCredentialReferences
        ):
            raise ValueError("venue execution requires mapped instruments and reference")
        self.reference.__post_init__()
        self.credentials.__post_init__()
        if (self.venue == "okx") != (self.credentials.passphrase_env is not None):
            raise ValueError("venue credential references do not match authentication")
        limits = {item.maximum.dimension.instrument_id: item for item in self.account.instruments}
        seen_ids: set[InstrumentId] = set()
        seen_symbols: set[str] = set()
        seen_pairs: set[tuple[str, str]] = set()
        for instrument in self.instruments:
            if type(instrument) is not VenueInstrument:
                raise TypeError("venue execution requires VenueInstrument mappings")
            instrument.__post_init__()
            instrument_id = instrument.dimension.instrument_id
            pair = (instrument.base_currency.code, instrument.quote_currency.code)
            if (
                instrument_id in seen_ids
                or instrument.native_symbol in seen_symbols
                or pair in seen_pairs
            ):
                raise ValueError("duplicate or ambiguous venue instrument mapping")
            seen_ids.add(instrument_id)
            seen_symbols.add(instrument.native_symbol)
            seen_pairs.add(pair)
            supported = limits.get(instrument_id)
            if (
                supported is None
                or supported.maximum.dimension != instrument.dimension
                or supported.tick.currency != instrument.quote_currency
                or instrument.quote_currency != self.account.budgets.valuation_currency
            ):
                raise ValueError("venue mapping differs from account units or valuation")
            definitions = (
                specification.instrument
                for specification in self.reference.specifications
                if specification.instrument.instrument_id == instrument_id
            )
            if not any(
                definition.venue.lower() == self.venue
                and definition.symbol == instrument.native_symbol
                and definition.product == "spot"
                and definition.base_currency == instrument.base_currency.code
                and definition.quote_currency == instrument.quote_currency.code
                for definition in definitions
            ):
                raise ValueError("venue mapping has no matching reference definition")

    @property
    def identity(self) -> str:
        """Identify the exact non-secret configuration bytes pinned by authorization."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class VenueAuthorization(WireRecord, frozen=True, kw_only=True):
    """Authorize a bounded test-account instrument scope separately from config."""

    config_sha256: str
    account_id: str
    environment: Literal["okx_demo", "bitfinex_paper"]
    instrument_ids: tuple[InstrumentId, ...]
    valid_from: datetime
    valid_until: datetime
    maximum_order_notional: Money
    submit_enabled: bool = False
    schema_version: Literal["venue-authorization"] = "venue-authorization"

    def __post_init__(self) -> None:
        """Require canonical identity, UTC interval and positive exact notional."""
        self._require_utc(self.valid_from, field_name="venue authority start")
        self._require_utc(self.valid_until, field_name="venue authority expiry")
        if (
            self.schema_version != "venue-authorization"
            or type(self.config_sha256) is not str
            or re.fullmatch(r"[a-f0-9]{64}", self.config_sha256) is None
            or type(self.account_id) is not str
            or not self.account_id
            or self.environment not in ("okx_demo", "bitfinex_paper")
            or type(self.instrument_ids) is not tuple
            or not self.instrument_ids
            or any(type(instrument_id) is not InstrumentId for instrument_id in self.instrument_ids)
            or len(set(self.instrument_ids)) != len(self.instrument_ids)
            or self.valid_until <= self.valid_from
            or type(self.maximum_order_notional) is not Money
            or type(self.submit_enabled) is not bool
        ):
            raise ValueError("invalid venue authorization scope")
        self.maximum_order_notional.model_copy()
        if self.maximum_order_notional.value <= 0:
            raise ValueError("venue order notional must be positive")

    def authorize(
        self,
        config: VenueExecutionConfiguration,
        at: datetime,
        instrument: InstrumentId,
        notional: Money | None,
        *,
        cancel: bool = False,
    ) -> None:
        """Check an exact request before physical dispatch.

        Cancellation remains available after submit authority expires, but only
        for the same configured account and instrument after ``valid_from``.
        """
        self.__post_init__()
        config.__post_init__()
        self._require_utc(at, field_name="venue authorization check")
        if (
            self.config_sha256 != config.identity
            or self.account_id != config.account_id
            or self.environment != config.environment
            or type(instrument) is not InstrumentId
            or instrument not in self.instrument_ids
            or instrument not in {item.dimension.instrument_id for item in config.instruments}
            or self.maximum_order_notional.currency != config.account.budgets.valuation_currency
            or at < self.valid_from
        ):
            raise ValueError("venue request is outside separate authorization scope")
        if cancel:
            if notional is not None:
                raise ValueError("venue cancellation cannot supply a new notional")
            return
        if not self.submit_enabled or at >= self.valid_until or type(notional) is not Money:
            raise ValueError("venue submission is disabled or expired")
        notional.model_copy()
        if (
            notional.currency != self.maximum_order_notional.currency
            or notional.value <= 0
            or notional.value > self.maximum_order_notional.value
        ):
            raise ValueError("venue order notional exceeds authorization")
