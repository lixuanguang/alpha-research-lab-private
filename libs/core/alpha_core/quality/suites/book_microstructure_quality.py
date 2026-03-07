"""Microstructure quality expectations for silver books partitions."""

from __future__ import annotations

import itertools
import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import pyarrow as pa
import pyarrow.compute as pc

import alpha_core.quality.base as quality_base
import alpha_core.quality.suites.book_quality as book_quality_base

_MISSING_NOTE = "empty table or missing required columns - skipped"


def _all_null(column: pa.ChunkedArray) -> bool:
    """Return True when every value in a column is null."""
    return pc.all(pc.is_null(column)).as_py()  # type: ignore[no-any-return]


def _group_by_instrument(table: pa.Table) -> dict[str, list[tuple[float, int]]]:
    """Return {instrument_id: [(ts_event_float, row_index), ...]} sorted by ts_event."""
    groups: dict[str, list[tuple[float, int]]] = defaultdict(list)
    instrument_column = table.column("instrument_id")
    timestamp_column = table.column("ts_event")
    for row_index in range(table.num_rows):
        instrument_id = instrument_column[row_index].as_py()
        timestamp_value = timestamp_column[row_index].as_py()
        timestamp_float = (
            timestamp_value.timestamp()
            if isinstance(timestamp_value, datetime)
            else float(timestamp_value) / 1e6
        )
        groups[instrument_id].append((timestamp_float, row_index))
    for instrument_rows in groups.values():
        instrument_rows.sort(key=lambda row: row[0])
    return groups


def _best_bid_ask_from_json(
    raw_bids: str,
    raw_asks: str,
) -> tuple[float | None, float | None]:
    bids = json.loads(raw_bids or "[]")
    asks = json.loads(raw_asks or "[]")
    best_bid = max((float(level["price"]) for level in bids), default=None)
    best_ask = min((float(level["price"]) for level in asks), default=None)
    return best_bid, best_ask


class SequenceContinuityExpectation(quality_base.QualityExpectation):
    """Sequence ids must be gap-free within each instrument stream."""

    name = "sequence_continuity"

    def __init__(self, *, severity: str = "warn") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        required = {"sequence_id", "instrument_id", "ts_event"}
        if table.num_rows == 0 or not required.issubset(table.schema.names):
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": _MISSING_NOTE},
            )
        if _all_null(table.column("sequence_id")):
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "sequence_id entirely null - venue has no sequence numbers"},
            )

        groups = _group_by_instrument(table)
        sequence_column = table.column("sequence_id")
        gap_count = 0
        for instrument_rows in groups.values():
            previous_sequence: int | None = None
            for _, row_index in instrument_rows:
                raw_sequence = sequence_column[row_index].as_py()
                if raw_sequence is None:
                    previous_sequence = None
                    continue
                try:
                    sequence_value = int(raw_sequence)
                except (TypeError, ValueError):
                    previous_sequence = None
                    continue
                if previous_sequence is not None and sequence_value - previous_sequence > 1:
                    gap_count += 1
                previous_sequence = sequence_value

        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=gap_count == 0,
            severity=self.severity,
            details={"sequence_gaps": gap_count},
        )


class SnapshotCadenceExpectation(quality_base.QualityExpectation):
    """Consecutive snapshots per instrument must not exceed a maximum gap."""

    name = "snapshot_cadence"

    def __init__(
        self,
        *,
        max_gap_seconds: float = 60.0,
        severity: str = "warn",
    ) -> None:
        if max_gap_seconds <= 0:
            raise ValueError("`max_gap_seconds` must be > 0")
        self.max_gap_seconds = max_gap_seconds
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        required = {"instrument_id", "ts_event"}
        if table.num_rows < 2 or not required.issubset(table.schema.names):
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": _MISSING_NOTE},
            )

        cadence_violations = 0
        max_observed_gap = 0.0
        for instrument_rows in _group_by_instrument(table).values():
            if len(instrument_rows) < 2:
                continue
            for (first_time, _), (second_time, _) in itertools.pairwise(instrument_rows):
                gap_seconds = second_time - first_time
                if gap_seconds > self.max_gap_seconds:
                    cadence_violations += 1
                max_observed_gap = max(max_observed_gap, gap_seconds)

        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=cadence_violations == 0,
            severity=self.severity,
            details={
                "cadence_violations": cadence_violations,
                "max_gap_seconds_observed": round(max_observed_gap, 3),
                "threshold_seconds": self.max_gap_seconds,
            },
        )


class TopOfBookStabilityExpectation(quality_base.QualityExpectation):
    """Top-of-book must not move by more than a fractional threshold between snapshots."""

    name = "top_of_book_stability"

    def __init__(
        self,
        *,
        max_move_frac: float = 0.20,
        severity: str = "warn",
    ) -> None:
        if not 0 < max_move_frac < 1:
            raise ValueError("`max_move_frac` must be in (0, 1)")
        self.max_move_frac = max_move_frac
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        required = {"bids_json", "asks_json", "instrument_id", "ts_event"}
        if table.num_rows < 2 or not required.issubset(table.schema.names):
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": _MISSING_NOTE},
            )

        bids_column = table.column("bids_json")
        asks_column = table.column("asks_json")
        violations = 0
        for instrument_rows in _group_by_instrument(table).values():
            if len(instrument_rows) < 2:
                continue
            previous_bid, previous_ask = _best_bid_ask_from_json(
                bids_column[instrument_rows[0][1]].as_py() or "[]",
                asks_column[instrument_rows[0][1]].as_py() or "[]",
            )
            for _, row_index in instrument_rows[1:]:
                current_bid, current_ask = _best_bid_ask_from_json(
                    bids_column[row_index].as_py() or "[]",
                    asks_column[row_index].as_py() or "[]",
                )
                for previous_value, current_value in (
                    (previous_bid, current_bid),
                    (previous_ask, current_ask),
                ):
                    if (
                        previous_value
                        and current_value
                        and previous_value > 0
                        and abs(current_value - previous_value) / previous_value
                        > self.max_move_frac
                    ):
                        violations += 1
                previous_bid, previous_ask = current_bid, current_ask

        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=violations == 0,
            severity=self.severity,
            details={
                "stability_violations": violations,
                "max_move_frac_threshold": self.max_move_frac,
            },
        )


