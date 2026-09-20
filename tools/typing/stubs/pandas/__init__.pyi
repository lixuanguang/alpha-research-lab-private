"""Consumed pandas 3.0.5 missing-timestamp singleton, a datetime subclass."""

# standard library imports
from datetime import datetime

NaT: datetime

class Series:
    """Describe the bounded numerical report projection."""
    def __init__(
        self,
        data: object = ...,
        index: object = ...,
        dtype: object = ...,
        name: object = ...,
        copy: bool | None = ...,
    ) -> None:
        """Construct an explicitly typed reporting series.

        Args:
            data: Complete analytical projections.
            index: Explicit reporting clocks.
            dtype: Declared numerical representation.
            name: Optional series name.
            copy: Optional copy policy.
        """
        ...

class DataFrame:
    """Describe the explicit object-frame construction used by model admission."""
    def __init__(
        self,
        data: object = ...,
        index: object = ...,
        columns: object = ...,
        dtype: object = ...,
        copy: bool | None = ...,
    ) -> None:
        """Construct an explicit object-dtype frame without numerical coercion.

        Args:
            data: Explicit model values.
            index: Optional dataframe index.
            columns: Declared ordered column names or schemas.
            dtype: Declared object dtype, preserving exact values.
            copy: Optional pandas copy policy.
        """
        ...
