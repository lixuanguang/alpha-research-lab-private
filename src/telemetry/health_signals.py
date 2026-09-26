"""Project periodic or final watchdog observations into retained health signals."""

from __future__ import annotations

# standard library imports
import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from pathlib import Path

# project library imports
from financial_units import ExactRatio
from telemetry.events import MonitoringEvent, MonitoringIdentity
from telemetry.health import HealthMetric
from telemetry.store import TelemetryStore


@dataclass(frozen=True, slots=True)
class HealthRecorderState:
    """Expose bounded writer loss and unfinished work after supervisor shutdown."""

    inserted: int
    dropped: int
    failures: int
    pending: int
    worker_alive: bool
    error: str | None


class HealthRecorder:
    """Persist periodic health off the supervisor's protective control thread."""

    def __init__(self, path: Path, *, max_batches: int = 8) -> None:
        """Bind one finite batch queue and one monitoring-only store."""
        if type(max_batches) is not int or not 1 <= max_batches <= 64:
            raise ValueError("health recorder requires a bounded batch capacity")
        self._store = TelemetryStore(path)
        self._queue: queue.Queue[tuple[MonitoringEvent, ...]] = queue.Queue(maxsize=max_batches)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._started = False
        self._queued = 0
        self._inflight = 0
        self._inserted = 0
        self._dropped = 0
        self._failures = 0
        self._error: str | None = None

    def start(self) -> None:
        """Start exactly one daemon writer before the first periodic offer."""
        if self._started:
            raise ValueError("health recorder is already started")
        self._started = True
        self._thread.start()

    def offer(self, events: tuple[MonitoringEvent, ...]) -> bool:
        """Enqueue a complete validated snapshot without waiting for disk I/O."""
        if not self._started or self._stop.is_set():
            raise ValueError("health recorder is not accepting observations")
        if not isinstance(events, tuple) or not 1 <= len(events) <= 64:
            raise ValueError("health recorder requires one bounded event batch")
        with self._lock:
            try:
                self._queue.put_nowait(events)
            except queue.Full:
                self._dropped += len(events)
                return False
            self._queued += len(events)
            return True

    def close(self, *, wait_seconds: float = 0.5) -> HealthRecorderState:
        """Allow a finite drain, then report unfinished bytes without blocking protection."""
        if not 0 <= wait_seconds <= 1:
            raise ValueError("health recorder shutdown wait must be bounded")
        self._stop.set()
        if self._started:
            self._thread.join(wait_seconds)
        with self._lock:
            return HealthRecorderState(
                inserted=self._inserted,
                dropped=self._dropped,
                failures=self._failures,
                pending=self._queued + self._inflight,
                worker_alive=self._thread.is_alive(),
                error=self._error,
            )

    def _drain(self) -> None:
        """Persist one complete sample at a time without holding producer locks."""
        while not self._stop.is_set() or not self._queue.empty():
            try:
                events = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            with self._lock:
                self._queued -= len(events)
                self._inflight += len(events)
            try:
                inserted = self._store.append(events)
            except Exception as error:
                with self._lock:
                    self._failures += 1
                    self._dropped += len(events)
                    self._error = type(error).__name__
            else:
                with self._lock:
                    self._inserted += inserted
            finally:
                with self._lock:
                    self._inflight -= len(events)
                self._queue.task_done()


