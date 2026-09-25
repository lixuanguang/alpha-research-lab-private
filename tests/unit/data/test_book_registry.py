"""Check independent books, causal consolidation and explicit reference admission."""

from __future__ import annotations

# standard library imports
import hashlib
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Literal

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from configuration import (
    BookEquivalence,
    BookRegistryConfiguration,
    BookSelection,
    CaptureConfig,
    DataCapability,
)
from financial_units import QuantityKind
from market_data.adapters.sources import BookAdapters
from market_data.books import BookRegistry
from market_data.contracts import BookQuote, BookQuoteSide, CaptureRecord, CaptureRequest
from reference_data.catalogs import InstrumentDefinition
from reference_data.instruments import InstrumentId
from serialization import DomainCodec


class _RegistryScenario:
    """Build deterministic fixtures for book-registry behavior tests."""

    _IDS: tuple[InstrumentId, InstrumentId, InstrumentId] = (
        InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        InstrumentId.from_canonical_text("22222222-2222-4222-8222-222222222222"),
        InstrumentId.from_canonical_text("33333333-3333-4333-8333-333333333333"),
    )
    _ROOT: Path = Path(__file__).parents[3]

    @staticmethod
    def _selection(
        venue: str,
        instrument_id: InstrumentId,
        *,
        quote_currency: str = "USD",
        base_currency: str = "BTC",
        unit: QuantityKind = QuantityKind.BASE_UNIT,
        source_clock: Literal["milliseconds", "iso8601", "unknown"] = "unknown",
        max_age_ns: int = 100,
        allow_degraded: bool = True,
    ) -> BookSelection:
        """Author one spot listing and its independent native capability."""
        return BookSelection(
            instrument=InstrumentDefinition(
                instrument_id=instrument_id,
                venue=venue,
                symbol=f"{base_currency}-{quote_currency}",
                product="spot",
                base_currency=base_currency,
                quote_currency=quote_currency,
                calendar="continuous-utc",
            ),
            source_id=f"{venue}-recording",
            capability=DataCapability(
                adapter=f"{venue}.native-book",
                version="1",
                venue=venue,
                product="spot",
                channel="books" if venue == "okx" else "level3" if venue == "coinbase" else "R0",
                representation="L2" if venue == "okx" else "L3",
                modes=("capture", "replay"),
                depth=25,
                source_clock=source_clock,
                sequence="consecutive",
                reference="none",
                calendar="continuous-utc",
                recovery="new-snapshot-epoch",
            ),
            quantity_unit=unit,
            max_age_ns=max_age_ns,
            allow_degraded=allow_degraded,
        )

    @staticmethod
    def _configuration(
        *selections: BookSelection,
        equivalent: bool = True,
        capacity: int = 8,
        known_ns: int = 0,
        valid_from_ns: int = 0,
        valid_to_ns: int | None = None,
    ) -> BookRegistryConfiguration:
        """Pin exact member order and a bounded query history."""
        groups = (
            (
                BookEquivalence(
                    name="btc-usd",
                    reference="authored:btc-usd:unit-v1",
                    members=tuple(item.key for item in selections),
                    known_ns=known_ns,
                    valid_from_ns=valid_from_ns,
                    valid_to_ns=valid_to_ns,
                ),
            )
            if equivalent
            else ()
        )
        return BookRegistryConfiguration(
            selections=selections, equivalences=groups, history_capacity=capacity
        )

    @staticmethod
    def _side(price: str, quantity: str, count: int = 1) -> BookQuoteSide:
        """Build exact native touch data without Decimal context arithmetic."""
        return BookQuoteSide(Decimal(price), Decimal(quantity), count)

    @staticmethod
    def _quote(
        selection: BookSelection,
        position: int,
        received_ns: int,
        *,
        available_ns: int | None = None,
        bid: BookQuoteSide | None = None,
        ask: BookQuoteSide | None = None,
        outcome: str = "snapshot",
        status: str = "degraded",
        source_time: str | None = None,
        epoch: int = 0,
        state_identity: str | None = None,
    ) -> BookQuote:
        """Make one complete boundary with distinct receipt and delivery clocks."""
        return BookQuote(
            venue=selection.key.venue,
            instrument_id=selection.key.instrument_id,
            source_id=selection.source_id,
            channel=selection.capability.channel,
            position=position,
            epoch=epoch,
            sequence=position,
            source_time=source_time,
            received_ns=received_ns,
            available_ns=received_ns if available_ns is None else available_ns,
            outcome=outcome,
            status=status,
            reason=outcome,
            state_identity=state_identity
            or hashlib.sha256(f"{selection.source_id}:{epoch}:{position}".encode()).hexdigest(),
            bid=bid,
            ask=ask,
        )


