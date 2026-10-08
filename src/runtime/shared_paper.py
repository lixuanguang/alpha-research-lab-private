"""Deliver retained native books to existing shared decisions and paper accounting."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Self

# third party library imports
import msgspec

# project library imports
from configuration import BookKey, PaperExecutionScenario
from execution import (
    AccountControl,
    AccountQuote,
    MarketTouch,
    PaperAccount,
    PaperMarket,
    PortfolioCommit,
)
from financial_units import Price, Quantity
from market_data.books import BookAsOfIndex, BookDepth, BookRegistry
from market_data.contracts import BookObservation, CaptureRecord
from research.observations import (
    DecisionInputs,
    DecisionSource,
    LiveBookDecisionSource,
    LiveTradeDecisionSource,
)
from runtime.feature_feed import ServedFeature, ServedFeatures
from runtime.live_inputs import LiveInputs
from runtime.live_paper import LiveBookDelivery
from runtime.portfolio import SharedDecisionRuntime, SharedStrategyBinding, SharedStrategyInput
from serialization import DomainCodec, WireRecord
from telemetry import RuntimeMeasurementJournal


class SharedDecisionGroup(WireRecord, frozen=True):
    """Retain one grid instant's causal inputs, observed quote and coordination clock.

    Coordination is the logical boundary at which the account learns the decision,
    one microsecond after the decision was known and after the previous group's
    coordination. Source-fed inputs are known at the instant: such a group is
    quoted at the latest market before its deciding delivery and coordinates before
    that delivery, whose book then matches it. A served snapshot is known only when
    the deciding delivery reads it: such a group is quoted at the latest market
    including that delivery's and coordinates after the delivery, so only a later
    book matches it. The account dates each decision one microsecond before its
    coordination.
    """

    at: datetime
    quote: AccountQuote
    touch: MarketTouch
    inputs: tuple[SharedStrategyInput, ...]
    coordinated_at: datetime

    def __post_init__(self) -> None:
        """Bind every input and the quote to this instant, before its coordination."""
        self._require_utc(self.at, field_name="shared decision instant")
        self._require_utc(self.coordinated_at, field_name="shared book coordination")
        if type(self.quote) is not AccountQuote or type(self.touch) is not MarketTouch:
            raise TypeError("shared decision group requires an account quote and touch")
        self.quote.__post_init__()
        self.touch.__post_init__()
        if type(self.inputs) is not tuple or not self.inputs:
            raise ValueError("shared decision group requires inputs")
        if self.quote.at >= self.coordinated_at or self.coordinated_at < self.at + timedelta(
            microseconds=1
        ):
            raise ValueError("shared decision quote or coordination clock is out of order")
        for item in self.inputs:
            if type(item) is not SharedStrategyInput:
                raise TypeError("shared decision group requires SharedStrategyInput")
            item.__post_init__()
            if item.decision_at != self.at or item.quote != self.quote or item.touch != self.touch:
                raise ValueError("shared input cutoff or quote differs from its instant")


class SharedBookDelivery(WireRecord, frozen=True):
    """Retain original source clocks, decided grid instants and account matching.

    Groups follow in coordination order: source-fed groups before the delivery,
    then served groups after it. ``matched`` marks every eligible priced book, a
    snapshot or update with a fresh two-sided touch; so a book that decides a
    source-fed instant always matches. A clock, heartbeat or control may decide
    without matching.
    """

    source: LiveBookDelivery
    decisions: tuple[SharedDecisionGroup, ...]
    matched: bool
    schema_version: Literal["shared-eligible-book-delivery"] = "shared-eligible-book-delivery"

    def __post_init__(self) -> None:
        """Reject unbound decision clocks or out-of-order coordination envelopes."""
        self._require_schema()
        LiveBookDelivery.__post_init__(self.source)
        self._require_coordination()

    @classmethod
    def decode(cls, payload: bytes, codec: DomainCodec) -> Self:
        """Decode one retained delivery line, refusing another format by its tag first.

        The tag is read before any other field, so a line in an earlier layout is
        refused as unsupported rather than as whichever field first fails to decode.

        Args:
            payload: One complete UTF-8 JSON delivery line, without its newline.
            codec: The reader's strict domain codec.

        Returns:
            The delivery, with every native, decision and coordination check applied.

        Raises:
            ValueError: The line names another schema, or is malformed or inconsistent.
        """
        if msgspec.json.decode(payload, type=_RetainedDeliverySchema).schema_version != (
            "shared-eligible-book-delivery"
        ):
            raise ValueError("unsupported shared book delivery schema")
        return codec.decode_json(payload, cls)

    def _require_schema(self) -> None:
        """Refuse any other retained delivery format before validating its content."""
        if self.schema_version != "shared-eligible-book-delivery":
            raise ValueError("unsupported shared book delivery schema")

    def _require_coordination(self) -> None:
        """Validate decisions and coordination after native validation."""
        if type(self.decisions) is not tuple or type(self.matched) is not bool:
            raise ValueError("unsupported shared book delivery schema")
        previous: datetime | None = None
        instants: dict[bool, datetime] = {}
        for group in self.decisions:
            if type(group) is not SharedDecisionGroup:
                raise TypeError("shared delivery requires decision groups")
            group.__post_init__()
            served = group.coordinated_at > self.source.available_at
            if (
                group.at >= self.source.available_at
                or (previous is not None and group.coordinated_at <= previous)
                or (served in instants and group.at <= instants[served])
                or any((item.served is not None) != served for item in group.inputs)
            ):
                raise ValueError("shared decision instants must precede their delivery in order")
            previous, instants[served] = group.coordinated_at, group.at
        priced = self.source.book.outcome in ("snapshot", "update")
        if (False in instants and priced and not self.matched) or (self.matched and not priced):
            raise ValueError("a book that decides an instant matches; only books match")


class ObservedLiveBookDelivery(LiveBookDelivery, frozen=True):
    """Wrap validated source records while checking the new actual availability clock."""

    def __post_init__(self) -> None:
        """Rely on the typed pipe or public observe boundary for native validation."""
        self._require_availability()


class ObservedSharedBookDelivery(SharedBookDelivery, frozen=True):
    """Coordinate validated native inputs without changing the retained wire schema."""

    def __post_init__(self) -> None:
        """Check only the new availability, decision and coordination invariants."""
        self._require_schema()
        self.source._require_availability()
        self._require_coordination()


class _RetainedDeliverySchema(msgspec.Struct, frozen=True):
    """Read only a retained delivery line's format tag; other fields are not decoded."""

    schema_version: object = None


