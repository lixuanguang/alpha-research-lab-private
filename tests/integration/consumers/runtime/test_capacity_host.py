"""Check the ungraded host-wide CPU sampler used around feature trials."""

from __future__ import annotations

# standard library imports
import time
from pathlib import Path

# third party library imports
import msgspec
from capacity_host import HostSampler


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
