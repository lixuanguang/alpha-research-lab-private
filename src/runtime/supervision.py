"""Own bounded workload supervision independently of application composition."""

# standard library imports
import asyncio
import hashlib
import multiprocessing
import time
from collections.abc import Callable
from pathlib import Path

# project library imports
from serialization import DomainCodec
from telemetry import HealthAlert, HealthMetric, HealthMetrics, HealthPolicy


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
    ) -> dict[str, object]:
        """Watch one child, terminate it before bounded alert delivery and retain its result.

        Args:
            root: Provisioned directory for policy and supervision evidence.
            policy: Validated liveness, progress and alert limits.
            workload: Spawn-picklable application workload receiving output and shared health.
            duration_seconds: Explicit finite workload duration.
            label: Safe non-secret workload identity for local alert delivery.
            implementation_identity: Retained installed runtime fingerprint.

        Returns:
            Stop reason, last health observation and bounded alert outcome.
        """
        policy.__post_init__()
        codec, health = DomainCodec(), HealthMetrics()
        (root / "health-policy.json").write_bytes(codec.encode_json(policy))
        process = multiprocessing.get_context("spawn").Process(target=workload, args=(root, health))
        reason, values = "", health.snapshot()
        deadline = (
            time.monotonic() + policy.startup_seconds + duration_seconds + policy.progress_seconds
        )
        process.start()
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
        result: dict[str, object] = {
            "stop_reason": reason,
            "implementation_identity": implementation_identity,
            "policy_identity": hashlib.sha256(codec.encode_json(policy)).hexdigest(),
            "supervision_directory": str(root.absolute()),
            "collector_stopped": not process.is_alive(),
            "exitcode": process.exitcode,
            "health": {metric.name.lower(): values[metric] for metric in HealthMetric},
            "alert_delivered": reason != "completed"
            and HealthAlert.deliver(policy.alert_socket, f"{root.name} {label} {reason}"),
        }
        (root / "health-summary.json").write_bytes(codec.encode_json(result))
        return result
