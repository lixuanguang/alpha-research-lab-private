"""Define reproducible temporal partitions and consumer-enforced fitting boundaries."""

from __future__ import annotations

# standard library imports
import bisect
import hashlib
import itertools
from datetime import UTC, datetime, timedelta
from typing import Literal

# project library imports
from serialization import DomainCodec, WireRecord


class TimeWindow(WireRecord, frozen=True, kw_only=True):
    """Assign decisions to a half-open UTC interval [start, end)."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        """Refuse empty, reversed or non-UTC intervals."""
        self._require_utc(self.start, field_name="start")
        self._require_utc(self.end, field_name="end")
        if self.start >= self.end:
            raise ValueError("time window must be nonempty")

    def contains(self, instant: datetime) -> bool:
        """Test membership with an exclusive end.

        Args:
            instant: UTC decision time.

        Returns:
            Whether the instant belongs to this partition.
        """
        self._require_utc(instant, field_name="instant")
        return self.start <= instant < self.end


class SampleInterval(WireRecord, frozen=True, kw_only=True):
    """Bind one sample's input/label bytes to its full closed information interval.

    The interval includes feature lookback, outcome horizon and any shared
    publication/execution information. Availability is separate from event time.
    An absent label clock means unknown or inapplicable, never immediately known.
    """

    row_id: str
    input_sha256: str
    decision_at: datetime
    information_start: datetime
    information_end: datetime
    features_available_at: datetime
    label_available_at: datetime | None

    def __post_init__(self) -> None:
        """Validate exact row identity, interval ordering and known availability clocks."""
        if type(self.row_id) is not str or not self.row_id.strip():
            raise ValueError("sample requires a row identity")
        if (
            type(self.input_sha256) is not str
            or len(self.input_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.input_sha256)
        ):
            raise ValueError("sample requires an input SHA-256")
        for name, value in (
            ("decision_at", self.decision_at),
            ("information_start", self.information_start),
            ("information_end", self.information_end),
            ("features_available_at", self.features_available_at),
        ):
            self._require_utc(value, field_name=name)
        if not self.information_start <= self.decision_at <= self.information_end:
            raise ValueError("information interval must contain the decision")
        if self.label_available_at is not None:
            self._require_utc(self.label_available_at, field_name="label_available_at")
            if self.label_available_at < self.information_end:
                raise ValueError("label cannot be available before its information ends")

    def _identity_key(self) -> str:
        """Order immutable sample records by their declared identity."""
        return self.row_id

    def _temporal_key(self) -> tuple[datetime, str]:
        """Resolve equal decision times with a stable sample identity."""
        return self.decision_at, self.row_id


class _ProtectedIntervals:
    """Index closed evaluation information intervals for purge and embargo queries.

    Bounds are exact integer UTC microseconds, sorted by start, with the latest end
    of every prefix. The intervals starting at or before a query's end form one
    prefix, so a single binary search decides whether any of them reaches the
    query's start. Each query costs O(log n) instead of a scan of every interval.
    """

    _EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
    _MICROSECOND = timedelta(microseconds=1)

    def __init__(self, intervals: list[tuple[datetime, datetime]]) -> None:
        """Order closed [start, end] UTC intervals by start and keep each prefix's latest end."""
        ordered = sorted(
            (self._microseconds(start), self._microseconds(end)) for start, end in intervals
        )
        self._starts = [start for start, _ in ordered]
        self._latest_ends = list(itertools.accumulate((end for _, end in ordered), max))

    def meets(self, start: datetime, end: datetime, *, margin_us: int) -> bool:
        """Test whether any interval lies within a margin of the closed interval [start, end].

        Args:
            start: UTC start of the queried closed interval.
            end: UTC end of the queried closed interval.
            margin_us: Nonnegative gap in microseconds; zero tests intersection.

        Returns:
            Whether some interval starts at most ``margin_us`` after ``end`` and ends
            at most ``margin_us`` before ``start``.
        """
        count = bisect.bisect_right(self._starts, self._microseconds(end) + margin_us)
        return count > 0 and self._latest_ends[count - 1] >= self._microseconds(start) - margin_us

    @classmethod
    def _microseconds(cls, instant: datetime) -> int:
        """Convert a UTC instant to exact integer microseconds since the Unix epoch."""
        return (instant - cls._EPOCH) // cls._MICROSECOND


