"""Consumed QuantLib 1.43 day-count surface; see tools/typing/README.md."""

__version__: str

class Date:
    """Represent a native calendar date in day, month, year order."""

    def __init__(self, d: int, m: int, y: int, /) -> None:
        """Initialize the native value using the documented constructor arguments.

        Args:
            d: Day of the month.
            m: Calendar month from 1 through 12.
            y: Calendar year.
        """
        ...

class DayCounter:
    """Expose the native floating-point year-fraction calculation."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize the native value using the documented constructor arguments.

        Args:
            args: Native base-constructor arguments; direct construction is unsupported.
            kwargs: Native constructor metadata.
        """
        ...

    def yearFraction(self, d1: Date, d2: Date, /) -> float:
        """Return the native year fraction under this counter's convention.

        Args:
            d1: Inclusive interval start.
            d2: Interval end.

        Returns:
            The native year fraction under this counter's convention.
        """
        ...

class Actual360(DayCounter):
    """Count actual days on a 360-day basis."""

    def __init__(self, includeLastDay: bool = False) -> None:
        """Initialize the native value using the documented constructor arguments.

        Args:
            includeLastDay: Whether to include the final day in the count.
        """
        ...

class Actual365Fixed(DayCounter):
    """Count actual days on the fixed 365-day basis."""

    def __init__(self, c: int = 0, /) -> None:
        """Initialize the native value using the documented constructor arguments.

        Args:
            c: Native integer convention identifier.
        """
        ...

class ActualActual(DayCounter):
    """Select an explicit actual/actual convention."""

    ISDA: int

    def __init__(self, c: int, /) -> None:
        """Initialize the native value using the documented constructor arguments.

        Args:
            c: Native integer convention identifier.
        """
        ...

class Thirty360(DayCounter):
    """Select an explicit 30/360 convention."""

    BondBasis: int
    European: int

    def __init__(self, c: int, /) -> None:
        """Initialize the native value using the documented constructor arguments.

        Args:
            c: Native integer convention identifier.
        """
        ...

class Settings:
    """Expose only the process-wide evaluation date used by isolation tests."""

    evaluationDate: Date

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Represent the native singleton; direct construction is unsupported.

        Args:
            args: Native base-constructor arguments.
            kwargs: Native base-constructor metadata.
        """
        ...

    @staticmethod
    def instance() -> Settings:
        """Return the process-wide native settings instance.

        Returns:
            The singleton containing the ambient evaluation date.
        """
        ...
