"""Consumed exchange-calendars 4.13.2 calendar factory."""

# standard library imports
from datetime import date
from typing import Literal

# project library imports
from .exchange_calendar import ExchangeCalendar as ExchangeCalendar

def get_calendar(
    name: str,
    start: date | None = None,
    end: date | None = None,
    side: Literal["left", "right", "both", "neither"] | None = None,
) -> ExchangeCalendar:
    """Load a named calendar over explicit inclusive date bounds.

    Args:
        name: Canonical exchange calendar name.
        start: Inclusive first date, or the source default when omitted.
        end: Inclusive last date, or the source default when omitted.
        side: Which boundary minutes belong to the session.

    Returns:
        A named calendar over explicit inclusive date bounds.
    """
    ...
