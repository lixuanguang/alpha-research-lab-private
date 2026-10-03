"""Provide shared builders and typed fixture records for venue-calendar tests."""

from __future__ import annotations

# standard library imports
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import NotRequired, Protocol, TypedDict
from uuid import UUID

# third party library imports
from hypothesis import given
from hypothesis.strategies import SearchStrategy
from pydantic import TypeAdapter

# project library imports
from reference_data.calendars import (
    EXCHANGE_CALENDARS_VERSION,
    AuctionWindow,
    CalendarAuthority,
    CalendarSourceVersion,
    MarketIdentifierCode,
    TradingSession,
    Venue,
    VenueId,
)

REPOSITORY_ROOT = Path(__file__).parents[3]
FIXTURE_PATH = REPOSITORY_ROOT / "tests" / "golden" / "venue_calendar" / "c02_calendars.json"


class _MarketStateGiven(Protocol):
    """Type the keyword Hypothesis decorator for generated boundary offsets."""

    def __call__(
        self, *, offset_seconds: SearchStrategy[int]
    ) -> Callable[[Callable[[int], None]], Callable[[], None]]:
        """Decorate a test callable with a generated session offset."""
        ...


class _VenueTimezoneGiven(Protocol):
    """Type the keyword Hypothesis decorator for generated UTC instants."""

    def __call__(
        self, *, instant: SearchStrategy[datetime]
    ) -> Callable[[Callable[[datetime], None]], Callable[[], None]]:
        """Decorate a test callable with a generated UTC instant."""
        ...


_given_market_state: _MarketStateGiven = given
_given_venue_timezone: _VenueTimezoneGiven = given


class _ExpectedSession(TypedDict):
    """Describe one expected UTC session row in the checked-in C02 fixture."""

    session_label: str
    opens_at: str
    closes_at: str
    kind: str
    break_starts_at: NotRequired[str]
    break_ends_at: NotRequired[str]


class _Holiday(TypedDict):
    """Describe one attributed holiday closure in the C02 fixture."""

    calendar_date: str
    name: str


class _VenueFixture(TypedDict):
    """Describe one venue calendar and its expected source sessions."""

    calendar_name: str
    venue_id: str
    mic: str
    operating_mic: str
    name: str
    timezone_name: str
    range: tuple[str, str]
    expected_sessions: list[_ExpectedSession]
    holiday: NotRequired[_Holiday]


class _MarketStateFixture(TypedDict):
    """Describe synthetic auction, halt and limit intervals in the fixture."""

    session_label: str
    opening_auction: tuple[str, str]
    halt: tuple[str, str]
    limit_up: tuple[str, str]


class _SettlementCalendarFixture(TypedDict):
    """Describe bounded settlement coverage and explicit eligible dates."""

    range: tuple[str, str]
    settlement_dates: list[str]


class _CalendarFixture(TypedDict):
    """Describe the complete strict C02 golden fixture document."""

    schema_version: int
    fixture_id: str
    synthetic: bool
    description: str
    adapter_name: str
    adapter_version: str
    authority: str
    venues: list[_VenueFixture]
    synthetic_market_state: _MarketStateFixture
    settlement_calendar: _SettlementCalendarFixture


class _InvalidUuidPayload(TypedDict, total=False):
    """Describe malformed UUID payloads used at the strict model boundary."""

    uuid_value: UUID | str
    unexpected: bool


class _InvalidVenuePayload(TypedDict):
    """Describe a raw nested venue identity payload rejected by model validation."""

    venue_id: dict[str, UUID]
    mic: MarketIdentifierCode
    operating_mic: MarketIdentifierCode
    name: str
    timezone_name: str


class _InvalidSnapshotPayload(TypedDict):
    """Describe a mutable session collection rejected by snapshot validation."""

    venue: Venue
    version: CalendarSourceVersion
    covered_from: date
    covered_through: date
    sessions: list[TradingSession]


class _FixedValue:
    """Return one bound value on every call."""

    def __init__(self, value: object) -> None:
        """Bind the value to return."""
        self._value = value

    def __call__(self) -> object:
        """Return the bound value."""
        return self._value


class _DynamicTimestamp:
    """Expose a timestamp converter only through ``__getattr__``."""

    def __init__(self, value: datetime) -> None:
        """Bind the datetime returned by the dynamic converter."""
        self._value = value

    def __getattr__(self, name: str) -> Callable[[], object]:
        """Return the converter dynamically while preserving normal missing attributes."""
        if name == "to_pydatetime":
            return self._converted
        raise AttributeError(name)

    def _converted(self) -> object:
        """Return the bound datetime as the dynamic converter does."""
        return self._value


