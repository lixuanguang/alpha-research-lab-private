"""Sample host-wide CPU and the busiest visible processes once a second during a trial.

The trial's own sampler sees only its process tree, so contention from anything else on
the host is invisible to it. This sampler runs in the otherwise idle cohort driver and
is diagnostic only: nothing grades it. Processes the user may not inspect (on macOS,
root-owned daemons) are counted only in the host total, never named.
"""

from __future__ import annotations

# standard library imports
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

# third party library imports
import msgspec
import psutil  # type: ignore[import-untyped]  # [owner=runtime; rationale=locked diagnostic dependency has no bundled typing stubs; expires=2027-02-01]

_TOP_PROCESSES = 12


class _HostTimes(Protocol):
    """Describe cumulative host CPU seconds."""

    idle: float


class _ProcessTimes(Protocol):
    """Describe cumulative process CPU seconds."""

    user: float
    system: float


class HostSampler:
    """Append one host CPU row per second to a JSON-lines file until stopped."""

    def __init__(self, path: Path) -> None:
        """Bind the output file; nothing is sampled until ``start``."""
        self.path = path
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.failures: list[str] = []

    def start(self) -> None:
        """Begin sampling on a background thread."""
        self.thread.start()

    def stop(self) -> None:
        """Stop sampling and wait for the last row."""
        self.stopping.set()
        self.thread.join(5)

    @staticmethod
    def _host() -> tuple[float, float]:
        """Return cumulative busy and total host CPU seconds."""
        times: object = psutil.cpu_times()  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil host counters narrowed at one diagnostic boundary; expires=2027-02-01]
        total = sum(cast(tuple[float, ...], times))
        return total - cast(_HostTimes, times).idle, total

    @staticmethod
    def _processes() -> dict[tuple[int, str], float]:
        """Return cumulative CPU seconds for every process this user may inspect."""
        seconds: dict[tuple[int, str], float] = {}
        for process in psutil.process_iter(["name", "cpu_times"]):  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil process scan narrowed at one diagnostic boundary; expires=2027-02-01]
            info = cast(dict[str, object], process.info)  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil process info narrowed at one diagnostic boundary; expires=2027-02-01]
            times = info.get("cpu_times")
            if times is None:
                continue
            sample = cast(_ProcessTimes, times)
            key = (cast(int, process.pid), str(info.get("name")))  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil process id narrowed at one diagnostic boundary; expires=2027-02-01]
            seconds[key] = sample.user + sample.system
        return seconds

    def _run(self) -> None:
        """Write one row per second: host busy cores and the busiest visible processes."""
        busy, total = self._host()
        processes = self._processes()
        previous_ns = time.monotonic_ns()
        with self.path.open("ab") as stream:
            while not self.stopping.wait(max(0.0, 1 - (time.monotonic_ns() - previous_ns) / 1e9)):
                try:
                    now_ns = time.monotonic_ns()
                    next_busy, next_total = self._host()
                    current = self._processes()
                    elapsed = (now_ns - previous_ns) / 1e9
                    deltas = sorted(
                        (
                            (seconds - processes.get(key, seconds), key)
                            for key, seconds in current.items()
                        ),
                        reverse=True,
                    )
                    row = {
                        "monotonic_ns": now_ns,
                        "at": datetime.now(UTC),
                        "elapsed_seconds": elapsed,
                        "host_busy_cores": (next_busy - busy) / elapsed,
                        "host_cpus": round((next_total - total) / elapsed),
                        "visible_process_cores": sum(delta for delta, _ in deltas) / elapsed,
                        "top": [
                            {"pid": pid, "name": name, "cores": delta / elapsed}
                            for delta, (pid, name) in deltas[:_TOP_PROCESSES]
                        ],
                    }
                    stream.write(msgspec.json.encode(row) + b"\n")
                    stream.flush()
                    busy, total, processes, previous_ns = next_busy, next_total, current, now_ns
                except (OSError, ValueError, TypeError) as error:
                    self.failures.append(f"{type(error).__name__}: {error}")
                    return
