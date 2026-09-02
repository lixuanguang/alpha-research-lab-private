"""Deterministic and adversarial tests for program governance."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

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


def _replace_program_fixture_text(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _metric_observation_event(
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
    event_payload: dict[str, object] = {
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
        event_payload.update(
            {
                "denominator": denominator,
                "denominator_unit": metric.denominator_unit,
                "numerator": numerator,
                "numerator_unit": metric.numerator_unit,
            }
        )
    return event_payload


def _write_observation_events(tmp_path: Path, events: list[dict[str, object]]) -> Path:
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
    assert len(program.package_states) == 11
    assert program.package_status == "partial"
    assert program.risk_class == "R2"
    assert program.maximum_observations == 10_000
    assert program.aggregation_workload_budget_ms == 1_000
    assert program.finding_ids == ("A08-F01", "A08-F02", "A08-F03")
    assert all(state.status == "partial" for state in program.package_states)
    assert all(state.repository_local_status == "passed" for state in program.package_states)
    assert all(metric.collection_mode == "automatic_event" for metric in program.metrics)
    assert all(not metric.manual_entry_allowed for metric in program.metrics)
    assert all(not metric.hard_gate_substitute for metric in program.metrics)
    assert all(metric.baseline_value is None for metric in program.metrics)
    assert all(metric.target_value is None for metric in program.metrics)
    repository_topology_state = program.state_for("B01")
    assert repository_topology_state is not None
    assert repository_topology_state.open_finding_ids == ("B01-F01", "B01-F02")
    build_graph_state = program.state_for("B02")
    assert build_graph_state is not None
    assert build_graph_state.open_finding_ids == ("B02-F01", "B02-F02", "B02-F03")
    environment_state = program.state_for("B03")
    assert environment_state is not None
    assert environment_state.open_finding_ids == ("B03-F01", "B03-F02", "B03-F03")


def test_program_aggregation_workload_stays_within_governed_budget() -> None:
    program = validate_repository(REPOSITORY_ROOT)
    metric = next(
        item for item in program.metrics if item.metric_id == "kpi.build_duration_seconds"
    )
    base_time = datetime(2026, 8, 30, tzinfo=UTC)
    observations = tuple(
        MetricObservation(
            event_id=f"workload-{index}",
            metric_id=metric.metric_id,
            source_event_type=metric.source_event_type,
            source_run_id=f"run-workload-{index}",
            source_revision="5" * 40,
            evidence_url=f"https://forge.example/runs/workload-{index}",
            window_start=base_time + timedelta(seconds=index),
            window_end=base_time + timedelta(seconds=index + 5),
            dimensions=tuple(
                (dimension, f"value-{dimension}") for dimension in metric.required_dimensions
            ),
            numerator=None,
            denominator=None,
        )
        for index in range(program.maximum_observations)
    )

    started_at = perf_counter()
    summaries = program.summarize_metrics(observations)
    elapsed_ms = (perf_counter() - started_at) * 1_000

    build_summary = next(item for item in summaries if item.metric_id == metric.metric_id)
    assert build_summary.observation_count == program.maximum_observations
    assert elapsed_ms <= program.aggregation_workload_budget_ms, (
        f"aggregation of {program.maximum_observations} observations took "
        f"{elapsed_ms:.1f} ms; budget is {program.aggregation_workload_budget_ms} ms"
    )


@pytest.mark.parametrize("invalid_date", ["20260901", "2026-W36-2"])
def test_program_dates_require_extended_calendar_format(tmp_path: Path, invalid_date: str) -> None:
    path = _policy_fixture(tmp_path)
    _replace_program_fixture_text(
        path,
        'as_of_date = "2026-09-01"',
        f'as_of_date = "{invalid_date}"',
    )

    with pytest.raises(ProgramGovernanceError, match="must use YYYY-MM-DD"):
        load_program(path, repository_root=REPOSITORY_ROOT)


def test_exact_ranges_conditional_dependencies_and_readiness_are_derived() -> None:
    program = validate_repository(REPOSITORY_ROOT)
    packages_by_id = {package.package_id: package for package in program.packages}

    assert packages_by_id["A08"].dependencies == tuple(f"A{number:02d}" for number in range(1, 8))
    assert packages_by_id["H02"].dependencies[-4:] == ("I01", "I02", "I03", "I04")
    assert packages_by_id["L01"].dependencies == tuple(
        f"{wave}{number:02d}" for wave in "CDEFGHIJK" for number in range(1, 9)
    )
    assert packages_by_id["L06"].any_of_dependency_groups == (("L01", "L02", "L04"),)
    assert packages_by_id["L07"].any_of_dependency_groups == (("L01", "L02", "L03", "L04"),)
    assert tuple(item.package_id for item in program.ready_packages(institutional=False)) == (
        "B04",
    )
    assert program.ready_packages(institutional=True) == ()


def test_roadmap_rejects_cycle_unknown_shorthand_and_missing_package(tmp_path: Path) -> None:
    cyclic = _roadmap_fixture(tmp_path)
    _replace_program_fixture_text(
        cyclic,
        "| A01 | Repository charter and monorepo boundary | — | "
        "Repository-owned governance; no external authority | - |",
        "| A01 | Repository charter and monorepo boundary | — | "
        "Repository-owned governance; no external authority | A08 |",
    )
    with pytest.raises(ProgramGovernanceError, match="dependency cycle"):
        load_roadmap(cyclic)

    shorthand = _roadmap_fixture(tmp_path)
    _replace_program_fixture_text(shorthand, "B01-B08, C01-C08, D06", "B, C, D06")
    with pytest.raises(ProgramGovernanceError, match="unsupported roadmap dependency token"):
        load_roadmap(shorthand)

    missing = _roadmap_fixture(tmp_path)
    _replace_program_fixture_text(
        missing,
        "| A08 | Program dependency graph and owned baseline KPIs | — | "
        "Metrics are non-vanity signals and never replace hard gates | A01-A07 |",
        "",
    )
    with pytest.raises(ProgramGovernanceError, match="A01-L08 exactly once"):
        load_roadmap(missing)

    malformed = _roadmap_fixture(tmp_path)
    _replace_program_fixture_text(
        malformed,
        "| A01 | Repository charter and monorepo boundary | — | "
        "Repository-owned governance; no external authority | - |",
        "| A01 | Repository charter and monorepo boundary | - |",
    )
    with pytest.raises(ProgramGovernanceError, match="must declare objective, library/tool"):
        load_roadmap(malformed)


def test_program_policy_rejects_local_gap_status_overclaim_and_vanity_controls(
    tmp_path: Path,
) -> None:
    local_gap = _policy_fixture(tmp_path)
    _replace_program_fixture_text(
        local_gap, 'repository_local_status = "passed"', 'repository_local_status = "failed"'
    )
    with pytest.raises(ProgramGovernanceError, match="passing repository-local evidence"):
        load_program(local_gap, repository_root=REPOSITORY_ROOT)

    validated = _policy_fixture(tmp_path)
    _replace_program_fixture_text(
        validated,
        'package_id = "A01"\nstatus = "partial"',
        'package_id = "A01"\nstatus = "validated"',
    )
    with pytest.raises(ProgramGovernanceError, match="must remain partial"):
        load_program(validated, repository_root=REPOSITORY_ROOT)

    manual = _policy_fixture(tmp_path)
    _replace_program_fixture_text(
        manual, "manual_entry_allowed = false", "manual_entry_allowed = true"
    )
    with pytest.raises(ProgramGovernanceError, match="manual KPI entry is prohibited"):
        load_program(manual, repository_root=REPOSITORY_ROOT)

    vanity = _policy_fixture(tmp_path)
    _replace_program_fixture_text(
        vanity, "hard_gate_substitute = false", "hard_gate_substitute = true"
    )
    with pytest.raises(ProgramGovernanceError, match="cannot substitute for a hard gate"):
        load_program(vanity, repository_root=REPOSITORY_ROOT)


def test_program_policy_rejects_unapproved_target_claim_and_unretained_finding(
    tmp_path: Path,
) -> None:
    target = _policy_fixture(tmp_path)
    _replace_program_fixture_text(
        target, 'target_status = "pending_owner_approval"', 'target_status = "approved"'
    )
    with pytest.raises(ProgramGovernanceError, match="approved target requires value and evidence"):
        load_program(target, repository_root=REPOSITORY_ROOT)

    finding = _policy_fixture(tmp_path)
    _replace_program_fixture_text(finding, '"A01-F03"', '"A01-F99"')
    with pytest.raises(ProgramGovernanceError, match="do not retain findings"):
        load_program(finding, repository_root=REPOSITORY_ROOT)

    deferred = _policy_fixture(tmp_path)
    _replace_program_fixture_text(deferred, '"organization",', '"later_technical_package",')
    with pytest.raises(ProgramGovernanceError, match="deferred evidence classes"):
        load_program(deferred, repository_root=REPOSITORY_ROOT)


def test_program_policy_rejects_impossible_approved_target_values(tmp_path: Path) -> None:
    negative = _policy_fixture(tmp_path)
    _replace_program_fixture_text(
        negative,
        'target_status = "pending_owner_approval"',
        'target_status = "approved"\n'
        "target_value = -1\n"
        'target_approval_evidence = "https://forge.example/approvals/negative-target"',
    )
    with pytest.raises(ProgramGovernanceError, match="target_value must be non-negative"):
        load_program(negative, repository_root=REPOSITORY_ROOT)

    over_scale = _policy_fixture(tmp_path)
    text = over_scale.read_text(encoding="utf-8")
    metric_marker = 'metric_id = "kpi.research_reproducibility_percent"'
    prefix, bounded_metric_and_rest = text.split(metric_marker, maxsplit=1)
    bounded_metric_and_rest = bounded_metric_and_rest.replace(
        'target_status = "pending_owner_approval"',
        'target_status = "approved"\n'
        "target_value = 101\n"
        'target_approval_evidence = "https://forge.example/approvals/over-scale-target"',
        1,
    )
    over_scale.write_text(prefix + metric_marker + bounded_metric_and_rest, encoding="utf-8")
    with pytest.raises(ProgramGovernanceError, match="bounded ratio scale"):
        load_program(over_scale, repository_root=REPOSITORY_ROOT)


def test_duration_and_ratio_observations_aggregate_from_sufficient_statistics(
    tmp_path: Path,
) -> None:
    program = validate_repository(REPOSITORY_ROOT)
    events = [
        _metric_observation_event(
            "kpi.build_duration_seconds", event_id=f"build-{number}", seconds=number
        )
        for number in range(1, 6)
    ]
    events.extend(
        [
            _metric_observation_event(
                "kpi.research_reproducibility_percent",
                event_id="research-1",
                numerator=8,
                denominator=10,
            ),
            _metric_observation_event(
                "kpi.research_reproducibility_percent",
                event_id="research-2",
                start_seconds=5,
                seconds=10,
                numerator=1,
                denominator=2,
            ),
        ]
    )
    observations = load_observations(_write_observation_events(tmp_path, events), program=program)
    summaries = {item.metric_id: item for item in program.summarize_metrics(observations)}

    assert summaries["kpi.build_duration_seconds"].value == 5
    assert summaries["kpi.build_duration_seconds"].status == "measured"
    assert summaries["kpi.research_reproducibility_percent"].value == 75
    assert summaries["kpi.deployment_lead_time_seconds"].status == ("insufficient_observations")
    assert summaries["kpi.deployment_lead_time_seconds"].value is None


def test_reporting_window_excludes_stale_duration_observations(tmp_path: Path) -> None:
    program = validate_repository(REPOSITORY_ROOT)
    stale = _metric_observation_event(
        "kpi.build_duration_seconds", event_id="build-stale", seconds=59
    )
    stale["window_start"] = "2026-01-01T00:00:00Z"
    stale["window_end"] = "2026-01-01T00:00:59Z"
    recent = [
        _metric_observation_event(
            "kpi.build_duration_seconds", event_id=f"build-{number}", seconds=number
        )
        for number in range(1, 6)
    ]

    observations = load_observations(
        _write_observation_events(tmp_path, [stale, *recent]), program=program
    )
    summaries = {item.metric_id: item for item in program.summarize_metrics(observations)}

    assert summaries["kpi.build_duration_seconds"].observation_count == 5
    assert summaries["kpi.build_duration_seconds"].value == 5


def test_identical_retry_is_idempotent_and_conflicting_duplicate_fails(tmp_path: Path) -> None:
    program = validate_repository(REPOSITORY_ROOT)
    event = _metric_observation_event(
        "kpi.incident_rate_per_1000_runtime_hours", event_id="incident-1"
    )
    observations = load_observations(
        _write_observation_events(tmp_path, [event, event]), program=program
    )
    assert len(observations) == 1

    conflicting = dict(event)
    conflicting["numerator"] = 2
    with pytest.raises(ProgramGovernanceError, match="conflicting duplicate"):
        load_observations(
            _write_observation_events(tmp_path, [event, conflicting]), program=program
        )


def test_ratio_observation_windows_cannot_overlap_for_the_same_dimensions(
    tmp_path: Path,
) -> None:
    program = validate_repository(REPOSITORY_ROOT)
    first = _metric_observation_event(
        "kpi.research_reproducibility_percent", event_id="research-first"
    )
    overlapping = _metric_observation_event(
        "kpi.research_reproducibility_percent",
        event_id="research-overlap",
        start_seconds=4,
        seconds=8,
    )

    with pytest.raises(ProgramGovernanceError, match="overlapping ratio observations"):
        load_observations(
            _write_observation_events(tmp_path, [first, overlapping]), program=program
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"window_start": "2026-08-30T00:00:00+00:00"}, "ending Z"),
        ({"source_revision": "branch-main"}, "full digest"),
        ({"evidence_url": "https://user@example.com/run"}, "without credentials"),
        ({"evidence_url": "https://@example.com/run"}, "without credentials"),
        ({"evidence_url": "https://[malformed/run"}, "valid HTTPS URL"),
        ({"dimensions": {"environment": "ci"}}, "dimensions do not match"),
        ({"window_end": "2026-08-30T00:00:00Z"}, "window must be positive"),
    ],
)
def test_observation_boundary_failures_are_explicit(
    tmp_path: Path, mutation: dict[str, object], message: str
) -> None:
    program = validate_repository(REPOSITORY_ROOT)
    event = _metric_observation_event("kpi.build_duration_seconds", event_id="build-invalid")
    event.update(mutation)

    with pytest.raises(ProgramGovernanceError, match=message):
        load_observations(_write_observation_events(tmp_path, [event]), program=program)


def test_ratio_rejects_zero_denominator_unit_drift_and_impossible_bounded_value(
    tmp_path: Path,
) -> None:
    program = validate_repository(REPOSITORY_ROOT)
    zero = _metric_observation_event(
        "kpi.research_reproducibility_percent",
        event_id="research-zero",
        denominator=0,
    )
    with pytest.raises(ProgramGovernanceError, match="denominator positive"):
        load_observations(_write_observation_events(tmp_path, [zero]), program=program)

    unit = _metric_observation_event(
        "kpi.research_reproducibility_percent",
        event_id="research-unit",
    )
    unit["denominator_unit"] = "trials"
    with pytest.raises(ProgramGovernanceError, match="denominator unit"):
        load_observations(_write_observation_events(tmp_path, [unit]), program=program)

    impossible = _metric_observation_event(
        "kpi.research_reproducibility_percent",
        event_id="research-impossible",
        numerator=2,
        denominator=1,
    )
    with pytest.raises(ProgramGovernanceError, match="bounded numerator"):
        load_observations(_write_observation_events(tmp_path, [impossible]), program=program)


def test_cli_emits_stable_filtered_dashboard(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events = [
        _metric_observation_event(
            "kpi.build_duration_seconds", event_id=f"build-{number}", seconds=number
        )
        for number in range(1, 6)
    ]
    path = _write_observation_events(tmp_path, events)

    arguments = [str(REPOSITORY_ROOT), "--observations", str(path), "--wave", "A"]
    assert main(arguments) == 0
    first = capsys.readouterr().out
    assert main(arguments) == 0
    second = capsys.readouterr().out
    assert first == second

    dashboard = json.loads(first)
    assert dashboard["package_count"] == 96
    assert len(dashboard["packages"]) == 8
    assert dashboard["next_solo_ready_package"] == "B04"
    assert dashboard["next_institutionally_ready_package"] is None
    assert dashboard["observation_count"] == 5
    assert all(item["definition"]["hard_gate_substitute"] is False for item in dashboard["metrics"])

    assert main([str(REPOSITORY_ROOT), "--ready", "solo"]) == 0
    ready = json.loads(capsys.readouterr().out)
    assert [item["package_id"] for item in ready["packages"]] == ["B04"]
