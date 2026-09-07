"""Exercise program-governance loaders, validators, renderers, and CLI behavior.

Arrange valid and mutated repository artifacts, then assert deterministic results
together with explicit rejection messages.
"""

from __future__ import annotations

# standard library imports
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import ClassVar, Never

# third party library imports
import pytest
from pydantic import TypeAdapter

# project library imports
import alpha_research_governance.program_governance.registry as program_registry
from alpha_research.program_governance import (
    METRIC_IDS,
    ROADMAP_PACKAGE_IDS,
    MetricObservation,
    ObservationReader,
    ProgramGovernanceError,
    ProgramRepository,
    ProgramStatusRenderer,
    RoadmapParser,
    load_observations,
    load_program,
    load_roadmap,
    main,
    render_status_markdown,
    validate_repository,
    validate_status_document,
)
from alpha_research_governance.change_risk import ChangeRiskPolicy
from alpha_research_governance.evidence import (
    EvidenceGovernanceError,
    EvidenceManifest,
    PackageEvidenceProfile,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs" / "governance" / "program-governance.toml"
ROADMAP_PATH = REPOSITORY_ROOT / "docs" / "roadmap" / "README.md"
RESEARCH_PROGRAM_PATH = REPOSITORY_ROOT / "docs" / "roadmap" / "research-program.md"


def _json_object(value: object) -> dict[str, object]:
    """Narrow a decoded CLI value to the object shape used by assertions."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError("expected a JSON object")
    return value


def _json_list(value: object) -> list[object]:
    """Narrow a decoded CLI value to a JSON array for nested assertions."""
    if not isinstance(value, list):
        raise TypeError("expected a JSON array")
    return value


class TestProgramServices:
    """Exercise service recovery after failed policy, roadmap, and observation reads.

    Assert that corrected inputs can be read again and produce the same valid
    results after each service has rejected an invalid input.
    """

    def test_repository_reloads_policy_and_explicit_ownership(self, tmp_path: Path) -> None:
        """Reload policy and a newly created ownership register after service failures.

        Arrange a temporary policy and initially missing ownership register, then
        create the register from the committed ownership document and mutate the
        policy between repository calls. Assert that the missing register raises
        ``FileNotFoundError``, the invalid risk class raises
        ``ProgramGovernanceError``, and the restored policy returns the same
        program through loading and validation.

        Args:
            tmp_path: Pytest directory where the temporary policy and ownership
                register are created.
        """
        path = _policy_fixture(tmp_path)
        ownership = tmp_path / "ownership.toml"
        repository = ProgramRepository(REPOSITORY_ROOT, ownership_register_path=ownership)
        with pytest.raises(FileNotFoundError):
            repository.load_program(path)
        ownership.write_text(
            (REPOSITORY_ROOT / "docs/governance/domain-ownership.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        expected = repository.load_program(path)
        original = path.read_text(encoding="utf-8")
        path.write_text(original.replace('risk_class = "R2"', 'risk_class = "R0"', 1))
        with pytest.raises(ProgramGovernanceError, match="risk_class must be"):
            repository.load_program(path)
        path.write_text(original, encoding="utf-8")
        assert repository.load_program(path) == expected
        assert repository.validate_repository() == expected

    def test_repository_reloads_scoped_state_after_effective_date_changes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Refresh ownership, effective date, and derived state on repeated loads.

        Construct a repository before its explicit ownership register exists, then
        load once before and once after a scoped security assignment becomes active.
        Assert the same repository re-evaluates A07 governance and reviewers from
        current inputs, and returns to founder-only state after the assignment is
        removed.

        Args:
            tmp_path: Pytest directory where the temporary ownership register is created.
            monkeypatch: Pytest patcher used to advance the public date boundary for loading.
        """
        ownership = tmp_path / "ownership.toml"
        repository = ProgramRepository(REPOSITORY_ROOT, ownership_register_path=ownership)
        baseline = (REPOSITORY_ROOT / "docs/governance/domain-ownership.toml").read_text(
            encoding="utf-8"
        )
        current_date = datetime.now(tz=UTC).date()
        effective_date = current_date + timedelta(days=1)
        ownership.write_text(
            baseline
            + f'''\n[[role_assignments]]
principal = "@security-hire"
role = "security"
domains = ["security"]
status = "active"
effective_from = "{effective_date.isoformat()}"
''',
            encoding="utf-8",
        )

        class MutableTodayDate(date):
            """Supply a controllable date to the repository loader."""

            current: ClassVar[date] = current_date

            @classmethod
            def today(cls) -> MutableTodayDate:
                """Return the selected date as a date-compatible subclass.

                Returns:
                    The controlled current date represented by this subclass.
                """
                current = cls.current
                return cls(current.year, current.month, current.day)

        monkeypatch.setattr(program_registry, "date", MutableTodayDate)
        before_activation = repository.load_program(POLICY_PATH)
        before_state = before_activation.state_for("A07")
        assert before_state is not None
        assert before_state.governance_status == "not_required"
        assert before_state.assigned_reviewers == ()

        MutableTodayDate.current = effective_date
        after_activation = repository.load_program(POLICY_PATH)
        after_state = after_activation.state_for("A07")
        assert after_state is not None
        assert after_state.governance_status == "pending"
        assert after_state.assigned_reviewers == ("@security-hire",)

        ownership.write_text(baseline, encoding="utf-8")
        restored = repository.load_program(POLICY_PATH)
        restored_state = restored.state_for("A07")
        assert restored_state is not None
        assert restored_state.governance_status == "not_required"
        assert restored_state.assigned_reviewers == ()

    def test_roadmap_parser_recovers_after_cycle_and_rereads_input(self, tmp_path: Path) -> None:
        """Reread a valid roadmap after rejecting a self-dependent mutation.

        Arrange a copied roadmap, mutate one dependency row into a self-cycle,
        and restore the original text after the rejection. Assert that repeated
        parses return the original parsed roadmap.

        Args:
            tmp_path: Pytest directory where the temporary roadmap is created.
        """
        path = _roadmap_fixture(tmp_path)
        parser = RoadmapParser()
        expected = parser.parse(path)
        original = path.read_text(encoding="utf-8")
        lines = original.splitlines()
        row = next(line for line in lines if line.startswith("| A01 |"))
        parts = row.split("|")
        parts[-2] = " A01 "
        path.write_text(original.replace(row, "|".join(parts), 1), encoding="utf-8")
        with pytest.raises(ProgramGovernanceError, match="cannot depend on itself"):
            parser.parse(path)
        path.write_text(original, encoding="utf-8")
        assert parser.parse(path) == expected
        assert parser.parse(path) == expected

    def test_observation_reader_discards_retry_and_overlap_state(self, tmp_path: Path) -> None:
        """Read corrected observation files after duplicate and overlap failures.

        Arrange duplicate, conflicting, and overlapping ratio events in one
        temporary JSONL file. Assert that identical retries collapse to one
        observation, conflicting duplicates and overlapping ratios raise
        ``ProgramGovernanceError``, and later valid or blank-only files return the
        expected results.

        Args:
            tmp_path: Pytest directory where observation JSONL files are written.
        """
        program = load_program(POLICY_PATH, repository_root=REPOSITORY_ROOT)
        metric = next(item for item in program.metrics if item.value_kind == "ratio")
        reader = ObservationReader(program)
        event = _metric_observation_event(metric.metric_id, event_id="retry-event")
        path = _write_observation_events(tmp_path, [event, event])
        expected = reader.read(path)
        assert len(expected) == 1
        conflicting = dict(event)
        conflicting["evidence_url"] = "https://forge.example/another-run"
        _write_observation_events(tmp_path, [event, conflicting])
        with pytest.raises(ProgramGovernanceError, match="conflicting duplicate"):
            reader.read(path)
        overlapping = dict(event)
        overlapping["event_id"] = "overlapping-event"
        _write_observation_events(tmp_path, [event, overlapping])
        with pytest.raises(ProgramGovernanceError, match="overlapping ratio"):
            reader.read(path)
        _write_observation_events(tmp_path, [event])
        assert reader.read(path) == expected
        assert (
            ProgramRepository(REPOSITORY_ROOT).load_observations(path, program=program) == expected
        )
        path.write_text("\n", encoding="utf-8")
        assert reader.read(path) == ()


class TestProgramStatusRenderer:
    """Exercise status rendering and validation across invalid and valid files.

    Assert that failures remain explicit and later valid validations still accept
    the expected generated status text.
    """

    def test_validation_recovers_after_missing_stale_and_invalid_utf8(self, tmp_path: Path) -> None:
        """Validate a corrected status file after missing, stale, and decoding failures.

        Exercise a missing path, an extra trailing newline, invalid UTF-8, and
        CRLF line endings for one status document. Assert that a missing-file
        ``ProgramGovernanceError`` preserves ``FileNotFoundError`` as its cause,
        stale text raises ``ProgramGovernanceError``, invalid UTF-8 propagates
        ``UnicodeDecodeError``, and normalized CRLF text validates repeatedly.

        Args:
            tmp_path: Pytest directory where temporary status files are written.
        """
        program = load_program(POLICY_PATH, repository_root=REPOSITORY_ROOT)
        renderer = ProgramStatusRenderer(program)
        expected = (REPOSITORY_ROOT / "docs/governance/program-status.md").read_text(
            encoding="utf-8"
        )
        status_path = tmp_path / "status.md"
        assert renderer.render() == expected
        with pytest.raises(ProgramGovernanceError, match="cannot read generated") as captured:
            renderer.validate(status_path)
        assert isinstance(captured.value.__cause__, FileNotFoundError)
        status_path.write_text(expected + "\n", encoding="utf-8")
        with pytest.raises(ProgramGovernanceError, match="status is stale"):
            renderer.validate(status_path)
        status_path.write_bytes(b"\xff")
        with pytest.raises(UnicodeDecodeError):
            renderer.validate(status_path)
        status_path.write_bytes(expected.replace("\n", "\r\n").encode("utf-8"))
        renderer.validate(status_path)
        renderer.validate(status_path)
        assert renderer.render() == expected

    def test_construction_defers_missing_status_contract_until_render(self) -> None:
        """Defer rejection of a missing status path until rendering.

        Arrange a program with its generated status path removed, construct the
        renderer, and render it twice. Assert that each render reports the same
        missing-path finding.
        """
        program = load_program(POLICY_PATH, repository_root=REPOSITORY_ROOT)
        updates: dict[str, None] = {"generated_status_path": None}
        legacy = program.model_copy(update=updates)
        renderer = ProgramStatusRenderer(legacy)
        for _ in range(2):
            with pytest.raises(ProgramGovernanceError) as captured:
                renderer.render()
            assert captured.value.findings == (
                "program schema does not define a generated status path",
            )


def _policy_fixture(tmp_path: Path) -> Path:
    """Copy the repository program policy, overwriting the temporary destination.

    Args:
        tmp_path: Pytest-provided directory for isolated fixture files.

    Returns:
        The temporary policy path consumed by mutation tests.

    Raises:
        OSError: If the source or destination policy cannot be read or written.
    """
    path = tmp_path / "program-governance.toml"
    path.write_text(POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _roadmap_fixture(tmp_path: Path) -> Path:
    """Copy the repository roadmap, overwriting the temporary destination.

    Args:
        tmp_path: Pytest-provided directory for isolated fixture files.

    Returns:
        The temporary roadmap path consumed by parser mutation tests.

    Raises:
        OSError: If the source or destination roadmap cannot be read or written.
    """
    path = tmp_path / "README.md"
    path.write_text(ROADMAP_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _replace_program_fixture_text(path: Path, old: str, new: str) -> None:
    """Replace the first expected text occurrence in a TOML or Markdown fixture.

    Args:
        path: Fixture file to read and rewrite as UTF-8 text.
        old: Existing text that must occur in the fixture.
        new: Replacement text written in place of the first occurrence.

    Raises:
        AssertionError: If ``old`` is absent, indicating a stale fixture contract.
        OSError: If the fixture cannot be read or rewritten.
    """
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _remove_package_state(path: Path, package_id: str) -> None:
    """Remove one package-state table while preserving later policy records.

    Args:
        path: Program-policy TOML fixture to rewrite in place.
        package_id: Package-state identifier whose table should be removed.

    Raises:
        ValueError: If the requested table or a following record boundary is absent.
        OSError: If the policy fixture cannot be read or rewritten.
    """
    text = path.read_text(encoding="utf-8")
    marker = f'[[package_states]]\npackage_id = "{package_id}"'
    start = text.index(marker)
    following_state = text.find("[[package_states]]", start + len(marker))
    following_metric = text.find("[[metrics]]", start + len(marker))
    candidates = [index for index in (following_state, following_metric) if index >= 0]
    end = min(candidates)
    path.write_text(text[:start] + text[end:], encoding="utf-8")


def _downgrade_current_policy(path: Path, *, schema_version: int) -> str:
    """Render legacy fixture text by removing v4 finding-disposition and status-path fields.

    Args:
        path: Policy fixture to read; its contents are not modified.
        schema_version: Legacy schema version to write into the returned record.

    Returns:
        TOML text with the first schema-version declaration replaced, finding-
        disposition tables and ``generated_status_path`` removed, and
        ``program-status.md`` appended to each ``evidence_paths`` list.
        Implementation fields remain for the caller to adjust.

    Raises:
        OSError: If the policy fixture cannot be read.
        ValueError: If the expected policy record boundaries are absent.
    """
    text = path.read_text(encoding="utf-8").replace(
        "schema_version = 4", f"schema_version = {schema_version}", 1
    )
    dispositions_start = text.index("[[finding_dispositions]]")
    package_states_start = text.index("[[package_states]]", dispositions_start)
    text = text[:dispositions_start] + text[package_states_start:]
    text = "\n".join(
        line for line in text.splitlines() if not line.startswith("generated_status_path =")
    )
    sections = text.split("evidence_paths = [")
    rendered = sections[0]
    for section in sections[1:]:
        body, suffix = section.split("]", 1)
        rendered += (
            "evidence_paths = ["
            f"{body.rstrip().removesuffix(',')}, "
            '"docs/governance/program-status.md"]'
            f"{suffix}"
        )
    return rendered + "\n"


class TestProgramContracts:
    """Exercise refactored program-state and local-evidence public contracts."""

    def test_repository_local_evidence_translates_io_failure_and_recovers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Translate a local-evidence read failure and recover on the next call.

        Arrange a typed manifest callback that raises ``OSError`` during repository
        validation. Assert the public repository method reports the exact A08 finding,
        preserves the filesystem cause, and succeeds again after the callback is restored.

        Args:
            monkeypatch: Pytest patcher used to inject and then remove the manifest failure.
        """
        repository = ProgramRepository(REPOSITORY_ROOT)

        def fail_manifest(
            path: Path,
            *,
            expected_commit_sha: str,
            change_policy: ChangeRiskPolicy,
        ) -> Never:
            """Raise the filesystem failure under test without reading its arguments.

            Args:
                path: Manifest path supplied by the repository validator.
                expected_commit_sha: Commit digest expected by the program record.
                change_policy: Loaded change-risk policy supplied to manifest validation.

            Returns:
                This callback never returns because it always raises ``OSError``.

            Raises:
                OSError: Always, to exercise the local-evidence I/O translation boundary.
            """
            del path, expected_commit_sha, change_policy
            raise OSError("manifest unavailable")

        with monkeypatch.context() as patch:
            patch.setattr(program_registry, "validate_manifest", fail_manifest)
            with pytest.raises(ProgramGovernanceError) as captured:
                repository.validate_repository()

        assert captured.value.findings == ("A08 local evidence bundle: manifest unavailable",)
        assert isinstance(captured.value.__cause__, OSError)
        assert repository.validate_repository() == validate_repository(REPOSITORY_ROOT)

    def test_repository_local_evidence_preserves_ordered_profile_findings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Preserve profile finding order and cause identity at the repository boundary.

        Arrange a typed package-profile callback that reports duplicate findings in a
        deliberate order. Assert ``validate_repository`` exposes the same ordered tuple
        and chains the exact originating ``EvidenceGovernanceError``.

        Args:
            monkeypatch: Pytest patcher used to inject the ordered profile findings.
        """
        findings = (
            "first profile mismatch",
            "second profile mismatch",
            "first profile mismatch",
        )
        profile_error = EvidenceGovernanceError(findings)

        def report_profile_findings(
            manifest: EvidenceManifest, profile: PackageEvidenceProfile
        ) -> Never:
            """Raise the ordered profile findings without changing inputs.

            Args:
                manifest: Validated A08 manifest passed to profile checking.
                profile: Fixed A08 profile passed to profile checking.

            Returns:
                This callback never returns because it always raises ``profile_error``.

            Raises:
                EvidenceGovernanceError: The ordered findings configured by this test.
            """
            del manifest, profile
            raise profile_error

        monkeypatch.setattr(program_registry, "validate_package_evidence", report_profile_findings)
        with pytest.raises(ProgramGovernanceError) as captured:
            ProgramRepository(REPOSITORY_ROOT).validate_repository()

        assert captured.value.findings == findings
        assert captured.value.__cause__ is profile_error

    @staticmethod
    def _schema_policy_fixture(tmp_path: Path, *, schema_version: int) -> Path:
        """Create a policy fixture using one of the supported schema versions.

        Args:
            tmp_path: Pytest-provided directory for the generated policy.
            schema_version: Program schema version from 1 through 4.

        Returns:
            A copied policy with schema-version fields and legacy state fields adjusted
            to the requested contract.

        Raises:
            OSError: If the source policy cannot be read or the fixture cannot be written.
            ValueError: If a requested schema version is unsupported.
        """
        if schema_version not in {1, 2, 3, 4}:
            raise ValueError(f"unsupported schema version {schema_version}")
        path = _policy_fixture(tmp_path)
        if schema_version == 4:
            return path
        downgraded = _downgrade_current_policy(path, schema_version=schema_version)
        if schema_version == 1:
            downgraded = (
                "\n".join(
                    line
                    for line in downgraded.splitlines()
                    if not line.startswith(
                        (
                            "implementation_status =",
                            "domain_id =",
                            "technical_finding_ids =",
                        )
                    )
                )
                + "\n"
            )
        path.write_text(downgraded, encoding="utf-8")
        return path

    @staticmethod
    def _swap_first_package_states(path: Path) -> None:
        """Swap the first two package-state records in a policy fixture.

        Args:
            path: Program-policy TOML fixture to rewrite in place.

        Raises:
            AssertionError: If the fixture does not begin with A01 and A02 records.
            OSError: If the fixture cannot be read or rewritten.
            ValueError: If fewer than three package-state boundaries are present.
        """
        text = path.read_text(encoding="utf-8")
        first_start = text.index("[[package_states]]")
        second_start = text.index("[[package_states]]", first_start + 1)
        third_start = text.index("[[package_states]]", second_start + 1)
        first = text[first_start:second_start]
        second = text[second_start:third_start]
        assert 'package_id = "A01"' in first
        assert 'package_id = "A02"' in second
        path.write_text(text[:first_start] + second + first + text[third_start:], encoding="utf-8")

    @pytest.mark.parametrize("schema_version", (1, 2, 3, 4))
    def test_package_state_evidence_reading_follows_schema_version(
        self, tmp_path: Path, schema_version: int
    ) -> None:
        """Apply legacy evidence-content checks while allowing schema-4 contracts.

        Arrange each supported program schema with A01 pointing at an existing Markdown
        file that does not retain its findings. Assert schemas 1 through 3 reject the
        missing finding text, while schema 4 accepts the existing contract path and
        preserves the loaded state order.

        Args:
            tmp_path: Pytest directory where the schema-specific policy is created.
            schema_version: Program schema version whose state evidence contract is tested.
        """
        path = self._schema_policy_fixture(tmp_path, schema_version=schema_version)
        if schema_version < 4:
            _replace_program_fixture_text(
                path,
                'evidence_paths = ["docs/governance/repository-charter.md", '
                '"docs/governance/program-status.md"]',
                'evidence_paths = ["docs/roadmap/README.md"]',
            )
            with pytest.raises(
                ProgramGovernanceError, match="evidence paths do not retain findings"
            ):
                load_program(path, repository_root=REPOSITORY_ROOT)
            return

        _replace_program_fixture_text(
            path,
            'evidence_paths = ["docs/governance/repository-charter.md"]',
            'evidence_paths = ["docs/roadmap/README.md"]',
        )
        program = load_program(path, repository_root=REPOSITORY_ROOT)
        state = program.state_for("A01")
        assert state is not None
        assert state.evidence_paths == ("docs/roadmap/README.md",)
        assert tuple(item.package_id for item in program.package_states[:2]) == (
            "A01",
            "A02",
        )

    @pytest.mark.parametrize("schema_version", (1, 2, 3, 4))
    def test_package_state_ordering_follows_schema_version(
        self, tmp_path: Path, schema_version: int
    ) -> None:
        """Enforce contiguous legacy prefixes and ordered modern state subsets.

        Arrange schemas 1 and 2 with A02 removed, and schemas 3 and 4 with A01 and
        A02 exchanged. Assert each schema reports its own ordering contract through
        the public program loader.

        Args:
            tmp_path: Pytest directory where the schema-specific policy is created.
            schema_version: Program schema version whose state ordering is tested.
        """
        path = self._schema_policy_fixture(tmp_path, schema_version=schema_version)
        if schema_version < 3:
            _remove_package_state(path, "A02")
            expected_finding = "package_states must be a contiguous implemented prefix"
        else:
            self._swap_first_package_states(path)
            expected_finding = "package_states must be unique, in roadmap order"

        with pytest.raises(ProgramGovernanceError, match=expected_finding):
            load_program(path, repository_root=REPOSITORY_ROOT)


def _metric_observation_event(
    program_metric_id: str,
    *,
    event_id: str,
    start_seconds: int = 0,
    seconds: int = 5,
    numerator: float = 1,
    denominator: float = 1,
) -> dict[str, object]:
    """Build an unvalidated mutable metric event payload for loader boundary tests.

    Args:
        program_metric_id: Registered metric identifier to populate.
        event_id: Stable event identifier used in evidence and source-run fields.
        start_seconds: Literal seconds component within the fixed
            ``2026-08-30T00:00Z`` start minute.
        seconds: Literal seconds component within the fixed
            ``2026-08-30T00:00Z`` end minute.
        numerator: Ratio numerator when the metric is ratio-valued; it may be invalid.
        denominator: Ratio denominator when the metric is ratio-valued; it may be invalid.

    Returns:
        A mutable JSON-compatible event payload with required dimensions, provenance,
        and ratio units when applicable. Callers may intentionally make it invalid.

    Raises:
        OSError: If the repository policy cannot be read.
        ProgramGovernanceError: If the repository policy is invalid.
        StopIteration: If ``program_metric_id`` is not registered in the policy.
    """
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
    """Write sorted-key JSONL events in order, overwriting the destination file.

    Args:
        tmp_path: Pytest-provided directory for the generated observation file.
        events: JSON-compatible event payloads to serialize in input order.

    Returns:
        The path of the UTF-8 JSONL file passed to the observation loader.

    Raises:
        OSError: If the destination file cannot be written.
        TypeError: If an event contains a value that JSON cannot serialize.
        ValueError: If JSON serialization encounters an invalid value such as a cycle.
    """
    path = tmp_path / "observations.jsonl"
    path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n",
        encoding="utf-8",
    )
    return path


class TestProgramGovernance:
    """Exercise repository program policy, roadmap, and readiness contracts."""

    def test_repository_program_is_complete_partial_and_non_vanity(self) -> None:
        """Validate the committed program graph, package states, findings, and KPI controls.

        Arrange the repository configuration, then assert its package and metric
        registries, partial status, finding dispositions, implementation and governance
        states, and non-vanity collection controls match the governed program.
        """
        program = validate_repository(REPOSITORY_ROOT)

        assert tuple(package.package_id for package in program.packages) == ROADMAP_PACKAGE_IDS
        assert tuple(metric.metric_id for metric in program.metrics) == METRIC_IDS
        assert len(program.packages) == 96
        assert len(program.package_states) == 19
        assert program.package_status == "partial"
        assert program.risk_class == "R2"
        assert program.maximum_observations == 10_000
        assert program.aggregation_workload_budget_ms == 1_000
        assert program.finding_ids == ("A08-F01", "A08-F02", "A08-F03")
        assert all(state.status == "partial" for state in program.package_states)
        assert all(state.repository_local_status == "passed" for state in program.package_states)
        assert program.schema_version == 4
        assert program.generated_status_path == "docs/governance/program-status.md"
        assert tuple(group.disposition for group in program.finding_dispositions) == (
            "technical",
            "operation_prerequisite",
            "role_handover",
        )
        assert program.finding_disposition_for("A01-F01") == "operation_prerequisite"
        assert program.finding_disposition_for("A01-F03") == "role_handover"
        assert sum(len(group.finding_ids) for group in program.finding_dispositions) == 54
        assert program.implementation_status == "complete"
        assert program.governance_status == "not_required"
        assert all(state.implementation_status == "complete" for state in program.package_states)
        assert all(state.governance_status == "not_required" for state in program.package_states)
        assert all(
            len(state.evidence_paths) == 1 and state.contract_path.endswith(".md")
            for state in program.package_states
        )
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
        standards_state = program.state_for("B04")
        assert standards_state is not None
        assert standards_state.open_finding_ids == ("B04-F01", "B04-F02", "B04-F03")
        continuous_integration_state = program.state_for("B05")
        assert continuous_integration_state is not None
        assert continuous_integration_state.open_finding_ids == (
            "B05-F01",
            "B05-F02",
            "B05-F03",
        )
        remote_execution_state = program.state_for("B06")
        assert remote_execution_state is not None
        assert remote_execution_state.open_finding_ids == (
            "B06-F01",
            "B06-F02",
            "B06-F03",
        )
        dependency_admission_state = program.state_for("B07")
        assert dependency_admission_state is not None
        assert dependency_admission_state.open_finding_ids == (
            "B07-F01",
            "B07-F02",
            "B07-F03",
        )
        artifact_supply_chain_state = program.state_for("B08")
        assert artifact_supply_chain_state is not None
        assert artifact_supply_chain_state.open_finding_ids == (
            "B08-F01",
            "B08-F02",
            "B08-F03",
        )
        instrument_identity_state = program.state_for("C01")
        assert instrument_identity_state is not None
        assert instrument_identity_state.open_finding_ids == (
            "C01-F01",
            "C01-F02",
            "C01-F03",
        )
        venue_calendar_state = program.state_for("C02")
        assert venue_calendar_state is not None
        assert venue_calendar_state.open_finding_ids == (
            "C02-F01",
            "C02-F02",
            "C02-F03",
        )
        financial_units_state = program.state_for("C03")
        assert financial_units_state is not None
        assert financial_units_state.open_finding_ids == (
            "C03-F01",
            "C03-F02",
            "C03-F03",
        )

    def test_program_dates_require_extended_calendar_format(self, tmp_path: Path) -> None:
        """Reject a policy whose as-of date omits the extended calendar separators.

        Arrange a copied policy with a compact date, then assert that loading it
        raises a governance error identifying the required ``YYYY-MM-DD`` format.

        Args:
            tmp_path: Pytest directory where the mutated policy is created.
        """
        path = _policy_fixture(tmp_path)
        _replace_program_fixture_text(
            path,
            'as_of_date = "2026-09-05"',
            'as_of_date = "20260901"',
        )

        with pytest.raises(ProgramGovernanceError, match="must use YYYY-MM-DD"):
            load_program(path, repository_root=REPOSITORY_ROOT)

    def test_exact_ranges_conditional_dependencies_and_readiness_are_derived(
        self,
    ) -> None:
        """Derive dependency ranges, purposes, and solo versus institutional readiness.

        Arrange the committed repository program and assert representative wave
        ranges, conditional dependencies, dependency purposes, and readiness queues
        expose the configured technical and operational relationships.
        """
        program = validate_repository(REPOSITORY_ROOT)
        packages_by_id = {package.package_id: package for package in program.packages}

        assert packages_by_id["A08"].dependencies == tuple(
            f"A{number:02d}" for number in range(1, 8)
        )
        assert packages_by_id["A08"].team_handover_dependencies == ("A03",)
        assert packages_by_id["H02"].dependencies[-4:] == ("I01", "I02", "I03", "I04")
        assert packages_by_id["L01"].dependencies == tuple(
            f"{wave}{number:02d}" for wave in "CDEFGHIJK" for number in range(1, 9)
        )
        assert packages_by_id["L06"].any_of_dependency_groups == (("L01", "L02", "L04"),)
        assert packages_by_id["L07"].any_of_dependency_groups == (("L01", "L02", "L03", "L04"),)
        assert packages_by_id["B07"].dependencies == ("B01", "B04", "B05")
        assert packages_by_id["B07"].operation_release_dependencies == ()
        assert packages_by_id["B07"].as_json()["dependency_purposes"] == {
            "implementation": {"all_of": ["B01", "B04", "B05"], "any_of": []},
            "operation_release": {"all_of": [], "any_of": []},
            "team_handover": {"all_of": [], "any_of": []},
        }
        assert packages_by_id["D01"].dependencies == ("C04",)
        assert packages_by_id["D01"].operation_release_dependencies == ("B08",)
        assert tuple(item.package_id for item in program.ready_packages(institutional=False)) == (
            "C04",
        )
        assert program.ready_packages(institutional=True) == ()

    def test_roadmap_rejects_cycle_unknown_shorthand_and_missing_package(
        self, tmp_path: Path
    ) -> None:
        """Reject roadmap cycles, shorthand dependencies, missing packages, and malformed rows.

        Arrange separate roadmap copies for each mutation, then assert that each
        invalid row raises a governance error containing the corresponding failure
        description.

        Args:
            tmp_path: Pytest directory where mutated roadmap copies are created.
        """
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
            "Metrics are non-vanity signals and never replace hard gates | "
            "implementation: A01-A07; team handover: A03 |",
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

        purpose_cycle = _roadmap_fixture(tmp_path)
        _replace_program_fixture_text(
            purpose_cycle,
            "| B05 | Source validation, package installation smoke checks, hygiene, secrets, and "
            "required CI result | uv, pre-commit, admitted secret scanner | One `make check` "
            "path is authoritative; focused checks remain optional | B01, B04 |",
            "| B05 | Source validation, package installation smoke checks, hygiene, secrets, and "
            "required CI result | uv, pre-commit, admitted secret scanner | One `make check` "
            "path is authoritative; focused checks remain optional | implementation: B01, "
            "B04; operation/release: B07 |",
        )
        with pytest.raises(ProgramGovernanceError, match="dependency cycle"):
            load_roadmap(purpose_cycle)

    def test_roadmap_parses_team_handover_purpose_without_changing_technical_readiness(
        self,
        tmp_path: Path,
    ) -> None:
        """Parse a team-handover dependency beside the technical dependency.

        Arrange a C02 roadmap row with an added A03 handover purpose, then assert the
        parsed package keeps C01 as its technical dependency and records A03 only in
        the team-handover dependency field.

        Args:
            tmp_path: Pytest directory where the mutated roadmap is created.
        """
        path = _roadmap_fixture(tmp_path)
        _replace_program_fixture_text(
            path,
            "| C02 | Venue, session, calendar, market-status, and timezone contracts | "
            "`exchange_calendars` 4.13.2 | Versioned source/override adapter and pinned "
            "fixtures; never live authority | C01 |",
            "| C02 | Venue, session, calendar, market-status, and timezone contracts | "
            "`exchange_calendars` 4.13.2 | Versioned source/override adapter and pinned "
            "fixtures; never live authority | implementation: C01; team handover: A03 |",
        )

        package = next(item for item in load_roadmap(path) if item.package_id == "C02")
        assert package.dependencies == ("C01",)
        assert package.team_handover_dependencies == ("A03",)

    def test_research_entry_rules_separate_technical_progress_from_operations_and_review(
        self,
    ) -> None:
        """Check that research-entry prose names technical, operational, and review boundaries.

        Arrange the committed research-program document and assert it contains the
        required phrases for technical completion, institutional validation, pending
        handover, and final out-of-sample access.
        """
        text = RESEARCH_PROGRAM_PATH.read_text(encoding="utf-8")

        assert "must have complete implementation and no technical finding" in text
        assert "It does not require\ninstitutional `validated` status" in text
        assert "Pending organizational handover does not block" in text
        assert "before final-OOS access and certification" in text

    def test_program_policy_rejects_local_gap_status_overclaim_and_vanity_controls(
        self,
        tmp_path: Path,
    ) -> None:
        """Reject policies with failed evidence, overclaimed status, or gate substitutes.

        Arrange four independent policy mutations and assert that loading each one
        raises the matching governance error for local evidence, package status,
        manual entry, or hard-gate substitution.

        Args:
            tmp_path: Pytest directory where mutated policy copies are created.
        """
        local_gap = _policy_fixture(tmp_path)
        _replace_program_fixture_text(
            local_gap,
            'repository_local_status = "passed"',
            'repository_local_status = "failed"',
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

    def test_program_policy_rejects_unapproved_target_claim_and_parallel_contracts(
        self,
        tmp_path: Path,
    ) -> None:
        """Reject unsupported target claims, parallel contracts, and deferred-evidence classes.

        Arrange independent mutations for an unsupported approved target, multiple
        capability contracts, and an invalid deferred-evidence class. Assert that
        each policy load raises the corresponding governance error.

        Args:
            tmp_path: Pytest directory where mutated policy copies are created.
        """
        target = _policy_fixture(tmp_path)
        _replace_program_fixture_text(
            target,
            'target_status = "pending_owner_approval"',
            'target_status = "approved"',
        )
        with pytest.raises(
            ProgramGovernanceError, match="approved target requires value and evidence"
        ):
            load_program(target, repository_root=REPOSITORY_ROOT)

        contracts = _policy_fixture(tmp_path)
        _replace_program_fixture_text(
            contracts,
            'evidence_paths = ["docs/governance/repository-charter.md"]',
            'evidence_paths = ["docs/governance/repository-charter.md", '
            '"docs/governance/domain-ownership.md"]',
        )
        with pytest.raises(
            ProgramGovernanceError, match="exactly one Markdown capability contract"
        ):
            load_program(contracts, repository_root=REPOSITORY_ROOT)

        deferred = _policy_fixture(tmp_path)
        _replace_program_fixture_text(deferred, '"organization",', '"later_technical_package",')
        with pytest.raises(ProgramGovernanceError, match="deferred evidence classes"):
            load_program(deferred, repository_root=REPOSITORY_ROOT)

    def test_program_policy_rejects_an_unmapped_active_historical_finding(
        self, tmp_path: Path
    ) -> None:
        """Reject an active historical finding without a migration disposition.

        Arrange a policy with one historical finding removed from its disposition
        group, then assert that loading the policy reports the unmapped finding.

        Args:
            tmp_path: Pytest directory where the mutated policy is created.
        """
        path = _policy_fixture(tmp_path)
        _replace_program_fixture_text(path, '  "A01-F01",\n', "")

        with pytest.raises(ProgramGovernanceError, match="lack a migration disposition"):
            load_program(path, repository_root=REPOSITORY_ROOT)

    def test_program_policy_rejects_impossible_approved_target_values(self, tmp_path: Path) -> None:
        """Reject approved targets that are negative or outside the bounded ratio scale.

        Arrange separate policies with a negative target and a ratio target above
        100, then assert that each load identifies the violated target constraint.

        Args:
            tmp_path: Pytest directory where mutated policy copies are created.
        """
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


class TestProgramObservations:
    """Exercise KPI observation parsing, aggregation, and boundary contracts."""

    def test_duration_and_ratio_observations_aggregate_from_sufficient_statistics(
        self,
        tmp_path: Path,
    ) -> None:
        """Aggregate duration and ratio events while marking under-sampled metrics insufficient.

        Arrange five duration events and two ratio events totaling 9/12 in a JSONL
        fixture, with no deployment observations. Assert the duration p95 is
        5 seconds, the pooled ratio is 75 percent, and deployment remains
        insufficient without a value.

        Args:
            tmp_path: Pytest directory where the observation JSONL file is written.
        """
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
        observations = load_observations(
            _write_observation_events(tmp_path, events), program=program
        )
        summaries = {item.metric_id: item for item in program.summarize_metrics(observations)}

        assert summaries["kpi.build_duration_seconds"].value == 5
        assert summaries["kpi.build_duration_seconds"].status == "measured"
        assert summaries["kpi.research_reproducibility_percent"].value == 75
        assert summaries["kpi.deployment_lead_time_seconds"].status == ("insufficient_observations")
        assert summaries["kpi.deployment_lead_time_seconds"].value is None

    def test_reporting_window_excludes_stale_duration_observations(self, tmp_path: Path) -> None:
        """Exclude stale duration events from the reporting-window summary.

        Arrange one January event and five August events, then assert the build-duration
        summary includes only the five August observations and returns 5 seconds.

        Args:
            tmp_path: Pytest directory where the observation JSONL file is written.
        """
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

    def test_identical_retry_is_idempotent_and_conflicting_duplicate_fails(
        self, tmp_path: Path
    ) -> None:
        """Collapse identical retries and reject conflicting duplicate payloads.

        Arrange two identical incident events, then replace one with a conflicting
        numerator. Assert that the retry yields one observation and the conflicting
        input raises the duplicate-payload error.

        Args:
            tmp_path: Pytest directory where observation JSONL files are written.
        """
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
                _write_observation_events(tmp_path, [event, conflicting]),
                program=program,
            )

    def test_ratio_observation_windows_cannot_overlap_for_the_same_dimensions(
        self,
        tmp_path: Path,
    ) -> None:
        """Reject overlapping ratio windows for identical metric dimensions.

        Arrange two research-ratio events whose windows overlap, then assert that
        loading them raises the overlap validation error.

        Args:
            tmp_path: Pytest directory where the observation JSONL file is written.
        """
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
                _write_observation_events(tmp_path, [first, overlapping]),
                program=program,
            )

    @pytest.mark.parametrize(
        ("mutation", "message"),
        [
            ({"window_start": "2026-08-30T00:00:00+00:00"}, "ending Z"),
            ({"source_revision": "branch-main"}, "full digest"),
            ({"evidence_url": "https://user@example.com/run"}, "without credentials"),
            ({"evidence_url": "https://[malformed/run"}, "valid HTTPS URL"),
            ({"dimensions": {"environment": "ci"}}, "dimensions do not match"),
            ({"window_end": "2026-08-30T00:00:00Z"}, "window must be positive"),
        ],
    )
    def test_observation_boundary_failures_are_explicit(
        self, tmp_path: Path, mutation: dict[str, object], message: str
    ) -> None:
        """Reject each malformed observation boundary with its specific message.

        Arrange the parametrized event mutation, load the resulting one-event JSONL
        fixture, and assert that the governance error includes the expected message
        fragment for its timestamp, provenance, URL, dimensions, or window failure.

        Args:
            tmp_path: Pytest directory where the mutated observation JSONL file is
                written.
            mutation: Event field change that introduces one boundary failure.
            message: Expected fragment in the resulting governance error.
        """
        program = validate_repository(REPOSITORY_ROOT)
        event = _metric_observation_event("kpi.build_duration_seconds", event_id="build-invalid")
        event.update(mutation)

        with pytest.raises(ProgramGovernanceError, match=message):
            load_observations(_write_observation_events(tmp_path, [event]), program=program)

    def test_ratio_rejects_zero_denominator_unit_drift_and_impossible_bounded_value(
        self,
        tmp_path: Path,
    ) -> None:
        """Reject invalid ratio denominators, units, and bounded numerators.

        Arrange events with a zero denominator, mismatched denominator units, and a
        numerator greater than its denominator. Assert each observation load reports
        the corresponding ratio violation.

        Args:
            tmp_path: Pytest directory where mutated observation JSONL files are written.
        """
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


class TestProgramCli:
    """Exercise deterministic program-governance CLI output contracts."""

    def test_cli_emits_stable_filtered_dashboard(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Emit the same filtered dashboard text and report the expected readiness values.

        Arrange five build observations, invoke the CLI twice for wave A, and compare
        the decoded stdout strings. Assert the dashboard counts, readiness fields,
        metric controls, and solo-ready package match the repository program.

        Args:
            tmp_path: Pytest directory where the observation JSONL file is written.
            capsys: Pytest capture fixture used to read each decoded CLI stdout value.
        """
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

        dashboard = _json_object(TypeAdapter(dict[str, object]).validate_json(first))
        assert dashboard["package_count"] == 96
        package_rows = [_json_object(item) for item in _json_list(dashboard["packages"])]
        assert len(package_rows) == 8
        assert dashboard["next_solo_ready_package"] == "C04"
        assert dashboard["next_implementation_ready_package"] == "C04"
        assert dashboard["next_institutionally_ready_package"] is None
        assert dashboard["observation_count"] == 5
        metric_rows = [_json_object(item) for item in _json_list(dashboard["metrics"])]
        assert all(
            _json_object(item["definition"])["hard_gate_substitute"] is False
            for item in metric_rows
        )

        assert main([str(REPOSITORY_ROOT), "--ready", "solo"]) == 0
        ready = _json_object(TypeAdapter(dict[str, object]).validate_json(capsys.readouterr().out))
        ready_rows = [_json_object(item) for item in _json_list(ready["packages"])]
        assert [item["package_id"] for item in ready_rows] == ["C04"]


class TestProgramReadiness:
    """Exercise package readiness, generated status, and version compatibility contracts."""

    def test_generated_status_is_deterministic_and_rejects_hand_edits(self, tmp_path: Path) -> None:
        """Validate rendered status content and reject an appended hand edit.

        Arrange a rendered status document in a temporary file, assert its required
        generated content validates, then append text and assert validation reports
        stale generated status.

        Args:
            tmp_path: Pytest directory where the generated status file is written.
        """
        program = validate_repository(REPOSITORY_ROOT)
        rendered = render_status_markdown(program)
        status_path = tmp_path / "program-status.md"
        status_path.write_text(rendered, encoding="utf-8")

        validate_status_document(status_path, program)
        assert "Registered implementation records: 19 of 96 packages" in rendered
        assert "Next implementation-ready package: `C04`" in rendered
        assert "`A01-F01`, `A01-F02`" in rendered
        assert "`A01-F03`" in rendered
        assert "No scoped handover is active" in rendered

        status_path.write_text(rendered + "hand edit\n", encoding="utf-8")
        with pytest.raises(ProgramGovernanceError, match="generated program status is stale"):
            validate_status_document(status_path, program)

    def test_solo_package_completes_without_invented_findings(self, tmp_path: Path) -> None:
        """Allow a cleared existing finding list to produce a complete solo package record.

        Arrange the existing A01 policy with its open findings removed, then assert
        the loaded record is technically complete without inventing findings and the
        institutional-ready package queue remains empty.

        Args:
            tmp_path: Pytest directory where the mutated policy is created.
        """
        path = _policy_fixture(tmp_path)
        _replace_program_fixture_text(
            path,
            'open_finding_ids = ["A01-F01", "A01-F02", "A01-F03"]',
            "open_finding_ids = []",
        )
        program = load_program(path, repository_root=REPOSITORY_ROOT)
        state = program.state_for("A01")
        assert state is not None
        assert state.implementation_status == "complete"
        assert state.open_finding_ids == ()
        assert state.technical_finding_ids == ()
        assert state.assigned_reviewers == ()
        assert state.governance_status == "not_required"
        assert program.ready_packages(institutional=True) == ()

    def test_blocked_technical_dependency_stops_solo_readiness(self, tmp_path: Path) -> None:
        """Reject a completed C02 record when its C01 technical dependency is blocked.

        Arrange a policy whose C01 implementation is blocked and local evidence is
        failed, then assert loading it raises the dependency-completion governance
        error for C02.

        Args:
            tmp_path: Pytest directory where the mutated policy is created.
        """
        path = _policy_fixture(tmp_path)
        text = path.read_text()
        prefix, suffix = text.split('package_id = "C01"', 1)
        suffix = suffix.replace(
            'implementation_status = "complete"', 'implementation_status = "blocked"', 1
        )
        suffix = suffix.replace(
            'repository_local_status = "passed"',
            'repository_local_status = "failed"',
            1,
        )
        path.write_text(prefix + 'package_id = "C01"' + suffix)
        with pytest.raises(
            ProgramGovernanceError,
            match="C02: completion requires complete technical dependencies",
        ):
            load_program(path, repository_root=REPOSITORY_ROOT)

    def test_non_contiguous_state_and_operational_dependency_do_not_block_delivery(
        self,
        tmp_path: Path,
    ) -> None:
        """Retain B07's loaded state when the separate B06 state record is absent.

        Arrange a policy with B06 removed, then assert B06 has no state, B07 retains
        a state, and the solo-ready queue contains B06 and C04.

        Args:
            tmp_path: Pytest directory where the mutated policy is created.
        """
        path = _policy_fixture(tmp_path)
        _remove_package_state(path, "B06")

        program = load_program(path, repository_root=REPOSITORY_ROOT)

        assert program.state_for("B06") is None
        assert program.state_for("B07") is not None
        assert tuple(item.package_id for item in program.ready_packages(institutional=False)) == (
            "B06",
            "C04",
        )

    def test_missing_implementation_dependency_still_blocks_non_contiguous_state(
        self,
        tmp_path: Path,
    ) -> None:
        """Reject C03 when its missing C02 implementation dependency prevents completion.

        Arrange a policy with the C02 state record removed, then assert loading it
        raises the dependency-completion governance error for C03.

        Args:
            tmp_path: Pytest directory where the mutated policy is created.
        """
        path = _policy_fixture(tmp_path)
        _remove_package_state(path, "C02")

        with pytest.raises(
            ProgramGovernanceError,
            match="C03: completion requires complete technical dependencies",
        ):
            load_program(path, repository_root=REPOSITORY_ROOT)

    def test_technical_findings_cannot_be_hidden_by_complete_status(self, tmp_path: Path) -> None:
        """Reject a completed-status record that contains a technical finding.

        Arrange the existing policy with one technical finding added to its otherwise
        complete implementation record, then assert loading it raises the
        no-technical-findings governance error.

        Args:
            tmp_path: Pytest directory where the mutated policy is created.
        """
        path = _policy_fixture(tmp_path)
        _replace_program_fixture_text(
            path,
            "technical_finding_ids = []",
            'technical_finding_ids = ["broken-schema"]',
        )
        with pytest.raises(ProgramGovernanceError, match="no technical findings"):
            load_program(path, repository_root=REPOSITORY_ROOT)

    def test_program_reader_retains_version_one_semantics(self, tmp_path: Path) -> None:
        """Read a version-one policy with its original institutional acceptance semantics.

        Arrange a downgraded legacy policy without newer implementation fields, then
        assert version one remains partial, has no institutional-ready packages, and
        still exposes C04 as the first solo-ready package.

        Args:
            tmp_path: Pytest directory where the downgraded policy is created.
        """
        path = _policy_fixture(tmp_path)
        lines = _downgrade_current_policy(path, schema_version=1).splitlines()
        path.write_text(
            "\n".join(
                line
                for line in lines
                if not line.startswith(
                    (
                        "implementation_status =",
                        "domain_id =",
                        "technical_finding_ids =",
                    )
                )
            )
            + "\n"
        )
        program = load_program(path, repository_root=REPOSITORY_ROOT)
        assert program.schema_version == 1
        assert program.ready_packages(institutional=True) == ()
        assert program.ready_packages(institutional=False)[0].package_id == "C04"
        assert all(state.status == "partial" for state in program.package_states)

    def test_program_reader_retains_version_two_dependency_semantics(self, tmp_path: Path) -> None:
        """Keep version-two loading independent of the retired B06 operation edge.

        Arrange a version-two policy with B06 blocked and its local evidence failed,
        then assert loading it still retains B07 because remote execution is no
        longer a technical or operation-release dependency.

        Args:
            tmp_path: Pytest directory where the downgraded and mutated policy is
                created.
        """
        path = _policy_fixture(tmp_path)
        path.write_text(_downgrade_current_policy(path, schema_version=2), encoding="utf-8")
        text = path.read_text(encoding="utf-8")
        prefix, suffix = text.split('package_id = "B06"', 1)
        suffix = suffix.replace(
            'implementation_status = "complete"', 'implementation_status = "blocked"', 1
        )
        suffix = suffix.replace(
            'repository_local_status = "passed"',
            'repository_local_status = "failed"',
            1,
        )
        path.write_text(prefix + 'package_id = "B06"' + suffix, encoding="utf-8")

        program = load_program(path, repository_root=REPOSITORY_ROOT)
        assert program.state_for("B07") is not None

    def test_hiring_derives_scoped_governance_without_rewriting_package_states(
        self, tmp_path: Path
    ) -> None:
        """Derive a scoped security handover while preserving implementation status.

        Arrange an active security hire in a copied ownership register, then assert
        only A07 becomes governance-pending, every package remains implementation
        complete, and solo readiness still begins with C04.

        Args:
            tmp_path: Pytest directory where the temporary ownership register is
                created.
        """
        register = tmp_path / "ownership.toml"
        register.write_text(
            (REPOSITORY_ROOT / "docs/governance/domain-ownership.toml").read_text()
            + """
    [[role_assignments]]
    principal = "@security-hire"
    role = "security"
    domains = ["security"]
    status = "active"
    effective_from = "2026-09-04"
    """
        )
        program = load_program(
            POLICY_PATH,
            repository_root=REPOSITORY_ROOT,
            ownership_register_path=register,
        )
        pending = [
            state.package_id
            for state in program.package_states
            if state.governance_status == "pending"
        ]
        assert pending == ["A07"]
        assert all(state.implementation_status == "complete" for state in program.package_states)
        assert program.ready_packages(institutional=False)[0].package_id == "C04"


class TestProgramWorkload:
    """Exercise the governed program aggregation workload budget."""

    @pytest.mark.performance
    def test_program_aggregation_workload_stays_within_governed_budget(self) -> None:
        """Measure maximum-observation aggregation against its configured time budget.

        Arrange the maximum number of duration observations and start timing only
        immediately before ``summarize_metrics``. Assert the summary count equals
        the configured maximum and elapsed aggregation milliseconds stay within the
        policy budget; the performance marker keeps this workload out of default
        test runs.
        """
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
