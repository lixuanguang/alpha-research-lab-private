"""Runtime-validation contracts shared by immutable boundary models."""

from __future__ import annotations

# standard library imports
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Never, TypeGuard

# third party library imports
import pytest
from pydantic import ValidationError

# project library imports
import alpha_research_governance.architecture_governance as architecture_module
import alpha_research_governance.change_risk.policy as change_policy_module
import alpha_research_governance.evidence.manifest as evidence_manifest_module
import alpha_research_governance.evidence.policy as evidence_policy_module
import alpha_research_governance.inventory.registry as inventory_module
import alpha_research_governance.program_governance.registry as program_module
import alpha_research_governance.security_controls.registry as security_module
from alpha_research_governance.architecture_governance import (
    ArchitectureGovernanceError,
)
from alpha_research_governance.change_risk import (
    ChangeRiskInput,
    ChangeRiskPolicyError,
    ReviewApproval,
    RiskClass,
    SampleChange,
)
from alpha_research_governance.change_risk import (
    load_policy as load_change_policy,
)
from alpha_research_governance.evidence import (
    EvidenceGovernanceError,
    EvidencePolicy,
    MrField,
)
from alpha_research_governance.inventory import (
    InventoryGovernanceError,
)
from alpha_research_governance.program_governance import (
    MetricObservation,
    PackageNode,
    ProgramGovernanceError,
)
from alpha_research_governance.program_governance import (
    validate_repository as validate_program,
)
from alpha_research_governance.security_controls import (
    AuthoritySource,
    SecurityControlError,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
CHANGE_POLICY_PATH = REPOSITORY_ROOT / "docs" / "governance" / "change-risk-policy.toml"


def _is_string_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    """Narrow serialized model mappings while retaining exact primitive values."""
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    """Narrow serialized model arrays without coercing their elements."""
    return isinstance(value, list)


def _observation_with(**updates: object) -> dict[str, object]:
    """Build one observation payload with a precise object-valued mutation shape."""
    values = _observation_values()
    values.update(updates)
    return values


def _change_values() -> dict[str, object]:
    """Build a fresh minimal documentation-only change payload for validation mutations."""
    return {
        "capital_at_risk": False,
        "blast_radius": "documentation_only",
        "data_model_materiality": "none",
        "security_privilege": "none",
        "reversibility": "immediate",
    }


def _observation_values() -> dict[str, object]:
    """Build a fresh five-second UTC build observation with strict scalar and tuple values."""
    return {
        "event_id": "event-validated-model",
        "metric_id": "kpi.build_duration_seconds",
        "source_event_type": "ci_build_completed",
        "source_run_id": "run-validated-model",
        "source_revision": "5" * 40,
        "evidence_url": "https://forge.example/runs/validated-model",
        "window_start": datetime(2026, 8, 30, tzinfo=UTC),
        "window_end": datetime(2026, 8, 30, 0, 0, 5, tzinfo=UTC),
        "dimensions": (("runner_class", "hosted"),),
        "numerator": None,
        "denominator": None,
    }


def _captured_validation_error() -> ValidationError:
    """Capture a real model error carrying the synthetic rejected boolean input.

    Returns:
        The caught ValidationError for reuse by loader failure doubles.

    Raises:
        pytest.fail.Exception: The malformed change unexpectedly passes validation.
    """
    invalid_values = _change_values()
    invalid_values["capital_at_risk"] = "not-a-boolean"
    with pytest.raises(ValidationError) as captured:
        ChangeRiskInput.model_validate(invalid_values)
    return captured.value


class TestBoundaryModelValidation:
    """Validate strict scalar, nested and serialized boundary model contracts."""

    def test_strict_primitives_enums_and_unknown_fields_fail(self) -> None:
        """Reject boolean coercion, raw enum strings and unknown change fields."""
        invalid_values = (
            {**_change_values(), "capital_at_risk": 1},
            {**_change_values(), "declared_class": "R2"},
            {**_change_values(), "unknown_field": "rejected"},
        )
        for values in invalid_values:
            with pytest.raises(ValidationError):
                ChangeRiskInput.model_validate(values)

    def test_missing_required_and_invalid_nested_models_fail(self) -> None:
        """Reject absent dimensions and revalidate a nested change corrupted after construction."""
        values = _change_values()
        del values["reversibility"]
        with pytest.raises(ValidationError):
            ChangeRiskInput.model_validate(values)

        invalid_change = ChangeRiskInput.model_validate(_change_values())
        # Simulate an untrusted nested instance that bypassed the public frozen API.
        object.__setattr__(invalid_change, "capital_at_risk", "not-a-boolean")
        with pytest.raises(ValidationError):
            SampleChange(
                change_id="invalid-nested-model",
                change=invalid_change,
                expected_class=RiskClass.R0,
            )

    def test_strict_paths_dates_datetimes_tuples_and_frozensets_fail(self) -> None:
        """Reject container and scalar coercion, invalid UTC windows and nonfinite metrics."""
        invalid_evidence_policy: dict[str, object] = {
            "template_path": "docs/template.md",
            "example_mr_body_path": Path("docs/example.md"),
            "example_manifest_path": Path("evidence/example.toml"),
            "example_commit_sha": "5" * 40,
            "applicable_gates": (),
            "mandatory_package_gates": (),
            "fields": (),
            "package_status": "partial",
            "finding_ids": (),
        }
        with pytest.raises(ValidationError):
            EvidencePolicy.model_validate(invalid_evidence_policy)
        invalid_authority: dict[str, object] = {
            "source_id": "source",
            "jurisdiction_id": "GLOBAL",
            "authority": "authority",
            "title": "title",
            "citation": "citation",
            "source_class": "framework",
            "url": "https://example.com",
            "last_verified_on": "2026-08-30",
        }
        with pytest.raises(ValidationError):
            AuthoritySource.model_validate(invalid_authority)
        invalid_package: dict[str, object] = {
            "package_id": "A01",
            "wave": "A",
            "objective": "objective",
            "dependencies": [],
            "any_of_dependency_groups": (),
        }
        with pytest.raises(ValidationError):
            PackageNode.model_validate(invalid_package)
        invalid_approval: dict[str, object] = {
            "reviewer_id": "reviewer",
            "roles": ["code_owner"],
        }
        with pytest.raises(ValidationError):
            ReviewApproval.model_validate(invalid_approval)
        with pytest.raises(ValidationError):
            MetricObservation.model_validate(_observation_with(window_start="2026-08-30T00:00:00Z"))
        with pytest.raises(ValidationError, match="UTC datetimes"):
            MetricObservation.model_validate(_observation_with(window_start=datetime(2026, 8, 30)))
        with pytest.raises(ValidationError, match="must be positive"):
            MetricObservation.model_validate(
                _observation_with(window_end=datetime(2026, 8, 29, tzinfo=UTC))
            )
        with pytest.raises(ValidationError, match="must be a float"):
            MetricObservation.model_validate(_observation_with(numerator=1))
        with pytest.raises(ValidationError):
            MetricObservation.model_validate(_observation_with(numerator=float("nan")))

    def test_json_mode_preserves_boundary_shapes(self) -> None:
        """Serialize enums and paths as text and approval roles in deterministic order."""
        change_values = _change_values()
        change_values["declared_class"] = RiskClass.R2
        change = ChangeRiskInput.model_validate(change_values)
        approval = ReviewApproval(
            reviewer_id="reviewer",
            roles=frozenset({"security", "code_owner"}),
        )
        policy = EvidencePolicy(
            template_path=Path("docs/template.md"),
            example_mr_body_path=Path("docs/example.md"),
            example_manifest_path=Path("evidence/example.toml"),
            example_commit_sha="5" * 40,
            applicable_gates=("QG01",),
            mandatory_package_gates=("QG01",),
            fields=(MrField(key="scope", heading="Scope"),),
            package_status="partial",
            finding_ids=("A05-F01",),
        )

        change_json: object = change.model_dump(mode="json")
        approval_json: object = approval.model_dump(mode="json")
        policy_json: object = policy.model_dump(mode="json")
        assert _is_string_mapping(change_json)
        assert _is_string_mapping(approval_json)
        assert _is_string_mapping(policy_json)
        assert change_json["declared_class"] == "R2"
        roles = approval_json["roles"]
        assert _is_object_list(roles)
        assert roles == ["code_owner", "security"]
        assert policy_json["template_path"] == "docs/template.md"


class TestBoundaryLoaderErrors:
    """Validate loader translation and redaction of model validation failures."""

    def test_public_loaders_translate_validation_errors_without_leaking_details(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Preserve loader errors and causes while hiding rejected values and URLs."""
        validation_error = _captured_validation_error()
        change_policy = load_change_policy(CHANGE_POLICY_PATH)
        program = validate_program(REPOSITORY_ROOT)

        def fail_validation(*_args: object, **_kwargs: object) -> Never:
            """Raise the captured model error at any patched private loader boundary.

            Args:
                *_args: Ignored positional arguments accepted by the patched loader.
                **_kwargs: Ignored keyword arguments accepted by the patched loader.

            Returns:
                No value; every call raises the same captured exception.

            Raises:
                ValidationError: The synthetic invalid boolean failed model validation.
            """
            raise validation_error

        cases: tuple[tuple[ModuleType, str, Callable[[], object], type[ValueError], str], ...] = (
            (
                architecture_module,
                "_validate_repository",
                lambda: architecture_module.validate_repository(REPOSITORY_ROOT),
                ArchitectureGovernanceError,
                "architecture model validation failed",
            ),
            (
                change_policy_module,
                "_load_policy",
                lambda: change_policy_module.load_policy(CHANGE_POLICY_PATH),
                ChangeRiskPolicyError,
                "policy model validation failed",
            ),
            (
                evidence_policy_module,
                "_load_policy",
                lambda: evidence_policy_module.load_policy(Path("policy.toml")),
                EvidenceGovernanceError,
                "policy model validation failed",
            ),
            (
                evidence_manifest_module,
                "_validate_manifest",
                lambda: evidence_manifest_module.validate_manifest(
                    Path("manifest.toml"),
                    expected_commit_sha="5" * 40,
                    change_policy=change_policy,
                ),
                EvidenceGovernanceError,
                "manifest model validation failed",
            ),
            (
                inventory_module,
                "_load_inventory",
                lambda: inventory_module.load_inventory(
                    Path("inventory.toml"), repository_root=REPOSITORY_ROOT
                ),
                InventoryGovernanceError,
                "inventory model validation failed",
            ),
            (
                program_module,
                "_load_roadmap",
                lambda: program_module.load_roadmap(Path("roadmap.md")),
                ProgramGovernanceError,
                "roadmap model validation failed",
            ),
            (
                program_module,
                "_load_program",
                lambda: program_module.load_program(
                    Path("program.toml"), repository_root=REPOSITORY_ROOT
                ),
                ProgramGovernanceError,
                "program model validation failed",
            ),
            (
                program_module,
                "_load_observations",
                lambda: program_module.load_observations(Path("events.jsonl"), program=program),
                ProgramGovernanceError,
                "observation model validation failed",
            ),
            (
                security_module,
                "_load_control_map",
                lambda: security_module.load_control_map(
                    Path("controls.toml"), repository_root=REPOSITORY_ROOT
                ),
                SecurityControlError,
                "control-map model validation failed",
            ),
        )

        for module, private_name, call, expected_error, message in cases:
            monkeypatch.setattr(module, private_name, fail_validation)
            with pytest.raises(expected_error, match=message) as captured:
                call()
            assert captured.value.__cause__ is validation_error
            rendered = str(captured.value)
            assert "errors.pydantic.dev" not in rendered
            assert "not-a-boolean" not in rendered

        monkeypatch.setattr(program_module.RoadmapParser, "_parse_rows", fail_validation)
        with pytest.raises(
            ProgramGovernanceError, match="roadmap model validation failed"
        ) as captured:
            program_module.ProgramRepository(REPOSITORY_ROOT).load_program(
                REPOSITORY_ROOT / "docs/governance/program-governance.toml"
            )
        assert captured.value.__cause__ is validation_error
        assert "not-a-boolean" not in str(captured.value)


class TestBoundaryPathInvariants:
    """Validate repository-relative path invariants on boundary models."""

    def test_repository_relative_paths_are_model_local_invariants(self) -> None:
        """Reject absolute paths and parent traversal within the evidence policy model."""
        base: dict[str, object] = {
            "template_path": Path("docs/template.md"),
            "example_mr_body_path": Path("docs/example.md"),
            "example_manifest_path": Path("evidence/example.toml"),
            "example_commit_sha": "5" * 40,
            "applicable_gates": (),
            "mandatory_package_gates": (),
            "fields": (),
            "package_status": "partial",
            "finding_ids": (),
        }
        for invalid_path in (Path("/absolute/template.md"), Path("docs/../outside.md")):
            invalid_values = base.copy()
            invalid_values["template_path"] = invalid_path
            with pytest.raises(ValidationError, match="inside the repository"):
                EvidencePolicy.model_validate(invalid_values)
