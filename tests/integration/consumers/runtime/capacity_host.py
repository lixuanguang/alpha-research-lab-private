"""Sample host-wide CPU and the busiest visible processes once a second during a trial.

The trial's own sampler sees only its process tree, so contention from anything else on
the host is invisible to it. This sampler runs in the otherwise idle cohort driver.
Baseline rows are diagnostic only. Given a trial root, each row also splits trial cores
(that process and its descendants) from non-trial cores, which the sustained host gate
grades. Processes the user may not inspect (on macOS, root-owned daemons) are counted
only in the host total and so as non-trial load, never named.
"""

from __future__ import annotations

# standard library imports
import os
import subprocess
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
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


class _Memory(Protocol):
    """Describe one process's resident memory."""

    rss: int


class _Disk(Protocol):
    """Describe host-wide cumulative disk writes."""

    write_bytes: int


class HostSampler:
    """Append one host CPU row per second to a JSON-lines file until stopped."""

    def __init__(self, path: Path, *, trial_root: int | None = None) -> None:
        """Bind the output file and optional trial root; nothing is sampled until ``start``."""
        self.path, self.trial_root = path, trial_root
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

    def _trial_pids(self) -> set[int]:
        """Return the trial root and every current descendant, or nothing without a root."""
        if self.trial_root is None:
            return set()
        try:
            root = psutil.Process(self.trial_root)  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil process tree narrowed at one diagnostic boundary; expires=2027-02-01]
            children = cast(list[object], root.children(recursive=True))  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil process tree narrowed at one diagnostic boundary; expires=2027-02-01]
        except psutil.Error:  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil exception narrowed at one diagnostic boundary; expires=2027-02-01]
            return {self.trial_root}
        return {self.trial_root, *(cast(int, child.pid) for child in children)}  # type: ignore[attr-defined]  # [owner=runtime; rationale=untyped psutil child identity narrowed at one diagnostic boundary; expires=2027-02-01]

    @staticmethod
    def _rss(pids: set[int]) -> int:
        """Return the summed resident bytes of the processes that are still alive."""
        total = 0
        for pid in pids:
            try:
                info: object = psutil.Process(pid).memory_info()  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil memory counters narrowed at one diagnostic boundary; expires=2027-02-01]
            except psutil.Error:  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil exception narrowed at one diagnostic boundary; expires=2027-02-01]
                continue
            total += cast(_Memory, info).rss
        return total

    @staticmethod
    def _disk_written() -> int | None:
        """Return host-wide cumulative disk bytes written, when the platform reports it."""
        counters: object = psutil.disk_io_counters()  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil disk counters narrowed at one diagnostic boundary; expires=2027-02-01]
        return None if counters is None else cast(_Disk, counters).write_bytes

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
                    host_cores = (next_busy - busy) / elapsed
                    row: dict[str, object] = {
                        "monotonic_ns": now_ns,
                        "at": datetime.now(UTC),
                        "elapsed_seconds": elapsed,
                        "host_busy_cores": host_cores,
                        "host_cpus": round((next_total - total) / elapsed),
                        "host_disk_written_bytes": self._disk_written(),
                        "visible_process_cores": sum(delta for delta, _ in deltas) / elapsed,
                        "top": [
                            {"pid": pid, "name": name, "cores": delta / elapsed}
                            for delta, (pid, name) in deltas[:_TOP_PROCESSES]
                        ],
                    }
                    if self.trial_root is not None:
                        trial = self._trial_pids()
                        trial_cores = (
                            sum(delta for delta, (pid, _) in deltas if pid in trial) / elapsed
                        )
                        row["trial_cores"] = trial_cores
                        row["trial_rss_bytes"] = self._rss(trial)
                        row["non_trial_cores"] = max(0.0, host_cores - trial_cores)
                        row["top_non_trial"] = [
                            {"pid": pid, "name": name, "cores": delta / elapsed}
                            for delta, (pid, name) in [
                                item for item in deltas if item[1][0] not in trial
                            ][:_TOP_PROCESSES]
                        ]
                    stream.write(msgspec.json.encode(row) + b"\n")
                    stream.flush()
                    busy, total, processes, previous_ns = next_busy, next_total, current, now_ns
                except (OSError, ValueError, TypeError) as error:
                    self.failures.append(f"{type(error).__name__}: {error}")
                    return


