"""PartitionValidator — run quality suites on silver partitions after write."""

from __future__ import annotations

from datetime import UTC, datetime

import alpha_core.quality.base as quality_base
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
                    Expected keys: "trades", "books", "ohlcv".
        """
        self._reader = reader
        self._suites = suites

    def validate_partition(
        self,
        event_type: str,
        venue: str,
        date: str,
        **extra_partitions: str,
    ) -> quality_base.SuiteReport:
        """
        Validate a single silver partition.

        Args:
            event_type: One of "trades", "books", "ohlcv".
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
        else:
            raise ValueError(f"Unsupported event_type='{event_type}'")

        partition_info: dict[str, str] = {"venue": venue, "date": date, **extra_partitions}
        return suite.validate(table, partition_info=partition_info)

    def validate_all_recent(self, since: datetime) -> list[quality_base.SuiteReport]:
        """
        Validate all event_types for all venues with data since `since`.

        Iterates each registered suite, reads data for the date window,
        and runs validation.
        """
        reports: list[quality_base.SuiteReport] = []
        start = since

        # No upper-bound end filter — include all partitions written after `since`
        event_type_readers = {
            "trades": lambda: self._reader.read_trades(start=start),
            "books": lambda: self._reader.read_books(start=start),
            "ohlcv": lambda: self._reader.read_ohlcv(start=start),
        }

        for event_type, suite in self._suites.items():
            reader_fn = event_type_readers.get(event_type)
            if reader_fn is None:
                continue
            table = reader_fn()
            if table.num_rows == 0:
                continue
            report = suite.validate(
                table,
                partition_info={"since": since.isoformat(), "event_type": event_type},
            )
            reports.append(report)

        return reports
