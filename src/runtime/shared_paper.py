"""Deliver retained native books to existing shared decisions and paper accounting."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec

# project library imports
from configuration import BookKey, PaperExecutionScenario
from execution import AccountControl, AccountQuote, PaperAccount, PaperMarket, PortfolioCommit
from financial_units import Price, Quantity
from market_data.books import BookAsOfIndex, BookDepth, BookRegistry
from market_data.contracts import BookObservation, CaptureRecord
from research.observations import DecisionInputs, LiveBookDecisionSource, LiveTradeDecisionSource
from runtime.feature_feed import ServedFeature, ServedFeatures
from runtime.live_paper import LiveBookDelivery
from runtime.portfolio import SharedDecisionRuntime, SharedStrategyBinding, SharedStrategyInput
from serialization import DomainCodec, WireRecord
from telemetry import RuntimeMeasurementJournal


class SharedDecisionGroup(WireRecord, frozen=True):
    """Retain one grid instant's causal inputs, observed quote and coordination clock.

    Coordination is the logical boundary one microsecond after the instant, so net
    orders and the account's knowledge stay before the book that crossed the instant.
    """

    at: datetime
    quote: AccountQuote
    inputs: tuple[SharedStrategyInput, ...]
    coordinated_at: datetime

    def __post_init__(self) -> None:
        """Bind every input and the quote to this instant, before its coordination."""
        self._require_utc(self.at, field_name="shared decision instant")
        self._require_utc(self.coordinated_at, field_name="shared book coordination")
        if type(self.quote) is not AccountQuote:
            raise TypeError("shared decision group requires an account quote")
        self.quote.__post_init__()
        if type(self.inputs) is not tuple or not self.inputs:
            raise ValueError("shared decision group requires inputs")
        if self.quote.at > self.at or self.coordinated_at != self.at + timedelta(microseconds=1):
            raise ValueError("shared decision quote or coordination clock is out of order")
        for item in self.inputs:
            if type(item) is not SharedStrategyInput:
                raise TypeError("shared decision group requires SharedStrategyInput")
            item.__post_init__()
            if item.decision_at != self.at or item.quote != self.quote:
                raise ValueError("shared input cutoff or quote differs from its instant")


class SharedBookDelivery(WireRecord, frozen=True):
    """Retain original source clocks, decided grid instants and account matching."""

    source: LiveBookDelivery
    decisions: tuple[SharedDecisionGroup, ...]
    matched: bool
    schema_version: Literal["shared-candidate-delivery"] = "shared-candidate-delivery"

    def __post_init__(self) -> None:
        """Reject unbound decision clocks or out-of-order coordination envelopes."""
        LiveBookDelivery.__post_init__(self.source)
        self._require_coordination()

    def _require_coordination(self) -> None:
        """Validate decisions and coordination after native validation."""
        if (
            self.schema_version != "shared-candidate-delivery"
            or type(self.decisions) is not tuple
            or type(self.matched) is not bool
        ):
            raise ValueError("unsupported shared book delivery schema")
        previous: datetime | None = None
        for group in self.decisions:
            if type(group) is not SharedDecisionGroup:
                raise TypeError("shared delivery requires decision groups")
            group.__post_init__()
            if group.at >= self.source.available_at or (
                previous is not None and group.at <= previous
            ):
                raise ValueError("shared decision instants must precede their delivery in order")
            previous = group.at
        if self.decisions and not self.matched:
            raise ValueError("a delivery that decides an instant also matches its market")


class ObservedLiveBookDelivery(LiveBookDelivery, frozen=True):
    """Wrap validated source records while checking the new actual availability clock."""

    def __post_init__(self) -> None:
        """Rely on the typed pipe or public observe boundary for native validation."""
        self._require_availability()


class ObservedSharedBookDelivery(SharedBookDelivery, frozen=True):
    """Coordinate validated native inputs without changing the retained wire schema."""

    def __post_init__(self) -> None:
        """Check only the new availability, decision and coordination invariants."""
        self.source._require_availability()
        self._require_coordination()


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
    """Decide candidates on their UTC grids and match each instant's crossing book.

    Native reconstruction, freshness and control invalidation remain owned by
    ``LiveBookDecisionSource`` and ``BookRegistry``. Each candidate decides at
    ``starts_at + k * cadence``. When the first eligible book after an instant
    arrives, the due candidates decide at that instant from the latest eligible
    market at or before it, then the arriving book matches orders. Books between
    instants update monitoring only. An instant without a fresh market or complete
    inputs is skipped, which the candidate's gap rule then governs. The fsynced
    delivery log retains decided inputs before effects; replay uses its clocks.
    A fresh observer rebuilds source state from the beginning of its recording.
    Account transactions and candidate retry identities survive process restart.

    With ``trades`` the same instrument's public trade tape is delivered through
    ``observe_trades`` and its fields join the book's in each candidate's inputs.
    Trade boundaries only update that source. Each is retained with its actual
    delivery time in the sibling ``.trades.jsonl`` log before it applies, so a
    replay interleaves both logs by delivery time and re-reads the same inputs.

    A feature-served candidate reads its pinned stream through ``features`` at each
    instant instead of the native sources. A pause reason (missing, stale, future,
    changed version or unavailable service) skips the instant like missing inputs
    and is kept in ``feature_pauses``. The delivery log retains the served vector
    and the exact snapshot; replay reopens that snapshot and requires the same value.
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
        matched = market is not None and self._crosses(source.available_at)
        groups = self._groups(source.available_at) if matched else ()
        delivery = ObservedSharedBookDelivery(source=source, decisions=groups, matched=matched)
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
            self._apply(delivery, market, replayed=False)
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
                        "market_selected": matched,
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
        if delivery.matched != (market is not None and self._crosses(delivery.source.available_at)):
            raise ValueError("retained delivery differs from the replayed decision grid")
        self._apply(delivery, market, replayed=True)

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

    def _groups(self, before: datetime) -> tuple[SharedDecisionGroup, ...]:
        """Build each due instant's inputs from the latest eligible market at or before it."""
        pending = self._pending
        if pending is None:
            return ()
        quote = AccountQuote(price=pending.ask, at=pending.at)
        crossed: list[tuple[datetime, SharedStrategyBinding]] = []
        for binding in self.runtime.bindings:
            instant = self._crossed.get(binding.instance_id)
            if (
                binding.instance_id not in self.active
                or instant is None
                or instant >= before
                or pending.at > instant
            ):
                continue
            last = self.runtime.last_committed(binding.instance_id)
            if last is not None and instant <= last:
                continue
            crossed.append((instant, binding))
        # Live sources freeze ascending cutoffs, so mixed grids read in instant order.
        crossed.sort(key=self._instant_order)
        due: dict[datetime, list[SharedStrategyInput]] = {}
        for instant, binding in crossed:
            inputs = self._instance_inputs(binding, instant)
            if isinstance(inputs, ServedFeature):
                due.setdefault(instant, []).append(
                    SharedStrategyInput(
                        instance_id=binding.instance_id, inputs=None, quote=quote, served=inputs
                    )
                )
            elif inputs is not None:
                due.setdefault(instant, []).append(
                    SharedStrategyInput(instance_id=binding.instance_id, inputs=inputs, quote=quote)
                )
        return tuple(
            SharedDecisionGroup(
                at=instant,
                quote=quote,
                inputs=tuple(due[instant]),
                coordinated_at=instant + timedelta(microseconds=1),
            )
            for instant in sorted(due)
        )

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
    def _instant_order(item: tuple[datetime, SharedStrategyBinding]) -> datetime:
        """Order crossed bindings by instant; equal instants keep binding order."""
        return item[0]

    def _instance_inputs(
        self, binding: SharedStrategyBinding, instant: datetime
    ) -> DecisionInputs | ServedFeature | None:
        """Select the candidate's exact fields or served feature, or None when unavailable."""
        if binding.candidate.deployment.input_mode == "online_features":
            if self.features is None:
                raise ValueError("feature-served candidate has no feature store")
            served = self.features.serve(binding.candidate, instant)
            if isinstance(served, str):
                self.feature_pauses[binding.instance_id] = served
                return None
            self.feature_pauses.pop(binding.instance_id, None)
            return served
        causal = self.source.read(binding.entity, instant).observations
        if self.trades is not None:
            causal += self.trades.read(binding.entity, instant).observations
        by_input = {row.input: row for row in causal}
        rows = tuple(by_input[item] for item in binding.candidate.definition.inputs)
        if any(row.value is None for row in rows):
            return None
        return DecisionInputs(entity=binding.entity, decision_at=instant, observations=rows)

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

    def _apply(
        self, delivery: SharedBookDelivery, market: PaperMarket | None, *, replayed: bool
    ) -> None:
        """Validate retained decision lineage and compose existing atomic public operations."""
        if market is None:
            if delivery.matched or delivery.decisions:
                raise ValueError("ineligible native input cannot decide or match")
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
        pending = self._pending
        for group in delivery.decisions:
            if pending is None or group.quote != AccountQuote(price=pending.ask, at=pending.at):
                raise ValueError("shared decision substituted its instant's market quote")
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
        if self._phases is not None and delivery.decisions:
            self._phases["evaluated_ns"] = time.monotonic_ns()
        self.last_market = market
        self._pending = market
        if not delivery.matched:
            return
        if not self.journal.paper_market_seen(self.account_id, market.identity):
            self.journal.observe(AccountQuote(price=market.ask, at=market.at))
        if self._phases is not None:
            self._phases["observed_ns"] = time.monotonic_ns()
        if self.journal.config.mode == "paper":
            self.journal.match_public_market(self.account_id, market, self.scenario)
        if self._phases is not None:
            self._phases["matched_ns"] = time.monotonic_ns()

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
