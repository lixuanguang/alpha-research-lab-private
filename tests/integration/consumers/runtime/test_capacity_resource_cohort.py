"""Require compatible bounded CPU cohorts and honest unsupported I/O evidence."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

# third party library imports
import msgspec
import pytest
from capacity_inputs import CapacityWorkload
from capacity_resource_cohort import CapacityResourceCohort

# project library imports
from configuration import PaperServiceConfiguration
from serialization import DomainCodec


class TestCapacityResourceCohort:
    """Protect sample counts, workload compatibility and physical counter limitations."""

    @staticmethod
    def _trial(root: Path, index: int, config: PaperServiceConfiguration) -> Path:
        """Author complete resource evidence for one independent homogeneous test interval."""
        path = root / str(index)
        (path / "reads/features").mkdir(parents=True)
        codec = DomainCodec()
        (path / "configuration.json").write_bytes(codec.encode_json(config))
        (path / "summary.json").write_bytes(
            codec.encode_json(
                {
                    "implementation": "f" * 64,
                    "public_venue": None,
                    "variant": "base",
                    "failures": (),
                    "passed": True,
                }
            )
        )
        (path / "reads/summary.json").write_bytes(
            codec.encode_json(
                {
                    "steady_duration_seconds": 60,
                    "cache_class": "warm",
                    "postprocess_status": "pass",
                    "poll_failure": False,
                    "resources": {
                        "samples": 60,
                        "visible_process_samples": 60,
                        "expected_one_hertz_samples": 60,
                        "sampling_failures": (),
                        "status": "pass",
                        "scope": "selected_tree",
                    },
                }
            )
        )
        (path / "reads/features/summary.json").write_bytes(
            codec.encode_json(
                {
                    "status": "pass_observed_schedule",
                    "matched_cutoff_parity": True,
                    "failures": (),
                    "expected_retrievals": 1920,
                    "ready_retrievals": 1920,
                }
            )
        )
        (path / "reads/features/sampling-plan.json").write_bytes(
            codec.encode_json(
                {
                    "implementation": "f" * 64,
                    "configuration": config.identity,
                    "cache_class": "warm",
                }
            )
        )
        (path / "observations.jsonl").write_bytes(
            codec.encode_json({"kind": "recovery_operator_started"})
            + b"\n"
            + codec.encode_json({"kind": "steady_health", "values": {"healthy": True}})
            + b"\n"
        )
        rows = tuple(
            {
                "steady_offset_seconds": slot + 0.001,
                "processes": 30,
                "rss_bytes": 1_000_000,
                "logical_cpus": None if not slot else 2.0,
                "logical_bytes": 3_000_000,
                "occupied_bytes": 4_000_000,
                "io_read_bytes_sampled_delta": None,
                "io_write_bytes_sampled_delta": None,
                "io_unavailable_reason": "os_process_counter_unavailable",
            }
            for slot in range(60)
        )
        (path / "reads/resources.jsonl").write_bytes(
            b"".join(codec.encode_json(row) + b"\n" for row in rows)
        )
        return path

    def test_seventeen_intervals_provide_1003_actual_cpu_deltas(self, tmp_path: Path) -> None:
        """Exclude first null deltas and keep logical sizes separate from missing writes."""
        config = CapacityWorkload(
            opening_at=datetime(2026, 9, 28, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-resource-test-sockets"),
        ).service_configuration()
        trials = tuple(self._trial(tmp_path / "trials", index, config) for index in range(17))
        result = CapacityResourceCohort(trials).write(tmp_path / "summary.json")
        assert result["qualified"] is True
        assert result["resource_rows"] == 1020
        cpu = cast(dict[str, object], result["cpu"])
        assert cpu["samples"] == 1003
        assert cpu["rows_without_prior_cpu_delta"] == 17
        assert cpu["p95_logical_cores"] == 2.0
        physical = cast(dict[str, object], result["physical_io"])
        assert physical["status"] == "unsupported"
        assert physical["read_bytes"] is None and physical["write_bytes"] is None
        assert result["peak_logical_file_bytes"] == 3_000_000

        path = trials[-1] / "reads/features/sampling-plan.json"
        plan = msgspec.json.decode(path.read_bytes(), type=dict[str, object])
        plan["cache_class"] = "application_cold"
        path.write_bytes(DomainCodec().encode_json(plan))
        invalid = CapacityResourceCohort(trials).write(tmp_path / "invalid.json")
        assert invalid["qualified"] is False
        cpu = cast(dict[str, object], invalid["cpu"])
        assert cpu["reason"] == "invalid_cohort"
        assert "p95_logical_cores" not in cpu

    def test_initial_steady_and_duplicate_trials_cannot_supply_cpu_tail(
        self, tmp_path: Path
    ) -> None:
        """A different lifecycle phase and repeated bytes do not increase eligible counts."""
        config = CapacityWorkload(
            opening_at=datetime(2026, 9, 28, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-resource-test-sockets"),
        ).service_configuration()
        trial = self._trial(tmp_path / "trials", 0, config)
        with pytest.raises(ValueError, match="same trial twice"):
            CapacityResourceCohort((trial, trial))
        (trial / "observations.jsonl").write_bytes(
            DomainCodec().encode_json({"kind": "steady_health", "values": {"healthy": True}})
            + b"\n"
        )
        result = CapacityResourceCohort((trial,)).write(tmp_path / "initial.json")
        assert result["qualified"] is False
        assert result["admitted_intervals"] == 0
        assert result["resource_rows"] == 0
