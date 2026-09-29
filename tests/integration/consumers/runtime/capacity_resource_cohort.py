"""Qualify one predeclared cohort of independent bounded recovery resource intervals."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import math
from pathlib import Path

# third party library imports
import msgspec

# project library imports
from configuration import PaperServiceConfiguration
from serialization import DomainCodec


class _Arguments(argparse.Namespace):
    """Select completed homogeneous trials and a fresh compact output."""

    trials: list[Path]
    output: Path


class _Trial(msgspec.Struct, frozen=True):
    """Require successful base-fixture intervals from the same installed implementation."""

    implementation: str
    public_venue: str | None
    variant: str
    failures: tuple[str, ...]
    passed: bool


class _ResourceSummary(msgspec.Struct, frozen=True):
    """Keep row counts and visible-process evidence separate from usable CPU deltas."""

    samples: int
    visible_process_samples: int
    expected_one_hertz_samples: int
    sampling_failures: tuple[str, ...]
    status: str
    scope: str


class _ReadSummary(msgspec.Struct, frozen=True):
    """Read the exact steady boundary and unchanged resource-observer scope."""

    steady_duration_seconds: int
    cache_class: str
    postprocess_status: str
    poll_failure: bool
    resources: _ResourceSummary


class _FeatureSummary(msgspec.Struct, frozen=True):
    """Require the same integrated feature workload rather than reusing no-feature CPU."""

    status: str
    matched_cutoff_parity: bool
    failures: tuple[str, ...]
    expected_retrievals: int
    ready_retrievals: int


class _ResourceRow(msgspec.Struct, frozen=True):
    """Read actual one-second process deltas and independently measured logical disk size."""

    steady_offset_seconds: float
    processes: int
    rss_bytes: int
    logical_cpus: float | None
    logical_bytes: int
    occupied_bytes: int
    io_read_bytes_sampled_delta: int | None
    io_write_bytes_sampled_delta: int | None
    io_unavailable_reason: str | None


class _Observation(msgspec.Struct, frozen=True):
    """Select recovery and health evidence without reinterpreting account facts."""

    kind: str


class _Health(msgspec.Struct, frozen=True):
    """Read an explicitly checked continuous-health observation."""

    healthy: bool


class _HealthObservation(msgspec.Struct, frozen=True):
    """Bind the healthy result to its original observation row."""

    values: _Health


class CapacityResourceCohort:
    """Pool only compatible recovery-steady CPU boundaries with original finite lifetimes.

    Every invocation retains its own startup, replacement claim and service stop.
    The result describes the bounded recovery cohort; it supplies no sustained
    service, uninterrupted capture or physical-I/O claim.
    """

    def __init__(self, trials: tuple[Path, ...]) -> None:
        """Reject duplicate intervals and require absolute retained trial identities."""
        if not trials or any(not path.is_absolute() for path in trials):
            raise ValueError("resource cohort requires absolute completed trial paths")
        if len(set(trials)) != len(trials):
            raise ValueError("resource cohort cannot count the same trial twice")
        self.trials = trials
        self.codec = DomainCodec()

    def _read_trial(self, path: Path) -> tuple[bytes, tuple[_ResourceRow, ...]]:
        """Admit only exact observed recovery intervals with the full integrated workload."""
        trial = self.codec.decode_json((path / "summary.json").read_bytes(), _Trial)
        reads = self.codec.decode_json((path / "reads/summary.json").read_bytes(), _ReadSummary)
        features = self.codec.decode_json(
            (path / "reads/features/summary.json").read_bytes(), _FeatureSummary
        )
        plan = msgspec.json.decode(
            (path / "reads/features/sampling-plan.json").read_bytes(), type=dict[str, object]
        )
        configuration = self.codec.decode_json(
            (path / "configuration.json").read_bytes(), PaperServiceConfiguration
        )
        if (
            not trial.passed
            or trial.failures
            or trial.public_venue is not None
            or trial.variant != "base"
            or reads.steady_duration_seconds != 60
            or reads.postprocess_status != "pass"
            or reads.poll_failure
            or reads.resources.status != "pass"
            or reads.resources.samples != 60
            or reads.resources.visible_process_samples != 60
            or reads.resources.expected_one_hertz_samples != 60
            or reads.resources.sampling_failures
            or features.status != "pass_observed_schedule"
            or not features.matched_cutoff_parity
            or features.failures
            or features.expected_retrievals != 1920
            or features.ready_retrievals != 1920
            or plan.get("implementation") != trial.implementation
            or plan.get("configuration") != configuration.identity
        ):
            raise ValueError("resource interval lacks compatible successful workload evidence")
        observations = (path / "observations.jsonl").read_bytes().splitlines()
        kinds = tuple(self.codec.decode_json(line, _Observation).kind for line in observations)
        health = tuple(
            self.codec.decode_json(line, _HealthObservation).values.healthy
            for line, kind in zip(observations, kinds, strict=True)
            if kind == "steady_health"
        )
        if kinds.count("recovery_operator_started") != 1 or not health or not all(health):
            raise ValueError("resource cohort requires healthy recovery-steady observations")
        rows = tuple(
            self.codec.decode_json(line, _ResourceRow)
            for line in (path / "reads/resources.jsonl").read_bytes().splitlines()
        )
        if len(rows) != 60 or any(
            not index <= row.steady_offset_seconds < index + 1
            or row.processes <= 0
            or row.rss_bytes < 0
            or row.logical_bytes < 0
            or row.occupied_bytes < 0
            or (
                row.logical_cpus is not None
                and (row.logical_cpus < 0 or not math.isfinite(row.logical_cpus))
            )
            for index, row in enumerate(rows)
        ):
            raise ValueError("resource interval has missing or invalid one-second rows")
        identity = self.codec.encode_json(
            (
                trial.implementation,
                trial.variant,
                configuration,
                reads.cache_class,
                reads.resources.scope,
                plan,
            )
        )
        return identity, rows

    def write(self, output: Path) -> dict[str, object]:
        """Report a CPU percentile only after 1,000 actual compatible deltas."""
        if not output.is_absolute() or output.exists():
            raise ValueError("resource cohort requires a fresh absolute output path")
        cohorts: list[tuple[_ResourceRow, ...]] = []
        failures: list[dict[str, str]] = []
        identity: bytes | None = None
        for path in self.trials:
            try:
                current, rows = self._read_trial(path)
                if identity is not None and current != identity:
                    raise ValueError("resource cohort mixes workload or implementation identities")
                identity = current
                cohorts.append(rows)
            except (OSError, ValueError, TypeError) as error:
                failures.append({"trial": str(path), "reason": f"{type(error).__name__}: {error}"})
        rows = tuple(row for cohort in cohorts for row in cohort)
        cpus = sorted(row.logical_cpus for row in rows if row.logical_cpus is not None)
        cpu: dict[str, object] = {
            "samples": len(cpus),
            "rows_without_prior_cpu_delta": len(rows) - len(cpus),
            "average_logical_cores": sum(cpus) / len(cpus) if cpus else None,
            "peak_logical_cores": max(cpus, default=None),
            "percentile_method": "empirical_nearest_rank",
            "mean_budget_logical_cores": 7,
            "p95_budget_logical_cores": 9,
        }
        if failures or len(cpus) < 1000:
            cpu.update(
                status="unmeasured",
                reason="invalid_cohort" if failures else "fewer_than_1000_actual_cpu_deltas",
            )
        else:
            p95 = cpus[math.ceil(len(cpus) * 0.95) - 1]
            cpu.update(
                p95_logical_cores=p95,
                status="pass" if sum(cpus) / len(cpus) <= 7 and p95 <= 9 else "fail",
            )
        unsupported_io = sum(
            row.io_read_bytes_sampled_delta is None or row.io_write_bytes_sampled_delta is None
            for row in rows
        )
        result: dict[str, object] = {
            "schema_version": "bounded-recovery-resource-cohort",
            "evidence_class": "compatible_independent_60s_recovery_steady_intervals",
            "trials": tuple(str(path) for path in self.trials),
            "admitted_intervals": len(cohorts),
            "resource_rows": len(rows),
            "cohort_identity": None if identity is None else hashlib.sha256(identity).hexdigest(),
            "cpu": cpu,
            "peak_rss_bytes": max((row.rss_bytes for row in rows), default=None),
            "peak_logical_file_bytes": max((row.logical_bytes for row in rows), default=None),
            "peak_occupied_bytes": max((row.occupied_bytes for row in rows), default=None),
            "physical_io": {
                "status": "unsupported" if unsupported_io else "measured_sampled_deltas",
                "unsupported_rows": unsupported_io,
                "unavailable_reasons": tuple(
                    sorted({row.io_unavailable_reason for row in rows if row.io_unavailable_reason})
                ),
                "read_bytes": None
                if unsupported_io
                else sum(row.io_read_bytes_sampled_delta or 0 for row in rows),
                "write_bytes": None
                if unsupported_io
                else sum(row.io_write_bytes_sampled_delta or 0 for row in rows),
            },
            "logical_disk_basis": (
                "retained_file_sizes_separate_from_physical_or_logical_write_bytes"
            ),
            "failures": tuple(failures),
            "qualified": not failures and cpu["status"] == "pass",
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(self.codec.encode_json(result))
        return result


def main() -> None:
    """Resolve the predeclared completed cohort and publish its compact resource proof."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(namespace=_Arguments())
    result = CapacityResourceCohort(tuple(args.trials)).write(args.output)
    print(
        DomainCodec()
        .encode_json({"qualified": result["qualified"], "output": str(args.output)})
        .decode()
    )
    if result["qualified"] is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