class TemporalSplit(WireRecord, frozen=True, kw_only=True):
    """Retain one fixed earlier-only fold with explicit purge/embargo and fit policy.

    Callers can compose rolling/nested folds from these records. Closed sample
    intervals must not intersect evaluation intervals or their symmetric embargo
    expansion. The embargo is an explicit conservative gap in microseconds; zero
    is permitted with an authored rationale. This is not random cross-validation.
    """

    schema_version: Literal["temporal-split"] = "temporal-split"
    training: TimeWindow | None
    validation: TimeWindow
    holdout: TimeWindow
    samples: tuple[SampleInterval, ...]
    fit_mode: Literal["labels", "features", "none"]
    fit_cutoff: datetime | None
    embargo_us: int
    rationale: str

    def __post_init__(self) -> None:
        """Require ordered disjoint partitions and explicit fitting inapplicability."""
        if self.schema_version != "temporal-split":
            raise ValueError("unsupported temporal split schema")
        for window in (self.validation, self.holdout):
            if type(window) is not TimeWindow:
                raise TypeError("evaluation partitions require TimeWindow")
            window.__post_init__()
        if self.validation.end > self.holdout.start:
            raise ValueError("validation must precede the untouched holdout")
        if type(self.embargo_us) is not int or not 0 <= self.embargo_us <= 31_536_000_000_000:
            raise ValueError("embargo must be integer microseconds within one year")
        if type(self.rationale) is not str or not self.rationale.strip():
            raise ValueError("split requires a fit and embargo rationale")
        if type(self.samples) is not tuple:
            raise TypeError("samples must be an immutable tuple")
        for row in self.samples:
            if type(row) is not SampleInterval:
                raise TypeError("split requires SampleInterval records")
            row.__post_init__()
        if len({row.row_id for row in self.samples}) != len(self.samples):
            raise ValueError("split row identities must be unique")
        if self.fit_mode == "none":
            if self.training is not None or self.fit_cutoff is not None:
                raise ValueError("inapplicable fitting must not invent training rows or a cutoff")
        elif self.fit_mode in ("labels", "features"):
            if type(self.training) is not TimeWindow or self.fit_cutoff is None:
                raise ValueError("fitting requires training and a cutoff")
            self.training.__post_init__()
            self._require_utc(self.fit_cutoff, field_name="fit_cutoff")
            if not self.training.end <= self.fit_cutoff <= self.validation.start:
                raise ValueError("fit cutoff must follow training and precede validation")
        else:
            raise ValueError("unsupported fit mode")

    @property
    def identity(self) -> str:
        """Hash semantic clocks, input digests and split choices independent of row order.

        Returns:
            SHA-256 of this versioned split contract.
        """
        self.__post_init__()
        return hashlib.sha256(
            DomainCodec().encode_json(
                (
                    self.schema_version,
                    self.training,
                    self.validation,
                    self.holdout,
                    tuple(sorted(self.samples, key=SampleInterval._identity_key)),
                    self.fit_mode,
                    self.fit_cutoff,
                    self.embargo_us,
                    self.rationale,
                )
            )
        ).hexdigest()

    def fitting_rows(self) -> tuple[SampleInterval, ...]:
        """Return only train rows whose inputs and optional labels were then available.

        Returns:
            Deterministically ordered admitted samples; empty for a rule with no fit.
            Consumers must select values by these identities, not reuse the full input.
        """
        excluded = dict(self.exclusions())
        return tuple(
            row
            for row in sorted(self.samples, key=SampleInterval._temporal_key)
            if row.row_id not in excluded
        )

    def require_fit_rows(self, row_ids: tuple[str, ...]) -> None:
        """Reject consumer attempts to fit with anything outside the admitted training set.

        Args:
            row_ids: Exact unique IDs about to enter preprocessing or fitting.

        Raises:
            ValueError: Fitting is inapplicable, empty, duplicated or contains forbidden rows.
        """
        allowed = {row.row_id for row in self.fitting_rows()}
        if (
            self.fit_mode == "none"
            or not row_ids
            or len(set(row_ids)) != len(row_ids)
            or not set(row_ids) <= allowed
        ):
            raise ValueError("fit rows must be a nonempty unique subset of admitted training")

    def exclusions(self) -> tuple[tuple[str, str], ...]:
        """Explain every sample that cannot enter fitting, including holdout/future rows.

        Returns:
            Sorted row identities and the first applicable refusal reason.
        """
        self.__post_init__()
        evaluation = [
            (self.validation.start, self.validation.end),
            (self.holdout.start, self.holdout.end),
        ]
        evaluation.extend(
            (row.information_start, row.information_end)
            for row in self.samples
            if self.validation.contains(row.decision_at) or self.holdout.contains(row.decision_at)
        )
        protected = _ProtectedIntervals(evaluation)
        excluded: list[tuple[str, str]] = []
        for row in sorted(self.samples, key=SampleInterval._identity_key):
            reason = ""
            if self.training is None or self.fit_cutoff is None:
                reason = "fitting not applicable"
            elif not self.training.contains(row.decision_at):
                reason = "outside training partition"
            elif row.features_available_at > row.decision_at:
                reason = "features unavailable at decision"
            elif row.information_end > self.fit_cutoff:
                reason = "information extends beyond fitting cutoff"
            elif self.fit_mode == "labels" and (
                row.label_available_at is None or row.label_available_at > self.fit_cutoff
            ):
                reason = "label unavailable at fitting cutoff"
            elif protected.meets(row.information_start, row.information_end, margin_us=0):
                reason = "purged overlapping information"
            elif protected.meets(
                row.information_start, row.information_end, margin_us=self.embargo_us
            ):
                reason = "embargoed shared information"
            if reason:
                excluded.append((row.row_id, reason))
        return tuple(excluded)
