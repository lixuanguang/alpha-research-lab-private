"""Test venue sessions, market state, settlement, and timezone behavior."""

from __future__ import annotations

# standard library imports
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

# third party library imports
import pytest
from venue_calendar_cases import _CalendarTestData

# project library imports
from reference_data.calendars import (
    EXCHANGE_CALENDARS_VERSION,
    AuctionKind,
    AuctionWindow,
    CalendarClosure,
    CalendarCoverageError,
    ClosureKind,
    ExchangeCalendarsAdapter,
    InterruptionKind,
    MarketIdentifierCode,
    MarketInterruption,
    MarketState,
    MarketStatus,
    PriceLimitState,
    PriceLimitWindow,
    SessionKind,
    SessionOverride,
    SessionOverrideAction,
    SettlementCalendar,
    UnknownSessionError,
    UnknownSettlementDateError,
    VenueCalendarSnapshot,
    VenueCalendarValidationError,
)


class TestVenueCalendarSessionContracts(_CalendarTestData):
    """Exercise bounded session, market-state and settlement contracts."""

    @pytest.mark.parametrize("label", [date(2024, 3, 10), date(2024, 3, 11)])
    def test_overnight_session_outside_label_coverage_is_unknown(self, label: date) -> None:
        """An omitted next-label session cannot be mistaken for a closed local evening."""
        adapter = ExchangeCalendarsAdapter()
        venue = self._venue(mic="XCME", timezone_name="America/Chicago")
        narrow = adapter.build_snapshot(
            venue=venue,
            calendar_name="CMES",
            version=self._version(),
            start=label,
            end=label,
        )
        wider = adapter.build_snapshot(
            venue=venue,
            calendar_name="CMES",
            version=self._version(),
            start=label,
            end=label + timedelta(days=1),
        )
        instant = datetime.combine(label, datetime.min.time(), UTC) + timedelta(hours=23)

        assert wider.market_state_at(instant).status is MarketStatus.CONTINUOUS
        with pytest.raises(CalendarCoverageError, match="outside snapshot coverage"):
            narrow.market_state_at(instant)

    def test_closed_state_requires_neighboring_sessions(self) -> None:
        """Retained sessions bound a closed weekend, while edge instants remain unknown."""
        snapshot = ExchangeCalendarsAdapter().build_snapshot(
            venue=self._venue(),
            calendar_name="XNYS",
            version=self._version(),
            start=date(2024, 3, 8),
            end=date(2024, 3, 11),
        )

        assert snapshot.market_state_at(datetime(2024, 3, 10, 16, tzinfo=UTC)).status is (
            MarketStatus.CLOSED
        )
        for instant in (
            snapshot.sessions[0].opens_at - timedelta(microseconds=1),
            snapshot.sessions[-1].closes_at,
        ):
            with pytest.raises(CalendarCoverageError, match="outside snapshot coverage"):
                snapshot.market_state_at(instant)

    def test_adapter_matches_pinned_cross_timezone_dst_half_day_and_break_fixture(
        self,
    ) -> None:
        """Match pinned venue sessions, DST shifts, half days and breaks to golden UTC instants."""
        fixture = self._load_fixture()
        assert fixture["adapter_version"] == EXCHANGE_CALENDARS_VERSION
        adapter = ExchangeCalendarsAdapter()

        venues = fixture["venues"]
        for raw_venue in venues:
            calendar_name = raw_venue["calendar_name"]
            raw_range = raw_venue["range"]
            snapshot = adapter.build_snapshot(
                venue=self._venue(
                    identifier=raw_venue["venue_id"],
                    mic=raw_venue["mic"],
                    timezone_name=raw_venue["timezone_name"],
                ),
                calendar_name=calendar_name,
                version=self._version(),
                start=date.fromisoformat(raw_range[0]),
                end=date.fromisoformat(raw_range[1]),
            )
            expected_sessions = raw_venue["expected_sessions"]
            for expected in expected_sessions:
                session = snapshot.session_for_label(date.fromisoformat(expected["session_label"]))
                assert session.opens_at == self._instant(expected["opens_at"])
                assert session.closes_at == self._instant(expected["closes_at"])
                assert session.kind is SessionKind(expected["kind"])
                assert snapshot.market_state_at(session.opens_at).status is MarketStatus.CONTINUOUS
                if "break_starts_at" in expected:
                    assert session.break_starts_at == self._instant(expected["break_starts_at"])
                    assert session.break_ends_at == self._instant(expected["break_ends_at"])

    def test_named_holiday_closure_is_attributed_and_cannot_be_a_session(self) -> None:
        """Retain holiday attribution and reject a date that is both a closure and a session."""
        fixture = self._load_fixture()
        raw_venues = fixture["venues"]
        raw_venue = raw_venues[0]
        raw_holiday = raw_venue["holiday"]
        holiday = CalendarClosure(
            calendar_date=date.fromisoformat(raw_holiday["calendar_date"]),
            kind=ClosureKind.HOLIDAY,
            name=raw_holiday["name"],
            source="fixture.exchange",
            source_revision="holiday",
        )
        snapshot = ExchangeCalendarsAdapter().build_snapshot(
            venue=self._venue(),
            calendar_name="XNYS",
            version=self._version(),
            start=date(2024, 11, 27),
            end=date(2024, 11, 29),
            closures=(holiday,),
        )

        assert snapshot.closure_for_date(date(2024, 11, 28)) == holiday
        with pytest.raises(UnknownSessionError, match="unknown session label 2024-11-28"):
            snapshot.session_for_label(date(2024, 11, 28))
        with pytest.raises(VenueCalendarValidationError, match="cannot also be a session"):
            VenueCalendarSnapshot(
                venue=snapshot.venue,
                version=snapshot.version,
                covered_from=snapshot.covered_from,
                covered_through=snapshot.covered_through,
                sessions=snapshot.sessions,
                closures=(
                    CalendarClosure(
                        calendar_date=date(2024, 11, 29),
                        kind=ClosureKind.AD_HOC,
                        name="Invalid collision",
                        source="fixture.exchange",
                        source_revision="collision",
                    ),
                ),
            )

    def test_versioned_override_add_replace_and_remove_actions_are_exact(self) -> None:
        """Apply each versioned override action and retain its ordered provenance record."""
        adapter = ExchangeCalendarsAdapter()
        saturday = self._session(
            label=date(2024, 3, 9),
            opens_at=datetime(2024, 3, 9, 14, 30, tzinfo=UTC),
            closes_at=datetime(2024, 3, 9, 15, 0, tzinfo=UTC),
            break_starts_at=None,
            break_ends_at=None,
        )
        replacement = self._session(
            label=date(2024, 3, 11),
            opens_at=datetime(2024, 3, 11, 14, 0, tzinfo=UTC),
            closes_at=datetime(2024, 3, 11, 18, 0, tzinfo=UTC),
            break_starts_at=None,
            break_ends_at=None,
        )
        snapshot = adapter.build_snapshot(
            venue=self._venue(),
            calendar_name="XNYS",
            version=self._version(overridden=True),
            start=date(2024, 3, 8),
            end=date(2024, 3, 12),
            overrides=(
                SessionOverride(
                    override_id="remove-2024-03-08",
                    action=SessionOverrideAction.REMOVE,
                    session_label=date(2024, 3, 8),
                    reason="Synthetic emergency closure",
                    source="fixture.overrides",
                    source_revision="override",
                ),
                SessionOverride(
                    override_id="add-2024-03-09",
                    action=SessionOverrideAction.ADD,
                    session_label=date(2024, 3, 9),
                    replacement=saturday,
                    reason="Synthetic special session",
                    source="fixture.overrides",
                    source_revision="override",
                ),
                SessionOverride(
                    override_id="replace-2024-03-11",
                    action=SessionOverrideAction.REPLACE,
                    session_label=date(2024, 3, 11),
                    replacement=replacement,
                    reason="Synthetic shortened session",
                    source="fixture.overrides",
                    source_revision="override",
                ),
            ),
        )

        with pytest.raises(UnknownSessionError):
            snapshot.session_for_label(date(2024, 3, 8))
        assert snapshot.session_for_label(date(2024, 3, 9)) == saturday
        assert snapshot.session_for_label(date(2024, 3, 11)) == replacement
        assert tuple(item.override_id for item in snapshot.applied_overrides) == (
            "remove-2024-03-08",
            "add-2024-03-09",
            "replace-2024-03-11",
        )

    @pytest.mark.parametrize(
        ("action", "label", "message"),
        [
            (SessionOverrideAction.ADD, date(2024, 3, 11), "absent base session"),
            (SessionOverrideAction.REPLACE, date(2024, 3, 10), "existing base session"),
            (SessionOverrideAction.REMOVE, date(2024, 3, 10), "existing base session"),
        ],
    )
    def test_invalid_override_target_fails_closed(
        self, action: SessionOverrideAction, label: date, message: str
    ) -> None:
        """Reject additions to existing sessions and replacements or removals of absent sessions."""
        replacement = None
        if action is not SessionOverrideAction.REMOVE:
            replacement = self._session(
                label=label,
                opens_at=datetime.combine(label, datetime.min.time(), tzinfo=UTC),
                closes_at=datetime.combine(label, datetime.min.time(), tzinfo=UTC)
                + timedelta(hours=1),
                break_starts_at=None,
                break_ends_at=None,
            )
        override = SessionOverride(
            override_id=f"invalid-{action.value}",
            action=action,
            session_label=label,
            replacement=replacement,
            reason="Synthetic invalid target",
            source="fixture.overrides",
            source_revision="override",
        )
        with pytest.raises(VenueCalendarValidationError, match=message):
            ExchangeCalendarsAdapter().build_snapshot(
                venue=self._venue(),
                calendar_name="XNYS",
                version=self._version(overridden=True),
                start=date(2024, 3, 11),
                end=date(2024, 3, 12),
                overrides=(override,),
            )

    @pytest.mark.parametrize("action", list(SessionOverrideAction))
    def test_direct_snapshot_rejects_override_records_that_disagree_with_sessions(
        self,
        action: SessionOverrideAction,
    ) -> None:
        """Reject retained override actions whose result disagrees with snapshot sessions."""
        session = self._session()
        override = SessionOverride(
            override_id="inconsistent-result",
            action=action,
            session_label=session.session_label,
            reason="Synthetic inconsistent retained record",
            source="fixture.overrides",
            source_revision="override",
            replacement=None if action is SessionOverrideAction.REMOVE else session,
        )
        with pytest.raises(VenueCalendarValidationError, match=r"applied .* override must"):
            VenueCalendarSnapshot(
                venue=self._venue(),
                version=self._version(overridden=True),
                covered_from=session.session_label,
                covered_through=session.session_label,
                sessions=(session,) if action is SessionOverrideAction.REMOVE else (),
                applied_overrides=(override,),
            )

    def test_market_state_precedence_and_half_open_boundaries(self) -> None:
        """Project auction, halt, limit and break transitions with exact boundaries and coverage."""
        raw_state = self._load_fixture()["synthetic_market_state"]
        raw_auction = raw_state["opening_auction"]
        raw_halt = raw_state["halt"]
        raw_limit = raw_state["limit_up"]
        auction = AuctionWindow(
            kind=AuctionKind.OPENING,
            starts_at=self._instant(raw_auction[0]),
            ends_at=self._instant(raw_auction[1]),
        )
        session = self._session(auctions=(auction,))
        interruption = MarketInterruption(
            interruption_id="synthetic-halt-1",
            kind=InterruptionKind.HALT,
            starts_at=self._instant(raw_halt[0]),
            ends_at=self._instant(raw_halt[1]),
            reason="Synthetic volatility halt",
            source="fixture.market",
            source_revision="market",
        )
        price_limit = PriceLimitWindow(
            limit_id="synthetic-limit-1",
            state=PriceLimitState.LIMIT_UP,
            starts_at=self._instant(raw_limit[0]),
            ends_at=self._instant(raw_limit[1]),
            source="fixture.market",
            source_revision="market",
        )
        snapshot = VenueCalendarSnapshot(
            venue=self._venue(
                identifier="33333333-3333-4333-8333-333333333333",
                mic="XHKG",
                timezone_name="Asia/Hong_Kong",
            ),
            version=self._version(overridden=True),
            covered_from=date(2024, 3, 10),
            covered_through=date(2024, 3, 12),
            sessions=(
                self._session(
                    label=date(2024, 3, 10),
                    opens_at=session.opens_at - timedelta(days=1),
                    closes_at=session.closes_at - timedelta(days=1),
                    break_starts_at=None,
                    break_ends_at=None,
                ),
                session,
                self._session(
                    label=date(2024, 3, 12),
                    opens_at=session.opens_at + timedelta(days=1),
                    closes_at=session.closes_at + timedelta(days=1),
                    break_starts_at=None,
                    break_ends_at=None,
                ),
            ),
            interruptions=(interruption,),
            price_limits=(price_limit,),
        )

        assert snapshot.market_state_at(session.opens_at - timedelta(microseconds=1)).status is (
            MarketStatus.CLOSED
        )
        opening = snapshot.market_state_at(session.opens_at)
        assert opening.status is MarketStatus.AUCTION
        assert opening.auction_kind is AuctionKind.OPENING
        assert snapshot.market_state_at(auction.ends_at).status is MarketStatus.CONTINUOUS
        halted_and_limited = snapshot.market_state_at(datetime(2024, 3, 11, 2, 5, tzinfo=UTC))
        assert halted_and_limited.status is MarketStatus.HALTED
        assert halted_and_limited.price_limit_state is PriceLimitState.LIMIT_UP
        after_halt = snapshot.market_state_at(interruption.ends_at)
        assert after_halt.status is MarketStatus.CONTINUOUS
        assert after_halt.price_limit_state is PriceLimitState.LIMIT_UP
        assert (
            snapshot.market_state_at(price_limit.ends_at).price_limit_state is PriceLimitState.NONE
        )
        assert session.break_starts_at is not None
        assert session.break_ends_at is not None
        assert snapshot.market_state_at(session.break_starts_at).status is MarketStatus.BREAK
        assert snapshot.market_state_at(session.break_ends_at).status is MarketStatus.CONTINUOUS
        assert snapshot.market_state_at(session.closes_at).status is MarketStatus.CLOSED
        with pytest.raises(CalendarCoverageError, match="outside snapshot coverage"):
            snapshot.market_state_at(datetime(2024, 3, 13, 2, 0, tzinfo=UTC))
        with pytest.raises(CalendarCoverageError, match="outside snapshot coverage"):
            snapshot.closure_for_date(date(2024, 3, 13))

    @pytest.mark.parametrize("halt_start", ["2024-03-11T01:32:00Z", "2024-03-11T04:10:00Z"])
    def test_halt_takes_precedence_over_auction_and_break(self, halt_start: str) -> None:
        """Project a halt during either an auction or a scheduled break as HALTED."""
        session = self._session(
            auctions=(
                AuctionWindow(
                    kind=AuctionKind.OPENING,
                    starts_at=datetime(2024, 3, 11, 1, 30, tzinfo=UTC),
                    ends_at=datetime(2024, 3, 11, 1, 35, tzinfo=UTC),
                ),
            )
        )
        starts_at = self._instant(halt_start)
        snapshot = VenueCalendarSnapshot(
            venue=self._venue(),
            version=self._version(),
            covered_from=session.session_label,
            covered_through=session.session_label,
            sessions=(session,),
            interruptions=(
                MarketInterruption(
                    interruption_id="priority-halt",
                    kind=InterruptionKind.HALT,
                    starts_at=starts_at,
                    ends_at=starts_at + timedelta(minutes=1),
                    reason="Synthetic phase precedence",
                    source="fixture.market",
                    source_revision="v1",
                ),
            ),
        )

        assert snapshot.market_state_at(starts_at).status is MarketStatus.HALTED

    @pytest.mark.parametrize(
        "limit_state",
        [PriceLimitState.LIMIT_UP, PriceLimitState.LIMIT_DOWN, PriceLimitState.LOCKED],
    )
    def test_non_normal_limit_state_is_independent_of_continuous_phase(
        self,
        limit_state: PriceLimitState,
    ) -> None:
        """Retain the continuous phase while separately reporting each active price-limit state."""
        starts_at = datetime(2024, 3, 11, 2, 0, tzinfo=UTC)
        snapshot = VenueCalendarSnapshot(
            venue=self._venue(),
            version=self._version(),
            covered_from=date(2024, 3, 11),
            covered_through=date(2024, 3, 11),
            sessions=(self._session(),),
            price_limits=(
                PriceLimitWindow(
                    limit_id="synthetic-limit",
                    state=limit_state,
                    starts_at=starts_at,
                    ends_at=starts_at + timedelta(minutes=1),
                    source="fixture.market",
                    source_revision="v1",
                ),
            ),
        )

        state = snapshot.market_state_at(starts_at)
        assert state.status is MarketStatus.CONTINUOUS
        assert state.price_limit_state is limit_state

    def test_settlement_calendar_is_bounded_and_does_not_infer_conventions(
        self,
    ) -> None:
        """Search explicit settlement dates and reject uncovered or exhausted date requests."""
        raw_calendar = self._load_fixture()["settlement_calendar"]
        raw_range = raw_calendar["range"]
        raw_dates = raw_calendar["settlement_dates"]
        calendar = SettlementCalendar(
            calendar_id="synthetic-usd-settlement",
            calendar_version="settlement",
            timezone_name="America/New_York",
            covered_from=date.fromisoformat(raw_range[0]),
            covered_through=date.fromisoformat(raw_range[1]),
            settlement_dates=tuple(date.fromisoformat(item) for item in raw_dates),
            source="fixture.settlement",
            source_revision="settlement",
        )

        assert calendar.is_settlement_day(date(2024, 11, 28)) is False
        assert calendar.settlement_day_on_or_after(date(2024, 11, 28)) == date(2024, 11, 29)
        with pytest.raises(UnknownSettlementDateError, match="outside calendar coverage"):
            calendar.is_settlement_day(date(2024, 11, 26))
        with pytest.raises(UnknownSettlementDateError, match="outside calendar coverage"):
            calendar.settlement_day_on_or_after(date(2024, 11, 26))
        with pytest.raises(UnknownSettlementDateError, match="no settlement date"):
            calendar.settlement_day_on_or_after(date(2024, 12, 3))

    @pytest.mark.parametrize(
        "bad_mic",
        ["xnys", "NYS", "XNYS ", "XNYS1", "X-YZ"],
    )
    def test_invalid_mic_fails_without_normalization(self, bad_mic: str) -> None:
        """Reject noncanonical market identifier codes without trimming or changing case."""
        with pytest.raises(VenueCalendarValidationError, match="four uppercase ASCII"):
            MarketIdentifierCode(value=bad_mic)

    def test_invalid_time_and_interval_state_fails_closed(self) -> None:
        """Reject naive or non-UTC times, invalid breaks and NONE price-limit windows."""
        with pytest.raises(VenueCalendarValidationError, match="timezone-aware UTC"):
            self._session(opens_at=datetime(2024, 3, 11, 1, 30))
        with pytest.raises(VenueCalendarValidationError, match="must use UTC"):
            self._venue().local_time(
                datetime(2024, 3, 11, 1, 30, tzinfo=ZoneInfo("Asia/Singapore"))
            )
        with pytest.raises(VenueCalendarValidationError, match="strictly inside"):
            self._session(break_starts_at=datetime(2024, 3, 11, 1, 0, tzinfo=UTC))
        with pytest.raises(VenueCalendarValidationError, match="non-NONE"):
            PriceLimitWindow(
                limit_id="invalid-none",
                state=PriceLimitState.NONE,
                starts_at=datetime(2024, 3, 11, 2, 0, tzinfo=UTC),
                ends_at=datetime(2024, 3, 11, 2, 1, tzinfo=UTC),
                source="fixture.market",
                source_revision="market",
            )

    @pytest.mark.parametrize(
        ("mutation", "message"),
        [
            ("overlap", "cannot overlap"),
            ("duplicate", "labels must be unique"),
            ("reversed", "ordered by opening instant"),
            ("outside", "outside snapshot coverage"),
        ],
    )
    def test_snapshot_session_graph_rejects_invalid_state(
        self, mutation: str, message: str
    ) -> None:
        """Reject overlapping, duplicate, unordered and uncovered sessions."""
        first = self._session()
        second_label = date(2024, 3, 13) if mutation == "outside" else date(2024, 3, 12)
        if mutation == "duplicate":
            second_label = first.session_label
        second_open = (
            datetime(2024, 3, 11, 7, 0, tzinfo=UTC)
            if mutation == "overlap"
            else datetime(2024, 3, 12, 1, 30, tzinfo=UTC)
        )
        second = self._session(
            label=second_label,
            opens_at=second_open,
            closes_at=second_open + timedelta(hours=2),
            break_starts_at=None,
            break_ends_at=None,
        )
        sessions = (second, first) if mutation == "reversed" else (first, second)

        with pytest.raises(VenueCalendarValidationError, match=message):
            VenueCalendarSnapshot(
                venue=self._venue(),
                version=self._version(),
                covered_from=date(2024, 3, 11),
                covered_through=date(2024, 3, 12),
                sessions=sessions,
            )

    def test_auction_windows_allow_repeated_kinds_but_reject_overlap(self) -> None:
        """Allow adjacent auctions of one kind while rejecting overlapping auction intervals."""
        first = AuctionWindow(
            kind=AuctionKind.OPENING,
            starts_at=datetime(2024, 3, 11, 1, 30, tzinfo=UTC),
            ends_at=datetime(2024, 3, 11, 1, 35, tzinfo=UTC),
        )
        second = AuctionWindow(
            kind=AuctionKind.OPENING,
            starts_at=datetime(2024, 3, 11, 1, 35, tzinfo=UTC),
            ends_at=datetime(2024, 3, 11, 1, 40, tzinfo=UTC),
        )
        assert self._session(auctions=(first, second)).auctions == (first, second)

        overlapping = AuctionWindow(
            kind=AuctionKind.REOPENING,
            starts_at=datetime(2024, 3, 11, 1, 34, tzinfo=UTC),
            ends_at=datetime(2024, 3, 11, 1, 40, tzinfo=UTC),
        )
        with pytest.raises(VenueCalendarValidationError, match="non-overlapping"):
            self._session(auctions=(first, overlapping))

    @pytest.mark.parametrize("window_kind", ["halt", "limit"])
    @pytest.mark.parametrize("mutation", ["outside", "overlap", "duplicate"])
    def test_market_windows_reject_unsafe_graphs(self, window_kind: str, mutation: str) -> None:
        """Reject uncovered, overlapping or duplicate halt and price-limit windows."""
        first_start = datetime(2024, 3, 11, 1 if mutation == "outside" else 2, 0, tzinfo=UTC)
        starts = (
            (first_start,)
            if mutation == "outside"
            else (
                first_start,
                first_start + timedelta(minutes=5),
            )
        )
        interruptions: list[MarketInterruption] = []
        limits: list[PriceLimitWindow] = []
        for index, starts_at in enumerate(starts):
            identifier = "window-0" if mutation == "duplicate" else f"window-{index}"
            if window_kind == "halt":
                interruptions.append(
                    MarketInterruption(
                        interruption_id=identifier,
                        kind=InterruptionKind.HALT,
                        starts_at=starts_at,
                        ends_at=starts_at + timedelta(minutes=10),
                        reason="Invalid synthetic interval graph",
                        source="fixture.market",
                        source_revision="v1",
                    )
                )
            else:
                limits.append(
                    PriceLimitWindow(
                        limit_id=identifier,
                        state=PriceLimitState.LIMIT_DOWN,
                        starts_at=starts_at,
                        ends_at=starts_at + timedelta(minutes=10),
                        source="fixture.market",
                        source_revision="v1",
                    )
                )
        message = {
            "outside": "inside exactly one session",
            "overlap": "non-overlapping",
            "duplicate": "IDs must be unique",
        }[mutation]
        with pytest.raises(VenueCalendarValidationError, match=message):
            VenueCalendarSnapshot(
                venue=self._venue(),
                version=self._version(),
                covered_from=date(2024, 3, 11),
                covered_through=date(2024, 3, 11),
                sessions=(self._session(),),
                interruptions=tuple(interruptions),
                price_limits=tuple(limits),
            )

    def test_market_state_rejects_incoherent_phase_metadata(self) -> None:
        """Require phase metadata consistent with closed, auction and halted states."""
        with pytest.raises(VenueCalendarValidationError, match="closed market state"):
            MarketState(
                status=MarketStatus.CLOSED,
                price_limit_state=PriceLimitState.LOCKED,
            )
        with pytest.raises(VenueCalendarValidationError, match="auction_kind"):
            MarketState(
                status=MarketStatus.AUCTION,
                price_limit_state=PriceLimitState.NONE,
                session_label=date(2024, 3, 11),
            )
        with pytest.raises(VenueCalendarValidationError, match="interruption_id"):
            MarketState(
                status=MarketStatus.HALTED,
                price_limit_state=PriceLimitState.NONE,
                session_label=date(2024, 3, 11),
            )

    def test_explicit_timezone_conversion_preserves_dst_gap_and_fold(self) -> None:
        """Preserve the spring DST gap and distinct UTC instants in the autumn repeated hour."""
        venue = self._venue()
        before_gap = venue.local_time(datetime(2024, 3, 10, 6, 59, tzinfo=UTC))
        after_gap = venue.local_time(datetime(2024, 3, 10, 7, 0, tzinfo=UTC))
        first_fold = venue.local_time(datetime(2024, 11, 3, 5, 30, tzinfo=UTC))
        second_fold = venue.local_time(datetime(2024, 11, 3, 6, 30, tzinfo=UTC))

        assert (before_gap.hour, before_gap.minute) == (1, 59)
        assert (after_gap.hour, after_gap.minute) == (3, 0)
        assert first_fold.hour == second_fold.hour == 1
        assert (first_fold.fold, second_fold.fold) == (0, 1)
        assert first_fold.astimezone(UTC) != second_fold.astimezone(UTC)
