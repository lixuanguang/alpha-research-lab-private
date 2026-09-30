"""Protect bounded reference queries, scoped projection and retained replay inputs."""

from __future__ import annotations

# standard library imports
from collections.abc import Generator
from datetime import timedelta
from decimal import Decimal
from threading import Event

# third party library imports
import pytest
from msgspec.structs import force_setattr
from test_asof import TestAsOfSelector as _Scenario

# project library imports
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import Occurrence, Trade
from market_data.query import AsOfSelector, QueryBatch, QueryColumn, QueryMarketRow, QueryReader
from market_data.validation import TradeRevision


class TestQueryReader:
    """Reuse admitted as-of scenarios to compare projection at the actual query boundary."""

    @staticmethod
    def _reader() -> QueryReader:
        """Build two bindings with an original, late correction and instrument-less controls."""
        fixture = _Scenario()
        payloads = []
        precedence = []
        for instrument in (0, 1):
            request = fixture._request(instrument=instrument)
            original = fixture._item(request)
            revised = fixture._item(request, capture=2, price="101.00", digest="b" * 64)
            control = fixture._item(request, position=1, capture=3, disconnect=True)
            payloads.append(
                fixture._canonical(
                    request,
                    (original, control, revised),
                    corrections=(fixture._correction(original, revised),),
                )
            )
            precedence.append(fixture._binding(request))
        return QueryReader(
            tuple(payloads),
            readers=SourceAdapters(),
            precedence=tuple(precedence),
            max_bytes=262_144,
        )

    @staticmethod
    def _batches(
        reader: QueryReader,
        *,
        seconds: int = 10,
        batch_size: int = 1,
        columns: tuple[QueryColumn, ...] = ("price",),
    ) -> Generator[QueryBatch]:
        """Select BTC at the shared scenario's business window and independent cutoff."""
        request = _Scenario._request()
        return reader.batches(
            (request.instrument.instrument_id,),
            start=request.start,
            end=request.end,
            known_at=request.start + timedelta(seconds=seconds),
            columns=columns,
            batch_size=batch_size,
        )

    @pytest.mark.parametrize("seconds", [0, 1, 5, 9, 10, 43_200, 1])
    def test_projection_matches_asof_with_late_corrections_and_membership(
        self, seconds: int
    ) -> None:
        """Projection cannot select a future correction or bypass a known exclusion."""
        reader = self._reader()
        request = _Scenario._request()
        expected = reader._selector.select(
            (request.instrument.instrument_id,),
            start=request.start,
            end=request.end,
            known_at=request.start + timedelta(seconds=seconds),
        )
        batches = list(self._batches(reader, seconds=seconds, columns=("revision",)))
        actual = tuple(
            row if isinstance(row, Occurrence) else row.values[0]
            for batch in batches
            for row in batch.rows
        )
        assert actual == expected
        assert all(len(batch.rows) <= 1 for batch in batches)
        assert all(len(batch.evidence) == 1 for batch in batches)
        assert batches[0].evidence[0].request == request
        assert batches[0].evidence[0].scope == "exploratory_degraded"
        assert batches[0].evidence[0].reasons

    def test_scoped_controls_survive_projection_and_left_boundary(self) -> None:
        """A price-only query still exposes the BTC disconnect and excludes ETH's control."""
        request = _Scenario._request()
        batches = list(
            self._reader().batches(
                (request.instrument.instrument_id,),
                start=request.start + timedelta(seconds=4),
                end=request.end,
                known_at=request.start + timedelta(seconds=10),
                columns=("price",),
                batch_size=1,
            )
        )
        assert len(batches) == 1 and len(batches[0].rows) == 1
        control = batches[0].rows[0]
        assert isinstance(control, Occurrence) and control.event.instrument_id is None
        assert control.request == request and control.origin.sha256 == "a" * 64

    def test_history_preserves_earlier_version_and_withdrawn_membership(self) -> None:
        """History retains economic predecessors and membership even after terminal exclusion."""
        request = _Scenario._request()
        reader = self._reader()
        history = list(
            reader.batches(
                (request.instrument.instrument_id,),
                start=request.start,
                end=request.end,
                known_at=request.start + timedelta(hours=12),
                columns=("revision", "price"),
                mode="history",
                batch_size=1,
            )
        )
        row = history[0].rows[0]
        assert isinstance(row, QueryMarketRow) and isinstance(row.values[0], TradeRevision)
        assert row.values[1] == Decimal("101.00") and row.values[0].previous is not None
        assert row.values[0].ts_knowledge == request.start + timedelta(seconds=10)
        assert isinstance(row.values[0].previous.occurrences[0].event, Trade)
        assert row.values[0].previous.occurrences[0].event.price == Decimal("100.00")
        assert len(history[0].evidence[0].eligibility.assertions) > 1
        earlier = list(
            reader.batches(
                (request.instrument.instrument_id,),
                start=request.start,
                end=request.end,
                known_at=request.start + timedelta(seconds=9),
                columns=("revision",),
                mode="history",
                batch_size=1,
            )
        )
        earlier_row = earlier[0].rows[0]
        assert (
            isinstance(earlier_row, QueryMarketRow)
            and earlier_row.values[0] == row.values[0].previous
        )
        assert history[0].identity != earlier[0].identity
        force_setattr(row.values[0], "schema_version", "unsafe")
        repeated = list(self._batches(reader))[1].rows[0]
        assert isinstance(repeated, QueryMarketRow) and repeated.values == (Decimal("101.00"),)

    def test_history_keeps_correction_that_retires_window_value(self) -> None:
        """A moved business timestamp must not leave a stale earlier version active in replay."""
        fixture = _Scenario()
        request = fixture._request()
        original = fixture._item(request)
        revised = fixture._item(request, capture=20, price="101.00", digest="b" * 64)
        payload = fixture._canonical(
            request, (original, revised), corrections=(fixture._correction(original, revised),)
        )
        reader = QueryReader(
            (payload,),
            readers=SourceAdapters(),
            precedence=(fixture._binding(request),),
            max_bytes=262_144,
        )
        history = list(
            reader.batches(
                (request.instrument.instrument_id,),
                start=request.start,
                end=request.start + timedelta(seconds=10),
                known_at=request.start + timedelta(seconds=20),
                columns=("revision",),
                batch_size=1,
                mode="history",
            )
        )
        row = history[0].rows[0]
        assert isinstance(row, QueryMarketRow) and isinstance(row.values[0], TradeRevision)
        assert row.values[0].previous is not None
        assert row.values[0].ts_knowledge == request.start + timedelta(seconds=20)

    def test_identity_batch_size_empty_results_cancellation_and_close(self) -> None:
        """Batch size changes delivery only; cancelled or closed queries cannot poison reuse."""
        reader = self._reader()
        one, many = list(self._batches(reader)), list(self._batches(reader, batch_size=10))
        assert one[0].identity == many[0].identity
        assert tuple(row for batch in one for row in batch.rows) == many[0].rows
        quantity_batches = list(self._batches(reader, columns=("quantity",)))
        assert quantity_batches[0].identity != one[0].identity
        empty = list(self._batches(reader, seconds=0))
        assert len(empty) == 1 and empty[0].rows == () and empty[0].evidence
        stop = Event()
        request = _Scenario._request()
        stream = reader.batches(
            (request.instrument.instrument_id,),
            start=request.start,
            end=request.end,
            known_at=request.start + timedelta(seconds=10),
            columns=("price",),
            batch_size=1,
            cancelled=stop.is_set,
        )
        assert next(stream) == one[0]
        stop.set()
        with pytest.raises(InterruptedError, match="query cancelled"):
            next(stream)
        stream = self._batches(reader)
        assert next(stream) == one[0]
        stream.close()
        assert list(stream) == [] and list(self._batches(reader)) == one
        with pytest.raises(InterruptedError):
            next(
                reader.batches(
                    (request.instrument.instrument_id,),
                    start=request.start,
                    end=request.end,
                    known_at=request.start,
                    columns=("price",),
                    batch_size=1,
                    cancelled=stop.is_set,
                )
            )

    @pytest.mark.parametrize("columns", [(), ("price", "price")])
    def test_invalid_projection_and_batch_bounds(self, columns: tuple[QueryColumn, ...]) -> None:
        """Reject invalid projections before returning even a control or evidence batch."""
        reader = self._reader()
        with pytest.raises(ValueError, match="unique supported columns"):
            list(self._batches(reader, columns=columns))
        for size in (0, -1, True):
            with pytest.raises(ValueError, match="positive batches"):
                list(self._batches(reader, batch_size=size))
        request = _Scenario._request()
        with pytest.raises(ValueError, match="history requires revision"):
            list(
                reader.batches(
                    (request.instrument.instrument_id,),
                    start=request.start,
                    end=request.end,
                    known_at=request.start,
                    columns=("price",),
                    batch_size=1,
                    mode="history",
                )
            )

    def test_total_budget_and_cross_partition_invariants(self) -> None:
        """Aggregate limits and original selector conflict checks remain mandatory."""
        fixture = _Scenario()
        request = fixture._request()
        payload = fixture._canonical(request, (fixture._item(request),))
        for limit in (0, True, len(payload) - 1):
            with pytest.raises(ValueError, match="max_bytes"):
                QueryReader(
                    (payload,),
                    readers=SourceAdapters(),
                    precedence=(fixture._binding(request),),
                    max_bytes=limit,
                )
        with pytest.raises(ValueError, match="overlapping"):
            QueryReader(
                (payload, payload),
                readers=SourceAdapters(),
                precedence=(fixture._binding(request),),
                max_bytes=262_144,
            )
        assert AsOfSelector(
            (payload,), readers=SourceAdapters(), precedence=(fixture._binding(request),)
        ).history == (payload,)

    def test_returned_evidence_cannot_mutate_cached_admission(self) -> None:
        """Unsafe mutations of returned policy and membership cannot alter later queries."""
        reader = self._reader()
        first = list(self._batches(reader))
        expected = list(self._batches(reader))
        evidence = first[0].evidence[0]
        force_setattr(evidence.policy, "max_gap", timedelta(0))
        force_setattr(evidence.eligibility.assertions[0], "state", "excluded")
        assert list(self._batches(reader)) == expected

    def test_partitions_of_one_result_share_isolated_evidence_copies(self) -> None:
        """Equal evidence is copied once per result, never shared with the cache or others."""
        fixture = _Scenario()
        requests = tuple(fixture._request(minute=minute) for minute in (0, 1))
        payloads = tuple(
            fixture._canonical(
                request, (fixture._item(request, capture=60 * minute + 1, trade_id=minute),)
            )
            for minute, request in enumerate(requests)
        )
        reader = QueryReader(
            payloads,
            readers=SourceAdapters(),
            precedence=(fixture._binding(requests[0]),),
            max_bytes=2_000_000,
        )
        selector = AsOfSelector(
            payloads, readers=SourceAdapters(), precedence=(fixture._binding(requests[0]),)
        )

        def query() -> list[QueryBatch]:
            """Select both BTC partitions at a cutoff after both."""
            return list(
                reader.batches(
                    (requests[0].instrument.instrument_id,),
                    start=requests[0].start,
                    end=requests[1].end,
                    known_at=requests[1].end,
                    columns=("price",),
                    batch_size=10,
                )
            )

        first, expected = query(), query()
        evidence = first[0].evidence
        # Values are exactly the admitted partitions' evidence.
        assert evidence == tuple(
            (p.request, p.scope, p.policy, p.eligibility, p.reasons) for p in selector._partitions
        )
        assert evidence[0].request.manifest is evidence[1].request.manifest
        assert evidence[0].eligibility is evidence[1].eligibility
        assert evidence[0].request.manifest is not expected[0].evidence[0].request.manifest
        force_setattr(evidence[1].eligibility.assertions[0], "state", "excluded")
        force_setattr(evidence[1].request.manifest, "implementation_identity", "0" * 64)
        force_setattr(evidence[1].policy, "max_gap", timedelta(0))
        assert query() == expected
