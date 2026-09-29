"""Resolve bounded L2 research scenarios without changing source-clock admission."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

# project library imports
from configuration.archives import OKXHistoryConfig
from financial_units import DecimalGrid, Money, Quantity
from risk import SpotLimits
from serialization import DomainCodec, WireRecord


class BookTiming(WireRecord, frozen=True):
    """Declare synthetic microsecond delays separately from original source evidence."""

    feed_us: int
    processing_us: int
    entry_us: int
    response_us: int
    cadence_us: int
    stale_us: int
    schema_version: str = "constant-book-delays"

    def __post_init__(self) -> None:
        """Require bounded delays, positive entry/cadence and an explicit research model."""
        if (
            self.schema_version != "constant-book-delays"
            or any(
                type(value) is not int or not 0 <= value <= 86_400_000_000
                for value in (
                    self.feed_us,
                    self.processing_us,
                    self.entry_us,
                    self.response_us,
                    self.cadence_us,
                    self.stale_us,
                )
            )
            or min(self.entry_us, self.cadence_us, self.stale_us) <= 0
        ):
            raise ValueError("invalid constant book timing scenario")


class BookInstance(WireRecord, frozen=True):
    """Select one isolated rule, account, exact grids and liquidity-taking envelope."""

    instance: str
    rule: str
    quantity: Quantity
    initial_cash: Money
    limits: SpotLimits
    imbalance_threshold: Decimal
    depth: int
    fee_rate: Decimal
    rounding: str
    take_fraction: Decimal

    def __post_init__(self) -> None:
        """Reject malformed financial inputs and unsupported strategy/risk parameters."""
        if (
            type(self.instance) is not str
            or not self.instance.strip()
            or type(self.rule) is not str
            or not self.rule.strip()
            or type(self.quantity) is not Quantity
            or type(self.initial_cash) is not Money
            or type(self.limits) is not SpotLimits
        ):
            raise ValueError("book instance requires explicit identity and exact spot values")
        self.limits.__post_init__()
        self.quantity.model_copy()
        self.initial_cash.model_copy()
        for value in (self.imbalance_threshold, self.fee_rate, self.take_fraction):
            DecimalGrid.require_decimal(value)
        if (
            self.quantity.value <= 0
            or self.initial_cash.value <= 0
            or self.initial_cash.currency != self.limits.tick.currency
            or self.limits.target_reason(self.quantity, self.quantity, pending=False) is not None
            or not 0 <= self.imbalance_threshold < 1
            or not 0 <= self.fee_rate < 1
            or not 0 < self.take_fraction <= 1
            or self.rounding not in ("half_even", "half_up")
            or type(self.depth) is not int
            or not 1 <= self.depth <= 400
        ):
            raise ValueError("invalid book strategy, cash, fee or size envelope")


class BookRun(WireRecord, frozen=True):
    """Pin an archive prefix and independent strategy instances to one timing scenario."""

    history: OKXHistoryConfig
    start: datetime
    end: datetime
    timing: BookTiming
    instances: tuple[BookInstance, ...]
    schema_version: str = "l2-spot-research"

    def __post_init__(self) -> None:
        """Validate source, UTC window, bounds and spot dimensions before any replay."""
        self._require_utc(self.start, field_name="start")
        self._require_utc(self.end, field_name="end")
        if (
            self.schema_version != "l2-spot-research"
            or type(self.history) is not OKXHistoryConfig
            or type(self.timing) is not BookTiming
            or type(self.instances) is not tuple
            or not 1 <= len(self.instances) <= 8
        ):
            raise ValueError("unsupported L2 run schema or selections")
        self.history.__post_init__()
        self.timing.__post_init__()
        if (
            self.end <= self.start
            or self.start.date() != self.history.day
            or self.end.date() != self.history.day
            or self.history.max_records > 10_000
            or (self.end - self.start) // timedelta(microseconds=self.timing.cadence_us) > 10_000
        ):
            raise ValueError("book run requires one bounded day and at most 10000 decisions")
        for instance in self.instances:
            if type(instance) is not BookInstance:
                raise TypeError("book run requires typed instances")
            instance.__post_init__()
            if (
                instance.quantity.dimension.instrument_id != self.history.instrument_id
                or instance.initial_cash.currency.code != self.history.quote_currency
            ):
                raise ValueError("book instance differs from archive instrument or quote currency")
        if len({item.instance for item in self.instances}) != len(self.instances):
            raise ValueError("duplicate book strategy instance")

    @property
    def identity(self) -> str:
        """Hash every resolved non-secret input choice.

        Returns:
            Stable configuration SHA-256 independent of file location.
        """
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    @classmethod
    def read(cls, path: Path) -> BookRun:
        """Read a strict versioned configuration through the existing exact codec.

        Args:
            path: Explicit JSON file containing resolved archive and instance selections.

        Returns:
            Validated immutable research configuration.
        """
        return DomainCodec().decode_json(path.read_bytes(), cls)
