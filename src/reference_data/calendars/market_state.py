"""Define immutable venue interruption, price-limit, and market-state contracts."""

from __future__ import annotations

# standard library imports
from datetime import date, datetime
from enum import StrEnum

# third party library imports
from pydantic import field_validator

# project library imports
from reference_data.calendars.core import (
    VenueCalendarModel,
    VenueCalendarValidationError,
)
from reference_data.calendars.sessions import AuctionKind, TradingSession


class InterruptionKind(StrEnum):
    """Classify an explicitly supplied interruption of normal session state."""

    HALT = "halt"


class MarketInterruption(VenueCalendarModel):
    """Represent one source-attributed half-open halt interval.

    The snapshot checks that the halt lies in exactly one session and does not
    overlap other halts. Halts can overlap auctions, breaks and price limits.

    Attributes:
        interruption_id: Stable token identifying the halt.
        kind: Typed interruption classification, currently HALT.
        starts_at: Inclusive aware UTC start.
        ends_at: Exclusive aware UTC end strictly after the start.
        reason: Unpadded nonempty explanation, up to 256 characters.
        source: Stable attribution token.
        source_revision: Stable source revision token.
    """

    interruption_id: str
    kind: InterruptionKind
    starts_at: datetime
    ends_at: datetime
    reason: str
    source: str
    source_revision: str

    def model_post_init(self, _context: object, /) -> None:
        """Validate the halt interval and its source attribution.

        Raises:
            VenueCalendarValidationError: An ID, kind, bounded reason, attribution token or
                increasing UTC interval is invalid.
        """
        VenueCalendarModel._require_stable_token(self.interruption_id, field_name="interruption_id")
        if not isinstance(self.kind, InterruptionKind):
            raise VenueCalendarValidationError("interruption kind must be an InterruptionKind")
        start = VenueCalendarModel._require_utc_datetime(
            self.starts_at, field_name="interruption starts_at"
        )
        end = VenueCalendarModel._require_utc_datetime(
            self.ends_at, field_name="interruption ends_at"
        )
        if end <= start:
            raise VenueCalendarValidationError("interruption ends_at must be after starts_at")
        VenueCalendarModel._require_bounded_text(
            self.reason, field_name="interruption reason", maximum_length=256
        )
        VenueCalendarModel._require_stable_token(self.source, field_name="interruption source")
        VenueCalendarModel._require_stable_token(
            self.source_revision, field_name="interruption source_revision"
        )

    def contains(self, instant: datetime) -> bool:
        """Return whether an explicit UTC instant lies in this half-open interruption.

        Args:
            instant: Aware datetime with a zero UTC offset.

        Returns:
            True from the inclusive start until the exclusive end defined by starts_at and
            ends_at.

        Raises:
            VenueCalendarValidationError: The input is not an aware datetime with a zero UTC
                offset.
        """
        checked = VenueCalendarModel._require_utc_datetime(instant, field_name="instant")
        return self.starts_at <= checked < self.ends_at


class PriceLimitState(StrEnum):
    """Describe the explicit price-limit state observed for a venue."""

    NONE = "none"
    LIMIT_UP = "limit_up"
    LIMIT_DOWN = "limit_down"
    LOCKED = "locked"


class PriceLimitWindow(VenueCalendarModel):
    """Represent one source-attributed half-open non-normal limit interval.

    The snapshot checks single-session containment and non-overlap with other
    price-limit windows. A price limit can coexist with an auction, break or halt.

    Attributes:
        limit_id: Stable token identifying the limit window.
        state: Typed non-NONE price-limit state.
        starts_at: Inclusive aware UTC start.
        ends_at: Exclusive aware UTC end strictly after the start.
        source: Stable attribution token.
        source_revision: Stable source revision token.
    """

    limit_id: str
    state: PriceLimitState
    starts_at: datetime
    ends_at: datetime
    source: str
    source_revision: str

    def model_post_init(self, _context: object, /) -> None:
        """Require a non-normal attributed price-limit interval.

        Raises:
            VenueCalendarValidationError: An ID or attribution token is invalid, state is
                untyped or NONE, or UTC bounds are invalid.
        """
        VenueCalendarModel._require_stable_token(self.limit_id, field_name="limit_id")
        if not isinstance(self.state, PriceLimitState) or self.state is PriceLimitState.NONE:
            raise VenueCalendarValidationError(
                "price-limit window state must be a non-NONE PriceLimitState"
            )
        start = VenueCalendarModel._require_utc_datetime(
            self.starts_at, field_name="price-limit starts_at"
        )
        end = VenueCalendarModel._require_utc_datetime(
            self.ends_at, field_name="price-limit ends_at"
        )
        if end <= start:
            raise VenueCalendarValidationError("price-limit ends_at must be after starts_at")
        VenueCalendarModel._require_stable_token(self.source, field_name="price-limit source")
        VenueCalendarModel._require_stable_token(
            self.source_revision, field_name="price-limit source_revision"
        )

    def contains(self, instant: datetime) -> bool:
        """Return whether an explicit UTC instant lies in this half-open price-limit window.

        Args:
            instant: Aware datetime with a zero UTC offset.

        Returns:
            True from the inclusive start until the exclusive end defined by starts_at and
            ends_at.

        Raises:
            VenueCalendarValidationError: The input is not an aware datetime with a zero UTC
                offset.
        """
        checked = VenueCalendarModel._require_utc_datetime(instant, field_name="instant")
        return self.starts_at <= checked < self.ends_at


