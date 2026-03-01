"""PartitionValidator — run quality suites on silver partitions after write."""

from __future__ import annotations

from datetime import UTC, datetime

import pyarrow as pa  # type: ignore[import-untyped]

import alpha_core.quality.base as quality_base
import alpha_core.quality.suites.book_quality as book_quality_suites
import alpha_core.quality.suites.ohlcv_quality as ohlcv_quality_suites
import alpha_core.quality.suites.trade_quality as trade_quality_suites
import alpha_core.storage.parquet_reader as parquet_reader_mod


class PartitionValidator:
    """Validates silver partitions by running registered quality suites."""

    def __init__(
        self,
        reader: parquet_reader_mod.ParquetEventReader,
        suites: dict[str, quality_base.QualitySuite],
    ) -> None:
        """
        Args:
            reader: Parquet reader pointed at the silver storage root.
            suites: Mapping of event_type key → QualitySuite.
                    Standard keys: "trades", "books", "ohlcv", "book_deltas".
        """
        self._reader = reader
        self._suites = suites

    @classmethod
    def from_defaults(
        cls,
        reader: parquet_reader_mod.ParquetEventReader,
        *,
        include_microstructure: bool = True,
    ) -> PartitionValidator:
        """Construct a validator with the standard suites pre-registered.

        Args:
            reader:                  Parquet reader for the silver storage root.
            include_microstructure:  When True (default), also registers
                                     microstructure suites for ``"books"``
                                     and ``"book_deltas"``.
        """
        suites: dict[str, quality_base.QualitySuite] = {
            "trades": trade_quality_suites.TRADE_SUITE,
            "books": (
                book_quality_suites.BOOK_WITH_MICROSTRUCTURE_SUITE
                if include_microstructure
                else book_quality_suites.BOOK_SUITE
            ),
            "ohlcv": ohlcv_quality_suites.OHLCV_SUITE,
        }
        if include_microstructure:
            suites["book_deltas"] = book_quality_suites.BOOK_DELTA_MICROSTRUCTURE_SUITE
        return cls(reader=reader, suites=suites)

    def validate_partition(
        self,
        event_type: str,
        venue: str,
        date: str,
        **extra_partitions: str,
    ) -> quality_base.SuiteReport:
        """Validate a single silver partition.

        Args:
            event_type: One of "trades", "books", "ohlcv", "book_deltas".
            venue: Venue identifier string.
            date: Partition date string "YYYY-MM-DD".
            **extra_partitions: Additional partition keys, e.g. resolution="1h".

        Returns:
            SuiteReport from the matching quality suite.
        """
        suite = self._suites.get(event_type)
        if suite is None:
            raise KeyError(f"No quality suite registered for event_type='{event_type}'")

        start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=UTC)
        end = datetime(start.year, start.month, start.day, 23, 59, 59, 999999, tzinfo=UTC)

        if event_type == "trades":
            table = self._reader.read_trades(venue=venue, start=start, end=end)
        elif event_type == "books":
            table = self._reader.read_books(venue=venue, start=start, end=end)
        elif event_type == "ohlcv":
            resolution = extra_partitions.get("resolution")
            table = self._reader.read_ohlcv(
                venue=venue, resolution=resolution, start=start, end=end
            )
        elif event_type == "book_deltas":
            table = self._reader.read_book_deltas(venue=venue, start=start, end=end)
        else:
            raise ValueError(f"Unsupported event_type='{event_type}'")

        partition_info: dict[str, str] = {"venue": venue, "date": date, **extra_partitions}
        return suite.validate(table, partition_info=partition_info)

    def validate_all_recent(self, since: datetime) -> list[quality_base.SuiteReport]:
        """Validate all registered event_types for all venues since ``since``.

        Iterates each registered suite, reads data for the date window,
        and runs validation.
        """
        reports: list[quality_base.SuiteReport] = []

        for event_type, suite in self._suites.items():
            try:
                table = self._read_since(event_type=event_type, since=since, venue=None)
            except ValueError:
                continue
            if table.num_rows == 0:
                continue
            report = suite.validate(
                table,
                partition_info={"since": since.isoformat(), "event_type": event_type},
            )
            reports.append(report)

        return reports

    def validate_since(
        self,
        *,
        since: datetime,
        venue: str | None = None,
    ) -> list[quality_base.SuiteReport]:
        """Validate all registered suites for data since ``since``.

        Args:
            since: Lower bound for ``ts_event``.
            venue: Optional venue filter. When omitted, validates all venues.
        """
        reports: list[quality_base.SuiteReport] = []
        for event_type, suite in self._suites.items():
            try:
                table = self._read_since(event_type=event_type, since=since, venue=venue)
            except ValueError:
                continue
            if table.num_rows == 0:
                continue
            partition_info: dict[str, str] = {
                "since": since.isoformat(),
                "event_type": event_type,
            }
            if venue is not None:
                partition_info["venue"] = venue
            reports.append(suite.validate(table, partition_info=partition_info))
        return reports

    def _read_since(
        self,
        *,
        event_type: str,
        since: datetime,
        venue: str | None,
    ) -> pa.Table:
        if event_type == "trades":
            return self._reader.read_trades(start=since, venue=venue)
        if event_type == "books":
            return self._reader.read_books(start=since, venue=venue)
        if event_type == "ohlcv":
            return self._reader.read_ohlcv(start=since, venue=venue)
        if event_type == "book_deltas":
            return self._reader.read_book_deltas(start=since, venue=venue)
        raise ValueError(f"Unsupported event_type='{event_type}'")
