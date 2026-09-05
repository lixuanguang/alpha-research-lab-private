"""Deterministic contract tests for C02 venue and calendar behavior."""

from __future__ import annotations

# standard library imports
import json
import os
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

# third party library imports
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

# project library imports
import alpha_research.venue_calendar.adapter as calendar_adapter_module
from alpha_research.venue_calendar import (
    EXCHANGE_CALENDARS_VERSION,
    AuctionKind,
    AuctionWindow,
    CalendarAdapterError,
    CalendarAuthority,
    CalendarClosure,
    CalendarCoverageError,
    CalendarSourceVersion,
    ClosureKind,
    ExchangeCalendarsAdapter,
    IncompatibleCalendarLibraryError,
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
    TradingSession,
    UnknownSessionError,
    UnknownSettlementDateError,
    Venue,
    VenueCalendarSnapshot,
    VenueCalendarValidationError,
    VenueId,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
FIXTURE_PATH = REPOSITORY_ROOT / "tests" / "golden" / "venue_calendar" / "c02_calendars.json"


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _venue(
    *,
    identifier: str = "11111111-1111-4111-8111-111111111111",
    mic: str = "XNYS",
    timezone_name: str = "America/New_York",
) -> Venue:
    return Venue(
        venue_id=VenueId.from_canonical_text(identifier),
        mic=MarketIdentifierCode(value=mic),
        operating_mic=MarketIdentifierCode(value=mic),
        name=f"Synthetic {mic} venue",
        timezone_name=timezone_name,
    )


def _version(*, overridden: bool = False) -> CalendarSourceVersion:
    return CalendarSourceVersion(
        calendar_version="c02-fixture-v1",
        base_source="exchange_calendars",
        base_source_revision=EXCHANGE_CALENDARS_VERSION,
        adapter_name="exchange_calendars",
        adapter_version=EXCHANGE_CALENDARS_VERSION,
        authority=CalendarAuthority.SYNTHETIC_FIXTURE,
        override_source="fixture.overrides" if overridden else None,
        override_revision="override-v1" if overridden else None,
    )


def _session(
    *,
    label: date = date(2024, 3, 11),
    opens_at: datetime = datetime(2024, 3, 11, 1, 30, tzinfo=UTC),
    closes_at: datetime = datetime(2024, 3, 11, 8, 0, tzinfo=UTC),
    break_starts_at: datetime | None = datetime(2024, 3, 11, 4, 0, tzinfo=UTC),
    break_ends_at: datetime | None = datetime(2024, 3, 11, 5, 0, tzinfo=UTC),
    auctions: tuple[AuctionWindow, ...] = (),
) -> TradingSession:
    return TradingSession(
        session_label=label,
        opens_at=opens_at,
        closes_at=closes_at,
        break_starts_at=break_starts_at,
        break_ends_at=break_ends_at,
        auctions=auctions,
    )


def _load_fixture() -> dict[str, object]:
    fixture: object = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(fixture, dict)
    return fixture


def test_adapter_matches_pinned_cross_timezone_dst_half_day_and_break_fixture() -> None:
    fixture = _load_fixture()
    assert fixture["adapter_version"] == EXCHANGE_CALENDARS_VERSION
    adapter = ExchangeCalendarsAdapter()

    venues = fixture["venues"]
    assert isinstance(venues, list)
    for raw_venue in venues:
        assert isinstance(raw_venue, dict)
        calendar_name = str(raw_venue["calendar_name"])
        raw_range = raw_venue["range"]
        assert isinstance(raw_range, list)
        snapshot = adapter.build_snapshot(
            venue=_venue(
                identifier=str(raw_venue["venue_id"]),
                mic=str(raw_venue["mic"]),
                timezone_name=str(raw_venue["timezone_name"]),
            ),
            calendar_name=calendar_name,
            version=_version(),
            start=date.fromisoformat(str(raw_range[0])),
            end=date.fromisoformat(str(raw_range[1])),
        )
        expected_sessions = raw_venue["expected_sessions"]
        assert isinstance(expected_sessions, list)
        for expected in expected_sessions:
            assert isinstance(expected, dict)
            session = snapshot.session_for_label(date.fromisoformat(str(expected["session_label"])))
            assert session.opens_at == _instant(str(expected["opens_at"]))
            assert session.closes_at == _instant(str(expected["closes_at"]))
            assert session.kind is SessionKind(str(expected["kind"]))
            assert snapshot.market_state_at(session.opens_at).status is MarketStatus.CONTINUOUS
            if "break_starts_at" in expected:
                assert session.break_starts_at == _instant(str(expected["break_starts_at"]))
                assert session.break_ends_at == _instant(str(expected["break_ends_at"]))


def test_named_holiday_closure_is_attributed_and_cannot_be_a_session() -> None:
    fixture = _load_fixture()
    raw_venues = fixture["venues"]
    assert isinstance(raw_venues, list)
    raw_venue = raw_venues[0]
    assert isinstance(raw_venue, dict)
    raw_holiday = raw_venue["holiday"]
    assert isinstance(raw_holiday, dict)
    holiday = CalendarClosure(
        calendar_date=date.fromisoformat(str(raw_holiday["calendar_date"])),
        kind=ClosureKind.HOLIDAY,
        name=str(raw_holiday["name"]),
        source="fixture.exchange",
        source_revision="holiday-v1",
    )
    snapshot = ExchangeCalendarsAdapter().build_snapshot(
        venue=_venue(),
        calendar_name="XNYS",
        version=_version(),
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
                    source_revision="collision-v1",
                ),
            ),
        )


