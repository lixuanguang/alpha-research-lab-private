"""Own bounded workload supervision independently of application composition."""

# standard library imports
import asyncio
import hashlib
import multiprocessing
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# project library imports
from serialization import DomainCodec
from telemetry import (
    HealthAlert,
    HealthMetric,
    HealthMetrics,
    HealthPolicy,
    HealthRecorder,
    HealthSignals,
)


class ProcessSupervisor:
    """Supervise an explicitly supplied workload and retain bounded failure evidence."""

    @staticmethod
    async def heartbeat(health: HealthMetrics) -> None:
        """Advance process liveness independently of data and disk progress.

        Args:
            health: Shared observation owned by this child and its parent watchdog.
        """
        while True:
            health.set(HealthMetric.HEARTBEAT, time.monotonic_ns())
            await asyncio.sleep(0.1)

    @staticmethod
    def run(
        root: Path,
        policy: HealthPolicy,
        workload: Callable[[Path, HealthMetrics], None],
        *,
        duration_seconds: int,
        label: str,
        implementation_identity: str,
        protect: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        """Watch one child, terminate it before bounded alert delivery and retain its result.

        Args:
            root: Provisioned directory for policy and supervision evidence.
            policy: Validated liveness, progress and alert limits.
            workload: Spawn-picklable application workload receiving output and shared health.
            duration_seconds: Explicit finite workload duration.
            label: Safe non-secret workload identity for local alert delivery.
            implementation_identity: Retained installed runtime fingerprint.
            protect: Optional parent-owned durable stop after the child has been fenced.

        Returns:
            Stop reason, last health observation and bounded alert outcome.
        """
        policy.__post_init__()
        codec, health = DomainCodec(), HealthMetrics()
        (root / "health-policy.json").write_bytes(codec.encode_json(policy))
        process = multiprocessing.get_context("spawn").Process(target=workload, args=(root, health))
        reason, values = "", health.snapshot()
        initial_values = values
        telemetry: HealthRecorder | None = None
        projection_failures = 0
        projection_error: str | None = None
        next_monitor_at = time.monotonic() + 1
        deadline = (
            time.monotonic() + policy.startup_seconds + duration_seconds + policy.progress_seconds
        )
        process.start()
        try:
            telemetry = HealthRecorder(root / "monitor.sqlite3")
            telemetry.start()
        except Exception as error:
            # A monitoring resource error cannot prevent supervision of a started child.
            telemetry = None
            projection_failures += 1
            projection_error = type(error).__name__
        try:
            while True:
                process.join(0.1)
                try:
                    values = health.snapshot()
                    reason = policy.reason(values, now_ns=time.monotonic_ns())
                except TimeoutError:
                    reason = "health_observation_stalled"
                if not reason and time.monotonic() > deadline:
                    reason = "completion_stalled"
                if (
                    telemetry is not None
                    and not reason
                    and process.is_alive()
                    and time.monotonic() >= next_monitor_at
                ):
                    try:
                        telemetry.offer(
                            HealthSignals.project(
                                scope=f"capture:{root.name}",
                                release=implementation_identity,
                                sample=uuid4().hex,
                                observed_at=datetime.now(UTC),
                                observed_monotonic_ns=time.monotonic_ns(),
                                initial=initial_values,
                                final=values,
                                stop_reason="running",
                                alert_delivered=False,
                            )
                        )
                    except Exception as error:
                        projection_failures += 1
                        projection_error = type(error).__name__
                    next_monitor_at = time.monotonic() + 1
                if reason or not process.is_alive():
                    reason = reason or ("collector_lost" if process.exitcode != 0 else "completed")
                    break
        finally:
            if process.is_alive():
                process.terminate()
                process.join(1)
            if process.is_alive():
                process.kill()
                process.join(1)
        protection_error: str | None = None
        if reason != "completed" and protect is not None:
            try:
                protect(reason)
            except Exception as error:
                # This is the process boundary: the child is already stopped.
                # Retain failure and still attempt the independent alert channel.
                protection_error = type(error).__name__
        result: dict[str, object] = {
            "stop_reason": reason,
            "implementation_identity": implementation_identity,
            "policy_identity": hashlib.sha256(codec.encode_json(policy)).hexdigest(),
            "supervision_directory": str(root.absolute()),
            "collector_stopped": not process.is_alive(),
            "exitcode": process.exitcode,
            "protection_applied": reason != "completed"
            and protect is not None
            and protection_error is None,
            "protection_error": protection_error,
            "health": {metric.name.lower(): values[metric] for metric in HealthMetric},
            "alert_delivered": reason != "completed"
            and HealthAlert.deliver(
                policy.alert_socket,
                f"{root.name} {label} {reason}"
                + (" protection_failed" if protection_error else ""),
            ),
        }
        if telemetry is not None:
            try:
                observed_at = datetime.now(UTC)
                events = HealthSignals.project(
                    scope=f"capture:{root.name}",
                    release=implementation_identity,
                    sample=uuid4().hex,
                    observed_at=observed_at,
                    observed_monotonic_ns=time.monotonic_ns(),
                    initial=initial_values,
                    final=values,
                    stop_reason=reason,
                    alert_delivered=result["alert_delivered"] is True,
                )
                telemetry.offer(events)
            except Exception as error:
                # The child has been fenced and the optional hard stop already ran.
                # Monitoring storage cannot change that protective outcome.
                projection_failures += 1
                projection_error = type(error).__name__
            telemetry_state = telemetry.close()
            result["telemetry_events"] = telemetry_state.inserted
            result["telemetry_dropped"] = telemetry_state.dropped
            result["telemetry_pending"] = telemetry_state.pending
            result["telemetry_worker_alive"] = telemetry_state.worker_alive
            result["telemetry_failures"] = telemetry_state.failures + projection_failures
            telemetry_error = telemetry_state.error or projection_error
        else:
            result["telemetry_events"] = 0
            result["telemetry_dropped"] = 0
            result["telemetry_pending"] = 0
            result["telemetry_worker_alive"] = False
            result["telemetry_failures"] = projection_failures
            telemetry_error = projection_error
        if telemetry_error is not None:
            result["telemetry_error"] = telemetry_error
        (root / "health-summary.json").write_bytes(codec.encode_json(result))
        return result