class RetainedLiveBookDelivery(msgspec.Struct, frozen=True, kw_only=True):
    """Encode ``LiveBookDelivery`` around row bytes the live source already encoded."""

    record: CaptureRecord
    book: msgspec.Raw
    available_at: datetime


class RetainedSharedBookDelivery(msgspec.Struct, frozen=True, kw_only=True):
    """Encode ``SharedBookDelivery`` with the same fields; the sorted encoder fixes order."""

    source: RetainedLiveBookDelivery
    decisions: tuple[SharedDecisionGroup, ...]
    matched: bool
    schema_version: str


class _ProjectedRowObserver:
    """Feed rows the in-process capture runner has just constructed and validated.

    ``BookProjection.capture`` builds each row, which runs its full validation,
    and passes it straight to the observer; no other code holds it in between.
    """

    def __init__(self, observer: SharedPaperCaptureObserver) -> None:
        """Bind the shared observer that owns every downstream check."""
        self._observer = observer

    def observe(self, record: CaptureRecord, row: BookObservation) -> None:
        """Skip only the repeated native row validation."""
        self._observer._observe_validated(record, row)


class SharedPaperCaptureObserver:
    """Decide candidates on their UTC grids and match every eligible priced book.

    Native reconstruction, freshness and control invalidation remain owned by
    ``LiveBookDecisionSource`` and ``BookRegistry``. Each candidate decides at
    ``starts_at + k * cadence``. Time and market are separate axes. Any delivery
    advances the grid while the source's market is current: an eligible book, or a
    clock, heartbeat or control that leaves the retained market current. At the
    first such delivery after an instant, the instant opens if an eligible market at
    or before it exists, and the due candidates decide at that instant, quoted at
    that latest market. Every eligible book, a snapshot or update with a fresh
    two-sided touch, matches the account's open orders, whether they came from a
    decision, a direct admission, a reissue or a protective reduction; the
    scenario's entry and cancel delays alone decide which orders it can fill.
    Which books match depends only on the retained delivery stream, never on the
    destination journal. A clock, heartbeat or control never matches; between
    instants it updates monitoring only, unless it decides an awaited served
    instant. An instant without a fresh market or complete inputs
    is skipped, which the candidate's gap rule then governs. The fsynced
    delivery log retains decided inputs before effects; replay uses its clocks.
    A fresh observer rebuilds source state from the beginning of its recording.
    Account transactions and candidate retry identities survive process restart.

    With ``trades`` the same instrument's public trade tape is delivered through
    ``observe_trades`` and its fields join the book's in each candidate's inputs.
    Trade boundaries only update that source. Each is retained with its actual
    delivery time in the sibling ``.trades.jsonl`` log before it applies, so a
    replay interleaves both logs by delivery time and re-reads the same inputs.

    A feature-served candidate reads its pinned stream's snapshot exactly at each
    instant through ``features`` instead of the native sources. The snapshot is known
    only when a delivery reads it, so that decision coordinates after the delivery's
    match, quoted at the market known then, and only a later book can fill it. While the
    snapshot is ``feature-pending`` the instant stays open and is retried on each
    later delivery that advances the grid; it is skipped as
    ``feature-not-published`` when a delivery that opens the candidate's next
    instant cannot decide it either. Any other
    pause reason (missing, expired, future, changed version or unavailable service)
    skips the instant like missing inputs. Reasons are kept in ``feature_pauses``.
    The delivery log retains the served vector and the exact snapshot; replay
    reopens that snapshot, requires the same value, and recomputes coordination.
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
        delivery_path: Path | None,
        active: tuple[str, ...] | None = None,
        clock: Callable[[], datetime] | None = None,
        measurements: RuntimeMeasurementJournal | None = None,
        index: BookAsOfIndex | None = None,
        trades: LiveTradeDecisionSource | None = None,
        features: ServedFeatures | None = None,
    ) -> None:
        """Bind explicit admitted owners and optional new-recording retention path.

        ``active`` selects the deciding instances; every binding still sets the
        matching grid, so a stopped cohort keeps draining accepted obligations.
        """
        scenario.__post_init__()
        request = source.request
        self._key = BookKey(venue=request.config.venue, instrument_id=request.config.instrument_id)
        selected = books.lookup(self._key, cutoff_ns=0).selection
        if (
            scenario.venue != request.config.venue
            or scenario.instrument_id != request.config.instrument_id
            or selected.source_id != request.identity
            or selected.instrument.symbol != request.config.symbol
            or selected.instrument.product != "spot"
            or selected.instrument.base_currency != request.config.base_currency
            or selected.instrument.quote_currency != scenario.adverse.currency.code
            or selected.capability.channel != request.config.channel
            or runtime.journal is not journal
        ):
            raise ValueError("shared public paper binding differs from source or account")
        provided = set(source.requirements)
        if trades is not None:
            if trades.request.config.instrument_id != request.config.instrument_id:
                raise ValueError("shared trade feed names another instrument")
            provided |= set(trades.requirements)
        for binding in runtime.bindings:
            served = binding.candidate.deployment.input_mode == "online_features"
            if binding.entity != str(request.config.instrument_id) or (served and features is None):
                raise ValueError("shared candidate differs from its instrument or feature store")
            if not served and not set(binding.candidate.definition.inputs) <= provided:
                raise ValueError("shared candidate inputs differ from the native sources")
        self.source, self.books, self.journal, self.runtime = source, books, journal, runtime
        self.trades = trades
        self.features = features
        self.feature_pauses: dict[str, str] = {}
        self.trades_delivered = 0
        self.trades_path = (
            None
            if trades is None or delivery_path is None
            else delivery_path.with_name(delivery_path.stem + ".trades.jsonl")
        )
        self._trade_bytes = 0
        self._maximum_trade_bytes = 0 if trades is None else trades.request.recording_max_bytes * 4
        # The request is immutable; its identity hashes the encoded request.
        self._source_id = request.identity
        self.account_id, self.scenario = account_id, scenario
        self.active = (
            tuple(binding.instance_id for binding in runtime.bindings) if active is None else active
        )
        self.delivery_path = delivery_path
        self.index = index
        self._clock = clock
        self.measurements = measurements
        self._crossed: dict[str, datetime] = {}
        self._pending: PaperMarket | None = None
        # Each instance's open grid instants, ascending.
        self._open: dict[str, list[datetime]] = {}
        # The latest coordination; every later decision group coordinates after it.
        self._coordinated: datetime | None = None
        self._codec = DomainCodec()
        self._retained_bytes = 0
        self._maximum_bytes = request.recording_max_bytes * 4
        self.decisions: list[PortfolioCommit] = []
        self.processing_ns: int | None = None
        # Opt-in phase clocks for the delivery being measured; None when unmeasured.
        self._phases: dict[str, int] | None = None
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

    def observe_trades(self, record: CaptureRecord, row: BookObservation) -> None:
        """Advance the trade source by one durable boundary at its actual delivery.

        Raises:
            ValueError: The observer has no trade feed, or the boundary is out of order.
        """
        if self.trades is None or self.trades_path is None:
            raise ValueError("shared observer has no retained trade feed")
        delivery = LiveBookDelivery(record=record, book=row, available_at=self._now())
        payload = self._codec.encode_json(delivery) + b"\n"
        if self._trade_bytes + len(payload) > self._maximum_trade_bytes:
            raise ValueError("shared paper trade retention exceeded configured bound")
        with self.trades_path.open("ab") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        self._trade_bytes += len(payload)
        self.trades.accept(record, row, available_at=delivery.available_at)
        self.trades_delivered += 1

    def deliver_trades(self, delivery: LiveBookDelivery) -> None:
        """Replay one retained trade boundary at its original delivery time.

        Raises:
            ValueError: The observer has no trade feed, or the boundary is out of order.
        """
        if self.trades is None:
            raise ValueError("shared observer has no trade feed")
        LiveBookDelivery.__post_init__(delivery)
        self.trades.accept(delivery.record, delivery.book, available_at=delivery.available_at)
        self.trades_delivered += 1

    def projected_rows(self) -> _ProjectedRowObserver:
        """Return the observer for an in-process ``CaptureRunner`` in this process.

        Returns:
            An observer that trusts rows the runner has just projected and validated.
        """
        return _ProjectedRowObserver(self)

    def _observe_validated(
        self, record: CaptureRecord, row: BookObservation, *, received_ns: int | None = None
    ) -> None:
        """Consume native invariants checked by public observe or typed pipe decoding.

        ``received_ns`` is the supervisor's monotonic pipe receipt, retained only in
        opt-in measurements.
        """
        book_started_ns = time.monotonic_ns() if self.measurements is not None else 0
        self._phases = {} if self.measurements is not None else None
        source = ObservedLiveBookDelivery(record=record, book=row, available_at=self._now())
        market = self._market(source)
        bbo_observed_ns = time.monotonic_ns() if self.measurements is not None else 0
        timed = self._timed(source, market)
        if timed and self._crosses(source.available_at):
            self._open_crossed(source.available_at)
        groups = self._groups(source.available_at, market) if timed else ()
        delivery = ObservedSharedBookDelivery(
            source=source, decisions=groups, matched=market is not None
        )
        offset, length = self._retain(delivery, self._row_payload(row))
        if self.index is not None:
            latest = self.books.latest(self._key)
            if latest is None:
                raise ValueError("retained delivery has no accepted book boundary")
            self.index.append(*latest, offset=offset, length=length)
        started_ns = time.monotonic_ns()
        if self._phases is not None:
            self._phases["retained_ns"] = started_ns
        prior_decisions = len(self.decisions)
        try:
            self._apply(delivery, market, timed=timed, replayed=False)
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
                        "market_selected": delivery.matched,
                        "policy_selected": bool(groups),
                        "checkpoint_acknowledged": acknowledged,
                        "checkpoint_status": self.decisions[-1].status if acknowledged else None,
                        "checkpoint_reason": self.decisions[-1].reason if acknowledged else None,
                        "book_started_ns": book_started_ns,
                        "bbo_observed_ns": bbo_observed_ns,
                        "checkpoint_acknowledged_ns": finished_ns if acknowledged else None,
                        "book_to_checkpoint_ns": (
                            finished_ns - book_started_ns if acknowledged else None
                        ),
                        "pipe_received_ns": received_ns,
                        "phase_ns": self._phases,
                        "finished_ns": finished_ns,
                    }
                )
            self._phases = None

    def deliver(self, delivery: SharedBookDelivery) -> None:
        """Replay one retained envelope into a fresh source and an existing account journal."""
        SharedBookDelivery.__post_init__(delivery)
        market = self._market(delivery.source)
        timed = self._timed(delivery.source, market)
        if timed and self._crosses(delivery.source.available_at):
            self._open_crossed(delivery.source.available_at)
        if delivery.matched != (market is not None):
            raise ValueError("retained delivery matching differs from replayed book eligibility")
        self._apply(delivery, market, timed=timed, replayed=True)

    def _instant(self, binding: SharedStrategyBinding, before: datetime) -> datetime | None:
        """Return the binding's latest grid instant strictly before ``before``."""
        start = binding.candidate.deployment.starts_at
        if before <= start:
            return None
        cadence = timedelta(microseconds=binding.candidate.definition.cadence_us)
        return start + ((before - start - timedelta(microseconds=1)) // cadence) * cadence

    def _crosses(self, before: datetime) -> bool:
        """Advance every binding's grid and report whether any instant was crossed."""
        crossed = False
        for binding in self.runtime.bindings:
            instant = self._instant(binding, before)
            prior = self._crossed.get(binding.instance_id)
            if instant is not None and (prior is None or instant > prior):
                self._crossed[binding.instance_id] = instant
                crossed = True
        return crossed

    def _open_crossed(self, before: datetime) -> None:
        """Open each active binding's newly crossed instant that has a market by it.

        Opening depends only on the delivery stream, so replay into an existing
        journal reopens exactly the instants the live run opened.
        """
        pending = self._pending
        for binding in self.runtime.bindings:
            name = binding.instance_id
            instant = self._crossed.get(name)
            opened = self._open.get(name, [])
            if (
                instant is None
                or (opened and opened[-1] >= instant)
                or name not in self.active
                or pending is None
                or pending.at > instant
            ):
                continue
            self._open[name] = [*opened, instant]

    def _close_open(self) -> None:
        """End a delivery: only a served instance's latest crossed instant may stay open.

        An older awaited instant was superseded by its candidate's next instant before
        its snapshot was published, so it is skipped.
        """
        for binding in self.runtime.bindings:
            name = binding.instance_id
            opened = self._open.pop(name, [])
            if binding.candidate.deployment.input_mode != "online_features":
                continue
            latest = self._crossed.get(name)
            kept = [instant for instant in opened if instant == latest]
            if len(kept) != len(opened):
                self.feature_pauses[name] = "feature-not-published"
            if kept:
                self._open[name] = kept

    @staticmethod
    def _coordination(known: datetime, previous: datetime | None) -> datetime:
        """Coordinate one microsecond after the decision was known and after ``previous``."""
        coordinated = known + timedelta(microseconds=1)
        if previous is not None:
            coordinated = max(coordinated, previous + timedelta(microseconds=1))
        return coordinated

    def _groups(
        self, before: datetime, market: PaperMarket | None
    ) -> tuple[SharedDecisionGroup, ...]:
        """Decide each open instant whose inputs are ready, in coordination order.

        A source-fed group is quoted at the latest eligible market known before this
        delivery and coordinates by ``before``; an instant that cannot stays open.
        A served group is quoted at the latest market including this delivery's and
        coordinates after it. Instants are read in ascending order, as live sources
        freeze ascending cutoffs. An awaited served instant stays open; any other
        unavailable input closes its instant unread.
        """
        pending = self._pending
        if pending is None:
            return ()
        known = pending if market is None else market
        quotes = {
            False: (
                AccountQuote(price=pending.ask, at=pending.at),
                MarketTouch(bid=pending.bid, ask=pending.ask),
            ),
            True: (
                AccountQuote(price=known.ask, at=known.at),
                MarketTouch(bid=known.bid, ask=known.ask),
            ),
        }
        bindings = {binding.instance_id: binding for binding in self.runtime.bindings}
        opened = sorted(
            ((instant, name) for name, items in self._open.items() for instant in items),
            key=self._open_order,
        )
        due: dict[bool, dict[datetime, list[SharedStrategyInput]]] = {False: {}, True: {}}
        previous = self._coordinated
        for instant, name in opened:
            served = bindings[name].candidate.deployment.input_mode == "online_features"
            if (
                not served
                and instant not in due[False]
                and self._coordination(instant, previous) > before
            ):
                continue
            # An instant the account already committed is not decided again live.
            last = self.runtime.last_committed(name)
            if last is not None and instant <= last:
                self._open[name].remove(instant)
                continue
            inputs = self._instance_inputs(bindings[name], instant)
            if isinstance(inputs, str) or inputs is None:
                if inputs != "feature-pending":
                    self._open[name].remove(instant)
                continue
            quote, touch = quotes[served]
            if isinstance(inputs, ServedFeature):
                item = SharedStrategyInput(
                    instance_id=name, inputs=None, quote=quote, touch=touch, served=inputs
                )
            else:
                if instant not in due[False]:
                    previous = self._coordination(instant, previous)
                item = SharedStrategyInput(
                    instance_id=name, inputs=inputs, quote=quote, touch=touch
                )
            due[served].setdefault(instant, []).append(item)
        groups: list[SharedDecisionGroup] = []
        previous = self._coordinated
        for served, instants in due.items():
            quote, touch = quotes[served]
            for instant in sorted(instants):
                previous = self._coordination(before if served else instant, previous)
                groups.append(
                    SharedDecisionGroup(
                        at=instant,
                        quote=quote,
                        touch=touch,
                        inputs=tuple(instants[instant]),
                        coordinated_at=previous,
                    )
                )
        return tuple(groups)

    def _replayed(
        self, binding: SharedStrategyBinding, at: datetime, item: SharedStrategyInput
    ) -> bool:
        """Check a retained input against fresh sources or its exact retained snapshot."""
        if item.served is not None:
            if self.features is None:
                return False
            try:
                self.features.verify(binding.candidate, item.served)
            except ValueError:
                return False
            return item.served.served_at == at
        return self._instance_inputs(binding, at) == item.inputs

    @staticmethod
    def _open_order(item: tuple[datetime, str]) -> datetime:
        """Order open instants ascending; equal instants keep binding order."""
        return item[0]

    def _instance_inputs(
        self, binding: SharedStrategyBinding, instant: datetime
    ) -> DecisionInputs | ServedFeature | str | None:
        """Select the candidate's exact fields or served feature.

        Returns None when native inputs are incomplete, or a served pause reason.
        """
        if binding.candidate.deployment.input_mode == "online_features":
            if self.features is None:
                raise ValueError("feature-served candidate has no feature store")
            served = self.features.serve(binding.candidate, instant)
            if isinstance(served, str):
                self.feature_pauses[binding.instance_id] = served
                return served
            self.feature_pauses.pop(binding.instance_id, None)
            return served
        sources: tuple[DecisionSource, ...] = (
            (self.source,) if self.trades is None else (self.source, self.trades)
        )
        inputs = LiveInputs(binding.candidate.definition.inputs, sources).read(
            binding.entity, instant
        )
        if any(row.value is None for row in inputs.observations):
            return None
        return inputs

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
                source_id=self._source_id,
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

    def _timed(self, delivery: LiveBookDelivery, market: PaperMarket | None) -> bool:
        """Report whether a delivery advances the decision grid.

        Time and market are separate: a priced book advances the grid and matches,
        while any other delivery (a clock, heartbeat or control) advances the grid
        only while the retained market is still current at it, and never matches.
        """
        if market is not None:
            return True
        return (
            self._pending is not None
            and self.source.current_book(str(self.scenario.instrument_id), delivery.available_at)
            is not None
        )

    def _apply(
        self,
        delivery: SharedBookDelivery,
        market: PaperMarket | None,
        *,
        timed: bool,
        replayed: bool,
    ) -> None:
        """Validate retained decision lineage and compose existing atomic public operations."""
        if market is None and (delivery.matched or (delivery.decisions and not timed)):
            raise ValueError("ineligible native input cannot decide or match")
        if not timed:
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
        if market is not None:
            self._ineligible_book = False
        boundary = delivery.source.available_at
        for group in delivery.decisions:
            if group.coordinated_at <= boundary:
                self._decide(delivery, group, self._pending, replayed=replayed)
        if self._phases is not None and delivery.decisions:
            self._phases["evaluated_ns"] = time.monotonic_ns()
        if market is not None:
            self.last_market = market
            self._pending = market
            if delivery.matched:
                if not self._market_applied(market, replayed=replayed):
                    self.journal.observe(AccountQuote(price=market.ask, at=market.at))
                if self._phases is not None:
                    self._phases["observed_ns"] = time.monotonic_ns()
                if self.journal.config.mode == "paper":
                    self.journal.match_public_market(self.account_id, market, self.scenario)
                if self._phases is not None:
                    self._phases["matched_ns"] = time.monotonic_ns()
        # A served snapshot became known with this delivery, so its book cannot fill it.
        for group in delivery.decisions:
            if group.coordinated_at > boundary:
                self._decide(delivery, group, self._pending, replayed=replayed)
        self._close_open()

    def _market_applied(self, market: PaperMarket, *, replayed: bool) -> bool:
        """Report whether the account already applied this book, so replay retries it.

        Paper retains one trace per matched book. Shadow keeps only the latest
        valuation, so a replayed book older than it was already applied; an equal clock
        is observed again, which accepts only the same quote.
        """
        if self.journal.paper_market_seen(self.account_id, market.identity):
            return True
        if not replayed or self.journal.config.mode == "paper":
            return False
        latest = self.journal.valuation(market.ask.per)
        return latest is not None and market.at < latest.at

    def _decide(
        self,
        delivery: SharedBookDelivery,
        group: SharedDecisionGroup,
        known: PaperMarket | None,
        *,
        replayed: bool,
    ) -> None:
        """Check one group's clock, quote and lineage, then commit its batch."""
        served = group.coordinated_at > delivery.source.available_at
        expected = self._coordination(
            delivery.source.available_at if served else group.at, self._coordinated
        )
        if group.coordinated_at != expected:
            raise ValueError("shared decision coordination differs from its delivery order")
        if (
            known is None
            or group.quote != AccountQuote(price=known.ask, at=known.at)
            or group.touch != MarketTouch(bid=known.bid, ask=known.ask)
        ):
            raise ValueError("shared decision substituted its known market quote")
        for item in group.inputs:
            if group.at not in self._open.get(item.instance_id, ()):
                raise ValueError("shared decision names an instant that is not open")
        # A live delivery's inputs were just read from these sources; a replayed one
        # is read again, in ascending instants, and must equal what it retained.
        bindings = {binding.instance_id: binding for binding in self.runtime.bindings}
        for item in group.inputs:
            binding = bindings.get(item.instance_id)
            if binding is None or (replayed and not self._replayed(binding, group.at, item)):
                raise ValueError("shared decision substituted native input lineage")
        identity = hashlib.sha256(self._codec.encode_json((delivery.source, group))).hexdigest()
        # An already retained batch is an exact retry; its quote was observed with it.
        if self.journal.portfolio_batch(identity) is None:
            self.journal.observe(group.quote)
        commit = self.runtime.evaluate(
            identity=identity, at=group.coordinated_at, inputs=group.inputs
        )
        if commit is not None:
            self.decisions.append(commit)
        for item in group.inputs:
            self._open[item.instance_id].remove(group.at)
        self._coordinated = group.coordinated_at

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

    def _now(self) -> datetime:
        """Read the injected or system UTC clock without inventing a future instant."""
        return datetime.now(UTC) if self._clock is None else self._clock()

    def _row_payload(self, row: BookObservation) -> bytes:
        """Reuse the live source's encoding of this exact row, or encode it once."""
        source = self.source
        if source._latest_book is row and source._latest_book_payload is not None:
            return source._latest_book_payload
        return self._codec.encode_json(row)

    def _retain(self, delivery: SharedBookDelivery, row_payload: bytes) -> tuple[int, int]:
        """Persist bounded replay bytes before changing state; return their byte range.

        The sorted encoder writes a nested row exactly as it writes the row alone,
        so the envelope around the already encoded row equals the full encoding.
        """
        if self.delivery_path is None:
            raise ValueError("live shared paper requires a retained delivery path")
        source = delivery.source
        envelope = RetainedSharedBookDelivery(
            source=RetainedLiveBookDelivery(
                record=source.record,
                book=msgspec.Raw(row_payload),
                available_at=source.available_at,
            ),
            decisions=delivery.decisions,
            matched=delivery.matched,
            schema_version=delivery.schema_version,
        )
        payload = self._codec.encode_json(envelope) + b"\n"
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