class TestBookRegistry:
    """Verify registry admission, history, recovery, and consolidation."""

    def test_tied_best_prices_sum_exactly_and_retain_each_original_quote(self) -> None:
        """Tie totals and provenance come from independent venue touches, even at low precision."""
        first, second, third = (
            _RegistryScenario._selection("okx", _RegistryScenario._IDS[0]),
            _RegistryScenario._selection("bitfinex", _RegistryScenario._IDS[1]),
            _RegistryScenario._selection("coinbase", _RegistryScenario._IDS[2]),
        )
        registry = BookRegistry(_RegistryScenario._configuration(first, second, third))
        quotes = (
            _RegistryScenario._quote(
                first,
                0,
                100,
                bid=_RegistryScenario._side("101", "999999999999999999.000000000000000001"),
                ask=_RegistryScenario._side("105", "7"),
            ),
            _RegistryScenario._quote(
                second,
                0,
                101,
                bid=_RegistryScenario._side("101", "0.000000000000000002", 2),
                ask=_RegistryScenario._side("103", "2"),
            ),
            _RegistryScenario._quote(
                third,
                0,
                102,
                bid=_RegistryScenario._side("100", "8"),
                ask=_RegistryScenario._side("103", "3", 3),
            ),
        )
        with localcontext() as context:
            context.prec = 6
            for quote in quotes:
                registry.accept(quote)
            result = registry.consolidated("btc-usd", cutoff_ns=105)
        assert result.market_state == "two_sided"
        assert result.partial is False
        assert result.selected_keys == tuple(item.key for item in (first, second, third))
        assert result.eligible_keys == result.selected_keys
        assert result.bid is not None and result.ask is not None
        assert result.bid.price == Decimal("101")
        assert result.bid.quantity == Decimal("999999999999999999.000000000000000003")
        assert result.bid.venues == ("bitfinex", "okx")
        assert result.bid.contributions == (quotes[1], quotes[0])
        assert result.ask.price == Decimal("103") and result.ask.quantity == Decimal("5")
        assert result.ask.venues == ("bitfinex", "coinbase")
        assert result.ask.contributions == (quotes[1], quotes[2])
        assert tuple(book.reason for book in result.books) == ("eligible",) * 3
        assert result.books[0].quote == quotes[0]
        assert registry.lookup(first.key, cutoff_ns=105).quote == quotes[0]

    def test_cutoff_is_historical_and_expires_without_a_new_boundary(self) -> None:
        """Later cached prices cannot leak backward and age alone removes coverage."""
        first, second = (
            _RegistryScenario._selection("okx", _RegistryScenario._IDS[0], max_age_ns=20),
            _RegistryScenario._selection("bitfinex", _RegistryScenario._IDS[1], max_age_ns=20),
        )
        registry = BookRegistry(_RegistryScenario._configuration(first, second))
        old = _RegistryScenario._quote(
            first,
            0,
            100,
            bid=_RegistryScenario._side("99", "2"),
            ask=_RegistryScenario._side("101", "2"),
        )
        later = _RegistryScenario._quote(
            first,
            1,
            110,
            bid=_RegistryScenario._side("102", "3"),
            ask=_RegistryScenario._side("104", "3"),
            outcome="update",
        )
        other = _RegistryScenario._quote(
            second,
            0,
            105,
            bid=_RegistryScenario._side("98", "1"),
            ask=_RegistryScenario._side("103", "1"),
        )
        for quote in (old, other, later):
            registry.accept(quote)
        assert registry.lookup(first.key, cutoff_ns=99).reason == "not_yet_available"
        assert registry.lookup(first.key, cutoff_ns=105).quote == old
        assert registry.lookup(first.key, cutoff_ns=111).quote == later
        historical_bid = registry.consolidated("btc-usd", cutoff_ns=105).bid
        assert historical_bid is not None and historical_bid.price == Decimal("99")
        expired = registry.consolidated("btc-usd", cutoff_ns=131)
        assert expired.market_state == "unavailable"
        assert expired.partial is True and expired.eligible_keys == ()
        assert tuple(book.reason for book in expired.books) == ("stale", "stale")

    def test_delayed_delivery_source_clock_and_unknown_receipt_are_explicit(self) -> None:
        """Delivery, source-clock, and receipt cutoffs remain explicit."""
        selected = _RegistryScenario._selection(
            "okx", _RegistryScenario._IDS[0], source_clock="milliseconds", max_age_ns=2_000_000
        )
        registry = BookRegistry(_RegistryScenario._configuration(selected))
        future = _RegistryScenario._quote(
            selected,
            0,
            1_000_000,
            available_ns=1_100_000,
            source_time="2",
            bid=_RegistryScenario._side("100", "1"),
            ask=_RegistryScenario._side("101", "1"),
        )
        registry.accept(future)
        assert registry.lookup(selected.key, cutoff_ns=1_050_000).reason == "not_yet_available"
        assert registry.lookup(selected.key, cutoff_ns=1_500_000).reason == "future_source_time"
        assert registry.lookup(selected.key, cutoff_ns=2_000_000).quote == future
        unknown = _RegistryScenario._quote(
            selected,
            1,
            2_100_000,
            source_time=None,
            bid=_RegistryScenario._side("102", "1"),
            ask=_RegistryScenario._side("103", "1"),
            outcome="update",
        )
        registry.accept(unknown)
        assert registry.lookup(selected.key, cutoff_ns=2_100_000).reason == "unknown_source_time"

        delayed = _RegistryScenario._selection("bitfinex", _RegistryScenario._IDS[1], max_age_ns=20)
        late_registry = BookRegistry(_RegistryScenario._configuration(delayed))
        late = _RegistryScenario._quote(
            delayed,
            0,
            100,
            available_ns=130,
            bid=_RegistryScenario._side("100", "1"),
            ask=_RegistryScenario._side("101", "1"),
        )
        late_registry.accept(late)
        assert late_registry.lookup(delayed.key, cutoff_ns=120).reason == "not_yet_available"
        assert late_registry.lookup(delayed.key, cutoff_ns=130).reason == "stale"
        unknown_receipt = replace(
            late,
            position=1,
            received_ns=None,
            available_ns=140,
            outcome="update",
        )
        late_registry.accept(unknown_receipt)
        assert late_registry.lookup(delayed.key, cutoff_ns=140).reason == "unknown_receipt"

    def test_control_keeps_original_market_clock_then_disconnect_and_snapshot_recover(self) -> None:
        """A heartbeat cannot freshen a touch, while a gap hides it until a new epoch."""
        selected = _RegistryScenario._selection(
            "bitfinex", _RegistryScenario._IDS[0], max_age_ns=20
        )
        registry = BookRegistry(_RegistryScenario._configuration(selected))
        market = _RegistryScenario._quote(
            selected,
            0,
            100,
            bid=_RegistryScenario._side("100", "2"),
            ask=_RegistryScenario._side("101", "3"),
        )
        registry.accept(market)
        registry.accept(
            _RegistryScenario._quote(
                selected,
                1,
                110,
                outcome="heartbeat",
                state_identity=market.state_identity,
            )
        )
        assert registry.lookup(selected.key, cutoff_ns=115).quote == market
        assert registry.lookup(selected.key, cutoff_ns=121).reason == "stale"
        registry.accept(
            _RegistryScenario._quote(selected, 2, 122, outcome="gap", status="recovering")
        )
        assert registry.lookup(selected.key, cutoff_ns=122).reason == "unavailable"
        recovered = _RegistryScenario._quote(
            selected,
            3,
            125,
            epoch=1,
            bid=_RegistryScenario._side("102", "4"),
            ask=_RegistryScenario._side("103", "5"),
        )
        registry.accept(recovered)
        assert registry.lookup(selected.key, cutoff_ns=124).reason == "unavailable"
        assert registry.lookup(selected.key, cutoff_ns=125).quote == recovered

    def test_one_sided_empty_crossed_and_partial_coverage_are_named(self) -> None:
        """Consolidation keeps missing sides distinct from missing venue coverage."""
        first, second = (
            _RegistryScenario._selection("okx", _RegistryScenario._IDS[0]),
            _RegistryScenario._selection("bitfinex", _RegistryScenario._IDS[1]),
        )
        registry = BookRegistry(_RegistryScenario._configuration(first, second))
        assert registry.consolidated("btc-usd", cutoff_ns=90).market_state == "unavailable"
        registry.accept(
            _RegistryScenario._quote(first, 0, 100, bid=_RegistryScenario._side("100", "1"))
        )
        one = registry.consolidated("btc-usd", cutoff_ns=100)
        assert one.market_state == "one_sided" and one.partial is True
        assert one.ask is None and one.bid is not None
        assert one.books[1].reason == "missing"
        registry.accept(
            _RegistryScenario._quote(second, 0, 101, ask=_RegistryScenario._side("100", "2"))
        )
        assert registry.consolidated("btc-usd", cutoff_ns=101).market_state == "locked"
        registry.accept(
            _RegistryScenario._quote(
                second, 1, 102, outcome="update", ask=_RegistryScenario._side("99", "2")
            )
        )
        assert registry.consolidated("btc-usd", cutoff_ns=102).market_state == "crossed"
        registry.accept(_RegistryScenario._quote(first, 1, 103, outcome="update"))
        one_remaining = registry.consolidated("btc-usd", cutoff_ns=103)
        assert one_remaining.market_state == "one_sided" and one_remaining.partial is False
        registry.accept(_RegistryScenario._quote(second, 2, 104, outcome="update"))
        empty = registry.consolidated("btc-usd", cutoff_ns=104)
        assert empty.market_state == "empty" and empty.partial is False

    def test_binding_order_and_duplicate_guards_keep_other_books_intact(self) -> None:
        """A bad source, key or position cannot mutate another venue's accepted quote."""
        first, second = (
            _RegistryScenario._selection("okx", _RegistryScenario._IDS[0]),
            _RegistryScenario._selection("bitfinex", _RegistryScenario._IDS[1]),
        )
        registry = BookRegistry(_RegistryScenario._configuration(first, second))
        quote = _RegistryScenario._quote(
            first,
            0,
            100,
            bid=_RegistryScenario._side("100", "1"),
            ask=_RegistryScenario._side("101", "1"),
        )
        registry.accept(quote)
        registry.accept(quote)
        bad = (
            replace(quote, source_id="different-source"),
            replace(quote, channel="R0"),
            replace(quote, instrument_id=second.key.instrument_id),
            replace(quote, position=2, received_ns=110, available_ns=110),
            replace(quote, bid=_RegistryScenario._side("99", "1")),
        )
        for candidate in bad:
            with pytest.raises(ValueError):
                registry.accept(candidate)
            assert registry.lookup(first.key, cutoff_ns=100).quote == quote
        second_quote = _RegistryScenario._quote(
            second,
            0,
            101,
            bid=_RegistryScenario._side("98", "1"),
            ask=_RegistryScenario._side("102", "1"),
        )
        registry.accept(second_quote)
        assert registry.lookup(second.key, cutoff_ns=101).quote == second_quote
        with pytest.raises(ValueError):
            BookRegistry(_RegistryScenario._configuration(first)).accept(
                _RegistryScenario._quote(first, 1, 100)
            )
        with pytest.raises(ValueError):
            registry.accept(replace(_RegistryScenario._quote(first, 1, 90), available_ns=90))

    def test_equivalence_and_quality_admission_are_explicit(self) -> None:
        """Reference mapping never merges USD/USDT or another quantity unit."""
        usd = _RegistryScenario._selection("bitfinex", _RegistryScenario._IDS[0])
        usdt = _RegistryScenario._selection("okx", _RegistryScenario._IDS[1], quote_currency="USDT")
        with pytest.raises(ValueError, match="mismatch"):
            _RegistryScenario._configuration(usd, usdt)
        contracts = _RegistryScenario._selection(
            "okx", _RegistryScenario._IDS[1], unit=QuantityKind.CONTRACT
        )
        with pytest.raises(ValueError, match="mismatch"):
            _RegistryScenario._configuration(usd, contracts)
        duplicate_venue = _RegistryScenario._selection("bitfinex", _RegistryScenario._IDS[2])
        with pytest.raises(ValueError):
            _RegistryScenario._configuration(usd, duplicate_venue)
        without_equivalence = BookRegistry(
            _RegistryScenario._configuration(usd, usdt, equivalent=False)
        )
        without_equivalence.accept(
            _RegistryScenario._quote(usd, 0, 100, bid=_RegistryScenario._side("100", "1"))
        )
        without_equivalence.accept(
            _RegistryScenario._quote(usdt, 0, 100, bid=_RegistryScenario._side("100", "1"))
        )
        assert without_equivalence.lookup(usd.key, cutoff_ns=100).eligible
        assert without_equivalence.lookup(usdt.key, cutoff_ns=100).eligible
        with pytest.raises(ValueError):
            without_equivalence.consolidated("btc-usd", cutoff_ns=100)

        refused = _RegistryScenario._selection(
            "bitfinex", _RegistryScenario._IDS[2], allow_degraded=False
        )
        strict = BookRegistry(_RegistryScenario._configuration(refused))
        strict.accept(
            _RegistryScenario._quote(refused, 0, 100, bid=_RegistryScenario._side("100", "1"))
        )
        assert strict.lookup(refused.key, cutoff_ns=100).reason == "quality_not_admitted"

    def test_reference_interval_history_eviction_and_roundtrip(self) -> None:
        """History and reference knowledge have separate cutoffs and survive exact encoding."""
        selected = _RegistryScenario._selection("bitfinex", _RegistryScenario._IDS[0])
        config = _RegistryScenario._configuration(
            selected, capacity=2, known_ns=95, valid_from_ns=95, valid_to_ns=130
        )
        codec = DomainCodec()
        assert codec.decode_json(codec.encode_json(config), BookRegistryConfiguration) == config
        registry = BookRegistry(config)
        for position, received in enumerate((100, 110, 120)):
            registry.accept(
                _RegistryScenario._quote(
                    selected,
                    position,
                    received,
                    outcome="snapshot" if position == 0 else "update",
                    bid=_RegistryScenario._side(str(100 + position), "1"),
                    ask=_RegistryScenario._side(str(103 + position), "1"),
                )
            )
        assert registry.lookup(selected.key, cutoff_ns=100).reason == "history_evicted"
        assert registry.lookup(selected.key, cutoff_ns=115).quote is not None
        before = registry.consolidated("btc-usd", cutoff_ns=94)
        assert before.books[0].reason == "reference_unavailable"
        assert before.market_state == "unavailable"
        after = registry.consolidated("btc-usd", cutoff_ns=130)
        assert after.books[0].reason == "reference_unavailable"
        current = registry.consolidated("btc-usd", cutoff_ns=120)
        assert current.bid is not None and current.bid.price == Decimal("102")
        assert codec.decode_json(codec.encode_json(current), type(current)) == current

    def test_attached_native_okx_book_projects_and_invalidates_the_registry(self) -> None:
        """Use the installed decoder's whole-message boundary under explicit source admission."""
        capture = CaptureConfig.read(_RegistryScenario._ROOT / "configs/live/okx-btc-usdt.json")
        request = CaptureRequest(
            config=capture,
            recording_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            implementation_identity="b" * 64,
        )
        selection = BookSelection(
            instrument=InstrumentDefinition(
                instrument_id=capture.instrument_id,
                venue=capture.venue,
                symbol=capture.symbol,
                product="spot",
                base_currency=capture.base_currency,
                quote_currency=capture.quote_currency,
                calendar="continuous-utc",
            ),
            source_id=request.identity,
            capability=BookAdapters.capability(capture),
            quantity_unit=QuantityKind.BASE_UNIT,
            max_age_ns=1_000_000_000,
            allow_degraded=True,
        )
        registry = BookRegistry(_RegistryScenario._configuration(selection))
        registry.attach(request, book_factory=BookAdapters.create)
        registry.apply(
            selection.key,
            CaptureRecord(kind="session", epoch=0, received_ns=900_000_000),
            available_ns=900_000_000,
        )
        registry.apply(
            selection.key,
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=950_000_000,
                raw=b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}',
            ),
            available_ns=950_000_000,
        )
        snapshot = registry.apply(
            selection.key,
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=1_000_000_000,
                raw=DomainCodec().encode_json(
                    {
                        "arg": {"channel": "books", "instId": "BTC-USDT"},
                        "action": "snapshot",
                        "data": [
                            {
                                "prevSeqId": -1,
                                "seqId": 10,
                                "ts": "1000",
                                "bids": [["100", "2", "0", "1"]],
                                "asks": [["101", "3", "0", "1"]],
                            }
                        ],
                    }
                ),
            ),
            available_ns=1_000_000_000,
        )
        assert snapshot.bid == _RegistryScenario._side("100", "2")
        assert snapshot.ask == _RegistryScenario._side("101", "3")
        assert registry.lookup(selection.key, cutoff_ns=1_000_000_000).quote == snapshot
        with pytest.raises(ValueError, match="requires apply"):
            registry.accept(snapshot)
        with pytest.raises(ValueError):
            registry.attach(request, book_factory=BookAdapters.create)
        registry.apply(
            selection.key,
            CaptureRecord(
                kind="gap", epoch=0, received_ns=1_000_000_010, reason="disconnect_unknown_loss"
            ),
            available_ns=1_000_000_010,
        )
        assert registry.lookup(selection.key, cutoff_ns=1_000_000_009).quote == snapshot
        assert registry.lookup(selection.key, cutoff_ns=1_000_000_010).reason == "unavailable"

    def test_iso_source_fraction_does_not_leak_nanoseconds(self) -> None:
        """A sub-microsecond native clock remains future until its exact nanosecond."""
        selection = _RegistryScenario._selection(
            "coinbase", _RegistryScenario._IDS[0], source_clock="iso8601"
        )
        registry = BookRegistry(_RegistryScenario._configuration(selection))
        quote = _RegistryScenario._quote(
            selection,
            0,
            1,
            available_ns=1,
            source_time="1970-01-01T00:00:00.000000009Z",
            bid=_RegistryScenario._side("100", "1"),
        )
        registry.accept(quote)
        assert registry.lookup(selection.key, cutoff_ns=8).reason == "future_source_time"
        assert registry.lookup(selection.key, cutoff_ns=9).quote == quote
        malformed = replace(quote, position=1, source_time="1970-01-01T00:00:00.0000000091Z")
        registry.accept(malformed)
        assert registry.lookup(selection.key, cutoff_ns=9).reason == "unknown_source_time"

    def test_two_instruments_on_one_venue_keep_independent_state(self) -> None:
        """Updating one selected listing cannot overwrite another listing on that venue."""
        first = _RegistryScenario._selection("okx", _RegistryScenario._IDS[0])
        second = _RegistryScenario._selection("okx", _RegistryScenario._IDS[1], base_currency="ETH")
        registry = BookRegistry(_RegistryScenario._configuration(first, second, equivalent=False))
        left = _RegistryScenario._quote(first, 0, 10, bid=_RegistryScenario._side("100", "1"))
        right = _RegistryScenario._quote(second, 0, 10, ask=_RegistryScenario._side("200", "2"))
        registry.accept(left)
        registry.accept(right)
        registry.accept(
            replace(
                left,
                position=1,
                received_ns=20,
                available_ns=20,
                bid=_RegistryScenario._side("101", "3"),
            )
        )
        assert registry.lookup(second.key, cutoff_ns=20).quote == right
        assert registry.lookup(first.key, cutoff_ns=10).quote == left
        current = registry.lookup(first.key, cutoff_ns=20).quote
        assert current is not None and current.bid == _RegistryScenario._side("101", "3")
