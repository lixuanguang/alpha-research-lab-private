"""Quality expectations for silver books partitions."""

from __future__ import annotations

import itertools
import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]

import alpha_core.quality.base as quality_base


class CrossedBookExpectation(quality_base.QualityExpectation):
    """Best bid must be strictly less than best ask; no crossed books."""

    name = "crossed_book"

    def __init__(self, *, severity: str = "fail") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        missing = {"bids_json", "asks_json"} - set(table.schema.names)
        if table.num_rows == 0 or missing:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "empty table or missing columns"},
            )
        crossed = 0
        for row in range(table.num_rows):
            bids = json.loads(table.column("bids_json")[row].as_py() or "[]")
            asks = json.loads(table.column("asks_json")[row].as_py() or "[]")
            if not bids or not asks:
                continue
            best_bid = max(float(b["price"]) for b in bids)
            best_ask = min(float(a["price"]) for a in asks)
            if best_bid >= best_ask:
                crossed += 1
        passed = crossed == 0
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={"crossed_rows": crossed},
        )


class EmptyBookExpectation(quality_base.QualityExpectation):
    """Warn if both bids and asks are empty in any snapshot."""

    name = "empty_book"

    def __init__(self, *, severity: str = "warn") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        missing = {"bids_json", "asks_json"} - set(table.schema.names)
        if table.num_rows == 0 or missing:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "empty table or missing columns"},
            )
        empty_count = 0
        for row in range(table.num_rows):
            bids = json.loads(table.column("bids_json")[row].as_py() or "[]")
            asks = json.loads(table.column("asks_json")[row].as_py() or "[]")
            if not bids and not asks:
                empty_count += 1
        passed = empty_count == 0
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={"empty_book_rows": empty_count},
        )


class PriceLevelOrderExpectation(quality_base.QualityExpectation):
    """Bids must be descending; asks must be ascending by price."""

    name = "price_level_order"

    def __init__(self, *, severity: str = "fail") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        missing = {"bids_json", "asks_json"} - set(table.schema.names)
        if table.num_rows == 0 or missing:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "empty table or missing columns"},
            )
        violations = 0
        for row in range(table.num_rows):
            raw_bids = table.column("bids_json")[row].as_py() or "[]"
            raw_asks = table.column("asks_json")[row].as_py() or "[]"
            bids = [float(b["price"]) for b in json.loads(raw_bids)]
            asks = [float(a["price"]) for a in json.loads(raw_asks)]
            if any(bids[i] < bids[i + 1] for i in range(len(bids) - 1)):
                violations += 1
            if any(asks[i] > asks[i + 1] for i in range(len(asks) - 1)):
                violations += 1
        passed = violations == 0
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={"ordering_violations": violations},
        )


BOOK_SUITE = quality_base.QualitySuite(
    "silver_books",
    [
        CrossedBookExpectation(severity="fail"),
        EmptyBookExpectation(severity="warn"),
        PriceLevelOrderExpectation(severity="fail"),
    ],
)


# ---------------------------------------------------------------------------
# Microstructure expectations (D5 extension — 11.2)
# ---------------------------------------------------------------------------

_MISSING_NOTE = "empty table or missing required columns — skipped"


def _all_null(column: pa.ChunkedArray) -> bool:
    """Return True when every value in a column is null."""
    return pc.all(pc.is_null(column)).as_py()  # type: ignore[no-any-return]


def _group_by_instrument(
    table: pa.Table,
) -> dict[str, list[tuple[float, int]]]:
    """Return {instrument_id: [(ts_event_float, row_index), ...]} sorted by ts_event."""
    groups: dict[str, list[tuple[float, int]]] = defaultdict(list)
    inst_col = table.column("instrument_id")
    ts_col = table.column("ts_event")
    for i in range(table.num_rows):
        iid = inst_col[i].as_py()
        ts = ts_col[i].as_py()
        ts_float = ts.timestamp() if isinstance(ts, datetime) else float(ts) / 1e6
        groups[iid].append((ts_float, i))
    for key in groups:
        groups[key].sort(key=lambda t: t[0])
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
    """Sequence ids must be gap-free within each instrument stream.

    When a venue provides numeric ``sequence_id`` values, consecutive ids for
    the same instrument (sorted by ``ts_event``) must differ by exactly 1.
    Larger jumps indicate dropped messages.  If ``sequence_id`` is entirely
    null the expectation passes — the venue does not expose sequence numbers.
    """

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
                details={"note": "sequence_id entirely null — venue has no sequence numbers"},
            )

        groups = _group_by_instrument(table)
        seq_col = table.column("sequence_id")
        gap_count = 0
        for rows in groups.values():
            prev_seq: int | None = None
            for _, row_idx in rows:
                raw = seq_col[row_idx].as_py()
                if raw is None:
                    prev_seq = None
                    continue
                try:
                    seq = int(raw)
                except (ValueError, TypeError):
                    prev_seq = None
                    continue
                if prev_seq is not None and seq - prev_seq > 1:
                    gap_count += 1
                prev_seq = seq

        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=gap_count == 0,
            severity=self.severity,
            details={"sequence_gaps": gap_count},
        )


