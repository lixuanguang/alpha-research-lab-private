"""Qualify one predeclared homogeneous cohort of finite feature intervals."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
from datetime import datetime
from pathlib import Path
from typing import cast

# third party library imports
import msgspec
from capacity_features import CapacityFeatureObserver

# project library imports
from research.features import StoredFeature
from research.observations import DecisionInputs
from serialization import DomainCodec


class _Trial(msgspec.Struct, frozen=True):
    """Require an actually successful replacement-owner invocation of the same workload."""

    passed: bool
    features: bool
    recover: bool
    variant: str
    public_venue: str | None


class _Interval(msgspec.Struct, frozen=True):
    """Retain the exact measured finite interval, excluding startup and shutdown."""

    started_monotonic_ns: int
    scheduled_stop_monotonic_ns: int
    steady_ended_monotonic_ns: int
    steady_duration_seconds: int
    postprocess_status: str
    poll_failure: bool


class _Publication(msgspec.Struct, frozen=True):
    """Read one distinct atomic instrument version without expanding its two scalars."""

    source: str
    phase: str
    slot: int
    due_ns: int
    began_ns: int
    completed_ns: int
    completed_within_interval: bool
    durable_ns: int | None
    durable_to_available_ns: int | None
    native_position: int | None
    source_request_identity: str
    published_at: datetime
    inputs: DecisionInputs
    feature: StoredFeature
    version: str
    parity: bool
    quality: str
    status: str


class FeatureCohortResults:
    """Reconcile 17 finite recovery-steady runs per unchanged source/boundary class.

    Initial steady, source-specific materialization and global eight-reader
    retrieval are distinct populations. Every individual trial must retain its
    complete schedule and budgets before the materialization cohort is admitted.
    """

    def __init__(self, roots: tuple[Path, ...]) -> None:
        """Bind exactly the predeclared 17 feature roots without extending collection."""
        if len(roots) != 17 or len(set(root.resolve() for root in roots)) != 17:
            raise ValueError("feature materialization cohort requires 17 distinct finite runs")
        self.roots = roots
        self.codec = DomainCodec()

    def collect(self) -> dict[str, object]:
        """Require identical plans and validate actual source-bound version observations."""
        baseline: dict[str, object] | None = None
        durations: dict[str, list[int]] = {}
        versions: set[str] = set()
        retained: list[dict[str, object]] = []
        for root in self.roots:
            plan_path = root / "sampling-plan.json"
            plan = msgspec.json.decode(plan_path.read_bytes(), type=dict[str, object])
            if plan.get("cohort") != "recovery_steady":
                raise ValueError(
                    "initial steady and recovery-steady feature boundaries cannot pool"
                )
            if baseline is None:
                baseline = plan
                definitions = cast(dict[str, object], plan["feature_definitions"])
                durations = {source: [] for source in definitions}
            elif plan != baseline:
                raise ValueError(
                    "feature cohort changed implementation/configuration/cache/boundary"
                )
            trial_path = root.parent.parent / "summary.json"
            trial = msgspec.json.decode(trial_path.read_bytes(), type=_Trial)
            interval_path = root.parent / "summary.json"
            interval = msgspec.json.decode(interval_path.read_bytes(), type=_Interval)
            summary_path = root / "summary.json"
            summary = msgspec.json.decode(summary_path.read_bytes(), type=dict[str, object])
            if (
                not trial.passed
                or not trial.features
                or not trial.recover
                or trial.variant != "base"
                or trial.public_venue is not None
                or interval.steady_duration_seconds != 60
                or interval.scheduled_stop_monotonic_ns - interval.started_monotonic_ns
                != 60_000_000_000
                or interval.steady_ended_monotonic_ns < interval.scheduled_stop_monotonic_ns
                or interval.postprocess_status != "pass"
                or interval.poll_failure
                or summary.get("status") != "pass_observed_schedule"
                or summary.get("ready_retrievals") != 1920
                or summary.get("matched_cutoff_parity") is not True
            ):
                raise ValueError("feature cohort has an incomplete or failed finite interval")
            for boundary in ("service_latency", "response_latency"):
                if cast(dict[str, object], summary[boundary]).get("status") != "pass":
                    raise ValueError("feature retrieval did not qualify in every finite interval")
            sample_path = root / "materialization-samples.jsonl"
            groups: dict[str, list[_Publication]] = {source: [] for source in durations}
            for line in sample_path.read_bytes().splitlines():
                row = self.codec.decode_json(line, _Publication)
                if row.phase == "initialization":
                    continue
                if row.source not in groups:
                    raise ValueError("feature publication names an undeclared native source")
                self._validate(row, interval, versions)
                groups[row.source].append(row)
            for source, rows in groups.items():
                if len(rows) != 60 or {row.slot for row in rows} != set(range(60)):
                    raise ValueError("feature source lacks its 60 distinct one-second versions")
                if len({row.native_position for row in rows}) != 60:
                    raise ValueError("authored feature cohort repeated a native input position")
                durations[source].extend(
                    row.durable_to_available_ns
                    for row in rows
                    if row.durable_to_available_ns is not None
                )
            retained.append(
                {
                    "feature_root": str(root.resolve()),
                    "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                    "materialization_samples_sha256": hashlib.sha256(
                        sample_path.read_bytes()
                    ).hexdigest(),
                    "retrieval_samples_sha256": hashlib.sha256(
                        (root / "retrieval-samples.jsonl").read_bytes()
                    ).hexdigest(),
                    "trial_sha256": hashlib.sha256(trial_path.read_bytes()).hexdigest(),
                    "interval_sha256": hashlib.sha256(interval_path.read_bytes()).hexdigest(),
                    "service_latency": summary["service_latency"],
                    "response_latency": summary["response_latency"],
                }
            )
        results = {
            source: CapacityFeatureObserver.summarize(values, budgets_ms=(2000, 2000, 2000))
            for source, values in durations.items()
        }
        return {
            "schema_version": "finite-feature-cohort",
            "status": "pass"
            if all(result["status"] == "pass" for result in results.values())
            else "fail",
            "scope": "17_homogeneous_recovery_steady_60_second_intervals",
            "initial_steady": "excluded",
            "materialization_unit": "one_two_value_instrument_version",
            "materialization_per_source": results,
            "retrieval": "each_interval_qualified_independently_1920_requests",
            "runs": retained,
        }

    @staticmethod
    def _validate(row: _Publication, interval: _Interval, versions: set[str]) -> None:
        """Reject duplicate versions, future inputs and unjustified monotonic durations."""
        vector = row.feature.vector
        row.inputs.__post_init__()
        row.feature.__post_init__()
        if (
            row.phase != "steady"
            or row.status != "ok"
            or row.quality != "ready"
            or not row.parity
            or not row.completed_within_interval
            or row.version in versions
            or row.due_ns != interval.started_monotonic_ns + row.slot * 1_000_000_000
            or not row.due_ns
            <= row.began_ns
            <= row.completed_ns
            <= interval.scheduled_stop_monotonic_ns
            or row.durable_ns is None
            or not 0 <= row.durable_ns <= row.began_ns
            or row.durable_to_available_ns != row.completed_ns - row.durable_ns
            or row.native_position is None
            or row.feature.source_sha256 != row.source_request_identity
            or row.feature.dataset_sha256 != row.inputs.identity
            or row.feature.revision_identity != row.inputs.identity
            or vector.entity != row.inputs.entity
            or vector.decision_at != row.inputs.decision_at
            or vector.values != tuple(observation.value for observation in row.inputs.observations)
            or len(vector.values) != 2
            or any(value is None for value in vector.values)
            or row.published_at < vector.available_at
        ):
            raise ValueError("invalid same-boundary feature publication observation")
        versions.add(row.version)


class _Arguments(argparse.Namespace):
    """Carry retained feature roots and a fresh compact report path."""

    roots: list[Path]
    output: Path


def main() -> None:
    """Compose explicit finite evidence inputs and retain their compact qualification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs=17, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(namespace=_Arguments())
    result = FeatureCohortResults(tuple(args.roots)).collect()
    with args.output.open("xb") as stream:
        stream.write(DomainCodec().encode_json(result))
    print(
        DomainCodec().encode_json({"status": result["status"], "output": str(args.output)}).decode()
    )


if __name__ == "__main__":
    main()