class DeltaConservationExpectation(quality_base.QualityExpectation):
    """Running book depth derived from reconstructed deltas must stay non-negative."""

    name = "delta_conservation"

    def __init__(
        self,
        *,
        epsilon: float = 1e-8,
        severity: str = "warn",
    ) -> None:
        self.epsilon = epsilon
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        required = {"delta_size", "is_reconstructed", "price", "side", "instrument_id", "ts_event"}
        if table.num_rows == 0 or not required.issubset(table.schema.names):
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": _MISSING_NOTE},
            )

        reconstructed_mask = pc.equal(table.column("is_reconstructed"), True)
        reconstructed_table = table.filter(reconstructed_mask)
        if reconstructed_table.num_rows == 0:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "no reconstructed deltas - skipped"},
            )

        timestamp_column = reconstructed_table.column("ts_event")
        instrument_column = reconstructed_table.column("instrument_id")
        price_column = reconstructed_table.column("price")
        side_column = reconstructed_table.column("side")
        size_column = reconstructed_table.column("delta_size")

        groups: dict[tuple[str, str, str], list[tuple[float, Decimal]]] = defaultdict(list)
        for row_index in range(reconstructed_table.num_rows):
            timestamp_value = timestamp_column[row_index].as_py()
            timestamp_float = (
                timestamp_value.timestamp()
                if isinstance(timestamp_value, datetime)
                else float(timestamp_value) / 1e6
            )
            group_key = (
                instrument_column[row_index].as_py(),
                str(price_column[row_index].as_py()),
                side_column[row_index].as_py(),
            )
            try:
                size_value = Decimal(str(size_column[row_index].as_py()))
            except InvalidOperation:
                continue
            groups[group_key].append((timestamp_float, size_value))

        violations = 0
        epsilon_limit = Decimal(str(-self.epsilon))
        for group_events in groups.values():
            group_events.sort(key=lambda event: event[0])
            running_depth = Decimal("0")
            for _, delta_size in group_events:
                running_depth += delta_size
                if running_depth < epsilon_limit:
                    violations += 1
                    break

        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=violations == 0,
            severity=self.severity,
            details={"conservation_violations": violations, "epsilon": self.epsilon},
        )


class StaleBookAgeExpectation(quality_base.QualityExpectation):
    """Latest snapshot must not be older than max_age_seconds."""

    name = "stale_book_age"

    def __init__(
        self,
        *,
        max_age_seconds: float = 30.0,
        severity: str = "warn",
    ) -> None:
        if max_age_seconds <= 0:
            raise ValueError("`max_age_seconds` must be > 0")
        self.max_age_seconds = max_age_seconds
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        if table.num_rows == 0 or "ts_event" not in table.schema.names:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": _MISSING_NOTE},
            )

        latest_value = pc.max(table.column("ts_event")).as_py()
        if latest_value is None:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "all ts_event values are null"},
            )

        latest_timestamp = (
            latest_value
            if isinstance(latest_value, datetime)
            else datetime.fromtimestamp(float(latest_value) / 1e6, tz=UTC)
        )
        age_seconds = (datetime.now(UTC) - latest_timestamp).total_seconds()

        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=age_seconds <= self.max_age_seconds,
            severity=self.severity,
            details={
                "latest_ts_event": latest_timestamp.isoformat(),
                "age_seconds": round(age_seconds, 3),
                "max_age_seconds": self.max_age_seconds,
            },
        )


def _snapshot_microstructure_expectations() -> list[quality_base.QualityExpectation]:
    return [
        SequenceContinuityExpectation(severity="warn"),
        SnapshotCadenceExpectation(max_gap_seconds=60.0, severity="warn"),
        TopOfBookStabilityExpectation(max_move_frac=0.20, severity="warn"),
        StaleBookAgeExpectation(max_age_seconds=30.0, severity="warn"),
    ]


BOOK_MICROSTRUCTURE_SUITE = quality_base.QualitySuite(
    "silver_books_microstructure",
    _snapshot_microstructure_expectations(),
)

BOOK_DELTA_MICROSTRUCTURE_SUITE = quality_base.QualitySuite(
    "silver_book_deltas_microstructure",
    [DeltaConservationExpectation(severity="warn")],
)

BOOK_WITH_MICROSTRUCTURE_SUITE = quality_base.QualitySuite(
    "silver_books_with_microstructure",
    [
        book_quality_base.CrossedBookExpectation(severity="fail"),
        book_quality_base.EmptyBookExpectation(severity="warn"),
        book_quality_base.PriceLevelOrderExpectation(severity="fail"),
        *_snapshot_microstructure_expectations(),
    ],
)
