"""Keep the durable as-of book index equal to a registry that retained every boundary."""

from __future__ import annotations

# standard library imports
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

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

    def test_rows_before_the_first_market_and_after_it_resolve_like_the_registry(
        self, tmp_path: Path
    ) -> None:
        """Rows before the reference market stay plain; later rows decode against it."""
        selection = _Scenario._selection("okx", _Scenario._IDS[0], max_age_ns=50)
        registry = BookRegistry(_Scenario._configuration(selection, equivalent=False, capacity=100))
        index = BookAsOfIndex.create(tmp_path / "late.index.sqlite3")
        quotes = (
            _Scenario._quote(selection, 0, 90, outcome="session", status="unavailable"),
            _Scenario._quote(selection, 1, 95, outcome="acknowledgement", status="unavailable"),
            _Scenario._quote(
                selection, 2, 100, bid=_Scenario._side("1", "2"), ask=_Scenario._side("2", "1")
            ),
            _Scenario._quote(
                selection, 3, 100, bid=_Scenario._side("1", "3"), ask=_Scenario._side("2", "1")
            ),
        )
        offset = 0
        for quote in quotes:
            registry.accept(quote)
            latest = registry.latest(selection.key)
            assert latest is not None
            index.append(*latest, offset=offset, length=7)
            offset += 7
        index.close()
        with closing(sqlite3.connect(index.path)) as connection:
            reference = cast(
                list[tuple[int]],
                connection.execute("SELECT position FROM boundary_reference").fetchall(),
            )
            carried = cast(
                list[tuple[int, int | None]],
                connection.execute(
                    "SELECT position, market_position FROM boundaries ORDER BY position"
                ).fetchall(),
            )
        assert reference == [(2,)]
        assert carried == [(0, None), (1, None), (2, 2), (3, 3)]
        reader = BookAsOfIndex(index.path)
        for cutoff in range(85, 160):
            lookup, selected = reader.lookup(selection, cutoff_ns=cutoff)
            assert lookup == registry.lookup(selection.key, cutoff_ns=cutoff)
            target = lookup.quote if lookup.quote is not None else lookup.boundary
            assert selected == (None if target is None else (7 * target.position, 7))
        # Equal availability: the later of the two boundaries is the one available.
        tied, _ = reader.lookup(selection, cutoff_ns=100)
        assert tied.boundary is not None and tied.boundary.position == 3

    def test_a_market_that_is_not_a_retained_boundary_is_refused(self, tmp_path: Path) -> None:
        """A row names its carried market by position, so the market must be one it holds."""
        selection = _Scenario._selection("okx", _Scenario._IDS[0])
        index = BookAsOfIndex.create(tmp_path / "carried.index.sqlite3")
        first = _Scenario._quote(selection, 0, 100, bid=_Scenario._side("1", "1"))
        other = _Scenario._quote(selection, 0, 100, bid=_Scenario._side("1", "2"))
        with pytest.raises(ValueError, match="boundary it retains"):
            index.append(first, other, offset=0, length=4)
        index.append(first, first, offset=0, length=4)
        later = _Scenario._quote(selection, 1, 110, outcome="heartbeat")
        unretained = _Scenario._quote(selection, 1, 110, bid=_Scenario._side("1", "1"))
        for market in (other, unretained):
            with pytest.raises(ValueError, match="boundary it retains"):
                index.append(later, market, offset=4, length=4)
        index.append(later, first, offset=4, length=4)
        lookup, selected = index.lookup(selection, cutoff_ns=110)
        assert lookup.quote == first and selected == (0, 4)
        index.close()

    def test_an_earlier_layout_or_damaged_rows_are_refused(self, tmp_path: Path) -> None:
        """An index in another layout is unsupported; a damaged frame is not decoded."""
        selection = _Scenario._selection("okx", _Scenario._IDS[0])
        earlier = tmp_path / "earlier.index.sqlite3"
        with closing(sqlite3.connect(earlier)) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS boundaries (position INTEGER PRIMARY KEY, "
                "available_ns INTEGER NOT NULL, boundary BLOB NOT NULL, market BLOB, "
                "offset INTEGER NOT NULL, length INTEGER NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS boundaries_available "
                "ON boundaries(available_ns, position)"
            )
        with pytest.raises(ValueError, match="unsupported book as-of index schema"):
            BookAsOfIndex(earlier).covered_bytes()
        with pytest.raises(ValueError, match="unsupported book as-of index schema"):
            BookAsOfIndex(earlier).lookup(selection, cutoff_ns=1)
        index = BookAsOfIndex.create(tmp_path / "damaged.index.sqlite3")
        first = _Scenario._quote(selection, 0, 100, bid=_Scenario._side("1", "1"))
        index.append(first, first, offset=0, length=4)
        index.close()
        with closing(sqlite3.connect(index.path)) as connection:
            connection.execute("UPDATE boundaries SET boundary = substr(boundary, 1, 8)")
            connection.commit()
        with pytest.raises(ValueError, match="frame is malformed"):
            BookAsOfIndex(index.path).lookup(selection, cutoff_ns=100)

    def test_a_refused_append_leaves_the_index_continuing_from_its_last_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed write rolls back and never advances the next expected position or range."""
        selection = _Scenario._selection("okx", _Scenario._IDS[0])
        index = BookAsOfIndex.create(tmp_path / "rollback.index.sqlite3")
        first = _Scenario._quote(selection, 0, 100, bid=_Scenario._side("1", "1"))
        monkeypatch.setattr(BookAsOfIndex, "_maximum_quote_bytes", 8)
        with pytest.raises(ValueError, match="exceeds its bound"):
            index.append(first, first, offset=0, length=4)
        monkeypatch.undo()
        assert index.covered_bytes() == 0
        with closing(sqlite3.connect(index.path)) as connection:
            count = cast(
                tuple[int], connection.execute("SELECT count(*) FROM boundary_reference").fetchone()
            )
        assert count == (0,)
        index.append(first, first, offset=0, length=4)
        index.append(_Scenario._quote(selection, 1, 101), None, offset=4, length=4)
        assert index.covered_bytes() == 8
        assert index.lookup(selection, cutoff_ns=100)[0].quote == first
        index.close()


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
