"""Runtime-validation contracts shared by immutable boundary models."""

from __future__ import annotations

# standard library imports
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Never

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


def _change_values() -> dict[str, object]:
    return {
        "capital_at_risk": False,
        "blast_radius": "documentation_only",
        "data_model_materiality": "none",
        "security_privilege": "none",
        "reversibility": "immediate",
    }


def _observation_values() -> dict[str, object]:
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


def test_strict_primitives_enums_and_unknown_fields_fail() -> None:
    invalid_values = (
        {**_change_values(), "capital_at_risk": 1},
        {**_change_values(), "declared_class": "R2"},
        {**_change_values(), "unknown_field": "rejected"},
    )
    for values in invalid_values:
        with pytest.raises(ValidationError):
            ChangeRiskInput.model_validate(values)


def test_missing_required_and_invalid_nested_models_fail() -> None:
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


def test_strict_paths_dates_datetimes_tuples_and_frozensets_fail() -> None:
    with pytest.raises(ValidationError):
        EvidencePolicy.model_validate(
            {
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
        )
    with pytest.raises(ValidationError):
        AuthoritySource.model_validate(
            {
                "source_id": "source",
                "jurisdiction_id": "GLOBAL",
                "authority": "authority",
                "title": "title",
                "citation": "citation",
                "source_class": "framework",
                "url": "https://example.com",
                "last_verified_on": "2026-08-30",
            }
        )
    with pytest.raises(ValidationError):
        PackageNode.model_validate(
            {
                "package_id": "A01",
                "wave": "A",
                "objective": "objective",
                "dependencies": [],
                "any_of_dependency_groups": (),
            }
        )
    with pytest.raises(ValidationError):
        ReviewApproval.model_validate({"reviewer_id": "reviewer", "roles": ["code_owner"]})
    with pytest.raises(ValidationError):
        MetricObservation.model_validate(
            {**_observation_values(), "window_start": "2026-08-30T00:00:00Z"}
        )
    with pytest.raises(ValidationError, match="UTC datetimes"):
        MetricObservation.model_validate(
            {**_observation_values(), "window_start": datetime(2026, 8, 30)}
        )
    with pytest.raises(ValidationError, match="must be positive"):
        MetricObservation.model_validate(
            {
                **_observation_values(),
                "window_end": datetime(2026, 8, 29, tzinfo=UTC),
            }
        )
    with pytest.raises(ValidationError, match="must be a float"):
        MetricObservation.model_validate({**_observation_values(), "numerator": 1})
    with pytest.raises(ValidationError):
        MetricObservation.model_validate({**_observation_values(), "numerator": float("nan")})


def test_json_mode_preserves_boundary_shapes() -> None:
    change = ChangeRiskInput.model_validate({**_change_values(), "declared_class": RiskClass.R2})
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

    assert change.model_dump(mode="json")["declared_class"] == "R2"
    assert approval.model_dump(mode="json")["roles"] == ["code_owner", "security"]
    assert policy.model_dump(mode="json")["template_path"] == "docs/template.md"


def _captured_validation_error() -> ValidationError:
    with pytest.raises(ValidationError) as captured:
        ChangeRiskInput.model_validate({**_change_values(), "capital_at_risk": "not-a-boolean"})
    return captured.value


def test_public_loaders_translate_validation_errors_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_error = _captured_validation_error()
    change_policy = load_change_policy(CHANGE_POLICY_PATH)
    program = validate_program(REPOSITORY_ROOT)

    def fail_validation(*_args: object, **_kwargs: object) -> Never:
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


def test_repository_relative_paths_are_model_local_invariants() -> None:
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
        with pytest.raises(ValidationError, match="inside the repository"):
            EvidencePolicy.model_validate({**base, "template_path": invalid_path})
