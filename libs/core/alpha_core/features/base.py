"""Feature base classes and result type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
import pyarrow as pa


@dataclass
class FeatureResult:
    """Output of a single feature computation.

    ``values`` is aligned index-for-index to the input table rows.
    NaN entries appear where insufficient history prevents computation.
    """

    name: str
    values: npt.NDArray[np.float64]
    computed_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    params: dict[str, Any] = field(default_factory=dict)

    def to_arrow(self) -> pa.ChunkedArray:
        """Return values as a PyArrow float64 array."""
        return pa.chunked_array([pa.array(self.values, type=pa.float64())])


class Feature(ABC):
    """Abstract base for all features.

    Sub-classes must implement :meth:`compute` and set :attr:`name`.
    The ``params`` property exposes a canonical snapshot of construction
    arguments used for deterministic hashing and manifest recording.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique feature name (must be a valid column identifier)."""

    @property
    @abstractmethod
    def params(self) -> dict[str, Any]:
        """Canonical, JSON-serialisable parameter snapshot."""

    @abstractmethod
    def compute(
        self,
        data: pa.Table,
        *,
        instrument_id: str | None = None,
    ) -> FeatureResult:
        """Compute this feature for ``data``.

        Args:
            data: PyArrow table, typically a gold dataset partition.
                  Expected columns: ``instrument_id``, ``ts_event``, ``price``, ``size``.
            instrument_id: When provided, compute only for that instrument
                           (rows for other instruments are expected to be pre-filtered).

        Returns:
            :class:`FeatureResult` with ``values`` aligned to the input row order.
        """

    @property
    def dependencies(self) -> list[str]:
        """Feature names this feature depends on (for registry topological sort)."""
        return []

    # ------------------------------------------------------------------
    # Helpers available to sub-classes
    # ------------------------------------------------------------------

    def _series_from_table(
        self,
        table: pa.Table,
        column: str,
    ) -> pd.Series:
        if column not in table.schema.names:
            raise KeyError(f"Column '{column}' not found in table (have: {table.schema.names})")
        return table.column(column).to_pandas()

    def _empty_result(self, n: int) -> FeatureResult:
        return FeatureResult(
            name=self.name,
            values=np.full(n, np.nan, dtype=np.float64),
            params=self.params,
        )