class _HostRow(msgspec.Struct, frozen=True):
    """Decode the graded fields of one sampled host row."""

    monotonic_ns: int
    elapsed_seconds: float
    non_trial_cores: float
    top_non_trial: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class HostGate:
    """Fail an attempt whose non-trial load stays above a declared ceiling too long.

    Budgets are never relaxed for host load; the gate instead attributes the run to the
    busiest non-trial processes so a desktop burst is never mistaken for the runtime.
    """

    ceiling_cores: float
    window_seconds: float

    def assess(self, rows: Iterable[bytes]) -> dict[str, object]:
        """Return the longest continuous excess, its attribution and the gate outcome."""
        longest, current = 0.0, 0.0
        worst: list[_HostRow] = []
        run: list[_HostRow] = []
        samples = 0
        for line in rows:
            row = msgspec.json.decode(line, type=_HostRow)
            samples += 1
            if row.non_trial_cores > self.ceiling_cores:
                current += row.elapsed_seconds
                run.append(row)
                if current > longest:
                    longest, worst = current, list(run)
            else:
                current, run = 0.0, []
        attribution: dict[str, float] = {}
        for row in worst:
            for item in row.top_non_trial:
                name = str(item.get("name"))
                cores = item.get("cores")
                if isinstance(cores, (int, float)):
                    attribution[name] = (
                        attribution.get(name, 0.0) + float(cores) * row.elapsed_seconds
                    )
        return {
            "status": "unmeasured"
            if not samples
            else "fail"
            if longest > self.window_seconds
            else "pass",
            "samples": samples,
            "ceiling_cores": self.ceiling_cores,
            "window_seconds": self.window_seconds,
            "longest_excess_seconds": longest,
            "attribution_core_seconds": {
                name: attribution[name]
                for name in sorted(attribution, key=attribution.__getitem__, reverse=True)[
                    :_TOP_PROCESSES
                ]
            },
        }