def test_versioned_override_add_replace_and_remove_actions_are_exact() -> None:
    adapter = ExchangeCalendarsAdapter()
    saturday = _session(
        label=date(2024, 3, 9),
        opens_at=datetime(2024, 3, 9, 14, 30, tzinfo=UTC),
        closes_at=datetime(2024, 3, 9, 15, 0, tzinfo=UTC),
        break_starts_at=None,
        break_ends_at=None,
    )
    replacement = _session(
        label=date(2024, 3, 11),
        opens_at=datetime(2024, 3, 11, 14, 0, tzinfo=UTC),
        closes_at=datetime(2024, 3, 11, 18, 0, tzinfo=UTC),
        break_starts_at=None,
        break_ends_at=None,
    )
    snapshot = adapter.build_snapshot(
        venue=_venue(),
        calendar_name="XNYS",
        version=_version(overridden=True),
        start=date(2024, 3, 8),
        end=date(2024, 3, 12),
        overrides=(
            SessionOverride(
                override_id="remove-2024-03-08",
                action=SessionOverrideAction.REMOVE,
                session_label=date(2024, 3, 8),
                reason="Synthetic emergency closure",
                source="fixture.overrides",
                source_revision="override-v1",
            ),
            SessionOverride(
                override_id="add-2024-03-09",
                action=SessionOverrideAction.ADD,
                session_label=date(2024, 3, 9),
                replacement=saturday,
                reason="Synthetic special session",
                source="fixture.overrides",
                source_revision="override-v1",
            ),
            SessionOverride(
                override_id="replace-2024-03-11",
                action=SessionOverrideAction.REPLACE,
                session_label=date(2024, 3, 11),
                replacement=replacement,
                reason="Synthetic shortened session",
                source="fixture.overrides",
                source_revision="override-v1",
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
    action: SessionOverrideAction, label: date, message: str
) -> None:
    replacement = None
    if action is not SessionOverrideAction.REMOVE:
        replacement = _session(
            label=label,
            opens_at=datetime.combine(label, datetime.min.time(), tzinfo=UTC),
            closes_at=datetime.combine(label, datetime.min.time(), tzinfo=UTC) + timedelta(hours=1),
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
        source_revision="override-v1",
    )
    with pytest.raises(VenueCalendarValidationError, match=message):
        ExchangeCalendarsAdapter().build_snapshot(
            venue=_venue(),
            calendar_name="XNYS",
            version=_version(overridden=True),
            start=date(2024, 3, 11),
            end=date(2024, 3, 12),
            overrides=(override,),
        )


@pytest.mark.parametrize("action", list(SessionOverrideAction))
def test_direct_snapshot_rejects_override_records_that_disagree_with_sessions(
    action: SessionOverrideAction,
) -> None:
    session = _session()
    override = SessionOverride(
        override_id="inconsistent-result",
        action=action,
        session_label=session.session_label,
        reason="Synthetic inconsistent retained record",
        source="fixture.overrides",
        source_revision="override-v1",
        replacement=None if action is SessionOverrideAction.REMOVE else session,
    )
    with pytest.raises(VenueCalendarValidationError, match=r"applied .* override must"):
        VenueCalendarSnapshot(
            venue=_venue(),
            version=_version(overridden=True),
            covered_from=session.session_label,
            covered_through=session.session_label,
            sessions=(session,) if action is SessionOverrideAction.REMOVE else (),
            applied_overrides=(override,),
        )


def test_market_state_precedence_and_half_open_boundaries() -> None:
    raw_state = _load_fixture()["synthetic_market_state"]
    assert isinstance(raw_state, dict)
    raw_auction = raw_state["opening_auction"]
    raw_halt = raw_state["halt"]
    raw_limit = raw_state["limit_up"]
    assert isinstance(raw_auction, list)
    assert isinstance(raw_halt, list)
    assert isinstance(raw_limit, list)
    auction = AuctionWindow(
        kind=AuctionKind.OPENING,
        starts_at=_instant(str(raw_auction[0])),
        ends_at=_instant(str(raw_auction[1])),
    )
    session = _session(auctions=(auction,))
    interruption = MarketInterruption(
        interruption_id="synthetic-halt-1",
        kind=InterruptionKind.HALT,
        starts_at=_instant(str(raw_halt[0])),
        ends_at=_instant(str(raw_halt[1])),
        reason="Synthetic volatility halt",
        source="fixture.market",
        source_revision="market-v1",
    )
    price_limit = PriceLimitWindow(
        limit_id="synthetic-limit-1",
        state=PriceLimitState.LIMIT_UP,
        starts_at=_instant(str(raw_limit[0])),
        ends_at=_instant(str(raw_limit[1])),
        source="fixture.market",
        source_revision="market-v1",
    )
    snapshot = VenueCalendarSnapshot(
        venue=_venue(
            identifier="33333333-3333-4333-8333-333333333333",
            mic="XHKG",
            timezone_name="Asia/Hong_Kong",
        ),
        version=_version(overridden=True),
        covered_from=date(2024, 3, 11),
        covered_through=date(2024, 3, 11),
        sessions=(session,),
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
    assert snapshot.market_state_at(price_limit.ends_at).price_limit_state is PriceLimitState.NONE
    assert session.break_starts_at is not None
    assert session.break_ends_at is not None
    assert snapshot.market_state_at(session.break_starts_at).status is MarketStatus.BREAK
    assert snapshot.market_state_at(session.break_ends_at).status is MarketStatus.CONTINUOUS
    assert snapshot.market_state_at(session.closes_at).status is MarketStatus.CLOSED
    with pytest.raises(CalendarCoverageError, match="outside snapshot coverage"):
        snapshot.market_state_at(datetime(2024, 3, 12, 2, 0, tzinfo=UTC))
    with pytest.raises(CalendarCoverageError, match="outside snapshot coverage"):
        snapshot.closure_for_date(date(2024, 3, 12))


@pytest.mark.parametrize("halt_start", ["2024-03-11T01:32:00Z", "2024-03-11T04:10:00Z"])
def test_halt_takes_precedence_over_auction_and_break(halt_start: str) -> None:
    session = _session(
        auctions=(
            AuctionWindow(
                kind=AuctionKind.OPENING,
                starts_at=datetime(2024, 3, 11, 1, 30, tzinfo=UTC),
                ends_at=datetime(2024, 3, 11, 1, 35, tzinfo=UTC),
            ),
        )
    )
    starts_at = _instant(halt_start)
    snapshot = VenueCalendarSnapshot(
        venue=_venue(),
        version=_version(),
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
    "limit_state", [PriceLimitState.LIMIT_UP, PriceLimitState.LIMIT_DOWN, PriceLimitState.LOCKED]
)
def test_non_normal_limit_state_is_independent_of_continuous_phase(
    limit_state: PriceLimitState,
) -> None:
    starts_at = datetime(2024, 3, 11, 2, 0, tzinfo=UTC)
    snapshot = VenueCalendarSnapshot(
        venue=_venue(),
        version=_version(),
        covered_from=date(2024, 3, 11),
        covered_through=date(2024, 3, 11),
        sessions=(_session(),),
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


def test_settlement_calendar_is_bounded_and_does_not_infer_conventions() -> None:
    raw_calendar = _load_fixture()["settlement_calendar"]
    assert isinstance(raw_calendar, dict)
    raw_range = raw_calendar["range"]
    raw_dates = raw_calendar["settlement_dates"]
    assert isinstance(raw_range, list)
    assert isinstance(raw_dates, list)
    calendar = SettlementCalendar(
        calendar_id="synthetic-usd-settlement",
        calendar_version="settlement-v1",
        timezone_name="America/New_York",
        covered_from=date.fromisoformat(str(raw_range[0])),
        covered_through=date.fromisoformat(str(raw_range[1])),
        settlement_dates=tuple(date.fromisoformat(str(item)) for item in raw_dates),
        source="fixture.settlement",
        source_revision="settlement-v1",
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
def test_invalid_mic_fails_without_normalization(bad_mic: str) -> None:
    with pytest.raises(VenueCalendarValidationError, match="four uppercase ASCII"):
        MarketIdentifierCode(value=bad_mic)


def test_invalid_time_and_interval_state_fails_closed() -> None:
    with pytest.raises(VenueCalendarValidationError, match="timezone-aware UTC"):
        _session(opens_at=datetime(2024, 3, 11, 1, 30))
    with pytest.raises(VenueCalendarValidationError, match="must use UTC"):
        _venue().local_time(datetime(2024, 3, 11, 1, 30, tzinfo=ZoneInfo("Asia/Singapore")))
    with pytest.raises(VenueCalendarValidationError, match="strictly inside"):
        _session(break_starts_at=datetime(2024, 3, 11, 1, 0, tzinfo=UTC))
    with pytest.raises(VenueCalendarValidationError, match="non-NONE"):
        PriceLimitWindow(
            limit_id="invalid-none",
            state=PriceLimitState.NONE,
            starts_at=datetime(2024, 3, 11, 2, 0, tzinfo=UTC),
            ends_at=datetime(2024, 3, 11, 2, 1, tzinfo=UTC),
            source="fixture.market",
            source_revision="market-v1",
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
def test_snapshot_session_graph_rejects_invalid_state(mutation: str, message: str) -> None:
    first = _session()
    second_label = date(2024, 3, 13) if mutation == "outside" else date(2024, 3, 12)
    if mutation == "duplicate":
        second_label = first.session_label
    second_open = (
        datetime(2024, 3, 11, 7, 0, tzinfo=UTC)
        if mutation == "overlap"
        else datetime(2024, 3, 12, 1, 30, tzinfo=UTC)
    )
    second = _session(
        label=second_label,
        opens_at=second_open,
        closes_at=second_open + timedelta(hours=2),
        break_starts_at=None,
        break_ends_at=None,
    )
    sessions = (second, first) if mutation == "reversed" else (first, second)

    with pytest.raises(VenueCalendarValidationError, match=message):
        VenueCalendarSnapshot(
            venue=_venue(),
            version=_version(),
            covered_from=date(2024, 3, 11),
            covered_through=date(2024, 3, 12),
            sessions=sessions,
        )


def test_auction_windows_allow_repeated_kinds_but_reject_overlap() -> None:
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
    assert _session(auctions=(first, second)).auctions == (first, second)

    overlapping = AuctionWindow(
        kind=AuctionKind.REOPENING,
        starts_at=datetime(2024, 3, 11, 1, 34, tzinfo=UTC),
        ends_at=datetime(2024, 3, 11, 1, 40, tzinfo=UTC),
    )
    with pytest.raises(VenueCalendarValidationError, match="non-overlapping"):
        _session(auctions=(first, overlapping))


@pytest.mark.parametrize("window_kind", ["halt", "limit"])
@pytest.mark.parametrize("mutation", ["outside", "overlap", "duplicate"])
def test_market_windows_reject_unsafe_graphs(window_kind: str, mutation: str) -> None:
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
            venue=_venue(),
            version=_version(),
            covered_from=date(2024, 3, 11),
            covered_through=date(2024, 3, 11),
            sessions=(_session(),),
            interruptions=tuple(interruptions),
            price_limits=tuple(limits),
        )


def test_market_state_rejects_incoherent_phase_metadata() -> None:
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


def test_explicit_timezone_conversion_preserves_dst_gap_and_fold() -> None:
    venue = _venue()
    before_gap = venue.local_time(datetime(2024, 3, 10, 6, 59, tzinfo=UTC))
    after_gap = venue.local_time(datetime(2024, 3, 10, 7, 0, tzinfo=UTC))
    first_fold = venue.local_time(datetime(2024, 11, 3, 5, 30, tzinfo=UTC))
    second_fold = venue.local_time(datetime(2024, 11, 3, 6, 30, tzinfo=UTC))

    assert (before_gap.hour, before_gap.minute) == (1, 59)
    assert (after_gap.hour, after_gap.minute) == (3, 0)
    assert first_fold.hour == second_fold.hour == 1
    assert (first_fold.fold, second_fold.fold) == (0, 1)
    assert first_fold.astimezone(UTC) != second_fold.astimezone(UTC)


def test_unknown_calendar_timezone_mismatch_and_unversioned_override_reject() -> None:
    adapter = ExchangeCalendarsAdapter()
    with pytest.raises(CalendarAdapterError, match="cannot load calendar"):
        adapter.build_snapshot(
            venue=_venue(),
            calendar_name="NOPE",
            version=_version(),
            start=date(2024, 3, 11),
            end=date(2024, 3, 12),
        )
    with pytest.raises(CalendarAdapterError, match="does not match venue timezone"):
        adapter.build_snapshot(
            venue=_venue(timezone_name="Europe/London"),
            calendar_name="XNYS",
            version=_version(),
            start=date(2024, 3, 11),
            end=date(2024, 3, 12),
        )
    with pytest.raises(VenueCalendarValidationError, match="overrides require"):
        adapter.build_snapshot(
            venue=_venue(),
            calendar_name="XNYS",
            version=_version(),
            start=date(2024, 3, 11),
            end=date(2024, 3, 12),
            overrides=(
                SessionOverride(
                    override_id="remove-without-revision",
                    action=SessionOverrideAction.REMOVE,
                    session_label=date(2024, 3, 11),
                    reason="Invalid unattributed override",
                    source="fixture.overrides",
                    source_revision="override-v1",
                ),
            ),
        )
    with pytest.raises(VenueCalendarValidationError, match="attribution must match"):
        adapter.build_snapshot(
            venue=_venue(),
            calendar_name="XNYS",
            version=_version(overridden=True),
            start=date(2024, 3, 11),
            end=date(2024, 3, 12),
            overrides=(
                SessionOverride(
                    override_id="remove-with-mismatched-source",
                    action=SessionOverrideAction.REMOVE,
                    session_label=date(2024, 3, 11),
                    reason="Invalid mismatched override attribution",
                    source="fixture.other",
                    source_revision="override-v1",
                ),
            ),
        )


def test_incompatible_calendar_library_version_fails_before_source_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(calendar_adapter_module, "installed_version", lambda _: "4.13.1")

    with pytest.raises(IncompatibleCalendarLibraryError, match=r"must be exactly 4\.13\.2"):
        ExchangeCalendarsAdapter().build_snapshot(
            venue=_venue(),
            calendar_name="XNYS",
            version=_version(),
            start=date(2024, 3, 11),
            end=date(2024, 3, 12),
        )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2024, 3, 9), date(2024, 3, 9)),
        (date(2024, 3, 9), date(2024, 3, 10)),
        (date(2024, 11, 28), date(2024, 11, 28)),
    ],
)
def test_closure_only_adapter_ranges_preserve_exact_empty_coverage(start: date, end: date) -> None:
    snapshot = ExchangeCalendarsAdapter().build_snapshot(
        venue=_venue(),
        calendar_name="XNYS",
        version=_version(),
        start=start,
        end=end,
    )

    assert snapshot.covered_from == start
    assert snapshot.covered_through == end
    assert snapshot.sessions == ()
    assert (
        snapshot.market_state_at(
            datetime.combine(start, datetime.min.time(), UTC) + timedelta(hours=16)
        ).status
        is MarketStatus.CLOSED
    )


def test_adapter_rejects_mislabeled_source_revision_and_duplicate_source_sessions() -> None:
    wrong_revision = _version().model_copy(update={"base_source_revision": "4.13.1"})
    with pytest.raises(VenueCalendarValidationError, match="base_source_revision"):
        ExchangeCalendarsAdapter().build_snapshot(
            venue=_venue(),
            calendar_name="XNYS",
            version=wrong_revision,
            start=date(2024, 3, 11),
            end=date(2024, 3, 12),
        )
    with pytest.raises(CalendarAdapterError, match="source session labels must be unique"):
        calendar_adapter_module._apply_overrides((_session(), _session()), ())


def test_source_session_query_failure_is_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingCalendar:
        name = "XNYS"
        tz = "America/New_York"
        sessions = (date(2024, 3, 11),)
        early_closes: tuple[date, ...] = ()

        def session_open(self, session: date) -> object:
            raise ValueError("Synthetic source query failure")

        def session_close(self, session: date) -> object:
            return datetime(2024, 3, 11, 20, 0, tzinfo=UTC)

        def session_break_start(self, session: date) -> object:
            return None

        def session_break_end(self, session: date) -> object:
            return None

    monkeypatch.setattr(
        calendar_adapter_module, "_load_exchange_calendar", lambda **_: FailingCalendar()
    )
    with pytest.raises(CalendarAdapterError, match="source failed to query session"):
        ExchangeCalendarsAdapter().build_snapshot(
            venue=_venue(),
            calendar_name="XNYS",
            version=_version(),
            start=date(2024, 3, 11),
            end=date(2024, 3, 12),
        )


def test_adapter_does_not_depend_on_host_local_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    if not hasattr(time, "tzset"):
        pytest.skip("host does not expose tzset")
    adapter = ExchangeCalendarsAdapter()
    observed: list[TradingSession] = []
    original_timezone = os.environ.get("TZ")
    try:
        for host_timezone in ("Pacific/Honolulu", "Asia/Singapore"):
            monkeypatch.setenv("TZ", host_timezone)
            time.tzset()
            observed.append(
                adapter.build_snapshot(
                    venue=_venue(),
                    calendar_name="XNYS",
                    version=_version(),
                    start=date(2024, 3, 11),
                    end=date(2024, 3, 11),
                ).session_for_label(date(2024, 3, 11))
            )
    finally:
        if original_timezone is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", original_timezone)
        time.tzset()

    assert observed[0] == observed[1]
    assert observed[0].opens_at == datetime(2024, 3, 11, 13, 30, tzinfo=UTC)


@pytest.mark.performance
def test_market_state_projection_stays_within_local_diagnostic_budget() -> None:
    snapshot = ExchangeCalendarsAdapter().build_snapshot(
        venue=_venue(),
        calendar_name="XNYS",
        version=_version(),
        start=date(2024, 3, 8),
        end=date(2024, 11, 29),
    )
    assert len(snapshot.sessions) == 185
    instants = tuple(session.opens_at for session in snapshot.sessions) + tuple(
        session.closes_at for session in snapshot.sessions
    )

    started_at = time.perf_counter()
    for index in range(10_000):
        snapshot.market_state_at(instants[index % len(instants)])
    elapsed_seconds = time.perf_counter() - started_at

    assert elapsed_seconds < 1.0


@settings(max_examples=50, derandomize=True, database=None)
@given(offset_seconds=st.integers(min_value=-1, max_value=23_401))
def test_market_state_projection_is_deterministic_for_every_boundary_offset(
    offset_seconds: int,
) -> None:
    session = TradingSession(
        session_label=date(2024, 1, 2),
        opens_at=datetime(2024, 1, 2, 14, 30, tzinfo=UTC),
        closes_at=datetime(2024, 1, 2, 21, 0, tzinfo=UTC),
    )
    snapshot = VenueCalendarSnapshot(
        venue=_venue(),
        version=_version(),
        covered_from=date(2024, 1, 2),
        covered_through=date(2024, 1, 2),
        sessions=(session,),
    )
    instant = session.opens_at + timedelta(seconds=offset_seconds)

    first = snapshot.market_state_at(instant)
    second = snapshot.market_state_at(instant)

    assert first == second
    assert first.status is (
        MarketStatus.CONTINUOUS if 0 <= offset_seconds < 23_400 else MarketStatus.CLOSED
    )


@settings(max_examples=50, derandomize=True, database=None)
@given(
    instant=st.datetimes(
        min_value=datetime(2024, 1, 1),
        max_value=datetime(2025, 12, 31, 23, 59, 59),
        timezones=st.just(UTC),
    )
)
def test_explicit_venue_timezone_round_trip_preserves_instant(instant: datetime) -> None:
    venue = _venue()

    assert venue.local_time(instant).astimezone(UTC) == instant


def test_venue_identity_and_calendar_version_reject_invalid_state() -> None:
    with pytest.raises(VenueCalendarValidationError, match="non-nil UUID"):
        VenueId(uuid_value=UUID(int=0))
    with pytest.raises(VenueCalendarValidationError, match="canonical UUID"):
        VenueId.from_canonical_text("11111111-1111-4111-8111-11111111111A")
    with pytest.raises(VenueCalendarValidationError, match="provided together"):
        CalendarSourceVersion(
            calendar_version="v1",
            base_source="exchange_calendars",
            base_source_revision="source-v1",
            adapter_name="exchange_calendars",
            adapter_version=EXCHANGE_CALENDARS_VERSION,
            authority=CalendarAuthority.REFERENCE_ONLY,
            override_source="fixture.overrides",
        )
    with pytest.raises(VenueCalendarValidationError, match="IANA timezone"):
        _venue(timezone_name="Local/Host")


def test_venue_calendar_models_are_strict_frozen_pydantic_boundaries() -> None:
    model_types = (
        VenueId,
        MarketIdentifierCode,
        Venue,
        CalendarSourceVersion,
        AuctionWindow,
        TradingSession,
        CalendarClosure,
        MarketInterruption,
        PriceLimitWindow,
        MarketState,
        SettlementCalendar,
        SessionOverride,
        VenueCalendarSnapshot,
    )
    assert all(issubclass(model_type, BaseModel) for model_type in model_types)

    venue_id = VenueId.from_canonical_text("11111111-1111-4111-8111-111111111111")
    with pytest.raises(ValidationError):
        VenueId.model_validate({"uuid_value": str(venue_id.uuid_value)})
    with pytest.raises(ValidationError):
        VenueId.model_validate({"uuid_value": venue_id.uuid_value, "unexpected": True})
    with pytest.raises(ValidationError):
        venue_id.uuid_value = UUID("22222222-2222-4222-8222-222222222222")
    with pytest.raises(ValidationError, match="must be a VenueId"):
        Venue.model_validate(
            {
                "venue_id": {"uuid_value": venue_id.uuid_value},
                "mic": MarketIdentifierCode(value="XNYS"),
                "operating_mic": MarketIdentifierCode(value="XNYS"),
                "name": "Invalid raw identity",
                "timezone_name": "America/New_York",
            }
        )
    with pytest.raises(ValidationError, match="immutable tuple"):
        VenueCalendarSnapshot.model_validate(
            {
                "venue": _venue(),
                "version": _version(),
                "covered_from": date(2024, 3, 11),
                "covered_through": date(2024, 3, 11),
                "sessions": [_session()],
            }
        )

    with pytest.raises(VenueCalendarValidationError, match="non-nil UUID"):
        VenueId.model_construct(uuid_value=UUID(int=0))
    tampered_id = venue_id.model_copy(update={"uuid_value": UUID(int=0)})
    with pytest.raises(VenueCalendarValidationError, match="non-nil UUID"):
        Venue(
            venue_id=tampered_id,
            mic=MarketIdentifierCode(value="XNYS"),
            operating_mic=MarketIdentifierCode(value="XNYS"),
            name="Invalid venue",
            timezone_name="America/New_York",
        )


def test_invalid_optional_source_instant_is_not_treated_as_an_absent_break() -> None:
    with pytest.raises(CalendarAdapterError, match="invalid session break"):
        calendar_adapter_module._as_utc_datetime(
            datetime(2024, 3, 11, 4, 0),
            field_name="session break",
            optional=True,
        )