class _AttributeErrorTimestamp:
    """Expose a converter property that raises when accessed."""

    @property
    def to_pydatetime(self) -> Callable[[], object]:
        """Raise the source-style missing-property failure."""
        raise AttributeError("synthetic converter unavailable")


class _NonCallableConverter:
    """Expose an instance ``__call__`` member without being callable itself."""

    __call__: Callable[[], object]

    def __init__(self, value: datetime) -> None:
        """Bind a callable instance member that should not satisfy ``callable``."""
        self.__call__ = _FixedValue(value)


class _NonCallableTimestamp:
    """Expose a non-callable converter object through ``to_pydatetime``."""

    to_pydatetime: _NonCallableConverter

    def __init__(self, value: datetime) -> None:
        """Bind the converter object returned by the timestamp boundary."""
        self.to_pydatetime = _NonCallableConverter(value)


class _CalendarTestData:
    """Own synthetic C02 builders and strict loading of the checked-in fixture."""

    @staticmethod
    def _instant(value: str) -> datetime:
        """Parse ISO fixture text, translating a trailing Z to an explicit UTC offset."""
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _venue(
        *,
        identifier: str = "11111111-1111-4111-8111-111111111111",
        mic: str = "XNYS",
        timezone_name: str = "America/New_York",
    ) -> Venue:
        """Build a synthetic venue with explicit identity and timezone inputs.

        Args:
            identifier: Canonical venue UUID text.
            mic: Code used for both market and operating MICs.
            timezone_name: IANA timezone name; never inferred from the host.

        Returns:
            Validated venue with a name derived from the MIC.

        Raises:
            VenueCalendarValidationError: Identity, MIC or timezone validation fails.
        """
        return Venue(
            venue_id=VenueId.from_canonical_text(identifier),
            mic=MarketIdentifierCode(value=mic),
            operating_mic=MarketIdentifierCode(value=mic),
            name=f"Synthetic {mic} venue",
            timezone_name=timezone_name,
        )

    @staticmethod
    def _version(*, overridden: bool = False) -> CalendarSourceVersion:
        """Build pinned synthetic calendar provenance with optional override attribution.

        Args:
            overridden: Whether to include the fixture override source and revision.

        Returns:
            Source version bound to the pinned exchange-calendars adapter version.
        """
        return CalendarSourceVersion(
            calendar_version="c02-fixture",
            base_source="exchange_calendars",
            base_source_revision=EXCHANGE_CALENDARS_VERSION,
            adapter_name="exchange_calendars",
            adapter_version=EXCHANGE_CALENDARS_VERSION,
            authority=CalendarAuthority.SYNTHETIC_FIXTURE,
            override_source="fixture.overrides" if overridden else None,
            override_revision="override" if overridden else None,
        )

    @staticmethod
    def _session(
        *,
        label: date = date(2024, 3, 11),
        opens_at: datetime = datetime(2024, 3, 11, 1, 30, tzinfo=UTC),
        closes_at: datetime = datetime(2024, 3, 11, 8, 0, tzinfo=UTC),
        break_starts_at: datetime | None = datetime(2024, 3, 11, 4, 0, tzinfo=UTC),
        break_ends_at: datetime | None = datetime(2024, 3, 11, 5, 0, tzinfo=UTC),
        auctions: tuple[AuctionWindow, ...] = (),
    ) -> TradingSession:
        """Build a synthetic session for interval and market-state tests.

        Args:
            label: Calendar date identifying the session.
            opens_at: Inclusive UTC opening instant.
            closes_at: Exclusive UTC closing instant.
            break_starts_at: Inclusive UTC break start, or None with no break end.
            break_ends_at: Exclusive UTC break end, or None with no break start.
            auctions: Ordered, nonoverlapping auction windows attached to the session.

        Returns:
            Validated session; the defaults describe a Hong Kong session with a lunch break.

        Raises:
            VenueCalendarValidationError: Times, intervals or auction relationships are invalid.
        """
        return TradingSession(
            session_label=label,
            opens_at=opens_at,
            closes_at=closes_at,
            break_starts_at=break_starts_at,
            break_ends_at=break_ends_at,
            auctions=auctions,
        )

    @staticmethod
    def _load_fixture() -> _CalendarFixture:
        """Read and strictly validate the checked-in C02 golden fixture document.

        Returns:
            Typed fixture records preserving every consumed field and scalar type.

        Raises:
            OSError: The fixture cannot be read.
            ValidationError: The fixture JSON does not match the owned record contract.
        """
        return TypeAdapter(_CalendarFixture).validate_json(FIXTURE_PATH.read_bytes(), strict=True)
