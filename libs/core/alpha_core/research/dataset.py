"""Gold-tier dataset handle — in-memory interface to a built gold dataset."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import alpha_core.research.as_of as as_of_mod
import alpha_core.utils.time as time_utils


class DatasetConfig(BaseModel):
    """Configuration for a gold dataset build."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    start: datetime
    end: datetime
    venues: list[str] | None = None
    event_types: list[str] = Field(default_factory=lambda: ["trades", "ohlcv"])
    universe_filters: dict[str, Any] = Field(default_factory=dict)
    require_quality_pass: bool = True
    require_gap_free: bool = False
    max_gap_hours: float = 24.0

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("dataset name cannot be empty")
        if "/" in cleaned or "\\" in cleaned:
            raise ValueError("dataset name must not contain path separators")
        if ".." in cleaned:
            raise ValueError("dataset name must not contain '..'")
        return cleaned

    @field_validator("start", "end")
    @classmethod
    def _normalize_time(cls, value: datetime) -> datetime:
        return time_utils.ensure_utc(value)

    @field_validator("venues")
    @classmethod
    def _normalize_venues(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for venue in value:
            cleaned = venue.strip().lower()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized or None

    @field_validator("event_types")
    @classmethod
    def _normalize_event_types(cls, value: list[str]) -> list[str]:
        supported = {"trades", "ohlcv", "books"}
        normalized: list[str] = []
        seen: set[str] = set()
        for event_type in value:
            cleaned = event_type.strip().lower()
            if not cleaned or cleaned in seen:
                continue
            if cleaned not in supported:
                raise ValueError(
                    f"unsupported event type '{cleaned}'; expected one of {sorted(supported)}"
                )
            seen.add(cleaned)
            normalized.append(cleaned)
        if not normalized:
            raise ValueError("at least one event type is required")
        return normalized

    @model_validator(mode="after")
    def _validate_window(self) -> DatasetConfig:
        if self.end <= self.start:
            raise ValueError("`end` must be later than `start`")
        return self


class DatasetManifest(BaseModel):
    """Metadata for a built gold dataset — persisted as ``_meta.json``."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    dataset_id: str  # Deterministic hash of config
    config: DatasetConfig
    built_at: datetime
    row_counts: dict[str, int]  # Per event type
    instrument_count: int
    date_range: tuple[datetime, datetime]
    quality_summary: dict[str, Any]
    schema_version: int = 1


class GoldDataset:
    """In-memory handle to a built gold-tier research dataset.

    Returned by :meth:`DatasetBuilder.build` or :meth:`DatasetBuilder.load`.
    All query methods accept an optional *instrument_id* filter; passing
    ``None`` (default) returns data for all instruments.
    """

    def __init__(self, manifest: DatasetManifest, dataset_dir: Path) -> None:
        self._manifest = manifest
        self._dir = dataset_dir
        # Lazy-loaded table cache
        self._cache: dict[str, pa.Table] = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def manifest(self) -> DatasetManifest:
        return self._manifest

    # ------------------------------------------------------------------
    # Data accessors
    # ------------------------------------------------------------------

    def trades(self, instrument_id: str | None = None) -> pa.Table:
        """Return gold trades table, optionally filtered to *instrument_id*."""
        table = self._load("trades")
        return _filter_by_instrument(table, instrument_id)

    def ohlcv(
        self,
        instrument_id: str | None = None,
        resolution: str | None = None,
    ) -> pa.Table:
        """Return gold OHLCV table with optional instrument and resolution filters."""
        table = self._load("ohlcv")
        table = _filter_by_instrument(table, instrument_id)
        if resolution is not None and "resolution" in table.schema.names:
            table = table.filter(pc.equal(table.column("resolution"), resolution))
        return table

    def books(self, instrument_id: str | None = None) -> pa.Table:
        """Return gold order-book snapshots table."""
        table = self._load("books")
        return _filter_by_instrument(table, instrument_id)

    # ------------------------------------------------------------------
    # Universe helpers
    # ------------------------------------------------------------------

    def universe_at(self, as_of: datetime) -> list[str]:
        """Return instrument IDs present in the universe at *as_of*.

        Uses the ``universe.parquet`` file which records point-in-time
        membership rows written at dataset build time.
        """
        universe_table = self._load("universe")
        if universe_table.num_rows == 0:
            return []

        as_of_utc = time_utils.ensure_utc(as_of)
        filtered = as_of_mod.as_of_filter(universe_table, as_of_column="as_of", cutoff=as_of_utc)
        if filtered.num_rows == 0 or "instrument_id" not in filtered.schema.names:
            return []
        latest_as_of = pc.max(filtered.column("as_of"))
        if not latest_as_of.is_valid:
            return []
        snapshot = filtered.filter(pc.equal(filtered.column("as_of"), latest_as_of))
        raw: list[str | None] = snapshot.column("instrument_id").to_pylist()
        return list(dict.fromkeys(x for x in raw if x is not None))

    def instruments(self) -> list[str]:
        """Return the full list of instrument IDs covered by this dataset."""
        universe_table = self._load("universe")
        if "instrument_id" not in universe_table.schema.names:
            return []
        raw: list[str | None] = universe_table.column("instrument_id").to_pylist()
        return list(dict.fromkeys(x for x in raw if x is not None))

    # ------------------------------------------------------------------
    # Other helpers
    # ------------------------------------------------------------------

    def date_range(self) -> tuple[datetime, datetime]:
        return self._manifest.date_range

    def to_pandas(self, event_type: str = "trades") -> pd.DataFrame:
        """Return the requested event type as a pandas DataFrame."""
        table = self._load(event_type)
        return table.to_pandas()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self, key: str) -> pa.Table:
        if key in self._cache:
            return self._cache[key]

        path = self._dir / f"{key}.parquet"
        if not path.exists():
            self._cache[key] = pa.table({})
            return self._cache[key]

        table = pq.read_table(path)
        self._cache[key] = table
        return table


def _filter_by_instrument(table: pa.Table, instrument_id: str | None) -> pa.Table:
    if instrument_id is None or "instrument_id" not in table.schema.names:
        return table
    return table.filter(pc.equal(table.column("instrument_id"), instrument_id))


__all__ = ["DatasetConfig", "DatasetManifest", "GoldDataset"]
