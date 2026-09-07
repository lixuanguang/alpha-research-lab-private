"""Consumed calendar exception hierarchy from exchange-calendars 4.13.2."""

class CalendarError(Exception):
    """Base exception for source calendar failures."""

    def __init__(self, **kwargs: object) -> None:
        """Initialize the native value using the documented constructor arguments.

        Args:
            kwargs: Native constructor metadata.
        """
        ...

class NoSessionsError(CalendarError):
    """Reject a source range containing no trading sessions."""
