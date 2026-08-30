"""Deterministic and adversarial tests for A08 program governance."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns

import pytest

from alpha_research.program_governance import (
    METRIC_IDS,
    PACKAGE_IDS,
    MetricObservation,
    ProgramGovernanceError,
    load_observations,
    load_program,
    load_roadmap,
    main,
    validate_repository,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs" / "governance" / "program-governance.toml"
ROADMAP_PATH = REPOSITORY_ROOT / "docs" / "roadmap" / "README.md"


def _policy_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "program-governance.toml"
    path.write_text(POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _roadmap_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "README.md"
    path.write_text(ROADMAP_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _event(
    program_metric_id: str,
    *,
    event_id: str,
    start_seconds: int = 0,
    seconds: int = 5,
    numerator: float = 1,
    denominator: float = 1,
) -> dict[str, object]:
    program = load_program(POLICY_PATH, repository_root=REPOSITORY_ROOT)
    metric = next(item for item in program.metrics if item.metric_id == program_metric_id)
    result: dict[str, object] = {
        "dimensions": {key: f"value-{key}" for key in metric.required_dimensions},
        "event_id": event_id,
        "evidence_url": f"https://forge.example/runs/{event_id}",
        "metric_id": metric.metric_id,
        "schema_version": 1,
        "source_event_type": metric.source_event_type,
        "source_revision": "5" * 40,
        "source_run_id": f"run-{event_id}",
        "window_end": f"2026-08-30T00:00:{seconds:02d}Z",
        "window_start": f"2026-08-30T00:00:{start_seconds:02d}Z",
    }
    if metric.value_kind == "ratio":
        result.update(
            {
                "denominator": denominator,
                "denominator_unit": metric.denominator_unit,
                "numerator": numerator,
                "numerator_unit": metric.numerator_unit,
            }
        )
    return result


def _write_events(tmp_path: Path, events: list[dict[str, object]]) -> Path:
    path = tmp_path / "observations.jsonl"
    path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n",
        encoding="utf-8",
    )
    return path


def test_repository_program_is_complete_partial_and_non_vanity() -> None:
    program = validate_repository(REPOSITORY_ROOT)

    assert tuple(package.package_id for package in program.packages) == PACKAGE_IDS
    assert tuple(metric.metric_id for metric in program.metrics) == METRIC_IDS
    assert len(program.packages) == 96
    assert len(program.package_states) == 8
    assert program.package_status == "partial"
    assert program.risk_class == "R2"
    assert program.finding_ids == ("A08-F01", "A08-F02", "A08-F03")
    assert all(state.status == "partial" for state in program.package_states)
    assert all(state.repository_local_status == "passed" for state in program.package_states)
    assert all(metric.collection_mode == "automatic_event" for metric in program.metrics)
    assert all(not metric.manual_entry_allowed for metric in program.metrics)
    assert all(not metric.hard_gate_substitute for metric in program.metrics)
    assert all(metric.baseline_value is None for metric in program.metrics)
    assert all(metric.target_value is None for metric in program.metrics)


def test_exact_ranges_conditional_dependencies_and_readiness_are_derived() -> None:
    program = validate_repository(REPOSITORY_ROOT)
    by_id = {package.package_id: package for package in program.packages}

    assert by_id["A08"].dependencies == tuple(f"A{number:02d}" for number in range(1, 8))
    assert by_id["H02"].dependencies[-4:] == ("I01", "I02", "I03", "I04")
    assert by_id["L01"].dependencies == tuple(
        f"{wave}{number:02d}" for wave in "CDEFGHIJK" for number in range(1, 9)
    )
    assert by_id["L06"].any_of_dependency_groups == (("L01", "L02", "L04"),)
    assert by_id["L07"].any_of_dependency_groups == (("L01", "L02", "L03", "L04"),)
    assert tuple(item.package_id for item in program.ready_packages(institutional=False)) == (
        "B01",
    )
    assert program.ready_packages(institutional=True) == ()


def test_roadmap_rejects_cycle_unknown_shorthand_and_missing_package(tmp_path: Path) -> None:
    cyclic = _roadmap_fixture(tmp_path)
    _replace(
        cyclic,
        "| A01 | Repository charter and monorepo boundary | - |",
        "| A01 | Repository charter and monorepo boundary | A08 |",
    )
    with pytest.raises(ProgramGovernanceError, match="dependency cycle"):
        load_roadmap(cyclic)

    shorthand = _roadmap_fixture(tmp_path)
    _replace(shorthand, "B01-B08, C01-C08, D06", "B, C, D06")
    with pytest.raises(ProgramGovernanceError, match="unsupported roadmap dependency token"):
        load_roadmap(shorthand)

    missing = _roadmap_fixture(tmp_path)
    _replace(missing, "| A08 | Program dependency graph and owned baseline KPIs | A01-A07 |", "")
    with pytest.raises(ProgramGovernanceError, match="A01-L08 exactly once"):
        load_roadmap(missing)


def test_program_policy_rejects_local_gap_status_overclaim_and_vanity_controls(
    tmp_path: Path,
) -> None:
    local_gap = _policy_fixture(tmp_path)
    _replace(local_gap, 'repository_local_status = "passed"', 'repository_local_status = "failed"')
    with pytest.raises(ProgramGovernanceError, match="passing repository-local evidence"):
        load_program(local_gap, repository_root=REPOSITORY_ROOT)

    validated = _policy_fixture(tmp_path)
    _replace(
        validated,
        'package_id = "A01"\nstatus = "partial"',
        'package_id = "A01"\nstatus = "validated"',
    )
    with pytest.raises(ProgramGovernanceError, match="must remain partial"):
        load_program(validated, repository_root=REPOSITORY_ROOT)

    manual = _policy_fixture(tmp_path)
    _replace(manual, "manual_entry_allowed = false", "manual_entry_allowed = true")
    with pytest.raises(ProgramGovernanceError, match="manual KPI entry is prohibited"):
        load_program(manual, repository_root=REPOSITORY_ROOT)

    vanity = _policy_fixture(tmp_path)
    _replace(vanity, "hard_gate_substitute = false", "hard_gate_substitute = true")
    with pytest.raises(ProgramGovernanceError, match="cannot substitute for a hard gate"):
        load_program(vanity, repository_root=REPOSITORY_ROOT)


def test_program_policy_rejects_unapproved_target_claim_and_unretained_finding(
    tmp_path: Path,
) -> None:
    target = _policy_fixture(tmp_path)
    _replace(target, 'target_status = "pending_owner_approval"', 'target_status = "approved"')
    with pytest.raises(ProgramGovernanceError, match="approved target requires value and evidence"):
        load_program(target, repository_root=REPOSITORY_ROOT)

    finding = _policy_fixture(tmp_path)
    _replace(finding, '"A01-F03"', '"A01-F99"')
    with pytest.raises(ProgramGovernanceError, match="do not retain findings"):
        load_program(finding, repository_root=REPOSITORY_ROOT)

    deferred = _policy_fixture(tmp_path)
    _replace(deferred, '"organization",', '"later_technical_package",')
    with pytest.raises(ProgramGovernanceError, match="deferred evidence classes"):
        load_program(deferred, repository_root=REPOSITORY_ROOT)


def test_duration_and_ratio_observations_aggregate_from_sufficient_statistics(
    tmp_path: Path,
) -> None:
    program = validate_repository(REPOSITORY_ROOT)
    events = [
        _event("kpi.build_duration_seconds", event_id=f"build-{number}", seconds=number)
        for number in range(1, 6)
    ]
    events.extend(
        [
            _event(
                "kpi.research_reproducibility_percent",
                event_id="research-1",
                numerator=8,
                denominator=10,
            ),
            _event(
                "kpi.research_reproducibility_percent",
                event_id="research-2",
                start_seconds=5,
                seconds=10,
                numerator=1,
                denominator=2,
            ),
        ]
    )
    observations = load_observations(_write_events(tmp_path, events), program=program)
    summaries = {item.metric_id: item for item in program.summarize_metrics(observations)}

    assert summaries["kpi.build_duration_seconds"].value == 5
    assert summaries["kpi.build_duration_seconds"].status == "measured"
    assert summaries["kpi.research_reproducibility_percent"].value == 75
    assert summaries["kpi.deployment_lead_time_seconds"].status == ("insufficient_observations")
    assert summaries["kpi.deployment_lead_time_seconds"].value is None


def test_reporting_window_excludes_stale_duration_observations(tmp_path: Path) -> None:
    program = validate_repository(REPOSITORY_ROOT)
    stale = _event("kpi.build_duration_seconds", event_id="build-stale", seconds=59)
    stale["window_start"] = "2026-01-01T00:00:00Z"
    stale["window_end"] = "2026-01-01T00:00:59Z"
    recent = [
        _event("kpi.build_duration_seconds", event_id=f"build-{number}", seconds=number)
        for number in range(1, 6)
    ]

    observations = load_observations(_write_events(tmp_path, [stale, *recent]), program=program)
    summaries = {item.metric_id: item for item in program.summarize_metrics(observations)}

    assert summaries["kpi.build_duration_seconds"].observation_count == 5
    assert summaries["kpi.build_duration_seconds"].value == 5


def test_identical_retry_is_idempotent_and_conflicting_duplicate_fails(tmp_path: Path) -> None:
    program = validate_repository(REPOSITORY_ROOT)
    event = _event("kpi.incident_rate_per_1000_runtime_hours", event_id="incident-1")
    observations = load_observations(_write_events(tmp_path, [event, event]), program=program)
    assert len(observations) == 1

    conflicting = dict(event)
    conflicting["numerator"] = 2
    with pytest.raises(ProgramGovernanceError, match="conflicting duplicate"):
        load_observations(_write_events(tmp_path, [event, conflicting]), program=program)


def test_ratio_observation_windows_cannot_overlap_for_the_same_dimensions(
    tmp_path: Path,
) -> None:
    program = validate_repository(REPOSITORY_ROOT)
    first = _event("kpi.research_reproducibility_percent", event_id="research-first")
    overlapping = _event(
        "kpi.research_reproducibility_percent",
        event_id="research-overlap",
        start_seconds=4,
        seconds=8,
    )

    with pytest.raises(ProgramGovernanceError, match="overlapping ratio observations"):
        load_observations(_write_events(tmp_path, [first, overlapping]), program=program)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"window_start": "2026-08-30T00:00:00+00:00"}, "ending Z"),
        ({"source_revision": "branch-main"}, "full digest"),
        ({"evidence_url": "https://user@example.com/run"}, "without credentials"),
        ({"dimensions": {"environment": "ci"}}, "dimensions do not match"),
        ({"window_end": "2026-08-30T00:00:00Z"}, "window must be positive"),
    ],
)
def test_observation_boundary_failures_are_explicit(
    tmp_path: Path, mutation: dict[str, object], message: str
) -> None:
    program = validate_repository(REPOSITORY_ROOT)
    event = _event("kpi.build_duration_seconds", event_id="build-invalid")
    event.update(mutation)

    with pytest.raises(ProgramGovernanceError, match=message):
        load_observations(_write_events(tmp_path, [event]), program=program)


def test_ratio_rejects_zero_denominator_unit_drift_and_impossible_bounded_value(
    tmp_path: Path,
) -> None:
    program = validate_repository(REPOSITORY_ROOT)
    zero = _event(
        "kpi.research_reproducibility_percent",
        event_id="research-zero",
        denominator=0,
    )
    with pytest.raises(ProgramGovernanceError, match="denominator positive"):
        load_observations(_write_events(tmp_path, [zero]), program=program)

    unit = _event(
        "kpi.research_reproducibility_percent",
        event_id="research-unit",
    )
    unit["denominator_unit"] = "trials"
    with pytest.raises(ProgramGovernanceError, match="denominator unit"):
        load_observations(_write_events(tmp_path, [unit]), program=program)

    impossible = _event(
        "kpi.research_reproducibility_percent",
        event_id="research-impossible",
        numerator=2,
        denominator=1,
    )
    with pytest.raises(ProgramGovernanceError, match="bounded numerator"):
        load_observations(_write_events(tmp_path, [impossible]), program=program)


def test_aggregation_workload_stays_within_the_governed_budget() -> None:
    program = validate_repository(REPOSITORY_ROOT)
    observation = MetricObservation(
        event_id="build-load",
        metric_id="kpi.build_duration_seconds",
        source_event_type="ci_build_completed",
        source_run_id="load-run",
        source_revision="6" * 40,
        evidence_url="https://forge.example/runs/load-run",
        window_start=datetime(2026, 8, 30, tzinfo=UTC),
        window_end=datetime(2026, 8, 30, 0, 0, 1, tzinfo=UTC),
        dimensions=(),
        numerator=None,
        denominator=None,
    )
    workload = (observation,) * program.maximum_observations

    started = perf_counter_ns()
    summaries = program.summarize_metrics(workload)
    elapsed_ms = (perf_counter_ns() - started) / 1_000_000

    assert summaries[0].observation_count == program.maximum_observations
    assert elapsed_ms <= program.aggregation_workload_budget_ms


def test_cli_emits_stable_filtered_dashboard(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events = [
        _event("kpi.build_duration_seconds", event_id=f"build-{number}", seconds=number)
        for number in range(1, 6)
    ]
    path = _write_events(tmp_path, events)

    arguments = [str(REPOSITORY_ROOT), "--observations", str(path), "--wave", "A"]
    assert main(arguments) == 0
    first = capsys.readouterr().out
    assert main(arguments) == 0
    second = capsys.readouterr().out
    assert first == second

    dashboard = json.loads(first)
    assert dashboard["package_count"] == 96
    assert len(dashboard["packages"]) == 8
    assert dashboard["next_solo_ready_package"] == "B01"
    assert dashboard["next_institutionally_ready_package"] is None
    assert dashboard["observation_count"] == 5
    assert all(item["definition"]["hard_gate_substitute"] is False for item in dashboard["metrics"])

    assert main([str(REPOSITORY_ROOT), "--ready", "solo"]) == 0
    ready = json.loads(capsys.readouterr().out)
    assert [item["package_id"] for item in ready["packages"]] == ["B01"]


def test_cli_rejects_invalid_selection_and_missing_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(REPOSITORY_ROOT), "--wave", "Z"]) == 1
    assert "unsupported roadmap wave" in capsys.readouterr().err

    assert main([str(REPOSITORY_ROOT), "--metric", "kpi.vanity"]) == 1
    assert "unsupported program metric" in capsys.readouterr().err

    assert main([str(REPOSITORY_ROOT), "--ready", "maybe"]) == 1
    assert "unsupported readiness mode" in capsys.readouterr().err

    assert main([str(tmp_path)]) == 1
    assert "program-governance.toml" in capsys.readouterr().err

    assert main(["--observations"]) == 2
    assert "usage:" in capsys.readouterr().err


def test_program_checker_is_integrated_with_repository_automation() -> None:
    command = "python -m alpha_research.program_governance"
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    pre_commit = (REPOSITORY_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    continuous_integration = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    documentation = (REPOSITORY_ROOT / "docs" / "README.md").read_text(encoding="utf-8")

    assert command in makefile
    assert command in pre_commit
    assert command in continuous_integration
    assert "make program-governance-check" in documentation
