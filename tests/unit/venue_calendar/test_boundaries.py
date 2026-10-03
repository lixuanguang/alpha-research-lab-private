"""Test strict venue-calendar boundaries and dependency stub conformance."""

from __future__ import annotations

# standard library imports
from datetime import date, datetime, tzinfo
from uuid import UUID

# third party library imports
import exchange_calendars
import pandas
import pytest
from exchange_calendars.errors import CalendarError, NoSessionsError
from pydantic import BaseModel, ValidationError
from venue_calendar_cases import (
    _CalendarTestData,
    _InvalidSnapshotPayload,
    _InvalidUuidPayload,
    _InvalidVenuePayload,
)

# project library imports
from reference_data.calendars import (
    EXCHANGE_CALENDARS_VERSION,
    AuctionWindow,
    CalendarAdapterError,
    CalendarAuthority,
    CalendarClosure,
    CalendarSourceVersion,
    ExchangeCalendarsAdapter,
    MarketIdentifierCode,
    MarketInterruption,
    MarketState,
    PriceLimitWindow,
    SessionOverride,
    SettlementCalendar,
    TradingSession,
    Venue,
    VenueCalendarSnapshot,
    VenueCalendarValidationError,
    VenueId,
)
from reference_data.calendars.models import VenueCalendarModel