class _ResourceRow(msgspec.Struct, frozen=True):
    """Decode one row's trial resources."""

    elapsed_seconds: float
    trial_cores: float
    trial_rss_bytes: int
    host_disk_written_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class ResourceGate:
    """Grade a sustained trial's own process tree: peak RSS, mean and p95 CPU demand.

    Disk bytes written are host-wide and reported, not graded.
    """

    maximum_rss_bytes: int
    mean_cores: float
    p95_cores: float

    def assess(self, rows: Iterable[bytes]) -> dict[str, object]:
        """Return the trial's peak RSS, time-weighted mean and p95 cores and the outcome."""
        cores: list[float] = []
        weighted = seconds = 0.0
        peak = 0
        written: list[int] = []
        for line in rows:
            row = msgspec.json.decode(line, type=_ResourceRow)
            cores.append(row.trial_cores)
            weighted += row.trial_cores * row.elapsed_seconds
            seconds += row.elapsed_seconds
            peak = max(peak, row.trial_rss_bytes)
            if row.host_disk_written_bytes is not None:
                written.append(row.host_disk_written_bytes)
        if not cores or not seconds:
            return {"status": "unmeasured", "samples": 0}
        cores.sort()
        mean = weighted / seconds
        p95 = cores[max(0, -(-95 * len(cores) // 100) - 1)]
        passed = (
            peak <= self.maximum_rss_bytes and mean <= self.mean_cores and p95 <= self.p95_cores
        )
        return {
            "status": "pass" if passed else "fail",
            "samples": len(cores),
            "peak_trial_rss_bytes": peak,
            "mean_trial_cores": mean,
            "p95_trial_cores": p95,
            "limits": {
                "maximum_rss_bytes": self.maximum_rss_bytes,
                "mean_cores": self.mean_cores,
                "p95_cores": self.p95_cores,
            },
            "host_disk_written_bytes": written[-1] - written[0] if len(written) > 1 else None,
        }


@dataclass(frozen=True, slots=True)
class QuietHostPrecheck:
    """Refuse a sustained attempt on a host that is not declared quiet.

    Declared interactive processes must be absent; iCloud pausing cannot be verified
    programmatically, so the operator's attestation is retained instead. The idle
    check samples the host with nothing of the trial running.
    """

    denied: frozenset[str]
    idle_seconds: float = 300
    ceiling_cores: float = 1.0

    @staticmethod
    def running(names: frozenset[str]) -> tuple[tuple[int, str], ...]:
        """Return every visible process whose exact name is declared interactive."""
        found: list[tuple[int, str]] = []
        for process in psutil.process_iter(["name"]):  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil process scan narrowed at one diagnostic boundary; expires=2027-02-01]
            name = str(cast(dict[str, object], process.info).get("name"))  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil process info narrowed at one diagnostic boundary; expires=2027-02-01]
            if name in names:
                found.append((cast(int, process.pid), name))  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil process id narrowed at one diagnostic boundary; expires=2027-02-01]
        return tuple(sorted(found))

    @staticmethod
    def hold_awake() -> subprocess.Popen[bytes]:
        """Keep the host awake for as long as the calling cohort process lives."""
        return subprocess.Popen(  # nosec B603  # [owner=runtime; rationale=fixed system power assertion bound to this process; expires=2027-03-01]
            ["/usr/bin/caffeinate", "-dimsu", "-w", str(os.getpid())]
        )

    def assess(
        self, interactive: tuple[tuple[int, str], ...], idle_rows: Iterable[bytes]
    ) -> dict[str, object]:
        """Grade declared interactive processes and the idle sample's mean non-trial load."""
        weighted, seconds = 0.0, 0.0
        for line in idle_rows:
            row = msgspec.json.decode(line, type=_HostRow)
            weighted += row.non_trial_cores * row.elapsed_seconds
            seconds += row.elapsed_seconds
        mean = weighted / seconds if seconds else None
        idle_passed = (
            mean is not None and seconds >= self.idle_seconds * 0.95 and mean <= self.ceiling_cores
        )
        return {
            "status": "pass" if not interactive and idle_passed else "fail",
            "interactive_processes": interactive,
            "idle_seconds": seconds,
            "idle_mean_non_trial_cores": mean,
            "idle_ceiling_cores": self.ceiling_cores,
        }

    def run(
        self, output: Path, *, icloud_paused_attested: bool, icloud_waived: bool = False
    ) -> dict[str, object]:
        """Refuse interactive processes, sample idle load and retain the precheck.

        The iCloud criterion passes only on the operator's attestation, or is recorded
        as waived by the owner; a waiver is never reported as a pause.
        """
        interactive = self.running(self.denied)
        rows_path = output / "quiet-host.idle.jsonl"
        if not interactive:
            sampler = HostSampler(rows_path, trial_root=os.getpid())
            sampler.start()
            time.sleep(self.idle_seconds)
            sampler.stop()
        rows = rows_path.read_bytes().splitlines() if rows_path.is_file() else []
        result = {
            **self.assess(interactive, rows),
            "icloud_paused_attested": icloud_paused_attested,
            "icloud_criterion": "attested_paused"
            if icloud_paused_attested
            else "waived_by_owner"
            if icloud_waived
            else "unmet",
            "denied_names": tuple(sorted(self.denied)),
        }
        if not icloud_paused_attested and not icloud_waived:
            result["status"] = "fail"
        (output / "quiet-host.json").write_bytes(msgspec.json.encode(result))
        return result
