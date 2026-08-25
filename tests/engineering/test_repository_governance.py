"""Contract tests for the A01 repository charter and boundary register."""

from __future__ import annotations

import hashlib
import subprocess
import tomllib
from pathlib import Path
from typing import cast

REPOSITORY_ROOT = Path(__file__).parents[2]
CHARTER_PATH = REPOSITORY_ROOT / "docs" / "governance" / "repository-charter.md"
REGISTER_PATH = REPOSITORY_ROOT / "docs" / "governance" / "system-boundaries.toml"
PLATFORM_README_PATH = REPOSITORY_ROOT / "docs" / "README.md"
ROADMAP_PATH = REPOSITORY_ROOT / "docs" / "roadmap" / "README.md"
ALLOWED_CLASSIFICATIONS = {"migrate", "bridge", "retain"}
REQUIRED_APPROVER_ROLES = {
    "platform",
    "quantitative_research",
    "trading_engineering",
    "risk",
    "sre",
    "security",
    "compliance",
}


def _load_register() -> dict[str, object]:
    parsed: object = tomllib.loads(REGISTER_PATH.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return cast(dict[str, object], parsed)


def _require_table(container: dict[str, object], key: str) -> dict[str, object]:
    value = container.get(key)
    assert isinstance(value, dict), f"{key} must be a TOML table"
    return cast(dict[str, object], value)


def _require_table_list(container: dict[str, object], key: str) -> list[dict[str, object]]:
    value = container.get(key)
    assert isinstance(value, list), f"{key} must be an array of TOML tables"
    assert all(isinstance(item, dict) for item in value)
    return cast(list[dict[str, object]], value)


def _require_string(container: dict[str, object], key: str) -> str:
    value = container.get(key)
    assert isinstance(value, str), f"{key} must be a string"
    return value


def test_charter_contains_every_a01_principal_artifact() -> None:
    charter = CHARTER_PATH.read_text(encoding="utf-8")
    normalized_charter = " ".join(charter.split())

    for heading in (
        "## Charter",
        "## Scope",
        "## Systems outside the monorepo",
        "## Repository disposition rules",
        "## Naming conventions",
        "## Source governance policy",
        "## Non-goals",
    ):
        assert heading in charter

    assert "source and governance boundary, not one deployable" in normalized_charter
    assert "No direct push to `main` is allowed" in charter
    assert all(classification in charter for classification in ALLOWED_CLASSIFICATIONS)


def test_solo_bootstrap_track_cannot_claim_institutional_acceptance() -> None:
    platform_readme = PLATFORM_README_PATH.read_text(encoding="utf-8")
    roadmap = ROADMAP_PATH.read_text(encoding="utf-8")

    assert "## Current operating mode: solo bootstrap" in platform_readme
    assert "## Solo-bootstrap execution overlay" in roadmap
    assert "does not mark missing approvals as passed" in platform_readme
    assert "package status remains `partial`" in roadmap
    assert "must not manufacture independent" in roadmap
    assert "Solo bootstrap never permits production credentials" in roadmap
    assert "Provisional work\nis not grandfathered" in roadmap


def test_every_known_repository_and_external_system_has_one_disposition() -> None:
    register = _load_register()
    repositories = _require_table_list(register, "repositories")
    external_systems = _require_table_list(register, "external_systems")

    assert register["schema_version"] == 1
    assert register["roadmap_package"] == "A01"

    repository_ids = [_require_string(item, "repository_id") for item in repositories]
    assert repository_ids == ["alpha-research-lab-private"]
    assert len(repository_ids) == len(set(repository_ids))

    for item in repositories + external_systems:
        assert _require_string(item, "classification") in ALLOWED_CLASSIFICATIONS
        assert _require_string(item, "owner_role")

    system_ids = [_require_string(item, "system_id") for item in external_systems]
    assert system_ids
    assert len(system_ids) == len(set(system_ids))


def test_policy_requires_protected_main_and_tracks_immutable_authority() -> None:
    register = _load_register()
    protected_branch = _require_table(register, "protected_branch")
    source_authority = _require_table(register, "source_authority")

    assert protected_branch == {
        "branch": "main",
        "direct_push_allowed": False,
        "verification_status": "pending",
        "evidence": "",
    }

    blueprint_path = _require_string(source_authority, "blueprint_path")
    tracked_result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", blueprint_path],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    blueprint_digest = hashlib.sha256((REPOSITORY_ROOT / blueprint_path).read_bytes()).hexdigest()

    assert tracked_result.returncode == 0
    assert source_authority["tracked_in_git"] is True
    assert source_authority["verification_status"] == "verified"
    assert source_authority["sha256"] == blueprint_digest
    assert _require_string(source_authority, "evidence")


def test_acceptance_cannot_close_without_inventory_controls_and_approvals() -> None:
    register = _load_register()
    approvals = _require_table_list(register, "approvals")
    acceptance = _require_table(register, "acceptance")
    protected_branch = _require_table(register, "protected_branch")
    source_authority = _require_table(register, "source_authority")

    assert {_require_string(item, "role") for item in approvals} == REQUIRED_APPROVER_ROLES
    assert all(
        _require_string(item, "status") in {"pending", "approved", "rejected"} for item in approvals
    )

    if _require_string(acceptance, "package_status") == "validated":
        assert register["inventory_complete"] is True
        assert source_authority["tracked_in_git"] is True
        assert protected_branch["verification_status"] == "verified"
        assert _require_string(protected_branch, "evidence")
        assert all(
            item["status"] == "approved" and _require_string(item, "evidence") for item in approvals
        )
    else:
        assert acceptance["package_status"] == "partial"
        assert acceptance["open_findings"]