class TestVenueCalendarBoundaryContracts(_CalendarTestData):
    """Exercise strict identity, model and source-value boundaries."""

    def test_model_error_details_preserve_order_and_validation_cause(self) -> None:
        """Join multiple nested field failures in order and retain the framework cause."""
        with pytest.raises(VenueCalendarValidationError) as raised:
            Venue(
                venue_id={"uuid_value": "11111111-1111-4111-8111-111111111111"},  # type: ignore[arg-type]  # [owner=platform; rationale=exercise raw nested identity rejection and preserve translated field details; expires=2027-03-01]
                mic={"value": "XNYS"},  # type: ignore[arg-type]  # [owner=platform; rationale=exercise raw nested MIC rejection and preserve translated field details; expires=2027-03-01]
                operating_mic={"value": "XNYS"},  # type: ignore[arg-type]  # [owner=platform; rationale=exercise raw nested operating MIC rejection and preserve translated field details; expires=2027-03-01]
                name="Synthetic venue",
                timezone_name="America/New_York",
            )

        assert str(raised.value) == (
            "venue_id must be a VenueId\n"
            "mic must be a MarketIdentifierCode\n"
            "operating_mic must be a MarketIdentifierCode"
        )
        assert isinstance(raised.value.__cause__, ValidationError)

    def test_venue_identity_and_calendar_version_reject_invalid_state(self) -> None:
        """Reject nil or noncanonical IDs, incomplete override provenance and unknown timezones."""
        with pytest.raises(VenueCalendarValidationError, match="non-nil UUID"):
            VenueId(uuid_value=UUID(int=0))
        with pytest.raises(VenueCalendarValidationError, match="canonical UUID"):
            VenueId.from_canonical_text("11111111-1111-4111-8111-11111111111A")
        with pytest.raises(VenueCalendarValidationError, match="provided together"):
            CalendarSourceVersion(
                calendar_version="v1",
                base_source="exchange_calendars",
                base_source_revision="source",
                adapter_name="exchange_calendars",
                adapter_version=EXCHANGE_CALENDARS_VERSION,
                authority=CalendarAuthority.REFERENCE_ONLY,
                override_source="fixture.overrides",
            )
        with pytest.raises(VenueCalendarValidationError, match="IANA timezone"):
            self._venue(timezone_name="Local/Host")

    def test_venue_calendar_models_are_strict_frozen_pydantic_boundaries(self) -> None:
        """Reject coercion, mutable collections, frozen assignment and invalid nested copies."""
        pydantic_model_type: type[object] = BaseModel
        model_types: tuple[type[VenueCalendarModel], ...] = (
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
        assert all(issubclass(model_type, pydantic_model_type) for model_type in model_types)

        venue_id = VenueId.from_canonical_text("11111111-1111-4111-8111-111111111111")
        invalid_uuid_payload: _InvalidUuidPayload = {
            "uuid_value": str(venue_id.uuid_value),
        }
        with pytest.raises(ValidationError):
            VenueId.model_validate(invalid_uuid_payload)
        unexpected_uuid_payload: _InvalidUuidPayload = {
            "uuid_value": venue_id.uuid_value,
            "unexpected": True,
        }
        with pytest.raises(ValidationError):
            VenueId.model_validate(unexpected_uuid_payload)
        with pytest.raises(ValidationError):
            venue_id.uuid_value = UUID("22222222-2222-4222-8222-222222222222")  # type: ignore[misc]  # [owner=platform; rationale=exercise frozen-field runtime rejection at the original assignment; expires=2027-03-01]
        with pytest.raises(ValidationError, match="must be a VenueId"):
            invalid_raw_identity_payload: _InvalidVenuePayload = {
                "venue_id": {"uuid_value": venue_id.uuid_value},
                "mic": MarketIdentifierCode(value="XNYS"),
                "operating_mic": MarketIdentifierCode(value="XNYS"),
                "name": "Invalid raw identity",
                "timezone_name": "America/New_York",
            }
            Venue.model_validate(invalid_raw_identity_payload)
        with pytest.raises(ValidationError, match="immutable tuple"):
            invalid_snapshot_payload: _InvalidSnapshotPayload = {
                "venue": self._venue(),
                "version": self._version(),
                "covered_from": date(2024, 3, 11),
                "covered_through": date(2024, 3, 11),
                "sessions": [self._session()],
            }
            VenueCalendarSnapshot.model_validate(invalid_snapshot_payload)

        with pytest.raises(VenueCalendarValidationError, match="non-nil UUID"):
            VenueId.model_construct(uuid_value=UUID(int=0))
        tampered_update: dict[str, UUID] = {"uuid_value": UUID(int=0)}
        tampered_id = venue_id.model_copy(update=tampered_update)
        with pytest.raises(VenueCalendarValidationError, match="non-nil UUID"):
            Venue(
                venue_id=tampered_id,
                mic=MarketIdentifierCode(value="XNYS"),
                operating_mic=MarketIdentifierCode(value="XNYS"),
                name="Invalid venue",
                timezone_name="America/New_York",
            )

    def test_invalid_optional_source_instant_is_not_treated_as_an_absent_break(
        self,
    ) -> None:
        """Reject a naive optional break timestamp instead of treating it as a missing break."""
        with pytest.raises(CalendarAdapterError, match="invalid session break"):
            ExchangeCalendarsAdapter._as_utc_datetime(
                datetime(2024, 3, 11, 4, 0),
                field_name="session break",
                optional=True,
            )


class TestCalendarStubConformance:
    """Check the declared calendar factory, timestamp and sentinel contracts."""

    @pytest.mark.parametrize("name", ["XNYS", "XHKG"])
    def test_native_schedule_surface(self, name: str) -> None:
        """Verify both continuous sessions and intraday-break sessions against the stubs."""
        calendar = exchange_calendars.get_calendar(
            name, start=date(2024, 11, 25), end=date(2024, 11, 29), side="left"
        )
        assert isinstance(calendar.name, str)
        assert isinstance(calendar.tz, tzinfo)
        assert isinstance(pandas.NaT, datetime)
        assert all(isinstance(label, datetime) for label in calendar.early_closes)
        labels = tuple(calendar.sessions)
        assert labels and all(isinstance(label, datetime) for label in labels)
        for label in labels:
            session = label.date()
            for stamp in (
                calendar.session_open(session),
                calendar.session_close(session),
            ):
                assert isinstance(stamp, datetime) and stamp.tzinfo is not None
            for stamp in (
                calendar.session_break_start(session),
                calendar.session_break_end(session),
            ):
                if name == "XNYS":
                    assert stamp is pandas.NaT
                else:
                    assert isinstance(stamp, datetime) and stamp.tzinfo is not None
        assert issubclass(NoSessionsError, CalendarError)
