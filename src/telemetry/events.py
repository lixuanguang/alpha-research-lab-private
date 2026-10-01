"""Define bounded, exact monitoring facts independently of trading authority."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from datetime import datetime
from typing import Literal, cast

# project library imports
from financial_units import ExactRatio
from serialization import DomainCodec, WireRecord

MonitoringMode = Literal["research", "paper", "shadow", "venue_test", "data"]
_TEXT_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f]")
# Encoding is stateless; one shared codec avoids building an encoder per digest.
_CODEC = DomainCodec()


class MonitoringIdentity(WireRecord, frozen=True):
    """Correlate retained facts using fixed fields rather than arbitrary metric labels."""

    scope: str
    mode: MonitoringMode
    release: str | None = None
    strategy: str | None = None
    model: str | None = None
    dataset: str | None = None
    source: str | None = None
    study: str | None = None
    account: str | None = None
    instrument: str | None = None
    venue: str | None = None
    order: str | None = None
    fill: str | None = None
    state_epoch: str | None = None
    incident: str | None = None

    def __post_init__(self) -> None:
        """Reject unbounded labels, control characters and unsupported operating modes."""
        self.check_text(self.scope)
        if self.mode not in ("research", "paper", "shadow", "venue_test", "data"):
            raise ValueError("unsupported monitoring mode")
        self.check_texts(
            tuple(
                value
                for value in (
                    self.release,
                    self.strategy,
                    self.model,
                    self.dataset,
                    self.source,
                    self.study,
                    self.account,
                    self.instrument,
                    self.venue,
                    self.order,
                    self.fill,
                    self.state_epoch,
                    self.incident,
                )
                if value is not None
            )
        )

    @staticmethod
    def check_text(value: str) -> None:
        """Require a bounded nonempty identity or unit with no control characters."""
        MonitoringIdentity.check_texts((value,))

    @staticmethod
    def check_texts(values: tuple[object, ...]) -> None:
        """Apply ``check_text`` to every value with one control-character scan.

        Every value is a ``str`` before the scan, so their concatenation contains a
        control character exactly when one of them does.
        """
        for value in values:
            # UTF-8 uses at most four bytes per character, so 64 characters fit unencoded.
            if (
                type(value) is not str
                or not value.strip()
                or (len(value) > 64 and len(value.encode()) > 256)
            ):
                raise ValueError("monitoring text must be bounded and nonempty")
        if _TEXT_CONTROL_CHARACTERS.search("".join(cast(tuple[str, ...], values))) is not None:
            raise ValueError("monitoring text must be bounded and nonempty")


class MonitoringEvent(WireRecord, frozen=True):
    """Retain one revision of a sample, with separate event, knowledge and receipt clocks.

    The sample key is (scope, mode, name, version, sample). Revisions preserve its
    event clock, units and correlation. ``recorded_at`` is assigned by the producer
    at the monitoring boundary; replay must preserve it. Unknown source knowledge
    is explicitly marked by clock_quality and must not be reconstructed from UTC.
    """

    context: MonitoringIdentity
    name: str
    version: str
    sample: str
    at: datetime
    available_at: datetime
    recorded_at: datetime
    units: str
    value: ExactRatio | None
    missing_reason: str | None = None
    revision: int = 0
    clock_quality: Literal["observed", "modeled", "unknown"] = "observed"
    sensitivity: Literal["public", "internal"] = "internal"
    schema_version: Literal["monitoring-event"] = "monitoring-event"

    def __post_init__(self) -> None:
        """Enforce exact values, causal clocks and immutable versioned sample semantics."""
        if type(self.context) is not MonitoringIdentity:
            raise TypeError("monitoring event requires a typed identity")
        self.context.__post_init__()
        MonitoringIdentity.check_texts((self.name, self.version, self.sample, self.units))
        for clock in (self.at, self.available_at, self.recorded_at):
            self._require_utc(clock, field_name="monitoring clock")
        if not self.at <= self.available_at <= self.recorded_at:
            raise ValueError("monitoring clocks must be causally ordered")
        if type(self.revision) is not int or not 0 <= self.revision <= 1_000_000:
            raise ValueError("invalid monitoring revision")
        if self.value is None:
            if self.missing_reason is None:
                raise ValueError("missing monitoring value requires a reason")
            MonitoringIdentity.check_text(self.missing_reason)
        elif type(self.value) is not ExactRatio or self.missing_reason is not None:
            raise ValueError("monitoring value requires an exact ratio and no missing reason")
        else:
            self.value.__post_init__()
        if (
            self.schema_version != "monitoring-event"
            or self.clock_quality not in ("observed", "modeled", "unknown")
            or self.sensitivity not in ("public", "internal")
        ):
            raise ValueError("unsupported monitoring schema or classification")

    @property
    def identity(self) -> str:
        """Return the digest of all retained bytes, including knowledge and receipt clocks."""
        return hashlib.sha256(_CODEC.encode_json(self)).hexdigest()


class MonitoringQuery(WireRecord, frozen=True):
    """Select one scope/mode in [start, end), known and received by as_of.

    A query never mixes accounts, currencies or operating modes implicitly.
    ``limit`` bounds returned facts; an overflow fails instead of truncating.
    """

    scope: str
    mode: MonitoringMode
    start: datetime
    end: datetime
    as_of: datetime
    limit: int = 10_000

    def __post_init__(self) -> None:
        """Require explicit UTC cutoffs and a bounded nonempty observation window."""
        MonitoringIdentity(scope=self.scope, mode=self.mode)
        for value in (self.start, self.end, self.as_of):
            self._require_utc(value, field_name="monitoring query clock")
        if self.start >= self.end or self.end > self.as_of:
            raise ValueError("monitoring query requires start < end <= as_of")
        if type(self.limit) is not int or not 1 <= self.limit <= 100_000:
            raise ValueError("monitoring query limit must be bounded")
