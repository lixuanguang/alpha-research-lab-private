"""Bind durably reconstructed public books to bounded live decision inputs."""

from __future__ import annotations

# standard library imports
import hashlib
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction

# project library imports
from financial_units import ExactRatio
from market_data.books import BookDepth, VisibleBook
from market_data.contracts import BookObservation, BookQuote, CaptureRecord, CaptureRequest
from research.observations.inputs import DecisionInputs, InputRequirement, NamedObservation
from serialization import DomainCodec


@dataclass(frozen=True, slots=True)
class _LiveBoundary:
    """Keep one delivery boundary and its last admitted economic observation."""

    available_at: datetime
    observation: NamedObservation
    book: BookObservation | None
    market_progress_at: datetime | None


class LiveBookDecisionSource:
    """Project one captured OKX or Bitfinex book into an incremental named source.

    The caller durably appends a ``CaptureRecord``, applies it to ``CaptureReplay``
    and passes its ``BookProjection.capture`` result with actual delivery time.
    A new recording with the same subscription keeps this source identity but
    starts unsynchronized. Exact old decisions require the retained delivery
    times as well as the original journal; the journal alone records receipt.
    """

    def __init__(
        self,
        request: CaptureRequest,
        requirement: InputRequirement,
        *,
        history_capacity: int,
    ) -> None:
        """Bind a stable subscription, named imbalance and finite causal read window.

        Args:
            request: Immutable source, instrument and recording identity.
            requirement: One exact book imbalance with a supported source clock.
            history_capacity: Maximum retained receipt boundaries, from 1 to 10000.
        """
        request.__post_init__()
        requirement.__post_init__()
        config = request.config
        if (
            config.venue not in ("okx", "bitfinex")
            or (config.venue == "okx" and config.channel != "books")
            or (config.venue == "bitfinex" and config.channel != "R0")
        ):
            raise ValueError("live decision source requires supported public spot books")
        if (
            requirement.family != "book"
            or requirement.clock
            not in (("event", "receipt") if config.venue == "okx" else ("receipt",))
            or requirement.field.name != "imbalance"
            or requirement.field.units != "dimensionless"
        ):
            raise ValueError("unsupported live book decision projection")
        if type(history_capacity) is not int or not 1 <= history_capacity <= 10_000:
            raise ValueError("live history capacity must be within 1..10000")
        self._request = request
        self._requirement = requirement
        self._history: deque[_LiveBoundary] = deque(maxlen=history_capacity)
        self._identity = hashlib.sha256(
            DomainCodec().encode_json(
                (
                    request.config,
                    request.implementation_identity,
                    request.universes,
                    requirement,
                    history_capacity,
                )
            )
        ).hexdigest()
        self._position = 0
        self._last_received_ns = 0
        self._last_available_at: datetime | None = None
        self._last_sequence: int | None = None
        self._latest_book: BookObservation | None = None
        self._market_lineage: str | None = None
        self._last_decision_at: datetime | None = None
        self._last_decision: DecisionInputs | None = None
        self._last_decision_book: BookObservation | None = None

    @property
    def request(self) -> CaptureRequest:
        """Expose the immutable admitted recording for connected per-venue consumers."""
        return self._request

    @property
    def identity(self) -> str:
        """Identify the stable live subscription and projection across recordings."""
        return self._identity

    @property
    def requirements(self) -> tuple[InputRequirement, ...]:
        """Expose the single exact book field and source freshness contract."""
        return (self._requirement,)

    @property
    def latest_book(self) -> BookObservation | None:
        """Expose the latest validated market state for current-state inspection.

        Use ``book_at`` to price a decision: this property does not establish
        freshness or bind the state to a historical decision cutoff.
        """
        return self._latest_book

    def book_at(self, entity: str, at: datetime) -> BookObservation | None:
        """Return the canonical book only when the frozen decision admits its value.

        Args:
            entity: Canonical instrument identity bound to this live source.
            at: Same UTC cutoff used for the named decision input.

        Returns:
            Validated original market row, or None when missing, stale or unbound.
        """
        self.read(entity, at)
        return (
            self._last_decision_book if entity == str(self._request.config.instrument_id) else None
        )

    def current_book(self, entity: str, at: datetime) -> BookObservation | None:
        """Inspect the latest delivered book without freezing a decision cutoff.

        Two market messages delivered in one UTC microsecond can both be observed
        by their collector callback. ``read`` and ``book_at`` retain the first
        frozen decision at that cutoff.

        Args:
            entity: Canonical instrument selected by the current capture.
            at: UTC cutoff at or after this boundary's actual delivery.

        Returns:
            Current canonical market row only while its source and local progress
            satisfy the selected freshness policy.
        """
        DecisionInputs._require_utc(at, field_name="at")
        if type(entity) is not str or not entity.strip():
            raise ValueError("live decision requires an entity")
        if entity != str(self._request.config.instrument_id) or not self._history:
            return None
        boundary = self._history[-1]
        if boundary.available_at > at or boundary.book is None or self._refusal(boundary, at):
            return None
        return boundary.book

    def current_quote(self, entity: str, at: datetime) -> BookQuote | None:
        """Expose the latest causally eligible book with its original market delivery time."""
        book = self.current_book(entity, at)
        if book is None:
            return None
        market_available_at = self._history[-1].observation.available_at
        if market_available_at is None:
            raise ValueError("current market book lacks its original delivery time")
        elapsed = market_available_at - datetime(1970, 1, 1, tzinfo=UTC)
        available_ns = (
            elapsed.days * 86_400 + elapsed.seconds
        ) * 1_000_000_000 + elapsed.microseconds * 1_000
        config = self._request.config
        return BookDepth.from_observation(book).quote(
            book,
            venue=config.venue,
            instrument_id=config.instrument_id,
            source_id=self._request.identity,
            channel=config.channel,
            available_ns=available_ns,
        )

    def accept(
        self,
        record: CaptureRecord,
        row: BookObservation,
        *,
        available_at: datetime | None = None,
    ) -> None:
        """Advance exactly one original durable message and canonical quality boundary.

        Args:
            record: Whole persisted source message, including session transitions.
            row: Canonical state immediately after applying this exact message.
            available_at: Actual UTC delivery to this source after durable apply. Omit
                only for deterministic saved reconstruction that explicitly uses receipt.

        Raises:
            ValueError: Positions, clocks or provenance do not match this stream.
        """
        record.__post_init__()
        row.__post_init__()
        self._accept_validated(record, row, available_at=available_at)

    def _accept_validated(
        self,
        record: CaptureRecord,
        row: BookObservation,
        *,
        available_at: datetime | None,
    ) -> None:
        """Advance a complete boundary already checked by LiveBookDelivery."""
        if (
            row.position != self._position
            or row.epoch != record.epoch
            or row.received_ns != record.received_ns
            or record.received_ns < self._last_received_ns
        ):
            raise ValueError("live book boundary differs from ordered original receipt")
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
        lineage = self._lineage(record, row, delivered_at)
        projection_available_at = delivered_at
        market_progress_at: datetime | None = None
        valid_market = (
            row.status == "degraded"
            and row.outcome in ("snapshot", "update")
            and self._has_two_sided_book(row)
        )
        has_market_value = False
        if valid_market:
            event_at = received_at
            reason = "visible_depth_only;recorder_coverage_unproven"
            if self._requirement.clock == "event":
                if row.source_time is None or not row.source_time.isdigit():
                    reason = "unknown_source_event_time"
                else:
                    event_at = self._from_ms(int(row.source_time))
            if reason != "unknown_source_event_time":
                self._latest_book = row
                self._market_lineage = lineage
                market_progress_at = min(received_at, event_at)
                has_market_value = True
            else:
                self._latest_book = None
                self._market_lineage = None
        elif (
            row.status == "degraded"
            and row.outcome in ("control", "heartbeat", "duplicate")
            and self._latest_book is not None
            and self._latest_book.epoch == row.epoch
            and (
                self._latest_book.state_identity == row.state_identity
                or self._unchanged_bitfinex_boundary(record, row)
            )
            and self._history
            and self._market_lineage is not None
        ):
            previous = self._history[-1].observation
            event_at, reason = previous.event_at, previous.reason
            lineage = f"{self._market_lineage}|{lineage}"
            projection_available_at = previous.available_at or delivered_at
            market_progress_at = self._history[-1].market_progress_at
            has_market_value = self._history[-1].book is not None
        else:
            self._latest_book = None
            self._market_lineage = None
            event_at = received_at
            reason = (
                f"{row.status}:{row.reason}"
                if row.status != "degraded"
                else "invalid_book_or_unsynchronized"
            )
        observation = NamedObservation(
            input=self._requirement,
            entity=str(self._request.config.instrument_id),
            event_at=event_at,
            available_at=projection_available_at,
            value=None,
            reason=reason,
            lineage=lineage,
        )
        self._history.append(
            _LiveBoundary(
                available_at=delivered_at,
                observation=observation,
                book=self._latest_book if has_market_value else None,
                market_progress_at=market_progress_at,
            )
        )
        self._position += 1
        self._last_received_ns = record.received_ns
        self._last_available_at = delivered_at
        self._last_sequence = row.sequence

    def _unchanged_bitfinex_boundary(self, record: CaptureRecord, row: BookObservation) -> bool:
        """Prove a sequenced heartbeat/control changed no retained visible L3 order."""
        market = self._latest_book
        if (
            self._request.config.venue != "bitfinex"
            or record.kind != "frame"
            or row.outcome not in ("heartbeat", "control", "duplicate")
            or market is None
            or market.sequence is None
            or self._last_sequence is None
            or row.sequence != self._last_sequence + (1 if row.outcome == "heartbeat" else 0)
            or row.source_time != market.source_time
            or row.orders
            or row.bids
            or row.asks
        ):
            return False
        visible = VisibleBook(self._request.config.max_orders)
        try:
            for order in market.orders:
                visible.set(order)
        except ValueError:
            return False
        visible.ready = True
        visible.sequence = market.sequence
        if market.state_identity != visible.identity:
            return False
        visible.sequence = row.sequence
        return row.state_identity == visible.identity

    def read(self, entity: str, at: datetime) -> DecisionInputs:
        """Freeze one then-known projection, preserving invalidation and event age.

        Equal cutoffs return the first frozen decision even if more messages arrive.
        Older cutoffs cannot be reopened after a newer live decision. Replaying the
        durable journal plus retained delivery times into a fresh source is the
        explicit reconstruction mechanism for an old recording.

        Args:
            entity: Canonical instrument identity selected by the capture request.
            at: UTC decision cutoff at which source and market-progress age are tested.

        Returns:
            One immutable exact observation or an explicit missing/stale reason.
        """
        DecisionInputs._require_utc(at, field_name="at")
        if type(entity) is not str or not entity.strip():
            raise ValueError("live decision requires an entity")
        if entity != str(self._request.config.instrument_id):
            return self._missing(entity, at, "entity_unbound", self._identity)
        if self._last_decision_at is not None:
            if at < self._last_decision_at:
                raise ValueError("live decision cutoff cannot move backwards")
            if at == self._last_decision_at and self._last_decision is not None:
                return self._last_decision
        selected = next((item for item in reversed(self._history) if item.available_at <= at), None)
        if selected is None:
            decision = self._missing(entity, at, "no_live_input", self._identity)
        else:
            row = selected.observation
            refusal = self._refusal(selected, at)
            if refusal is not None:
                decision = self._missing(
                    entity,
                    at,
                    refusal,
                    row.lineage,
                    row if refusal != "future_source_event" else None,
                )
            else:
                value = None if selected.book is None else self._book_value(selected.book)
                projected = (
                    row
                    if value is None
                    else NamedObservation(
                        input=row.input,
                        entity=row.entity,
                        event_at=row.event_at,
                        available_at=row.available_at,
                        value=value,
                        reason=row.reason,
                        lineage=row.lineage,
                    )
                )
                decision = DecisionInputs(entity=entity, decision_at=at, observations=(projected,))
        self._last_decision_at, self._last_decision = at, decision
        self._last_decision_book = (
            selected.book
            if selected is not None and decision.observations[0].value is not None
            else None
        )
        return decision

    def _refusal(self, selected: _LiveBoundary, at: datetime) -> str | None:
        """Apply identical future/source/local-progress rules to reads and live views."""
        row = selected.observation
        if row.event_at > at:
            return "future_source_event"
        if selected.book is None:
            return None
        if at - row.event_at > timedelta(microseconds=self._requirement.max_age_us):
            return "stale_input"
        if selected.market_progress_at is not None and at - selected.market_progress_at > timedelta(
            seconds=self._request.config.idle_seconds
        ):
            return "stale_market_progress"
        return None

    def _missing(
        self,
        entity: str,
        at: datetime,
        reason: str,
        lineage: str,
        selected: NamedObservation | None = None,
    ) -> DecisionInputs:
        """Construct one explicit absent value without changing its source identity."""
        row = NamedObservation(
            input=self._requirement,
            entity=entity,
            event_at=at if selected is None else selected.event_at,
            available_at=None if selected is None else selected.available_at,
            value=None,
            reason=reason,
            lineage=lineage,
        )
        return DecisionInputs(entity=entity, decision_at=at, observations=(row,))

    def _lineage(self, record: CaptureRecord, row: BookObservation, delivery_at: datetime) -> str:
        """Bind receipt, delivery, native clocks, quality and original bytes."""
        return ":".join(
            (
                "live-book",
                self._request.identity,
                str(row.position),
                str(row.epoch),
                str(record.received_ns),
                delivery_at.isoformat(),
                row.source_time or "unknown",
                str(row.sequence) if row.sequence is not None else "unknown",
                row.status,
                row.reason,
                row.state_identity,
                hashlib.sha256(record.raw).hexdigest(),
            )
        )

    @staticmethod
    def _has_two_sided_book(row: BookObservation) -> bool:
        """Check visible touch eligibility before deferring exact depth arithmetic."""
        if row.orders:
            bid = max((order.price for order in row.orders if order.side == "buy"), default=None)
            ask = min((order.price for order in row.orders if order.side == "sell"), default=None)
        else:
            bid = max((price for price, _ in row.bids), default=None)
            ask = min((price for price, _ in row.asks), default=None)
        return bid is not None and ask is not None and bid < ask

    @staticmethod
    def _book_value(row: BookObservation) -> ExactRatio | None:
        """Calculate exact visible imbalance for L2 levels or native L3 orders."""
        depth = BookDepth.from_observation(row)
        bids = depth.bids
        asks = depth.asks
        if (
            not bids
            or not asks
            or max(price for price, _ in bids) >= min(price for price, _ in asks)
        ):
            return None
        bid_size = sum((Fraction(level.size) for _, level in bids), Fraction())
        ask_size = sum((Fraction(level.size) for _, level in asks), Fraction())
        return ExactRatio.from_fraction((bid_size - ask_size) / (bid_size + ask_size))

    @staticmethod
    def _from_ns(ns: int) -> datetime:
        """Round a Unix-nanosecond receipt up so no value is available early."""
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=(ns + 999) // 1000)

    @staticmethod
    def _from_ms(ms: int) -> datetime:
        """Retain an exchange millisecond clock without float conversion."""
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)