class HealthSignals:
    """Describe final process and data progress without granting control authority."""

    @staticmethod
    def project(
        *,
        scope: str,
        release: str,
        sample: str,
        observed_at: datetime,
        observed_monotonic_ns: int,
        initial: tuple[int, ...],
        final: tuple[int, ...],
        stop_reason: str,
        alert_delivered: bool,
    ) -> tuple[MonitoringEvent, ...]:
        """Distinguish no progress from an old progress clock at final supervision."""
        MonitoringEvent._require_utc(observed_at, field_name="health observation")
        if len(initial) != len(HealthMetric) or len(final) != len(HealthMetric):
            raise ValueError("health observations require all fixed slots")
        context = MonitoringIdentity(
            scope=scope,
            mode="data",
            release=release,
            incident=stop_reason if stop_reason not in ("running", "completed") else None,
        )
        events: list[MonitoringEvent] = []
        for metric, name in (
            (HealthMetric.HEARTBEAT, "runtime.heartbeat_age_seconds"),
            (HealthMetric.INGESTION, "data.ingestion_age_seconds"),
            (HealthMetric.PERSISTENCE, "data.persistence_age_seconds"),
            (HealthMetric.MARKET, "data.market_age_seconds"),
        ):
            last = final[metric]
            progressed = last > 0 if metric == HealthMetric.HEARTBEAT else last != initial[metric]
            if not progressed:
                events.append(
                    HealthSignals._event(
                        context,
                        name,
                        sample,
                        observed_at,
                        "seconds",
                        None,
                        missing_reason=f"no_{metric.name.lower()}_progress",
                    )
                )
            elif last > observed_monotonic_ns:
                events.append(
                    HealthSignals._event(
                        context,
                        name,
                        sample,
                        observed_at,
                        "seconds",
                        None,
                        missing_reason="clock_regressed",
                    )
                )
            else:
                events.append(
                    HealthSignals._event(
                        context,
                        name,
                        sample,
                        observed_at,
                        "seconds",
                        Fraction(observed_monotonic_ns - last, 1_000_000_000),
                    )
                )
        for metric, name in (
            (HealthMetric.QUEUE, "data.queue_peak"),
            (HealthMetric.QUEUE_BYTES, "data.queue_bytes"),
            (HealthMetric.RECONNECTS, "data.reconnects"),
            (HealthMetric.INVALID, "data.invalid"),
            (HealthMetric.DUPLICATES, "data.duplicates"),
            (HealthMetric.GAPS, "data.gaps"),
            (HealthMetric.RECEIVED_FRAMES, "data.received_frames"),
            (HealthMetric.DURABLE_FRAMES, "data.durable_frames"),
            (HealthMetric.PERSISTED_RECORDS, "data.persisted_records"),
            (HealthMetric.PERSISTENCE_FAILED, "data.persistence_failed"),
        ):
            events.append(
                HealthSignals._event(
                    context,
                    name,
                    sample,
                    observed_at,
                    "bytes" if metric == HealthMetric.QUEUE_BYTES else "count",
                    final[metric],
                )
            )
        events.extend(
            (
                HealthSignals._event(
                    context,
                    "runtime.stopped",
                    sample,
                    observed_at,
                    "boolean",
                    int(stop_reason != "running"),
                ),
                HealthSignals._event(
                    context,
                    "runtime.faulted",
                    sample,
                    observed_at,
                    "boolean",
                    int(stop_reason not in ("running", "completed")),
                ),
                HealthSignals._event(
                    context,
                    "runtime.alert_delivery_failure",
                    sample,
                    observed_at,
                    "boolean",
                    int(stop_reason not in ("running", "completed") and not alert_delivered),
                ),
            )
        )
        if final[HealthMetric.DURABLE_FRAMES] == 0:
            events.append(
                HealthSignals._event(
                    context,
                    "data.receipt_to_durable_seconds",
                    sample,
                    observed_at,
                    "seconds",
                    None,
                    missing_reason="no_durable_frame",
                )
            )
        else:
            events.append(
                HealthSignals._event(
                    context,
                    "data.receipt_to_durable_seconds",
                    sample,
                    observed_at,
                    "seconds",
                    Fraction(final[HealthMetric.RECEIPT_DURABLE_LAG_NS], 1_000_000_000),
                )
            )
        oldest = final[HealthMetric.QUEUE_OLDEST_NS]
        if oldest > observed_monotonic_ns:
            events.append(
                HealthSignals._event(
                    context,
                    "data.queue_age_seconds",
                    sample,
                    observed_at,
                    "seconds",
                    None,
                    missing_reason="clock_regressed",
                )
            )
        else:
            events.append(
                HealthSignals._event(
                    context,
                    "data.queue_age_seconds",
                    sample,
                    observed_at,
                    "seconds",
                    Fraction(0)
                    if oldest == 0
                    else Fraction(observed_monotonic_ns - oldest, 1_000_000_000),
                )
            )
        events.append(
            HealthSignals._event(
                context,
                "data.source_clock_drift_seconds",
                sample,
                observed_at,
                "seconds",
                None,
                missing_reason="not_measured",
            )
        )
        return tuple(events)

    @staticmethod
    def _event(
        context: MonitoringIdentity,
        name: str,
        sample: str,
        at: datetime,
        units: str,
        value: int | Fraction | None,
        *,
        missing_reason: str | None = None,
    ) -> MonitoringEvent:
        """Keep a final health fact exact and separate from the hard watchdog policy."""
        return MonitoringEvent(
            context=context,
            name=name,
            version="1",
            sample=sample,
            at=at,
            available_at=at,
            recorded_at=at,
            units=units,
            value=None if value is None else ExactRatio.from_fraction(Fraction(value)),
            missing_reason=missing_reason,
        )
