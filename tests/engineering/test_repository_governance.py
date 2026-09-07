"""Contract tests for the repository charter and boundary register."""

from __future__ import annotations

# standard library imports
import hashlib
import subprocess
import tomllib
from pathlib import Path

# third party library imports
from pydantic import TypeAdapter

REPOSITORY_ROOT = Path(__file__).parents[2]
REGISTER_PATH = REPOSITORY_ROOT / "docs" / "governance" / "system-boundaries.toml"
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
REPOSITORY_CHARTER_OPEN_FINDING_IDS = ["A01-F01", "A01-F02", "A01-F03"]


def _load_register() -> dict[str, object]:
    """Read the repository boundary register and require a TOML-table root.

    Returns:
        Parsed root mapping used by the contract assertions.

    Raises:
        AssertionError: If the TOML root is not a mapping.
        OSError: If the register cannot be read.
        tomllib.TOMLDecodeError: If the register is malformed TOML.
    """
    parsed_register: object = tomllib.loads(REGISTER_PATH.read_text(encoding="utf-8"))
    return TypeAdapter(dict[str, object]).validate_python(parsed_register)


def _require_table(container: dict[str, object], key: str) -> dict[str, object]:
    """Extract a required TOML table from a parsed register mapping.

    Args:
        container: Parsed TOML mapping containing the requested key.
        key: Table key to retrieve.

    Returns:
        The original mapping object, shallowly narrowed for subsequent assertions.

    Raises:
        AssertionError: If the key is absent or does not contain a mapping.
    """
    value = container.get(key)
    assert isinstance(value, dict), f"{key} must be a TOML table"
    return TypeAdapter(dict[str, object]).validate_python(value)


def _require_table_list(container: dict[str, object], key: str) -> list[dict[str, object]]:
    """Extract a required array of TOML tables from a parsed register mapping.

    Args:
        container: Parsed TOML mapping containing the requested key.
        key: Array key to retrieve.

    Returns:
        The original list, shallowly narrowed to mapping elements for subsequent assertions.

    Raises:
        AssertionError: If the key is absent, is not a list, or contains a non-mapping item.
    """
    value = container.get(key)
    assert isinstance(value, list), f"{key} must be an array of TOML tables"
    return TypeAdapter(list[dict[str, object]]).validate_python(value)


def _require_string(container: dict[str, object], key: str) -> str:
    """Extract a present string field from a parsed register mapping; empty text is allowed.

    Args:
        container: Parsed TOML mapping containing the requested key.
        key: String field name to retrieve.

    Returns:
        The original string value, narrowed to ``str`` without trimming or other normalization.

    Raises:
        AssertionError: If the key is absent or its value is not a string.
    """
    value = container.get(key)
    assert isinstance(value, str), f"{key} must be a string"
    return value


def _require_nonempty_string(container: dict[str, object], key: str) -> str:
    """Extract a string field whose stripped value is nonblank from a parsed register mapping.

    Args:
        container: Parsed TOML mapping containing the requested key.
        key: String field name to retrieve.

    Returns:
        The original string value, preserving surrounding whitespace after validation.

    Raises:
        AssertionError: If the field is missing, non-string or blank after stripping.
    """
    value = _require_string(container, key)
    assert value.strip(), f"{key} must not be empty"
    return value


class TestRepositoryGovernanceContracts:
    """Exercise repository boundary register and acceptance-control contracts."""

    def test_every_known_repository_and_external_system_has_one_disposition(self) -> None:
        """Verify unique repository and external-system identities with allowed classifications."""
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

    def test_policy_requires_protected_main_and_tracks_immutable_authority(self) -> None:
        """Verify protected-main policy and the tracked blueprint's current SHA-256 digest."""
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
        blueprint_digest = hashlib.sha256(
            (REPOSITORY_ROOT / blueprint_path).read_bytes()
        ).hexdigest()

        assert tracked_result.returncode == 0
        assert source_authority["tracked_in_git"] is True
        assert source_authority["verification_status"] == "verified"
        assert source_authority["sha256"] == blueprint_digest
        assert _require_string(source_authority, "evidence")

    def test_acceptance_cannot_close_without_inventory_controls_and_approvals(self) -> None:
        """Verify current partial acceptance, governed approval records and exact open findings."""
        register = _load_register()
        approvals = _require_table_list(register, "approvals")
        acceptance = _require_table(register, "acceptance")
        findings = _require_table_list(register, "findings")
        protected_branch = _require_table(register, "protected_branch")
        source_authority = _require_table(register, "source_authority")

        assert register["operating_track"] == "solo_bootstrap"
        assert register["accountable_owner_role"] == "platform"
        assert register["inventory_attestation_owner"] == "platform"
        assert acceptance["package_status"] == "partial"

        assert {_require_string(item, "role") for item in approvals} == REQUIRED_APPROVER_ROLES
        assert all(
            _require_string(item, "status") in {"pending", "approved", "rejected"}
            for item in approvals
        )
        finding_ids = [_require_nonempty_string(finding, "finding_id") for finding in findings]
        assert len(finding_ids) == len(set(finding_ids))
        for finding in findings:
            assert _require_nonempty_string(finding, "owner_role")
            assert _require_nonempty_string(finding, "unavailable_evidence")
            assert _require_nonempty_string(finding, "closure_condition")

        if _require_string(acceptance, "package_status") == "validated":
            assert not findings
            assert acceptance["open_finding_ids"] == []
            assert register["inventory_complete"] is True
            assert source_authority["tracked_in_git"] is True
            assert protected_branch["verification_status"] == "verified"
            assert _require_string(protected_branch, "evidence")
            assert all(
                item["status"] == "approved" and _require_string(item, "evidence")
                for item in approvals
            )
        else:
            assert acceptance["package_status"] == "partial"
            assert finding_ids == REPOSITORY_CHARTER_OPEN_FINDING_IDS
            assert acceptance["open_finding_ids"] == finding_ids
