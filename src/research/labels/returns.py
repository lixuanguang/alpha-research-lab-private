"""Align exact delayed outcomes against a frozen decision-time price endpoint."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Literal, NamedTuple

# project library imports
from financial_units import ExactRatio
from market_data.query import QueryBatch
from research.features import FeatureValue, PriceWindow, WindowPolicy
from serialization import DomainCodec, WireRecord


class LabelValue(NamedTuple):
    """Retain outcome horizon, full information interval and conservative availability."""

    definition_identity: str
    decision_at: datetime
    outcome_at: datetime
    information_start: datetime
    information_end: datetime
    available_at: datetime | None
    window: PriceWindow | None
    missing: str | None
    value: ExactRatio | None


class ForwardReturn(WireRecord, frozen=True, kw_only=True):
    """Version future last price / frozen feature-window last price minus one.

    This is a diagnostic outcome with no execution delay or cost model. Outcome
    revisions are selected at horizon plus availability delay, never retrospectively
    refreshed at the study's later observation cutoff. Overlapping outcomes are
    permitted and expose full information intervals for temporal purging.
    """

    schema_version: Literal["forward-return-v1"] = "forward-return-v1"
    units: Literal["dimensionless"] = "dimensionless"
    horizon_us: int
    availability_delay_us: int
    policy: WindowPolicy

    def __post_init__(self) -> None:
        """Reject unsupported definitions and invalid horizon or delay."""
        if self.schema_version != "forward-return-v1" or self.units != "dimensionless":
            raise ValueError("unsupported forward-return definition")
        if type(self.policy) is not WindowPolicy:
            raise TypeError("forward return requires WindowPolicy")
        self.policy.__post_init__()
        if (
            type(self.horizon_us) is not int
            or not 0 < self.horizon_us <= 31_536_000_000_000
            or type(self.availability_delay_us) is not int
            or not 0 <= self.availability_delay_us <= 31_536_000_000_000
        ):
            raise ValueError("invalid outcome horizon or availability delay")

    @property
    def identity(self) -> str:
        """Hash outcome formula, units, horizon, window and availability policy.

        Returns:
            SHA-256 of the immutable definition.
        """
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    def evaluate(
        self, feature: FeatureValue, batches: tuple[QueryBatch, ...] | None, *, known_at: datetime
    ) -> LabelValue:
        """Compute an outcome only after its declared extraction time.

        Args:
            feature: Frozen earlier endpoint; its feature value is never modified.
            batches: Separate outcome cutoff query, or None while the label is pending.
            known_at: UTC study observation cutoff; cannot backdate label availability.

        Returns:
            Exact ratio or pending/missing label, with conservative publication-aware interval.

        Raises:
            ValueError: A pending outcome was read, or an available outcome lacks input batches.
        """
        self.__post_init__()
        self._require_utc(known_at, field_name="known_at")
        outcome = feature.decision_at + timedelta(microseconds=self.horizon_us)
        available = outcome + timedelta(microseconds=self.availability_delay_us)
        window = None
        value = None
        missing: str | None = "outcome not yet available"
        if known_at < available:
            if batches is not None:
                raise ValueError("pending outcome must not be read")
        else:
            if batches is None:
                raise ValueError("available outcome requires its cutoff query")
            window = self.policy.collect(
                batches, binding=feature.window.binding, end=outcome, known_at=available
            )
            missing = feature.window.missing or window.missing
            if missing is None:
                value = ExactRatio.from_fraction(
                    Fraction(window.points[-1].price) / Fraction(feature.window.points[-1].price)
                    - 1
                )
        return LabelValue(
            self.identity,
            feature.decision_at,
            outcome,
            min(feature.window.start, outcome - timedelta(microseconds=self.policy.lookback_us)),
            available,
            available if value is not None else None,
            window,
            missing,
            value,
        )
