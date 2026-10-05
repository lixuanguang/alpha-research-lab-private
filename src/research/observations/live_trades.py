"""Bind a durably captured public trade tape to bounded live decision inputs."""

from __future__ import annotations

# standard library imports
import hashlib
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction

# project library imports
from configuration import CaptureConfig
from financial_units import ExactRatio
from market_data.books import CaptureReplay, NativeBook, TradeTape, TradeTapeCoverage
from market_data.contracts import BookObservation, CaptureRecord, PublicTrade, RecordingRequest
from research.observations.inputs import DecisionInputs, InputRequirement, NamedObservation
from serialization import DomainCodec


@dataclass(frozen=True, slots=True)
class _TapeTrade:
    """Keep one applied trade with its venue time, actual delivery and lineage."""

    trade: PublicTrade
    event_at: datetime
    available_at: datetime
    position: int
    index: int
    lineage: str


@dataclass(frozen=True, slots=True)
class _TapeBoundary:
    """Keep one delivered boundary's receipt and continuity, for causal reads."""

    available_at: datetime
    received_at: datetime
    covered_from: datetime | None


class LiveTradeDecisionSource:
    """Project one captured OKX or Bitfinex public trade tape into named decision fields.

    One requirement name, ``trade`` family, ``event`` clock and age covers one or more
    fields: ``price`` (quote/base currencies), ``quantity`` and ``signed_quantity``
    (base currency) of the latest trade, and ``signed_flow`` (base currency), the
    aggressor-signed quantity of every trade with venue time in ``(at - age, at]``.
    These are the same fields and window rule research reads from retained trades.

    The source reconstructs the tape itself from each durable record and requires the
    collector's outcome and state identity, so both sides apply identical trades.
    Coverage starts when the tape synchronizes and ends at a gap, invalid frame or
    session end (``TradeTapeCoverage``, which published captured trades also use); a flow
    window must lie inside one coverage interval. The latest trade is the one with
    the latest venue time, then delivery, then message position and index within the
    message, the same order research applies to captured trades. Any field also
    needs a boundary within the capture's idle time, which proves the stream was live.
    Venue and local clocks are compared without skew correction, so recorder coverage
    stays unproven, as for retained trades.
    """

    _FIELDS = ("price", "quantity", "signed_quantity", "signed_flow")

    def __init__(
        self,
        request: RecordingRequest,
        requirements: tuple[InputRequirement, ...],
        *,
        tapes: Callable[[CaptureConfig], TradeTape],
        history_capacity: int,
        trade_capacity: int = 100_000,
    ) -> None:
        """Bind the trade feed, named fields, tape constructor and finite retention.

        Args:
            request: Immutable trade feed and recording identity.
            requirements: Distinct supported trade fields sharing one name and age.
            tapes: The installed venue tape constructor the collector also uses.
            history_capacity: Maximum retained boundaries, from 1 to 10000.
            trade_capacity: Maximum retained trades, from 1 to 1000000. Dropping an
                older trade moves coverage past it, so no flow window is understated.
        """
        request.__post_init__()
        config = request.config
        if config.channel != "trades" or config.venue not in ("okx", "bitfinex"):
            raise ValueError("live trade source requires a supported public trades feed")
        if type(requirements) is not tuple or not requirements:
            raise ValueError("live trade source requires trade field requirements")
        for item in requirements:
            if type(item) is not InputRequirement:
                raise TypeError("live trade source requires InputRequirement")
            item.__post_init__()
        first = requirements[0]
        units = {
            "price": f"{config.quote_currency}/{config.base_currency}",
            "quantity": config.base_currency,
            "signed_quantity": config.base_currency,
            "signed_flow": config.base_currency,
        }
        if (
            first.family != "trade"
            or first.clock != "event"
            or first.max_age_us <= 0
            or len({item.field.name for item in requirements}) != len(requirements)
            or any(
                (item.name, item.family, item.clock, item.max_age_us)
                != (first.name, first.family, first.clock, first.max_age_us)
                or units.get(item.field.name) != item.field.units
                for item in requirements
            )
        ):
            raise ValueError("unsupported live trade decision projection")
        if type(history_capacity) is not int or not 1 <= history_capacity <= 10_000:
            raise ValueError("live history capacity must be within 1..10000")
        if type(trade_capacity) is not int or not 1 <= trade_capacity <= 1_000_000:
            raise ValueError("live trade capacity must be within 1..1000000")
        self._request, self._requirements, self._requirement = request, requirements, first
        self._request_identity = request.identity
        self._window = timedelta(microseconds=first.max_age_us)
        self._idle = timedelta(seconds=config.idle_seconds)
        self._codec = DomainCodec()
        self._identity = hashlib.sha256(
            self._codec.encode_json(
                (
                    config,
                    request.implementation_identity,
                    request.universes,
                    requirements,
                    history_capacity,
                    trade_capacity,
                )
            )
        ).hexdigest()
        self._replay = CaptureReplay(config, book_factory=tapes)
        self._history: deque[_TapeBoundary] = deque(maxlen=history_capacity)
        self._trades: deque[_TapeTrade] = deque()
        self._trade_capacity = trade_capacity
        self._coverage = TradeTapeCoverage()
        self._covered_from: datetime | None = None
        self._position = 0
        self._last_received_ns = 0
        self._last_available_at: datetime | None = None
        self._last_decision_at: datetime | None = None
        self._last_decision: DecisionInputs | None = None

    @property
    def request(self) -> RecordingRequest:
        """Expose the immutable admitted trade recording."""
        return self._request

    @property
    def identity(self) -> str:
        """Identify the stable trade subscription and projection across recordings."""
        return self._identity

    @property
    def requirements(self) -> tuple[InputRequirement, ...]:
        """Expose the exact trade fields and their shared age and window."""
        return self._requirements

    def accept(
        self,
        record: CaptureRecord,
        row: BookObservation,
        *,
        available_at: datetime | None = None,
    ) -> None:
        """Advance exactly one durable message, checking the collector's reconstruction.

        Args:
            record: Whole persisted trade message, including session transitions.
            row: The collector's canonical boundary for this exact message.
            available_at: Actual UTC delivery after durable apply. Omit only for
                deterministic saved reconstruction that explicitly uses receipt.

        Raises:
            ValueError: Positions, clocks, outcome or tape state differ from the stream.
        """
        record.__post_init__()
        BookObservation.__post_init__(row)
        if (
            row.position != self._position
            or row.epoch != record.epoch
            or row.received_ns != record.received_ns
            or record.received_ns < self._last_received_ns
        ):
            raise ValueError("live trade boundary differs from ordered original receipt")
        received_at = self._from_ns(record.received_ns)
        delivered_at = (
            received_at
            if available_at is None
            else DecisionInputs._require_utc(available_at, field_name="available_at")
        )
        if delivered_at < received_at or (
            self._last_available_at is not None and delivered_at < self._last_available_at
        ):
            raise ValueError("live availability precedes receipt or prior delivery")
        outcome = self._replay.apply(record)
        tape = self._tape(self._replay.book)
        if outcome != row.outcome or tape.identity != row.state_identity:
            raise ValueError("live trade tape differs from the collector's reconstruction")
        opened_ns = self._coverage.step(
            record.kind, tape.ready and not self._replay.invalid, record.received_ns
        )
        if opened_ns is None:
            self._covered_from = None
        elif self._covered_from is None:
            self._covered_from = self._from_ns(opened_ns)
        if outcome in ("snapshot", "update"):
            lineage = self._lineage(record, row, delivered_at)
            for index, trade in enumerate(tape.trades):
                self._trades.append(
                    _TapeTrade(
                        trade=trade,
                        event_at=self._from_ms(trade.event_ms),
                        available_at=delivered_at,
                        position=row.position,
                        index=index,
                        lineage=f"{lineage}:{trade.trade_id}",
                    )
                )
            while len(self._trades) > self._trade_capacity:
                dropped = self._trades.popleft()
                if self._covered_from is not None:
                    self._covered_from = max(self._covered_from, dropped.event_at)
        self._history.append(
            _TapeBoundary(
                available_at=delivered_at,
                received_at=received_at,
                covered_from=self._covered_from,
            )
        )
        self._position += 1
        self._last_received_ns = record.received_ns
        self._last_available_at = delivered_at

    def read(self, entity: str, at: datetime) -> DecisionInputs:
        """Freeze one then-known projection of the latest trade and the flow window.

        Equal cutoffs return the first frozen decision; older cutoffs cannot be
        reopened after a newer one.

        Args:
            entity: Canonical instrument identity selected by the trade feed.
            at: UTC decision cutoff.

        Returns:
            Exact values, or each field's explicit missing reason.
        """
        DecisionInputs._require_utc(at, field_name="at")
        if type(entity) is not str or not entity.strip():
            raise ValueError("live decision requires an entity")
        if self._last_decision_at is not None:
            if at < self._last_decision_at:
                raise ValueError("live decision cutoff cannot move backwards")
            if at == self._last_decision_at and self._last_decision is not None:
                return self._last_decision
        boundary = next((item for item in reversed(self._history) if item.available_at <= at), None)
        if entity != str(self._request.config.instrument_id):
            refusal: str | None = "entity_unbound"
        elif boundary is None:
            refusal = "no_live_input"
        elif boundary.covered_from is None:
            refusal = "trade_stream_unsynchronized"
        elif at - boundary.received_at > self._idle:
            refusal = "stale_trade_stream"
        else:
            refusal = None
        known = tuple(
            item for item in self._trades if item.available_at <= at and item.event_at <= at
        )
        latest = max(known, key=self._order, default=None)
        observations = tuple(
            self._observation(requirement, entity, at, refusal, boundary, known, latest)
            for requirement in self._requirements
        )
        decision = DecisionInputs(entity=entity, decision_at=at, observations=observations)
        self._last_decision_at, self._last_decision = at, decision
        while self._trades and self._trades[0].event_at <= at - self._window:
            self._trades.popleft()
        return decision

    def _observation(
        self,
        requirement: InputRequirement,
        entity: str,
        at: datetime,
        refusal: str | None,
        boundary: _TapeBoundary | None,
        known: tuple[_TapeTrade, ...],
        latest: _TapeTrade | None,
    ) -> NamedObservation:
        """Project one field, or its missing reason, from the causal tape."""
        reason = refusal
        if requirement.field.name == "signed_flow":
            if (
                reason is None
                and boundary is not None
                and boundary.covered_from is not None
                and boundary.covered_from > at - self._window
            ):
                reason = "incomplete_trade_window"
            if reason is not None:
                return self._missing(requirement, entity, at, reason)
            window = tuple(item for item in known if item.event_at > at - self._window)
            flow = sum((self._signed(item.trade) for item in window), Fraction())
            return NamedObservation(
                input=requirement,
                entity=entity,
                event_at=at,
                available_at=at,
                value=ExactRatio.from_fraction(flow),
                reason="observed_public_trades;complete_tape_unproven",
                lineage=hashlib.sha256(
                    self._codec.encode_json(tuple(item.lineage for item in window))
                ).hexdigest(),
            )
        if reason is None and latest is None:
            reason = "no_trade"
        elif reason is None and latest is not None and at - latest.event_at > self._window:
            reason = "stale_input"
        if reason is not None or latest is None:
            return self._missing(requirement, entity, at, reason or "no_trade")
        trade = latest.trade
        amount = {
            "price": Fraction(trade.price),
            "quantity": Fraction(trade.quantity),
            "signed_quantity": self._signed(trade),
        }[requirement.field.name]
        return NamedObservation(
            input=requirement,
            entity=entity,
            event_at=latest.event_at,
            available_at=latest.available_at,
            value=ExactRatio.from_fraction(amount),
            reason="observed_public_trade;complete_tape_unproven",
            lineage=latest.lineage,
        )

    def _missing(
        self, requirement: InputRequirement, entity: str, at: datetime, reason: str
    ) -> NamedObservation:
        """Construct one explicit absent field."""
        return NamedObservation(
            input=requirement,
            entity=entity,
            event_at=at,
            available_at=None,
            value=None,
            reason=reason,
            lineage=self._identity,
        )

    def _lineage(self, record: CaptureRecord, row: BookObservation, delivery_at: datetime) -> str:
        """Bind receipt, delivery, native sequence and original bytes."""
        return ":".join(
            (
                "live-trades",
                self._request_identity,
                str(row.position),
                str(row.epoch),
                str(record.received_ns),
                delivery_at.isoformat(),
                str(row.sequence) if row.sequence is not None else "unknown",
                hashlib.sha256(record.raw).hexdigest(),
            )
        )

    @staticmethod
    def _tape(book: NativeBook) -> TradeTape:
        """Require the replay's native state to be a trade tape."""
        if not isinstance(book, TradeTape):
            raise TypeError("live trade source requires a trade tape")
        return book

    @staticmethod
    def _order(item: _TapeTrade) -> tuple[datetime, datetime, int, int]:
        """Select the latest venue time, then delivery, then message position and index."""
        return item.event_at, item.available_at, item.position, item.index

    @staticmethod
    def _signed(trade: PublicTrade) -> Fraction:
        """Sign a trade's quantity by its aggressor side."""
        quantity = Fraction(trade.quantity)
        return quantity if trade.side == "buy" else -quantity

    @staticmethod
    def _from_ns(ns: int) -> datetime:
        """Round a Unix-nanosecond receipt up so no value is available early."""
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=(ns + 999) // 1000)

    @staticmethod
    def _from_ms(ms: int) -> datetime:
        """Retain an exchange millisecond clock without float conversion."""
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)
