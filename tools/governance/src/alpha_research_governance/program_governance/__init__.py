"""Canonical A08 program-governance API and repository check command."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from alpha_research_governance.program_governance.models import (
    MetricDefinition,
    MetricObservation,
    MetricSummary,
    PackageNode,
    PackageState,
    ProgramGovernance,
    ProgramGovernanceError,
)
from alpha_research_governance.program_governance.registry import (
    APPLICABLE_GATE_IDS,
    METRIC_IDS,
    PACKAGE_IDS,
    load_observations,
    load_program,
    load_roadmap,
    validate_repository,
)

__all__ = [
    "APPLICABLE_GATE_IDS",
    "METRIC_IDS",
    "PACKAGE_IDS",
    "MetricDefinition",
    "MetricObservation",
    "MetricSummary",
    "PackageNode",
    "PackageState",
    "ProgramGovernance",
    "ProgramGovernanceError",
    "load_observations",
    "load_program",
    "load_roadmap",
    "main",
    "validate_repository",
]

_USAGE = (
    "usage: python -m alpha_research_governance.program_governance [repository-root] [--json] "
    "[--observations JSONL] [--wave A-L | --metric KPI_ID | --ready solo|institutional]"
)


def _parse_arguments(
    arguments: Sequence[str],
) -> tuple[Path, Path | None, bool, dict[str, str]]:
    root: Path | None = None
    observations: Path | None = None
    emit_json = False
    selection: dict[str, str] = {}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--json":
            if emit_json:
                raise ProgramGovernanceError([_USAGE])
            emit_json = True
            index += 1
            continue
        if argument == "--observations":
            if observations is not None or index + 1 >= len(arguments):
                raise ProgramGovernanceError([_USAGE])
            observations = Path(arguments[index + 1])
            index += 2
            continue
        if argument in {"--metric", "--ready", "--wave"}:
            if selection or index + 1 >= len(arguments):
                raise ProgramGovernanceError([_USAGE])
            selection[argument] = arguments[index + 1]
            index += 2
            continue
        if argument.startswith("--") or root is not None:
            raise ProgramGovernanceError([_USAGE])
        root = Path(argument)
        index += 1
    return (
        Path.cwd() if root is None else root,
        observations,
        emit_json or observations is not None or bool(selection),
        selection,
    )


def _package_json(program: ProgramGovernance, package: PackageNode) -> dict[str, object]:
    result = package.as_json()
    state = program.state_for(package.package_id)
    result["state"] = (
        {
            "evidence_paths": [],
            "open_finding_ids": [],
            "owner_role": None,
            "repository_local_status": "not_started",
            "status": "planned",
        }
        if state is None
        else state.as_json()
    )
    return result


def _json_result(
    program: ProgramGovernance,
    observations: tuple[MetricObservation, ...],
    selection: dict[str, str],
) -> dict[str, object]:
    selected_packages = program.packages
    selected_metrics = program.metrics
    ready_mode = selection.get("--ready")
    if "--wave" in selection:
        selected_packages = tuple(
            package for package in program.packages if package.wave == selection["--wave"]
        )
    if "--metric" in selection:
        selected_metrics = tuple(
            metric for metric in program.metrics if metric.metric_id == selection["--metric"]
        )
    if ready_mode is not None:
        selected_packages = program.ready_packages(institutional=ready_mode == "institutional")
    summaries = {summary.metric_id: summary for summary in program.summarize_metrics(observations)}
    solo_ready = program.ready_packages(institutional=False)
    institutional_ready = program.ready_packages(institutional=True)
    return {
        "accountable_owner_role": program.accountable_owner_role,
        "aggregation_limits": {
            "maximum_observations": program.maximum_observations,
            "workload_budget_ms": program.aggregation_workload_budget_ms,
        },
        "applicable_gate_ids": list(program.applicable_gate_ids),
        "as_of_date": program.as_of_date.isoformat(),
        "metrics": [
            {
                "definition": metric.as_json(),
                "observed_baseline": summaries[metric.metric_id].as_json(),
            }
            for metric in selected_metrics
        ],
        "next_institutionally_ready_package": (
            None if not institutional_ready else institutional_ready[0].package_id
        ),
        "next_solo_ready_package": None if not solo_ready else solo_ready[0].package_id,
        "observation_count": len(observations),
        "open_finding_ids": list(program.finding_ids),
        "operating_track": program.operating_track,
        "package_count": len(program.packages),
        "package_status": program.package_status,
        "packages": [_package_json(program, package) for package in selected_packages],
        "risk_class": program.risk_class,
        "roadmap_package": program.roadmap_package,
        "roadmap_path": program.roadmap_path,
        "schema_version": program.schema_version,
    }


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate A08 or emit a deterministic graph and KPI dashboard."""
    provided = list(sys.argv[1:] if arguments is None else arguments)
    try:
        repository_root, observation_path, emit_json, selection = _parse_arguments(provided)
    except ProgramGovernanceError as error:
        print(error, file=sys.stderr)
        return 2
    wave = selection.get("--wave")
    if wave is not None and (len(wave) != 1 or wave not in "ABCDEFGHIJKL"):
        print(f"unsupported roadmap wave {wave!r}", file=sys.stderr)
        return 1
    metric_id = selection.get("--metric")
    if metric_id is not None and metric_id not in METRIC_IDS:
        print(f"unsupported program metric {metric_id!r}", file=sys.stderr)
        return 1
    ready_mode = selection.get("--ready")
    if ready_mode is not None and ready_mode not in {"institutional", "solo"}:
        print(f"unsupported readiness mode {ready_mode!r}", file=sys.stderr)
        return 1
    try:
        program = validate_repository(repository_root)
        observations = (
            () if observation_path is None else load_observations(observation_path, program=program)
        )
    except (OSError, ProgramGovernanceError) as error:
        print(error, file=sys.stderr)
        return 1
    if emit_json:
        print(
            json.dumps(
                _json_result(program, observations, selection),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    else:
        print(
            f"Program governance passed for {len(program.packages)} packages and "
            f"{len(program.metrics)} KPIs; package status is {program.package_status}."
        )
    return 0
