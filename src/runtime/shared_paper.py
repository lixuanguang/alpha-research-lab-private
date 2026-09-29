"""Deliver retained native books to existing shared decisions and paper accounting."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

# project library imports
from configuration import BookKey, PaperExecutionScenario
from execution import AccountControl, AccountQuote, PaperAccount, PaperMarket, PortfolioCommit
from financial_units import Price, Quantity
from market_data.books import BookAsOfIndex, BookDepth, BookRegistry
from market_data.contracts import BookObservation, CaptureRecord
from research.observations import DecisionInputs, LiveBookDecisionSource
from runtime.live_paper import LiveBookDelivery
from runtime.portfolio import SharedDecisionRuntime, SharedStrategyInput
from serialization import DomainCodec, WireRecord
from telemetry import RuntimeMeasurementJournal


class SharedBookInputs(Protocol):
    """Build selected policy inputs from a causal native book projection.

    Implementations must be pure for the supplied inputs and pin their complete
    feature/model parameters in ``identity``. Policy state belongs to the shared
    decision runtime. A candidate feature/model adapter may implement this API;
    the adapter cannot approve risk or replace the independently observed quote.
    """

    @property
    def identity(self) -> str:
        """Identify the installed feature/model binding and all selected parameters."""
        ...

    def build(self, inputs: DecisionInputs, market: PaperMarket) -> tuple[SharedStrategyInput, ...]:
        """Return causal contexts at the input cutoff, with an ask-valued account quote."""
        ...


class SharedBookDelivery(WireRecord, frozen=True):
    """Retain original source clocks and the exact policy inputs before account effects."""

    source: LiveBookDelivery
    inputs: tuple[SharedStrategyInput, ...]
    coordinated_at: datetime | None
    schema_version: str = "shared-book-delivery"
    market_effects: bool = True

    def __post_init__(self) -> None:
        """Reject unbound policy clocks or partial coordination envelopes."""
        LiveBookDelivery.__post_init__(self.source)
        self._require_coordination()

    def _require_coordination(self) -> None:
        """Validate newly constructed selection and coordination after native validation."""
        if self.schema_version != "shared-book-delivery" or type(self.inputs) is not tuple:
            raise ValueError("invalid shared book delivery")
        if type(self.market_effects) is not bool:
            raise ValueError("invalid shared market selection")
        if self.market_effects is False and (self.inputs or self.coordinated_at is not None):
            raise ValueError("unselected market cannot coordinate decisions")
        if self.inputs:
            if self.coordinated_at is None:
                raise ValueError("shared delivery requires coordination time")
            self._require_utc(self.coordinated_at, field_name="shared book coordination")
            if self.coordinated_at <= self.source.available_at:
                raise ValueError("coordination must follow delivered inputs")
        elif self.coordinated_at is not None:
            raise ValueError("empty shared delivery cannot coordinate")
        for item in self.inputs:
            item.__post_init__()
            if item.context.decision_at != self.source.available_at:
                raise ValueError("shared input cutoff differs from actual delivery")


class _ObservedLiveBookDelivery(LiveBookDelivery, frozen=True):
    """Wrap validated source records while checking the new actual availability clock."""

    def __post_init__(self) -> None:
        """Rely on the typed pipe or public observe boundary for native validation."""
        self._require_availability()


class _ObservedSharedBookDelivery(SharedBookDelivery, frozen=True):
    """Coordinate validated native inputs without changing the retained wire schema."""

    def __post_init__(self) -> None:
        """Check only the new availability, policy and coordination invariants."""
        self.source._require_availability()
        self._require_coordination()


class SharedPaperCaptureObserver:
    """Match existing orders before decisions on selected eligible books.

    Native reconstruction, freshness and control invalidation remain owned by
    ``LiveBookDecisionSource`` and ``BookRegistry``. The append-only delivery log
    is fsynced before effects; replay uses its original clocks and exact contexts.
    An optional market interval defers account effects without dropping native rows.
    A fresh observer rebuilds source state from the beginning of its recording.
    Account transactions and policy retry identities survive process restart.
    """

    def __init__(
        self,
        *,
        source: LiveBookDecisionSource,
        books: BookRegistry,
        journal: PaperAccount,
        runtime: SharedDecisionRuntime,
        account_id: str,
        scenario: PaperExecutionScenario,
        inputs: SharedBookInputs,
        delivery_path: Path | None,
        clock: Callable[[], datetime] | None = None,
        market_interval_us: int = 0,
        measurements: RuntimeMeasurementJournal | None = None,
        index: BookAsOfIndex | None = None,
    ) -> None:
        """Bind explicit admitted owners and optional new-recording retention path."""
        scenario.__post_init__()
        request = source.request
        self._key = BookKey(venue=request.config.venue, instrument_id=request.config.instrument_id)
        selected = books.lookup(self._key, cutoff_ns=0).selection
        if (
            type(market_interval_us) is not int
            or market_interval_us < 0
            or market_interval_us
            > min(
                source.requirements[0].max_age_us,
                request.config.idle_seconds * 1_000_000,
            )
        ):
            raise ValueError("market interval exceeds source freshness or idle bound")
        if (
            scenario.venue != request.config.venue
            or scenario.instrument_id != request.config.instrument_id
            or selected.source_id != request.identity
            or selected.instrument.symbol != request.config.symbol
            or selected.instrument.product != "spot"
            or selected.instrument.base_currency != request.config.base_currency
            or selected.instrument.quote_currency != scenario.adverse.currency.code
            or selected.capability.channel != request.config.channel
            or not inputs.identity
            or runtime.journal is not journal
        ):
            raise ValueError("shared public paper binding differs from source or account")
        self.source, self.books, self.journal, self.runtime = source, books, journal, runtime
        self.account_id, self.scenario, self.inputs = account_id, scenario, inputs
        self.delivery_path = delivery_path
        self.index = index
        self._clock = clock
        self.market_interval_us = market_interval_us
        self.measurements = measurements
        self._last_effect_at: datetime | None = None
        self._codec = DomainCodec()
        self._retained_bytes = 0
        self._maximum_bytes = request.config.max_bytes * 4
        self.decisions: list[PortfolioCommit] = []
        self.processing_ns: int | None = None
        self.delivered_count = 0
        self.retained_count = 0
        self._public_faulted = False
        self._ineligible_book = False
        self.last_market: PaperMarket | None = None
        journal.bind_paper_scenario(account_id, scenario)

    def observe(self, record: CaptureRecord, row: BookObservation) -> None:
        """Retain actual post-persistence availability and coordination before effects."""
        record.__post_init__()
        BookObservation.__post_init__(row)
        self._observe_validated(record, row)

    def _observe_validated(self, record: CaptureRecord, row: BookObservation) -> None:
        """Consume native invariants checked by public observe or typed pipe decoding."""
        book_started_ns = time.monotonic_ns() if self.measurements is not None else 0
        source = _ObservedLiveBookDelivery(record=record, book=row, available_at=self._now())
        market = self._market(source)
        bbo_observed_ns = time.monotonic_ns() if self.measurements is not None else 0
        market_effects = market is not None and self._select_market(market.at)
        selected: tuple[SharedStrategyInput, ...] = ()
        if market_effects and market is not None:
            causal = self.source.read(str(self.scenario.instrument_id), source.available_at)
            selected = self.inputs.build(causal, market)
        delivery = _ObservedSharedBookDelivery(
            source=source,
            inputs=selected,
            coordinated_at=self._coordination_time(source.available_at) if selected else None,
            market_effects=market is None or market_effects,
        )
        offset, length = self._retain(delivery)
        if self.index is not None:
            latest = self.books.latest(self._key)
            if latest is None:
                raise ValueError("retained delivery has no accepted book boundary")
            self.index.append(*latest, offset=offset, length=length)
        started_ns = time.monotonic_ns()
        prior_decisions = len(self.decisions)
        try:
            self._apply(delivery, market)
        finally:
            finished_ns = time.monotonic_ns()
            self.processing_ns = finished_ns - started_ns
            self.delivered_count += 1
            if self.measurements is not None:
                acknowledged = len(self.decisions) > prior_decisions
                self.measurements.record(
                    {
                        "kind": "paper_book",
                        "position": row.position,
                        "outcome": row.outcome,
                        "market_eligible": market is not None,
                        "market_selected": market_effects,
                        "policy_selected": bool(selected),
                        "checkpoint_acknowledged": acknowledged,
                        "checkpoint_status": self.decisions[-1].status if acknowledged else None,
                        "book_started_ns": book_started_ns,
                        "bbo_observed_ns": bbo_observed_ns,
                        "checkpoint_acknowledged_ns": finished_ns if acknowledged else None,
                        "book_to_checkpoint_ns": (
                            finished_ns - book_started_ns if acknowledged else None
                        ),
                    }
                )

    def deliver(self, delivery: SharedBookDelivery) -> None:
        """Replay one retained envelope into a fresh source and an existing account journal."""
        SharedBookDelivery.__post_init__(delivery)
        market = self._market(delivery.source)
        self._apply(delivery, market)

    def _select_market(self, at: datetime) -> bool:
        """Select the first eligible book and then only books at the declared interval."""
        return self._last_effect_at is None or at - self._last_effect_at >= timedelta(
            microseconds=self.market_interval_us
        )

    def _market(self, delivery: LiveBookDelivery) -> PaperMarket | None:
        """Advance native quality before exposing finite eligible displayed touch liquidity."""
        self.source._accept_validated(
            delivery.record, delivery.book, available_at=delivery.available_at
        )
        elapsed = delivery.available_at - datetime(1970, 1, 1, tzinfo=UTC)
        available_ns = (
            elapsed.days * 86_400 + elapsed.seconds
        ) * 1_000_000_000 + elapsed.microseconds * 1000
        request = self.source.request
        self.books.accept(
            BookDepth._touch_quote_validated(
                delivery.book,
                venue=request.config.venue,
                instrument_id=request.config.instrument_id,
                source_id=request.identity,
                channel=request.config.channel,
                available_ns=available_ns,
            )
        )
        if (
            delivery.book.outcome not in ("snapshot", "update")
            or self.source.current_book(str(self.scenario.instrument_id), delivery.available_at)
            is None
        ):
            return None
        quote = self.books.lookup(self._key, cutoff_ns=available_ns).quote
        if quote is None or quote.market_state != "two_sided":
            return None
        bid, ask = quote.bid, quote.ask
        if bid is None or ask is None:
            return None
        dimension, currency = self.scenario.adverse.per, self.scenario.adverse.currency
        return PaperMarket(
            identity=hashlib.sha256(self._codec.encode_json(delivery)).hexdigest(),
            at=delivery.available_at,
            bid=Price(value=bid.price, currency=currency, per=dimension),
            ask=Price(value=ask.price, currency=currency, per=dimension),
            bid_quantity=Quantity(value=bid.quantity, dimension=dimension),
            ask_quantity=Quantity(value=ask.quantity, dimension=dimension),
        )

    def _apply(self, delivery: SharedBookDelivery, market: PaperMarket | None) -> None:
        """Validate retained feature lineage and compose existing atomic public operations."""
        if market is None:
            if delivery.market_effects is False:
                raise ValueError("ineligible native input cannot skip market effects")
            if delivery.inputs:
                raise ValueError("ineligible native input cannot produce shared decisions")
            if not self._public_faulted and self._source_invalidated(delivery):
                if self.journal.paper_owner is None:
                    self.journal.block(self.account_id, "public_input_invalid")
                else:
                    result = self.journal.control(
                        AccountControl(
                            identity="public-input-fault:"
                            + hashlib.sha256(self._codec.encode_json(delivery.source)).hexdigest(),
                            account_id=self.account_id,
                            kind="fault",
                            at=delivery.source.available_at,
                            reason="public_input_invalid",
                        )
                    )
                    if result.status != "applied" or result.phase != "faulted":
                        raise ValueError("public input fault was not applied")
                self._public_faulted = True
            return
        self._ineligible_book = False
        if delivery.market_effects is False:
            self.last_market = market
            return
        causal = self.source.read(str(self.scenario.instrument_id), market.at)
        quote = AccountQuote(price=market.ask, at=market.at)
        for item in delivery.inputs:
            if item.quote != quote or item.context.features.input_identity != causal.identity:
                raise ValueError("shared decision substituted native quote or input lineage")
        if not self.journal.paper_market_seen(self.account_id, market.identity):
            self.journal.observe(quote)
        if self.journal.config.mode == "paper":
            self.journal.match_public_market(self.account_id, market, self.scenario)
        self.last_market = market
        self._last_effect_at = market.at
        if delivery.inputs and delivery.coordinated_at is not None:
            self.decisions.append(
                self.runtime.evaluate(
                    identity=hashlib.sha256(self._codec.encode_json(delivery)).hexdigest(),
                    at=delivery.coordinated_at,
                    inputs=delivery.inputs,
                )
            )

    def _source_invalidated(self, delivery: SharedBookDelivery) -> bool:
        """Separate loss after a priced book from harmless controls and finite completion."""
        if self.last_market is None:
            return False
        record = delivery.source.record
        freshness = min(
            timedelta(microseconds=self.source.requirements[0].max_age_us),
            timedelta(seconds=self.source.request.config.idle_seconds),
        )
        if record.kind in ("session_end", "end") and record.reason in (
            "duration_limit",
            "message_limit",
            "supervisor_stop",
        ):
            return delivery.source.available_at - self.last_market.at > freshness
        if self._transiently_ineligible(delivery):
            # Per-order feeds split one atomic venue change into many messages, so a
            # valid book can be one-sided or crossed between them. Such a book is
            # never priced; it faults only if no eligible market follows in time.
            return delivery.source.available_at - self.last_market.at > freshness
        current = self.source.current_quote(
            str(self.scenario.instrument_id), delivery.source.available_at
        )
        return current is None or delivery.source.book.outcome in ("snapshot", "update")

    def _transiently_ineligible(self, delivery: SharedBookDelivery) -> bool:
        """Track a valid unpriceable book and the healthy controls that follow it."""
        book = delivery.source.book
        if delivery.source.record.kind != "frame" or book.status != "degraded":
            self._ineligible_book = False
        elif book.outcome in ("snapshot", "update"):
            self._ineligible_book = not LiveBookDecisionSource._has_two_sided_book(book)
        elif book.outcome not in ("heartbeat", "control"):
            self._ineligible_book = False
        return self._ineligible_book

    def _coordination_time(self, available_at: datetime) -> datetime:
        """Observe an actual strictly later UTC clock within a bounded read budget."""
        for _ in range(64):
            at = self._now()
            SharedBookDelivery._require_utc(at, field_name="shared book coordination")
            if at > available_at:
                return at
        raise ValueError("paper coordination clock did not advance beyond input delivery")

    def _now(self) -> datetime:
        """Read the injected or system UTC clock without inventing a future instant."""
        return datetime.now(UTC) if self._clock is None else self._clock()

    def _retain(self, delivery: SharedBookDelivery) -> tuple[int, int]:
        """Persist bounded replay bytes before changing state; return their byte range."""
        if self.delivery_path is None:
            raise ValueError("live shared paper requires a retained delivery path")
        payload = self._codec.encode_json(delivery) + b"\n"
        if self._retained_bytes + len(payload) > self._maximum_bytes:
            raise ValueError("shared paper delivery retention exceeded configured bound")
        with self.delivery_path.open("ab") as stream:
            offset = stream.seek(0, os.SEEK_END)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        self._retained_bytes += len(payload)
        self.retained_count += 1
        return offset, len(payload)
