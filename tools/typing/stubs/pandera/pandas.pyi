"""Type the consumed Pandera 0.33.1 object schema boundary."""

# standard library imports
from collections.abc import Callable, Mapping

# third party library imports
from pandas import DataFrame

class Check:
    """Describe an elementwise domain predicate."""
    def __init__(
        self, check_fn: Callable[[object], bool], *, element_wise: bool = ..., ignore_na: bool = ...
    ) -> None:
        """Bind a domain predicate to an elementwise schema check.

        Args:
            check_fn: Validated domain predicate.
            element_wise: Apply the predicate to individual values.
            ignore_na: Whether missing values bypass the predicate; explicit ratios disable this.
        """
        ...

class Column:
    """Describe one noncoercing object column."""
    def __init__(
        self, dtype: type[object], checks: Check, *, nullable: bool = ..., unique: bool = ...
    ) -> None:
        """Declare dtype, nullability and uniqueness for one explicit column.

        Args:
            dtype: Declared object dtype, preserving exact values.
            checks: Column domain-value check.
            nullable: Whether explicit missing values are allowed.
            unique: Whether duplicate row identities are refused.
        """
        ...

class DataFrameSchema:
    """Describe ordered strict dataframe admission."""
    def __init__(
        self,
        columns: Mapping[str, Column],
        *,
        ordered: bool,
        strict: bool,
        coerce: bool,
        unique_column_names: bool,
    ) -> None:
        """Declare the ordered strict schema for the selected model consumer.

        Args:
            columns: Declared ordered column names or schemas.
            ordered: Require authored column order.
            strict: Reject undeclared columns.
            coerce: Whether to coerce values; disabled by this consumer.
            unique_column_names: Refuse duplicate column names, including adjacent duplicates.
        """
        ...
    def validate(self, check_obj: DataFrame, *, inplace: bool = ...) -> DataFrame:
        """Validate the caller frame without changing its values.

        Args:
            check_obj: Caller-owned dataframe.
            inplace: Whether mutation is permitted; disabled by this consumer.

        Returns:
            Validated frame with preserved exact objects.
        """
        ...
