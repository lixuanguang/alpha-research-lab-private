"""Consumed pandas surface used by bounded research diagnostics."""

# standard library imports
from datetime import datetime
from typing import Literal, overload

NaT: datetime

class MultiIndex:
    """Describe the explicit date/instrument index sent to Alphalens."""

    def __new__(
        cls,
        levels: object = ...,
        codes: object = ...,
        sortorder: int | None = ...,
        names: object = ...,
        copy: bool = ...,
        name: object = ...,
        verify_integrity: bool = ...,
    ) -> MultiIndex:
        """Construct an index with pandas' explicit levels and code arrays."""
        ...

    @classmethod
    def from_tuples(
        cls, tuples: object, sortorder: int | None = ..., names: object = ...
    ) -> MultiIndex:
        """Construct a named multi-level index.

        Args:
            tuples: Ordered index tuples.
            sortorder: Optional native sort level.
            names: Ordered index level names.

        Returns:
            A named multi-level index.
        """
        ...

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
            data: Series values.
            index: Optional index values.
            dtype: Optional native dtype.
            name: Optional series name.
            copy: Optional copy policy.
        """
        ...

    def to_dict(self, *, into: type[dict[object, object]] = ...) -> dict[object, object]:
        """Project values for typed metric serialization.

        Args:
            into: Dictionary implementation receiving native index/value pairs.

        Returns:
            Native index/value mapping.
        """
        ...

class DataFrame:
    """Describe the explicit frame operations used by Alphalens."""

    def __init__(
        self,
        data: object = ...,
        index: object = ...,
        columns: object = ...,
        dtype: object = ...,
        copy: bool | None = ...,
    ) -> None:
        """Construct a frame from explicitly projected values.

        Args:
            data: Frame values.
            index: Optional row index.
            columns: Optional ordered column names.
            dtype: Optional native dtype.
            copy: Optional copy policy.
        """
        ...

    @property
    def empty(self) -> bool:
        """Whether the frame has no rows.

        Returns:
            Whether no rows are retained.
        """
        ...

    @overload
    def __getitem__(self, key: str) -> Series:
        """Select one named column."""
        ...

    @overload
    def __getitem__(self, key: list[str]) -> DataFrame:
        """Select an ordered set of named columns."""
        ...

    def __setitem__(self, key: str, value: object) -> None:
        """Assign one explicitly named column."""
        ...

    def dropna(
        self,
        *,
        axis: object = ...,
        how: object = ...,
        thresh: object = ...,
        subset: list[str] | None = ...,
        inplace: Literal[False] = ...,
        ignore_index: bool = ...,
    ) -> DataFrame:
        """Drop rows missing an explicitly named metric column.

        Args:
            axis: Native row or column axis.
            how: Native any/all missingness rule.
            thresh: Optional required non-null count.
            subset: Columns whose missing values exclude a row.
            inplace: Only the returned-frame mode is consumed by this adapter.
            ignore_index: Whether to replace the retained native index.

        Returns:
            A frame containing rows with complete selected columns.
        """
        ...

    def to_dict(self, orient: str = ..., *, into: object = ..., index: bool = ...) -> object:
        """Project a frame into a native mapping.

        Args:
            orient: Native pandas output orientation.
            into: Native mapping implementation.
            index: Whether to retain native index labels.

        Returns:
            Native frame mapping.
        """
        ...
