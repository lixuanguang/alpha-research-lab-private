"""Own independent native books and bounded causal quote caches for explicit markets."""

from __future__ import annotations

# standard library imports
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

# project library imports
from configuration import BookKey, BookRegistryConfiguration, BookSelection, CaptureConfig
from financial_units import QuantityKind
from market_data.books.projection import BookProjection
from market_data.books.protocol import NativeBook
from market_data.books.reconstruction import CaptureReplay
from market_data.contracts import (
    BookLookup,
    BookQuote,
    CaptureRecord,
    CaptureRequest,
    ConsolidatedBookQuote,
)


@dataclass(frozen=True, slots=True)
class _Boundary:
    """Keep the current control boundary separate from original priced-market clocks."""

    event: BookQuote
    market: BookQuote | None


class BookRegistry:
    """Scan selected book caches at explicit cutoffs without FX or execution routing.

    Each source supplies contiguous complete boundaries in nondecreasing delivery
    order. Historical queries select the last boundary available at the cutoff;
    an evicted cutoff reports ``history_evicted`` instead of reading future state.
    A fresh registry rebuilt from original records and delivery clocks is restart.
    Callers serialize access; this synchronous owner starts no workers or network.
    """

    def __init__(self, config: BookRegistryConfiguration) -> None:
        """Bind immutable admission and finite history for every independent listing."""
        config.__post_init__()
        self.config = config
        self._selections = {selection.key: selection for selection in config.selections}
        self._history: dict[BookKey, deque[_Boundary]] = {
            key: deque(maxlen=config.history_capacity) for key in self._selections
        }
        self._evicted: set[BookKey] = set()
        self._native: dict[BookKey, CaptureReplay] = {}

    def attach(
        self, request: CaptureRequest, *, book_factory: Callable[[CaptureConfig], NativeBook]
    ) -> None:
        """Admit one native reconstruction before input and retain its original source binding.

        Args:
            request: Exact selected recording; its spot currencies/channel must match reference.
            book_factory: Explicit installed native adapter constructor, never inferred from config.

        Raises:
            ValueError: The source is unselected, mismatched or already has state.
        """
        request.__post_init__()
        config = request.config
        key = BookKey(venue=config.venue, instrument_id=config.instrument_id)
        selection = self._selection(key)
        instrument = selection.instrument
        if (
            (
                request.identity,
                config.channel,
                config.symbol,
                config.base_currency,
                config.quote_currency,
                "spot",
                QuantityKind.BASE_UNIT,
            )
            != (
                selection.source_id,
                selection.capability.channel,
                instrument.symbol,
                instrument.base_currency,
                instrument.quote_currency,
                instrument.product,
                selection.quantity_unit,
            )
            or key in self._native
            or self._history[key]
        ):
            raise ValueError(
                "native book differs from selected reference/source or already has state"
            )
        self._native[key] = CaptureReplay(config, book_factory=book_factory)

    def apply(self, key: BookKey, record: CaptureRecord, *, available_ns: int) -> BookQuote:
        """Apply one complete native boundary and cache its quote using explicit delivery time.

        Saved receipt-only inputs require an explicitly labeled receipt-clock
        replay assumption. This method never substitutes receipt for availability.
        Native decoder/continuity failures follow CaptureReplay's invalidation.
        """
        selection = self._selection(key)
        record.__post_init__()
        history = self._history[key]
        if type(available_ns) is not int or available_ns < record.received_ns:
            raise ValueError("registry delivery precedes native receipt")
        if history and (
            available_ns < self._available(history[-1].event)
            or record.received_ns < (history[-1].event.received_ns or 0)
        ):
            raise ValueError("registry native clocks cannot regress")
        if key not in self._native:
            raise ValueError("native book is not attached")
        replay = self._native[key]
        outcome = replay.apply(record)
        quote = BookProjection.quote(
            0 if not history else history[-1].event.position + 1,
            record,
            outcome,
            replay,
            source_id=selection.source_id,
            available_ns=available_ns,
        )
        self._accept(quote, key)
        return quote

    def accept(self, quote: BookQuote) -> None:
        """Cache an externally reconstructed complete boundary without changing native state.

        The first position is zero; subsequent positions are contiguous. Repeating
        the exact latest boundary is idempotent. Known delivery time is mandatory;
        unknown receipt remains a query refusal. Future clocks and other sources
        cannot replace accepted state. Attached books use ``apply`` exclusively.
        """
        quote.__post_init__()
        key = BookKey(venue=quote.venue, instrument_id=quote.instrument_id)
        if key in self._native:
            raise ValueError("attached native book requires apply")
        self._accept(quote, key)

    def _accept(self, quote: BookQuote, key: BookKey) -> None:
        """Validate a full boundary before mutating its isolated cache."""
        selection = self._selection(key)
        if (quote.source_id, quote.channel) != (selection.source_id, selection.capability.channel):
            raise ValueError("quote differs from selected source/channel")
        available = self._available(quote)
        history = self._history[key]
        prior = history[-1] if history else None
        if prior is not None and quote == prior.event:
            return
        if quote.position != (0 if prior is None else prior.event.position + 1):
            raise ValueError("registry requires contiguous book positions")
        if prior is not None and (
            available < self._available(prior.event)
            or (
                quote.received_ns is not None
                and prior.event.received_ns is not None
                and quote.received_ns < prior.event.received_ns
            )
        ):
            raise ValueError("registry book clocks cannot regress")
        market = quote if quote.market_state != "unavailable" else None
        if (
            quote.status == "degraded"
            and quote.outcome in ("control", "heartbeat", "duplicate")
            and prior is not None
            and prior.market is not None
            and (quote.epoch, quote.state_identity)
            == (prior.market.epoch, prior.market.state_identity)
        ):
            market = prior.market
        if len(history) == self.config.history_capacity:
            self._evicted.add(key)
        history.append(_Boundary(quote, market))

    def lookup(self, key: BookKey, *, cutoff_ns: int) -> BookLookup:
        """Return an eligible native BBO or explicit refusal at an inclusive cutoff.

        Expiry is evaluated on every query, even without a new message. A later
        disconnect does not erase an earlier known quote. Missing sides remain
        distinct from excluded books. Older retained queries may run in any order.
        """
        selection = self._selection(key)
        self._require_cutoff(cutoff_ns)
        history = self._history[key]
        selected = next(
            (row for row in reversed(history) if self._available(row.event) <= cutoff_ns), None
        )
        if selected is None:
            reason = (
                "history_evicted"
                if key in self._evicted
                else "not_yet_available"
                if history
                else "missing"
            )
            return BookLookup(
                selection=selection, cutoff_ns=cutoff_ns, boundary=None, quote=None, reason=reason
            )
        reason = self._refusal(selection, selected.market, cutoff_ns)
        return BookLookup(
            selection=selection,
            cutoff_ns=cutoff_ns,
            boundary=selected.event,
            quote=selected.market if reason == "eligible" else None,
            reason=reason,
        )

    def consolidated(self, name: str, *, cutoff_ns: int) -> ConsolidatedBookQuote:
        """Query only explicitly equivalent listings and retain selected/excluded coverage."""
        self._require_cutoff(cutoff_ns)
        mapping = next((group for group in self.config.equivalences if group.name == name), None)
        if mapping is None:
            raise ValueError("unknown book equivalence")
        if cutoff_ns < max(mapping.known_ns, mapping.valid_from_ns) or (
            mapping.valid_to_ns is not None and cutoff_ns >= mapping.valid_to_ns
        ):
            books = tuple(
                BookLookup(
                    selection=self._selections[key],
                    cutoff_ns=cutoff_ns,
                    boundary=None,
                    quote=None,
                    reason="reference_unavailable",
                )
                for key in mapping.members
            )
        else:
            books = tuple(self.lookup(key, cutoff_ns=cutoff_ns) for key in mapping.members)
        return ConsolidatedBookQuote(mapping=mapping, cutoff_ns=cutoff_ns, books=books)

    def _selection(self, key: BookKey) -> BookSelection:
        """Reject unselected or malformed keys before reading or modifying state."""
        key.__post_init__()
        if key not in self._selections:
            raise ValueError("unselected registry book")
        return self._selections[key]

    @staticmethod
    def _require_cutoff(cutoff_ns: int) -> None:
        """Require exact nonnegative Unix nanoseconds without boolean coercion."""
        if type(cutoff_ns) is not int or cutoff_ns < 0:
            raise ValueError("registry cutoff must be nonnegative integer nanoseconds")

    @staticmethod
    def _available(quote: BookQuote) -> int:
        """Require explicit delivery knowledge rather than inventing unknown clocks."""
        if quote.available_ns is None:
            raise ValueError("registry requires known availability")
        return quote.available_ns

    @classmethod
    def _refusal(cls, selection: BookSelection, quote: BookQuote | None, cutoff_ns: int) -> str:
        """Apply the selected source-clock, original receipt and quality policy."""
        if quote is None:
            return "unavailable"
        if not selection.allow_degraded:
            return "quality_not_admitted"
        if quote.received_ns is None:
            return "unknown_receipt"
        clocks = [quote.received_ns, cls._available(quote)]
        if selection.capability.source_clock != "unknown":
            source_ns = cls._source_ns(selection, quote)
            if source_ns is None:
                return "unknown_source_time"
            if source_ns > cutoff_ns:
                return "future_source_time"
            clocks.append(source_ns)
        return (
            "stale"
            if any(cutoff_ns - clock > selection.max_age_ns for clock in clocks)
            else "eligible"
        )

    @staticmethod
    def _source_ns(selection: BookSelection, quote: BookQuote) -> int | None:
        """Read the declared native clock without repairing timestamps or substituting receipt."""
        raw = quote.source_time
        if raw is None:
            return None
        if selection.capability.source_clock == "milliseconds":
            return int(raw) * 1_000_000 if raw.isascii() and raw.isdigit() else None
        match = re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[.,](\d{1,9}))?(?:Z|\+00:00)", raw
        )
        if match is None:
            return None
        try:
            at = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if at.tzinfo is None or at.utcoffset() is None:
            return None
        elapsed = at.replace(microsecond=0) - datetime(1970, 1, 1, tzinfo=UTC)
        fraction = "" if match.start(1) == -1 else raw[match.start(1) : match.end(1)]
        return (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000_000 + int(
            fraction.ljust(9, "0")
        )
