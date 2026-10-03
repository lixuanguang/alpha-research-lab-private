"""Keep the durable as-of book index equal to a registry that retained every boundary."""

from __future__ import annotations

# standard library imports
from pathlib import Path

# third party library imports
import pytest
from test_book_registry import _RegistryScenario as _Scenario

# project library imports
from configuration import BookSelection
from market_data.books import BookAsOfIndex, BookRegistry
from market_data.contracts import BookQuote


class TestBookAsOfIndex:
    """Select the market delivery as of every cutoff and refuse invalid appends."""

    def test_every_cutoff_matches_the_registry_and_selects_the_market_delivery(
        self,
        tmp_path: Path,
    ) -> None:
        """Carried markets, staleness, gaps and recovery resolve exactly as the registry does."""
        selection = _Scenario._selection("bitfinex", _Scenario._IDS[0], max_age_ns=20)
        index, registry, ranges = BookAsOfFixture.index(tmp_path, selection)
        index.close()
        reader = BookAsOfIndex(index.path)
        for cutoff in range(95, 160):
            lookup, selected = reader.lookup(selection, cutoff_ns=cutoff)
            assert lookup == registry.lookup(selection.key, cutoff_ns=cutoff)
            target = lookup.quote if lookup.quote is not None else lookup.boundary
            assert selected == (None if target is None else ranges[target.position])
        carried, selected = reader.lookup(selection, cutoff_ns=115)
        assert carried.boundary is not None and carried.boundary.position == 1
        assert carried.quote is not None and carried.quote.position == 0
        assert selected == ranges[0]
        assert reader.covered_bytes() == sum(length for _, length in ranges.values())

    def test_empty_and_missing_indexes_and_invalid_cutoffs_are_explicit(
        self, tmp_path: Path
    ) -> None:
        """No row is missing, a later-only row is not yet available, and bad cutoffs fail."""
        selection = _Scenario._selection("okx", _Scenario._IDS[0])
        index = BookAsOfIndex.create(tmp_path / "empty.index.sqlite3")
        assert index.lookup(selection, cutoff_ns=5)[0].reason == "missing"
        assert index.covered_bytes() == 0
        boundary = _Scenario._quote(selection, 0, 50, bid=_Scenario._side("1", "1"))
        index.append(boundary, boundary, offset=0, length=4)
        assert index.lookup(selection, cutoff_ns=49)[1] is None
        assert index.lookup(selection, cutoff_ns=49)[0].reason == "not_yet_available"
        with pytest.raises(ValueError, match="nonnegative"):
            index.lookup(selection, cutoff_ns=-1)
        with pytest.raises(ValueError, match="missing"):
            BookAsOfIndex(tmp_path / "absent.sqlite3").lookup(selection, cutoff_ns=1)
        with pytest.raises(ValueError, match="already exists"):
            BookAsOfIndex.create(index.path)
        index.close()

    def test_append_refuses_gaps_regressions_and_detached_writers(self, tmp_path: Path) -> None:
        """Positions, availability and byte ranges must continue the retained log exactly."""
        selection = _Scenario._selection("okx", _Scenario._IDS[0])
        index = BookAsOfIndex.create(tmp_path / "strict.index.sqlite3")
        first = _Scenario._quote(selection, 0, 100)
        index.append(first, None, offset=0, length=8)
        for boundary, offset in (
            (_Scenario._quote(selection, 2, 110), 8),
            (_Scenario._quote(selection, 1, 95, available_ns=99), 8),
            (_Scenario._quote(selection, 1, 110), 9),
        ):
            with pytest.raises(ValueError, match="contiguous"):
                index.append(boundary, None, offset=offset, length=4)
        with pytest.raises(ValueError, match="byte range"):
            index.append(_Scenario._quote(selection, 1, 110), None, offset=8, length=0)
        index.close()
        with pytest.raises(ValueError, match="not open"):
            index.append(_Scenario._quote(selection, 1, 110), None, offset=8, length=4)
        assert BookAsOfIndex(index.path).covered_bytes() == 8


class BookAsOfFixture:
    """Build book boundaries and as-of indexes."""

    @staticmethod
    def boundaries(selection: BookSelection) -> tuple[BookQuote, ...]:
        """Cover a market, a carried heartbeat, a disconnect and a new-epoch recovery."""
        market = _Scenario._quote(
            selection,
            0,
            100,
            bid=_Scenario._side("100", "2"),
            ask=_Scenario._side("101", "3"),
        )
        return (
            market,
            _Scenario._quote(
                selection, 1, 110, outcome="heartbeat", state_identity=market.state_identity
            ),
            _Scenario._quote(selection, 2, 122, outcome="gap", status="recovering"),
            _Scenario._quote(
                selection,
                3,
                125,
                epoch=1,
                bid=_Scenario._side("102", "4"),
                ask=_Scenario._side("103", "5"),
            ),
            _Scenario._quote(selection, 4, 125, available_ns=130, bid=_Scenario._side("104", "1")),
        )

    @staticmethod
    def index(
        tmp_path: Path, selection: BookSelection
    ) -> tuple[BookAsOfIndex, BookRegistry, dict[int, tuple[int, int]]]:
        """Feed the same boundaries to a registry and an index with contiguous byte ranges."""
        registry = BookRegistry(_Scenario._configuration(selection, equivalent=False, capacity=100))
        index = BookAsOfIndex.create(tmp_path / "deliveries.index.sqlite3")
        ranges: dict[int, tuple[int, int]] = {}
        offset = 0
        for position, boundary in enumerate(BookAsOfFixture.boundaries(selection)):
            registry.accept(boundary)
            latest = registry.latest(selection.key)
            assert latest is not None
            length = 10 + position
            index.append(*latest, offset=offset, length=length)
            ranges[position] = (offset, length)
            offset += length
        return index, registry, ranges