class SnapshotCadenceExpectation(quality_base.QualityExpectation):
    """Consecutive snapshots per instrument must not exceed a maximum gap.

    Each instrument stream is sorted by ``ts_event`` and consecutive
    inter-snapshot intervals are checked against ``max_gap_seconds``.
    """

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

        groups = _group_by_instrument(table)
        cadence_violations = 0
        max_observed_gap = 0.0
        for rows in groups.values():
            if len(rows) < 2:
                continue
            for (t1, _), (t2, _) in itertools.pairwise(rows):
                gap = t2 - t1
                if gap > self.max_gap_seconds:
                    cadence_violations += 1
                if gap > max_observed_gap:
                    max_observed_gap = gap

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
    """Top-of-book must not move by more than a fractional threshold between snapshots.

    For each instrument stream (sorted by ``ts_event``), the best bid and
    best ask are compared between consecutive snapshots.  A move exceeding
    ``max_move_frac`` (e.g. ``0.20`` = 20%) of the previous value is flagged
    as a stability violation.
    """

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

        groups = _group_by_instrument(table)
        bids_col = table.column("bids_json")
        asks_col = table.column("asks_json")

        violations = 0
        for rows in groups.values():
            if len(rows) < 2:
                continue
            prev_bb, prev_ba = _best_bid_ask_from_json(
                bids_col[rows[0][1]].as_py() or "[]",
                asks_col[rows[0][1]].as_py() or "[]",
            )
            for _, row_idx in rows[1:]:
                curr_bb, curr_ba = _best_bid_ask_from_json(
                    bids_col[row_idx].as_py() or "[]",
                    asks_col[row_idx].as_py() or "[]",
                )
                for prev_val, curr_val in ((prev_bb, curr_bb), (prev_ba, curr_ba)):
                    if prev_val and curr_val and prev_val > 0:
                        if abs(curr_val - prev_val) / prev_val > self.max_move_frac:
                            violations += 1
                prev_bb, prev_ba = curr_bb, curr_ba

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
    """Running book depth derived from reconstructed deltas must stay non-negative.

    For each ``(instrument_id, price, side)`` group in the book_deltas table,
    the cumulative sum of ``delta_size`` (sorted by ``ts_event``) must never
    drop below ``-epsilon``.  Negative depth indicates a reconstruction error
    (more cancellations than additions at a price level).

    Only rows where ``is_reconstructed=True`` are evaluated; native-feed rows
    are excluded because they may legitimately carry negative delta_sizes.
    """

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

        # Filter to reconstructed deltas only.
        mask = pc.equal(table.column("is_reconstructed"), True)
        recon_table = table.filter(mask)
        if recon_table.num_rows == 0:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "no reconstructed deltas — skipped"},
            )

        ts_col = recon_table.column("ts_event")
        inst_col = recon_table.column("instrument_id")
        price_col = recon_table.column("price")
        side_col = recon_table.column("side")
        size_col = recon_table.column("delta_size")

        # Build per-(instrument, price, side) sorted event list.
        groups: dict[tuple[str, str, str], list[tuple[float, Decimal]]] = defaultdict(list)
        for i in range(recon_table.num_rows):
            ts_raw = ts_col[i].as_py()
            ts_f = ts_raw.timestamp() if isinstance(ts_raw, datetime) else float(ts_raw) / 1e6
            key = (inst_col[i].as_py(), str(price_col[i].as_py()), side_col[i].as_py())
            try:
                size = Decimal(str(size_col[i].as_py()))
            except InvalidOperation:
                continue
            groups[key].append((ts_f, size))

        violations = 0
        for events in groups.values():
            events.sort(key=lambda t: t[0])
            running = Decimal("0")
            for _, size in events:
                running += size
                if running < Decimal(str(-self.epsilon)):
                    violations += 1
                    break  # one violation per group is enough

        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=violations == 0,
            severity=self.severity,
            details={"conservation_violations": violations, "epsilon": self.epsilon},
        )


class StaleBookAgeExpectation(quality_base.QualityExpectation):
    """Latest snapshot must not be older than ``max_age_seconds``.

    Unlike :class:`~alpha_core.quality.suites.trade_quality.StaleDataExpectation`
    which uses an hour-scale threshold, this expectation targets microstructure
    usability where a book older than tens of seconds is considered stale.
    """

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

        latest_raw = pc.max(table.column("ts_event")).as_py()
        if latest_raw is None:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "all ts_event values are null"},
            )

        now_utc = datetime.now(UTC)
        latest_dt = (
            latest_raw
            if isinstance(latest_raw, datetime)
            else datetime.fromtimestamp(float(latest_raw) / 1e6, tz=UTC)
        )
        age_seconds = (now_utc - latest_dt).total_seconds()
        passed = age_seconds <= self.max_age_seconds

        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={
                "latest_ts_event": latest_dt.isoformat(),
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
        CrossedBookExpectation(severity="fail"),
        EmptyBookExpectation(severity="warn"),
        PriceLevelOrderExpectation(severity="fail"),
        *_snapshot_microstructure_expectations(),
    ],
)

# Backward-compatible alias retained for tests and callers that still reference
# the original name for the snapshot-focused microstructure suite.
MICROSTRUCTURE_BOOK_SUITE = BOOK_MICROSTRUCTURE_SUITE
