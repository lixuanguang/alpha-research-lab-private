"""Expose causal book coverage and exact consolidated visible quotes."""

from __future__ import annotations

# standard library imports
from decimal import Decimal
from fractions import Fraction
from typing import Literal

# project library imports
from configuration import BookEquivalence, BookKey, BookSelection
from financial_units import DecimalGrid
from market_data.contracts.quotes import BookQuote
from serialization import WireRecord


class BookLookup(WireRecord, frozen=True):
    """Retain selected source, latest known boundary and an eligible market or refusal.

    An excluded boundary can describe stale, disconnected or invalid state. Only
    ``quote`` is eligible; its original clocks are never refreshed by controls.
    """

    selection: BookSelection
    cutoff_ns: int
    boundary: BookQuote | None
    quote: BookQuote | None
    reason: str

    def __post_init__(self) -> None:
        """Reject inconsistent eligibility or a future/misbound market."""
        if type(self.selection) is not BookSelection:
            raise ValueError("lookup requires a selected book")
        self.selection.__post_init__()
        if (
            type(self.cutoff_ns) is not int
            or self.cutoff_ns < 0
            or type(self.reason) is not str
            or not self.reason
        ):
            raise ValueError("lookup requires a cutoff and reason")
        if (self.quote is not None) != (self.reason == "eligible"):
            raise ValueError("lookup eligibility contradicts its reason")
        for item in (self.boundary, self.quote):
            if item is not None:
                if type(item) is not BookQuote:
                    raise ValueError("lookup requires typed quotes")
                item.__post_init__()
                if (
                    (item.venue, item.instrument_id, item.source_id, item.channel)
                    != (
                        self.selection.instrument.venue,
                        self.selection.instrument.instrument_id,
                        self.selection.source_id,
                        self.selection.capability.channel,
                    )
                    or item.available_ns is None
                    or item.available_ns > self.cutoff_ns
                ):
                    raise ValueError("lookup contains future or unselected quote")
        if self.quote is not None and (
            self.boundary is None or self.quote.market_state == "unavailable"
        ):
            raise ValueError("eligible quote requires an available market boundary")

    @property
    def eligible(self) -> bool:
        """Report usable quality and clocks, independently of missing bid/ask sides."""
        return self.quote is not None


class ConsolidatedQuoteSide(WireRecord, frozen=True):
    """Retain every tied native contribution; summed size is visible, not routed liquidity."""

    side: Literal["bid", "ask"]
    contributions: tuple[BookQuote, ...]

    def __post_init__(self) -> None:
        """Require nonempty, same-price contributions with unique ordered venues."""
        if (
            self.side not in ("bid", "ask")
            or type(self.contributions) is not tuple
            or not self.contributions
        ):
            raise ValueError("consolidated side requires contributions")
        prices: set[Decimal] = set()
        venues: list[str] = []
        for quote in self.contributions:
            if type(quote) is not BookQuote:
                raise ValueError("consolidated side requires typed quotes")
            quote.__post_init__()
            value = quote.bid if self.side == "bid" else quote.ask
            if value is None:
                raise ValueError("consolidated side contribution is absent")
            prices.add(value.price)
            venues.append(quote.venue)
        if len(prices) != 1 or venues != sorted(set(venues)):
            raise ValueError("consolidated side requires tied prices and unique sorted venues")

    @property
    def price(self) -> Decimal:
        """Return the shared exact native price, with no currency conversion."""
        value = self.contributions[0].bid if self.side == "bid" else self.contributions[0].ask
        if value is None:
            raise ValueError("consolidated side contribution is absent")
        return value.price

    @property
    def quantity(self) -> Decimal:
        """Sum exact compatible units independently of ambient Decimal precision."""
        values = (quote.bid if self.side == "bid" else quote.ask for quote in self.contributions)
        return DecimalGrid.exact_decimal(
            sum((Fraction(value.quantity) for value in values if value is not None), Fraction())
        )

    @property
    def venues(self) -> tuple[str, ...]:
        """Identify each tied contributor in stable venue order."""
        return tuple(quote.venue for quote in self.contributions)


