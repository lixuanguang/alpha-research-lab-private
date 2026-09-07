"""Consumed schedule queries; pandas Timestamp and NaT subclass datetime."""

# standard library imports
from abc import ABCMeta, abstractmethod
from collections.abc import Iterable
from datetime import date, datetime, tzinfo
from typing import Literal

class ExchangeCalendar(metaclass=ABCMeta):
    """Provide bounded source sessions and timezone-aware timestamps."""

    def __init__(
        self,
        start: date | None = None,
        end: date | None = None,
        side: Literal["left", "right", "both", "neither"] = "left",
    ) -> None:
        """Initialize the native value using the documented constructor arguments.

        Args:
            start: Inclusive first date, or the source default when omitted.
            end: Inclusive last date, or the source default when omitted.
            side: Which boundary minutes belong to the session.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the source calendar's canonical identifier.

        Returns:
            The source calendar's canonical identifier.
        """
        ...

    @property
    @abstractmethod
    def tz(self) -> tzinfo:
        """Return the source calendar's local timezone.

        Returns:
            The source calendar's local timezone.
        """
        ...

    @property
    def sessions(self) -> Iterable[datetime]:
        """Return the source's ordered session labels.

        Returns:
            The source's ordered session labels.
        """
        ...

    @property
    def early_closes(self) -> Iterable[datetime]:
        """Return the labels with an earlier than regular close.

        Returns:
            The labels with an earlier than regular close.
        """
        ...

    def session_open(self, session: date, _parse: bool = True) -> datetime:
        """Return the timezone-aware opening timestamp for a session.

        Args:
            session: Source session label as a calendar date.
            _parse: Whether the source validates the session label before lookup.

        Returns:
            The timezone-aware opening timestamp for a session.
        """
        ...

    def session_close(self, session: date, _parse: bool = True) -> datetime:
        """Return the timezone-aware closing timestamp for a session.

        Args:
            session: Source session label as a calendar date.
            _parse: Whether the source validates the session label before lookup.

        Returns:
            The timezone-aware closing timestamp for a session.
        """
        ...

    def session_break_start(self, session: date, _parse: bool = True) -> datetime:
        """Return the timezone-aware break start or the NaT singleton.

        Args:
            session: Source session label as a calendar date.
            _parse: Whether the source validates the session label before lookup.

        Returns:
            The timezone-aware break start or the nat singleton.
        """
        ...

    def session_break_end(self, session: date, _parse: bool = True) -> datetime:
        """Return the timezone-aware break end or the NaT singleton.

        Args:
            session: Source session label as a calendar date.
            _parse: Whether the source validates the session label before lookup.

        Returns:
            The timezone-aware break end or the nat singleton.
        """
        ...
