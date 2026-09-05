"""Canonical program-governance API and repository check command."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from alpha_research_governance.program_governance.models import (
    FindingDispositionGroup,
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
    ROADMAP_PACKAGE_IDS,
    load_observations,
    load_program,
    load_roadmap,
    validate_repository,
)
from alpha_research_governance.program_governance.status import (
    render_status_markdown,
    validate_status_document,
)

__all__ = [
    "APPLICABLE_GATE_IDS",
    "METRIC_IDS",
    "ROADMAP_PACKAGE_IDS",
    "FindingDispositionGroup",
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
    "render_status_markdown",
    "validate_repository",
    "validate_status_document",
]

_USAGE = (
    "usage: python -m alpha_research_governance.program_governance [repository-root] [--json] "
    "[--observations JSONL] [--wave A-L | --metric KPI_ID | --ready solo|institutional] "
    "[--write-status]"
)


def _parse_arguments(
    arguments: Sequence[str],
) -> tuple[Path, Path | None, bool, bool, dict[str, str]]:
    repository_root: Path | None = None
    observation_path: Path | None = None
    should_emit_json = False
    should_write_status = False
    selection_options: dict[str, str] = {}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--json":
            if should_emit_json:
                raise ProgramGovernanceError([_USAGE])
            should_emit_json = True
            index += 1
            continue
        if argument == "--write-status":
            if should_write_status:
                raise ProgramGovernanceError([_USAGE])
            should_write_status = True
            index += 1
            continue
        if argument == "--observations":
            if observation_path is not None or index + 1 >= len(arguments):
                raise ProgramGovernanceError([_USAGE])
            observation_path = Path(arguments[index + 1])
            index += 2
            continue
        if argument in {"--metric", "--ready", "--wave"}:
            if selection_options or index + 1 >= len(arguments):
                raise ProgramGovernanceError([_USAGE])
            selection_options[argument] = arguments[index + 1]
            index += 2
            continue
        if argument.startswith("--") or repository_root is not None:
            raise ProgramGovernanceError([_USAGE])
        repository_root = Path(argument)
        index += 1
    if should_write_status and (should_emit_json or observation_path or selection_options):
        raise ProgramGovernanceError([_USAGE])
    return (
        Path.cwd() if repository_root is None else repository_root,
        observation_path,
        should_emit_json or observation_path is not None or bool(selection_options),
        should_write_status,
        selection_options,
    )


def _build_package_payload(program: ProgramGovernance, package: PackageNode) -> dict[str, object]:
    package_payload = package.as_json()
    package_state = program.state_for(package.package_id)
    package_payload["state"] = (
        {
            "implementation_status": "planned",
            "governance_status": None,
            "contract_path": None,
            "technical_finding_ids": [],
            "evidence_paths": [],
            "open_finding_ids": [],
            "owner_role": None,
            "repository_local_status": "not_started",
            "status": "planned",
        }
        if package_state is None
        else package_state.as_json()
    )
    return package_payload


def _build_program_dashboard_payload(
    program: ProgramGovernance,
    observations: tuple[MetricObservation, ...],
    selection_options: dict[str, str],
) -> dict[str, object]:
    selected_packages = program.packages
    selected_metrics = program.metrics
    ready_mode = selection_options.get("--ready")
    if "--wave" in selection_options:
        selected_packages = tuple(
            package for package in program.packages if package.wave == selection_options["--wave"]
        )
    if "--metric" in selection_options:
        selected_metrics = tuple(
            metric
            for metric in program.metrics
            if metric.metric_id == selection_options["--metric"]
        )
    if ready_mode is not None:
        selected_packages = program.ready_packages(institutional=ready_mode == "institutional")
    metric_summaries_by_id = {
        summary.metric_id: summary for summary in program.summarize_metrics(observations)
    }
    solo_ready_packages = program.ready_packages(institutional=False)
    institutional_ready_packages = program.ready_packages(institutional=True)
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
                "observed_baseline": metric_summaries_by_id[metric.metric_id].as_json(),
            }
            for metric in selected_metrics
        ],
        "next_institutionally_ready_package": (
            None if not institutional_ready_packages else institutional_ready_packages[0].package_id
        ),
        "next_implementation_ready_package": (
            None if not solo_ready_packages else solo_ready_packages[0].package_id
        ),
        "next_solo_ready_package": (
            None if not solo_ready_packages else solo_ready_packages[0].package_id
        ),
        "observation_count": len(observations),
        "open_finding_ids": list(program.finding_ids),
        "operating_track": program.operating_track,
        "package_count": len(program.packages),
        "package_status": program.package_status,
        "implementation_status": program.implementation_status,
        "governance_status": program.governance_status,
        "finding_dispositions": [group.as_json() for group in program.finding_dispositions],
        "institutional_status": program.package_status,
        "packages": [_build_package_payload(program, package) for package in selected_packages],
        "risk_class": program.risk_class,
        "roadmap_package": program.roadmap_package,
        "roadmap_path": program.roadmap_path,
        "schema_version": program.schema_version,
    }


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate program governance or emit a deterministic graph and KPI dashboard."""
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    try:
        (
            repository_root,
            observation_path,
            should_emit_json,
            should_write_status,
            selection_options,
        ) = _parse_arguments(cli_arguments)
    except ProgramGovernanceError as error:
        print(error, file=sys.stderr)
        return 2
    wave = selection_options.get("--wave")
    if wave is not None and (len(wave) != 1 or wave not in "ABCDEFGHIJKL"):
        print(f"unsupported roadmap wave {wave!r}", file=sys.stderr)
        return 1
    metric_id = selection_options.get("--metric")
    if metric_id is not None and metric_id not in METRIC_IDS:
        print(f"unsupported program metric {metric_id!r}", file=sys.stderr)
        return 1
    ready_mode = selection_options.get("--ready")
    if ready_mode is not None and ready_mode not in {"institutional", "solo"}:
        print(f"unsupported readiness mode {ready_mode!r}", file=sys.stderr)
        return 1
    try:
        if should_write_status:
            resolved_root = repository_root.resolve(strict=True)
            program = load_program(
                resolved_root / "docs" / "governance" / "program-governance.toml",
                repository_root=resolved_root,
            )
            if program.generated_status_path is None:
                raise ProgramGovernanceError(
                    ["program schema does not define a generated status path"]
                )
            output_path = resolved_root / program.generated_status_path
            output_path.write_text(render_status_markdown(program), encoding="utf-8")
            print(f"Wrote generated program status to {program.generated_status_path}.")
            return 0
        program = validate_repository(repository_root)
        observations = (
            () if observation_path is None else load_observations(observation_path, program=program)
        )
    except (OSError, ProgramGovernanceError) as error:
        print(error, file=sys.stderr)
        return 1
    if should_emit_json:
        print(
            json.dumps(
                _build_program_dashboard_payload(program, observations, selection_options),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    else:
        print(
            f"Program governance passed for {len(program.packages)} packages and "
            f"{len(program.metrics)} KPIs; implementation is {program.implementation_status}; "
            f"governance is {program.governance_status}; "
            f"institutional acceptance is {program.package_status}."
        )
    return 0
