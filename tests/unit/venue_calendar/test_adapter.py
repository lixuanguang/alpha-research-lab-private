"""Test the calendar adapter and generated point-in-time projections."""

from __future__ import annotations

# standard library imports
import os
import time
from datetime import UTC, date, datetime, timedelta

# third party library imports
import pytest
from hypothesis import settings
from hypothesis import strategies as st
from venue_calendar_cases import (
    _AttributeErrorTimestamp,
    _CalendarTestData,
    _DynamicTimestamp,
    _given_market_state,
    _given_venue_timezone,
    _NonCallableTimestamp,
)

# project library imports
import reference_data.calendars.adapter as calendar_adapter_module
from reference_data.calendars import (
    CalendarAdapterError,
    CalendarCoverageError,
    ExchangeCalendarsAdapter,
    IncompatibleCalendarLibraryError,
    MarketStatus,
    SessionOverride,
    SessionOverrideAction,
    TradingSession,
    VenueCalendarSnapshot,
    VenueCalendarValidationError,
)


class TestVenueCalendarAdapterContracts(_CalendarTestData):
    """Exercise source adapter compatibility and ownership boundaries."""

    def test_unknown_calendar_timezone_mismatch_and_unversioned_override_reject(
        self,
    ) -> None:
        """Reject unknown calendars, mismatched timezones and inconsistent attribution."""
        adapter = ExchangeCalendarsAdapter()
        with pytest.raises(CalendarAdapterError, match="cannot load calendar"):
            adapter.build_snapshot(
                venue=self._venue(),
                calendar_name="NOPE",
                version=self._version(),
                start=date(2024, 3, 11),
                end=date(2024, 3, 12),
            )
        with pytest.raises(CalendarAdapterError, match="does not match venue timezone"):
            adapter.build_snapshot(
                venue=self._venue(timezone_name="Europe/London"),
                calendar_name="XNYS",
                version=self._version(),
                start=date(2024, 3, 11),
                end=date(2024, 3, 12),
            )
        with pytest.raises(VenueCalendarValidationError, match="overrides require"):
            adapter.build_snapshot(
                venue=self._venue(),
                calendar_name="XNYS",
                version=self._version(),
                start=date(2024, 3, 11),
                end=date(2024, 3, 12),
                overrides=(
                    SessionOverride(
                        override_id="remove-without-revision",
                        action=SessionOverrideAction.REMOVE,
                        session_label=date(2024, 3, 11),
                        reason="Invalid unattributed override",
                        source="fixture.overrides",
                        source_revision="override",
                    ),
                ),
            )
        with pytest.raises(VenueCalendarValidationError, match="attribution must match"):
            adapter.build_snapshot(
                venue=self._venue(),
                calendar_name="XNYS",
                version=self._version(overridden=True),
                start=date(2024, 3, 11),
                end=date(2024, 3, 12),
                overrides=(
                    SessionOverride(
                        override_id="remove-with-mismatched-source",
                        action=SessionOverrideAction.REMOVE,
                        session_label=date(2024, 3, 11),
                        reason="Invalid mismatched override attribution",
                        source="fixture.other",
                        source_revision="override",
                    ),
                ),
            )

    def test_incompatible_calendar_library_version_fails_before_source_use(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reject a calendar dependency version that differs from the exact adapter pin."""

        def incompatible_version(distribution_name: str) -> str:
            """Return a deliberately incompatible installed distribution version.

            Args:
                distribution_name: Distribution queried by the adapter; retained for callback
                    compatibility and intentionally ignored.

            Returns:
                A version that differs from the pinned exchange-calendars contract.
            """
            del distribution_name
            return "4.13.1"

        monkeypatch.setattr(calendar_adapter_module, "installed_version", incompatible_version)

        with pytest.raises(IncompatibleCalendarLibraryError, match=r"must be exactly 4\.13\.2"):
            ExchangeCalendarsAdapter().build_snapshot(
                venue=self._venue(),
                calendar_name="XNYS",
                version=self._version(),
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
    def test_closure_only_adapter_ranges_preserve_exact_empty_coverage(
        self, start: date, end: date
    ) -> None:
        """Retain empty label coverage without inferring instant coverage from those dates."""
        snapshot = ExchangeCalendarsAdapter().build_snapshot(
            venue=self._venue(),
            calendar_name="XNYS",
            version=self._version(),
            start=start,
            end=end,
        )

        assert snapshot.covered_from == start
        assert snapshot.covered_through == end
        assert snapshot.sessions == ()
        with pytest.raises(CalendarCoverageError, match="outside snapshot coverage"):
            snapshot.market_state_at(
                datetime.combine(start, datetime.min.time(), UTC) + timedelta(hours=16)
            )

    def test_adapter_rejects_mislabeled_source_revision_and_duplicate_source_sessions(
        self,
    ) -> None:
        """Reject incorrect source revision claims and duplicate source session labels."""
        revision_update: dict[str, str] = {"base_source_revision": "4.13.1"}
        wrong_revision = self._version().model_copy(update=revision_update)
        with pytest.raises(VenueCalendarValidationError, match="base_source_revision"):
            ExchangeCalendarsAdapter().build_snapshot(
                venue=self._venue(),
                calendar_name="XNYS",
                version=wrong_revision,
                start=date(2024, 3, 11),
                end=date(2024, 3, 12),
            )
        with pytest.raises(CalendarAdapterError, match="source session labels must be unique"):
            ExchangeCalendarsAdapter()._apply_overrides((self._session(), self._session()), ())

    def test_source_session_query_failure_is_translated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Translate a source opening-time query failure into the owned calendar adapter error."""

        class FailingCalendar:
            """Provide one synthetic session whose opening query always fails."""

            name = "XNYS"
            tz = "America/New_York"
            sessions = (date(2024, 3, 11),)
            early_closes: tuple[date, ...] = ()

            def session_open(self, session: date) -> object:
                """Fail the source query to exercise adapter exception translation.

                Args:
                    session: Requested session label, intentionally unused.

                Returns:
                    No value; this source query always raises.

                Raises:
                    ValueError: The synthetic source query fails on every call.
                """
                raise ValueError("Synthetic source query failure")

            def session_close(self, session: date) -> object:
                """Supply the fixed UTC close required by the calendar source protocol.

                Args:
                    session: Requested session label, intentionally unused.

                Returns:
                    The synthetic session's close at 20:00 UTC on March 11, 2024.
                """
                return datetime(2024, 3, 11, 20, 0, tzinfo=UTC)

            def session_break_start(self, session: date) -> object:
                """Report that the synthetic source session has no break start.

                Args:
                    session: Requested session label, intentionally unused.

                Returns:
                    None, the fake source's absent-break sentinel.
                """
                return None

            def session_break_end(self, session: date) -> object:
                """Report that the synthetic source session has no break end.

                Args:
                    session: Requested session label, intentionally unused.

                Returns:
                    None, the fake source's absent-break sentinel.
                """
                return None

        def failing_calendar_loader(
            *, calendar_name: str, start: date, end: date
        ) -> FailingCalendar:
            """Return the synthetic source whose opening query always fails.

            Args:
                calendar_name: Requested source calendar name, intentionally ignored.
                start: Inclusive requested start date, intentionally ignored.
                end: Inclusive requested end date, intentionally ignored.

            Returns:
                A synthetic calendar whose opening query raises a controlled failure.
            """
            del calendar_name, start, end
            return FailingCalendar()

        adapter = ExchangeCalendarsAdapter()
        monkeypatch.setattr(adapter, "_load_calendar", failing_calendar_loader)
        with pytest.raises(CalendarAdapterError, match="source failed to query session"):
            adapter.build_snapshot(
                venue=self._venue(),
                calendar_name="XNYS",
                version=self._version(),
                start=date(2024, 3, 11),
                end=date(2024, 3, 12),
            )

    @pytest.mark.parametrize(
        ("helper_name", "expected"),
        [
            ("date", date(2024, 3, 11)),
            ("utc_datetime", datetime(2024, 3, 11, 1, 30, tzinfo=UTC)),
        ],
    )
    def test_timestamp_helpers_accept_dynamic_converter(
        self, helper_name: str, expected: date | datetime
    ) -> None:
        """Accept source timestamps whose converter is supplied through ``__getattr__``."""
        candidate = _DynamicTimestamp(datetime(2024, 3, 11, 1, 30, tzinfo=UTC))
        if helper_name == "date":
            assert (
                ExchangeCalendarsAdapter._as_date(candidate, field_name="synthetic timestamp")
                == expected
            )
        else:
            assert (
                ExchangeCalendarsAdapter._as_utc_datetime(
                    candidate, field_name="synthetic timestamp"
                )
                == expected
            )

    @pytest.mark.parametrize("converter_kind", ["attribute_error", "non_callable"])
    @pytest.mark.parametrize("helper_name", ["date", "utc_datetime"])
    def test_timestamp_helpers_translate_invalid_converter(
        self, converter_kind: str, helper_name: str
    ) -> None:
        """Translate converter access and callability failures into CalendarAdapterError."""
        candidate: object
        if converter_kind == "attribute_error":
            candidate = _AttributeErrorTimestamp()
        else:
            candidate = _NonCallableTimestamp(datetime(2024, 3, 11, 1, 30, tzinfo=UTC))
        with pytest.raises(
            CalendarAdapterError, match="calendar source returned invalid synthetic timestamp"
        ):
            if helper_name == "date":
                ExchangeCalendarsAdapter._as_date(candidate, field_name="synthetic timestamp")
            else:
                ExchangeCalendarsAdapter._as_utc_datetime(
                    candidate, field_name="synthetic timestamp"
                )

    def test_adapter_does_not_depend_on_host_local_timezone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Keep the same UTC session under Honolulu and Singapore host timezones.

        The test changes TZ and calls tzset, restoring both environment and process
        state afterward; it skips hosts without tzset.
        """
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
                        venue=self._venue(),
                        calendar_name="XNYS",
                        version=self._version(),
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
    def test_market_state_projection_stays_within_local_diagnostic_budget(self) -> None:
        """Keep ten thousand state projections over 185 sessions below one local second."""
        snapshot = ExchangeCalendarsAdapter().build_snapshot(
            venue=self._venue(),
            calendar_name="XNYS",
            version=self._version(),
            start=date(2024, 3, 8),
            end=date(2024, 11, 29),
        )
        assert len(snapshot.sessions) == 185
        instants = tuple(session.opens_at for session in snapshot.sessions) + tuple(
            session.closes_at for session in snapshot.sessions[:-1]
        )

        started_at = time.perf_counter()
        for index in range(10_000):
            snapshot.market_state_at(instants[index % len(instants)])
        elapsed_seconds = time.perf_counter() - started_at

        assert elapsed_seconds < 1.0


@settings(max_examples=50, derandomize=True, database=None)
@_given_market_state(offset_seconds=st.integers(min_value=-1, max_value=23_401))
def test_market_state_projection_is_deterministic_for_every_boundary_offset(
    offset_seconds: int,
) -> None:
    """Repeat generated boundary queries and enforce the inclusive-open, exclusive-close rule."""
    session = TradingSession(
        session_label=date(2024, 1, 2),
        opens_at=datetime(2024, 1, 2, 14, 30, tzinfo=UTC),
        closes_at=datetime(2024, 1, 2, 21, 0, tzinfo=UTC),
    )
    snapshot = VenueCalendarSnapshot(
        venue=_CalendarTestData._venue(),
        version=_CalendarTestData._version(),
        covered_from=date(2024, 1, 1),
        covered_through=date(2024, 1, 3),
        sessions=tuple(
            TradingSession(
                session_label=session.session_label + timedelta(days=offset),
                opens_at=session.opens_at + timedelta(days=offset),
                closes_at=session.closes_at + timedelta(days=offset),
            )
            for offset in (-1, 0, 1)
        ),
    )
    instant = session.opens_at + timedelta(seconds=offset_seconds)

    first = snapshot.market_state_at(instant)
    second = snapshot.market_state_at(instant)

    assert first == second
    assert first.status is (
        MarketStatus.CONTINUOUS if 0 <= offset_seconds < 23_400 else MarketStatus.CLOSED
    )


@settings(max_examples=50, derandomize=True, database=None)
@_given_venue_timezone(
    instant=st.datetimes(
        min_value=datetime(2024, 1, 1),
        max_value=datetime(2025, 12, 31, 23, 59, 59),
        timezones=st.just(UTC),
    )
)
def test_explicit_venue_timezone_round_trip_preserves_instant(
    instant: datetime,
) -> None:
    """Recover each generated UTC instant after conversion through the venue timezone."""
    venue = _CalendarTestData._venue()

    assert venue.local_time(instant).astimezone(UTC) == instant
