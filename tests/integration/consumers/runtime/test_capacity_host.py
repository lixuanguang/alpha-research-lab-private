"""Check the ungraded host-wide CPU sampler used around feature trials."""

from __future__ import annotations

# standard library imports
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

# third party library imports
import msgspec
from capacity_host import HostGate, HostSampler, QuietHostPrecheck


def _rows(*loads: float, top: str = "Preview") -> list[bytes]:
    """Author one-second host rows with the given non-trial loads."""
    rows: list[bytes] = []
    for index, load in enumerate(loads):
        attribution: dict[str, object] = {"pid": 7, "name": top, "cores": load}
        row: dict[str, object] = {
            "monotonic_ns": index * 1_000_000_000,
            "elapsed_seconds": 1.0,
            "non_trial_cores": load,
            "top_non_trial": [attribution],
        }
        rows.append(msgspec.json.encode(row))
    return rows


class TestHostSampler:
    """Retain one bounded row per second and stop promptly."""

    def test_rows_report_host_and_busiest_visible_processes(self, tmp_path: Path) -> None:
        """A short run writes rows with host cores, visible cores and at most 12 processes."""
        path = tmp_path / "host.jsonl"
        sampler = HostSampler(path)
        sampler.start()
        time.sleep(2.3)
        began = time.monotonic()
        sampler.stop()
        assert time.monotonic() - began < 2
        assert not sampler.thread.is_alive() and not sampler.failures
        rows = [
            msgspec.json.decode(line, type=dict[str, object])
            for line in path.read_bytes().splitlines()
        ]
        assert len(rows) >= 2
        for row in rows:
            assert 0.9 < float(str(row["elapsed_seconds"])) < 1.5
            assert 0 <= float(str(row["host_busy_cores"])) <= int(str(row["host_cpus"])) + 0.5
            top = row["top"]
            assert isinstance(top, list) and 0 < len(top) <= 12

    def test_trial_tree_load_is_separated_from_the_rest_of_the_host(self, tmp_path: Path) -> None:
        """A busy descendant of the trial root counts as trial, never as non-trial load."""
        path = tmp_path / "host.jsonl"
        busy = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import time\nend = time.time() + 3\nwhile time.time() < end: pass",
            ]
        )
        sampler = HostSampler(path, trial_root=os.getpid())
        try:
            sampler.start()
            time.sleep(2.3)
            sampler.stop()
        finally:
            busy.wait(10)
        rows = [
            msgspec.json.decode(line, type=dict[str, object])
            for line in path.read_bytes().splitlines()
        ]
        assert len(rows) >= 2 and not sampler.failures
        assert max(float(str(row["trial_cores"])) for row in rows) > 0.5
        for row in rows:
            non_trial = cast(list[dict[str, object]], row["top_non_trial"])
            assert busy.pid not in {item["pid"] for item in non_trial}
            assert float(str(row["non_trial_cores"])) >= 0


class TestHostGate:
    """Fail only a continuous non-trial excess longer than its declared window."""

    def test_short_or_interrupted_excess_passes(self) -> None:
        """Excess shorter than the window, or broken by a quiet second, does not fail."""
        gate = HostGate(ceiling_cores=1.5, window_seconds=3)
        result = gate.assess(_rows(2, 2, 2, 0.5, 2, 2, 2))
        assert result["status"] == "pass" and result["longest_excess_seconds"] == 3

    def test_sustained_excess_fails_with_attribution(self) -> None:
        """A longer continuous excess fails and names the busiest non-trial process."""
        result = HostGate(ceiling_cores=1.5, window_seconds=3).assess(_rows(0.2, 2, 3, 2, 2))
        assert result["status"] == "fail" and result["longest_excess_seconds"] == 4
        assert result["attribution_core_seconds"] == {"Preview": 9.0}
        assert HostGate(1.5, 3).assess([])["status"] == "unmeasured"


class TestQuietHostPrecheck:
    """Refuse declared interactive processes and a host that is not idle."""

    def test_idle_mean_and_interactive_processes_decide(self) -> None:
        """Only an idle sample at or below the ceiling and no interactive process passes."""
        check = QuietHostPrecheck(frozenset({"Safari"}), idle_seconds=4, ceiling_cores=1.0)
        assert check.assess((), _rows(0.5, 1.5, 0.5, 1.0))["status"] == "pass"
        assert check.assess((), _rows(1.5, 1.5, 0.5, 1.0))["status"] == "fail"
        assert check.assess(((9, "Safari"),), _rows(0, 0, 0, 0))["status"] == "fail"
        # A truncated idle sample cannot stand in for the declared duration.
        assert check.assess((), _rows(0.1, 0.1))["status"] == "fail"

    def test_running_matches_exact_declared_names(self) -> None:
        """This interpreter is found by its exact name and nothing else is invented."""
        name = QuietHostPrecheck.running(frozenset({"no-such-interactive-process"}))
        assert name == ()