class ConsolidatedBookQuote(WireRecord, frozen=True):
    """Describe selected versus eligible coverage for one explicit equivalent market."""

    mapping: BookEquivalence
    cutoff_ns: int
    books: tuple[BookLookup, ...]

    def __post_init__(self) -> None:
        """Require exactly the mapped books and one common causal cutoff."""
        if type(self.mapping) is not BookEquivalence:
            raise ValueError("consolidation requires an explicit mapping")
        self.mapping.__post_init__()
        if type(self.cutoff_ns) is not int or self.cutoff_ns < 0 or type(self.books) is not tuple:
            raise ValueError("consolidation requires a cutoff and immutable lookups")
        for book in self.books:
            if type(book) is not BookLookup or book.cutoff_ns != self.cutoff_ns:
                raise ValueError("consolidation requires matching lookup cutoffs")
            book.__post_init__()
        if tuple(book.selection.key for book in self.books) != self.mapping.members:
            raise ValueError("consolidation coverage differs from mapping")
        economics = {
            (
                book.selection.instrument.product,
                book.selection.instrument.base_currency,
                book.selection.instrument.quote_currency,
                book.selection.quantity_unit,
            )
            for book in self.books
        }
        if len(economics) != 1:
            raise ValueError("consolidation has incompatible economics")
        if self.eligible_keys and (
            self.cutoff_ns < max(self.mapping.known_ns, self.mapping.valid_from_ns)
            or (self.mapping.valid_to_ns is not None and self.cutoff_ns >= self.mapping.valid_to_ns)
        ):
            raise ValueError("consolidation uses unavailable reference mapping")

    @property
    def selected_keys(self) -> tuple[BookKey, ...]:
        """Return the explicitly selected coverage, including excluded books."""
        return self.mapping.members

    @property
    def eligible_keys(self) -> tuple[BookKey, ...]:
        """Return books meeting policy, even when an accepted book has no sides."""
        return tuple(book.selection.key for book in self.books if book.eligible)

    @property
    def partial(self) -> bool:
        """Report any excluded selected book; native coverage limitations still apply."""
        return len(self.eligible_keys) < len(self.selected_keys)

    @property
    def bid(self) -> ConsolidatedQuoteSide | None:
        """Return the highest eligible bid and all exact tied contributors."""
        return self._best("bid")

    @property
    def ask(self) -> ConsolidatedQuoteSide | None:
        """Return the lowest eligible ask and all exact tied contributors."""
        return self._best("ask")

    @property
    def market_state(
        self,
    ) -> Literal["unavailable", "empty", "one_sided", "locked", "crossed", "two_sided"]:
        """Distinguish excluded coverage, absent sides and consolidated price crossings."""
        if not self.eligible_keys:
            return "unavailable"
        bid, ask = self.bid, self.ask
        if bid is None and ask is None:
            return "empty"
        if bid is None or ask is None:
            return "one_sided"
        if bid.price == ask.price:
            return "locked"
        return "crossed" if bid.price > ask.price else "two_sided"

    def _best(self, side: Literal["bid", "ask"]) -> ConsolidatedQuoteSide | None:
        """Scan cached eligible quotes without imposing routing or executable-size claims."""
        quotes: list[BookQuote] = []
        best: Decimal | None = None
        for book in self.books:
            quote = book.quote
            if quote is None:
                continue
            value = quote.bid if side == "bid" else quote.ask
            if value is None:
                continue
            if best is None or (value.price > best if side == "bid" else value.price < best):
                best, quotes = value.price, [quote]
            elif value.price == best:
                quotes.append(quote)
        return (
            ConsolidatedQuoteSide(side=side, contributions=tuple(sorted(quotes, key=self._venue)))
            if quotes
            else None
        )

    @staticmethod
    def _venue(quote: BookQuote) -> str:
        """Order ties independently of mapping or ingestion order."""
        return quote.venue