class MarketStatus(StrEnum):
    """Describe the canonical schedule state at one instant."""

    CLOSED = "closed"
    AUCTION = "auction"
    CONTINUOUS = "continuous"
    BREAK = "break"
    HALTED = "halted"


class MarketState(VenueCalendarModel):
    """Return schedule, auction, halt, and independent price-limit state together.

    Attributes:
        status: Typed schedule state. CLOSED forbids session, auction, halt and limit
            metadata.
        price_limit_state: Independent typed limit state, always NONE when closed.
        session_label: Required date for every non-CLOSED state, including BREAK and HALTED.
        auction_kind: Present exactly when status is AUCTION.
        interruption_id: Stable halt token present exactly when status is HALTED.
    """

    status: MarketStatus
    price_limit_state: PriceLimitState
    session_label: date | None = None
    auction_kind: AuctionKind | None = None
    interruption_id: str | None = None

    def model_post_init(self, _context: object, /) -> None:
        """Reject incoherent schedule, auction, halt, or limit state.

        Raises:
            VenueCalendarValidationError: Types or metadata violate the CLOSED, session-label,
                auction-kind or halt-ID coupling rules.
        """
        if not isinstance(self.status, MarketStatus):
            raise VenueCalendarValidationError("market state status must be a MarketStatus")
        if not isinstance(self.price_limit_state, PriceLimitState):
            raise VenueCalendarValidationError(
                "market state price_limit_state must be a PriceLimitState"
            )
        if self.session_label is not None:
            VenueCalendarModel._require_date(
                self.session_label, field_name="market state session_label"
            )
        if self.status is MarketStatus.CLOSED:
            if (
                self.session_label is not None
                or self.auction_kind is not None
                or self.interruption_id is not None
                or self.price_limit_state is not PriceLimitState.NONE
            ):
                raise VenueCalendarValidationError(
                    "closed market state cannot carry session, auction, halt, or limit state"
                )
            return
        if self.session_label is None:
            raise VenueCalendarValidationError("open market state requires a session_label")
        if (self.status is MarketStatus.AUCTION) != (self.auction_kind is not None):
            raise VenueCalendarValidationError(
                "auction_kind must be present exactly for AUCTION market state"
            )
        if self.auction_kind is not None and not isinstance(self.auction_kind, AuctionKind):
            raise VenueCalendarValidationError("auction_kind must be an AuctionKind")
        if (self.status is MarketStatus.HALTED) != (self.interruption_id is not None):
            raise VenueCalendarValidationError(
                "interruption_id must be present exactly for HALTED market state"
            )
        if self.interruption_id is not None:
            VenueCalendarModel._require_stable_token(
                self.interruption_id, field_name="interruption_id"
            )


class SessionOverrideAction(StrEnum):
    """Declare how an explicit override changes one base calendar label."""

    ADD = "add"
    REPLACE = "replace"
    REMOVE = "remove"


class SessionOverride(VenueCalendarModel):
    """Describe one source-attributed, versioned change to a base session.

    Construction validates the instruction; the adapter applies it to the base
    calendar. A snapshot checks that the recorded result matches the instruction.

    Attributes:
        override_id: Stable override token, unique within a snapshot.
        action: Typed ADD, REPLACE or REMOVE instruction.
        session_label: Date of the targeted session.
        reason: Unpadded nonempty explanation, up to 256 characters.
        source: Stable token matching the snapshot override source.
        source_revision: Stable token matching the snapshot override revision.
        replacement: Same-label owned session required for ADD/REPLACE and forbidden for
            REMOVE.
    """

    override_id: str
    action: SessionOverrideAction
    session_label: date
    reason: str
    source: str
    source_revision: str
    replacement: TradingSession | None = None

    @field_validator("replacement", mode="before")
    @classmethod
    def typed_replacement(cls, value: object) -> object:
        """Require an owned replacement session when one is present.

        Args:
            value: Candidate TradingSession, or None for a removal.

        Returns:
            The original session or None; action-specific presence is checked later.

        Raises:
            VenueCalendarValidationError: A supplied value is not a TradingSession.
        """
        if value is not None and not isinstance(value, TradingSession):
            raise VenueCalendarValidationError("replacement must be a TradingSession")
        return value

    def model_post_init(self, _context: object, /) -> None:
        """Validate action, replacement label, and override attribution.

        Raises:
            VenueCalendarValidationError: An ID, date, reason, action or attribution is invalid;
                or replacement presence or label disagrees with the action.
        """
        VenueCalendarModel._require_stable_token(self.override_id, field_name="override_id")
        if not isinstance(self.action, SessionOverrideAction):
            raise VenueCalendarValidationError(
                "session override action must be a SessionOverrideAction"
            )
        VenueCalendarModel._require_date(self.session_label, field_name="override session_label")
        VenueCalendarModel._require_bounded_text(
            self.reason, field_name="override reason", maximum_length=256
        )
        VenueCalendarModel._require_stable_token(self.source, field_name="override source")
        VenueCalendarModel._require_stable_token(
            self.source_revision, field_name="override source_revision"
        )
        if self.action is SessionOverrideAction.REMOVE:
            if self.replacement is not None:
                raise VenueCalendarValidationError(
                    "REMOVE session override cannot include a replacement"
                )
            return
        if not isinstance(self.replacement, TradingSession):
            raise VenueCalendarValidationError(
                "ADD and REPLACE session overrides require a TradingSession replacement"
            )
        if self.replacement.session_label != self.session_label:
            raise VenueCalendarValidationError(
                "session override label must match replacement session_label"
            )
