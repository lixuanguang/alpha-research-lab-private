"""Deterministic tests for the ownership and CODEOWNERS policy."""

from __future__ import annotations

# standard library imports
import os
import shutil
import subprocess
from datetime import date
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research.ownership_governance import (
    OwnershipGovernanceError,
    validate_repository,
)
from alpha_research_governance.operating_model import OperatingModelError, load_operating_model

REPOSITORY_ROOT = Path(__file__).parents[2]
REGISTER_PATH = REPOSITORY_ROOT / "docs" / "governance" / "domain-ownership.toml"


@pytest.mark.parametrize(
    ("status", "effective_from", "expected"),
    [
        ("planned", "2026-09-04", "not_required"),
        ("active", "2026-09-06", "not_required"),
        ("inactive", "2026-09-04", "not_required"),
        ("active", "2026-09-04", "pending"),
    ],
)
def test_only_effective_scoped_hires_activate_handover(
    tmp_path: Path, status: str, effective_from: str, expected: str
) -> None:
    """Hiring activates only the joined person's assigned domain, without blocking engineering."""
    _, register, _ = _policy_fixture(tmp_path)
    with register.open("a") as stream:
        stream.write(f'''\n[[role_assignments]]
principal = "@security-hire"
role = "security"
domains = ["security"]
status = "{status}"
effective_from = "{effective_from}"
''')
    model = load_operating_model(register)
    security = model.resolve(
        domain_id="security", operation="implementation", on_date=date(2026, 9, 5)
    )
    platform = model.resolve(
        domain_id="repository_platform", operation="implementation", on_date=date(2026, 9, 5)
    )
    assert security.governance_status == expected
    assert platform.governance_status == "not_required"
    assert platform.assigned_reviewers == ()
    security.require_local_completion(repository_local_status="passed", technical_finding_ids=())


def test_solo_completion_needs_technical_evidence_but_no_external_approval() -> None:
    """The same resolver rejects technical failures and institutional operation shortcuts."""
    model = load_operating_model(REGISTER_PATH)
    rules = model.resolve(
        domain_id="repository_platform", operation="implementation", on_date=date(2026, 9, 5)
    )
    assert rules.profile == "founder"
    assert rules.assigned_reviewers == ()
    rules.require_local_completion(repository_local_status="passed", technical_finding_ids=())
    for result, findings in [("failed", ()), ("passed", ("broken-schema",))]:
        with pytest.raises(OperatingModelError, match="passing repository-local evidence"):
            rules.require_local_completion(
                repository_local_status=result, technical_finding_ids=findings
            )
    for operation in ("release", "activation", "institutional_acceptance"):
        institutional = model.resolve(
            domain_id="repository_platform", operation=operation, on_date=date(2026, 9, 5)
        )
        with pytest.raises(OperatingModelError, match="cannot authorize institutional"):
            institutional.require_local_completion(
                repository_local_status="passed", technical_finding_ids=()
            )


@pytest.mark.parametrize(
    ("principal", "role", "domain", "message"),
    [
        ("@lixuanguang", "security", "security", "founder cannot"),
        ("@new-hire", "invented_role", "security", "not defined"),
        ("@new-hire", "security", "unknown", "unknown assignment domain"),
        ("@organization/team", "security", "security", "individual @user"),
    ],
)
def test_operating_model_rejects_invented_or_misleading_assignments(
    tmp_path: Path, principal: str, role: str, domain: str, message: str
) -> None:
    """A role catalog or duplicate founder identity is not evidence of a new hire."""
    _, register, _ = _policy_fixture(tmp_path)
    with register.open("a") as stream:
        stream.write(f'''\n[[role_assignments]]
principal = "{principal}"
role = "{role}"
domains = ["{domain}"]
status = "active"
effective_from = "2026-09-04"
''')
    with pytest.raises(OperatingModelError, match=message):
        load_operating_model(register)


def _policy_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Copy ownership policy inputs into an isolated temporary repository fixture.

    Args:
        tmp_path: Temporary directory receiving the governance files and CODEOWNERS copy.

    Returns:
        The temporary repository root, ownership register path, and CODEOWNERS path.

    Raises:
        OSError: The fixture directories or copied policy files cannot be created or read.
    """
    governance = tmp_path / "docs" / "governance"
    governance.mkdir(parents=True)
    register = governance / "domain-ownership.toml"
    codeowners = tmp_path / "CODEOWNERS"
    register.write_text(REGISTER_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    codeowners.write_text((REPOSITORY_ROOT / "CODEOWNERS").read_text(encoding="utf-8"))
    return tmp_path, register, codeowners


def test_repository_ownership_policy_is_valid_and_complete() -> None:
    """Validate that the repository register and CODEOWNERS cover all declared domains."""
    domains = validate_repository(REPOSITORY_ROOT)

    assert set(domains) == {
        "assets",
        "data",
        "documentation_governance",
        "platform_runtime",
        "portfolio",
        "repository_platform",
        "research",
        "risk",
        "schemas",
        "security",
        "simulation",
        "trading",
    }


def test_policy_rejects_author_as_independent_reviewer(tmp_path: Path) -> None:
    """Reject a policy that lets the author role serve as an independent reviewer."""
    fixture_repository_root, register, _ = _policy_fixture(tmp_path)
    policy = register.read_text(encoding="utf-8").replace(
        'independent_review_roles = ["data_quality"]',
        'independent_review_roles = ["domain_architecture"]',
        1,
    )
    register.write_text(policy, encoding="utf-8")

    with pytest.raises(OwnershipGovernanceError, match="cannot satisfy independent review"):
        validate_repository(fixture_repository_root, repository_paths=())


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "author_may_satisfy_independent_review = false",
            "author_may_satisfy_independent_review = true",
            "author_may_satisfy_independent_review",
        ),
        ('package_status = "partial"', 'package_status = "validated"', "forge evidence"),
    ],
)
def test_policy_rejects_invalid_control_boundaries(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    """Reject policy changes that permit author independence or claim forge validation."""
    fixture_repository_root, register, _ = _policy_fixture(tmp_path)
    register.write_text(register.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")

    with pytest.raises(OwnershipGovernanceError, match=message):
        validate_repository(fixture_repository_root, repository_paths=())


def test_codeowners_must_match_the_ordered_register(tmp_path: Path) -> None:
    """Reject CODEOWNERS content that diverges from the ordered ownership register."""
    fixture_repository_root, _, codeowners = _policy_fixture(tmp_path)
    codeowners.write_text(
        codeowners.read_text(encoding="utf-8").replace(
            "/risk/ @lixuanguang", "/risk/ @different-owner"
        ),
        encoding="utf-8",
    )

    with pytest.raises(OwnershipGovernanceError, match="exactly match"):
        validate_repository(fixture_repository_root, repository_paths=())


def test_policy_rejects_an_orphaned_repository_path(tmp_path: Path) -> None:
    """Reject a repository path without a matching CODEOWNER pattern."""
    fixture_repository_root, _, _ = _policy_fixture(tmp_path)

    with pytest.raises(OwnershipGovernanceError, match=r"orphan.txt.*no CODEOWNER"):
        validate_repository(fixture_repository_root, repository_paths=("orphan.txt",))


@pytest.mark.integration
def test_pre_commit_rejects_a_staged_unowned_root_path(tmp_path: Path) -> None:
    """Ensure the actual pre-commit ownership hook rejects a staged unowned path.

    The test commits the copied baseline in a temporary Git repository, then stages
    a new unowned root path before invoking the hook.
    """
    fixture_repository_root = tmp_path / "repository"
    fixture_repository_root.mkdir()
    tracked_paths = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    for raw_path in tracked_paths:
        if not raw_path:
            continue
        relative_path = Path(os.fsdecode(raw_path))
        source = REPOSITORY_ROOT / relative_path
        if not source.is_file():
            continue
        destination = fixture_repository_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    subprocess.run(["git", "init", "--quiet"], cwd=fixture_repository_root, check=True)
    subprocess.run(["git", "add", "."], cwd=fixture_repository_root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Ownership Test",
            "-c",
            "user.email=ownership-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "baseline",
        ],
        cwd=fixture_repository_root,
        check=True,
    )
    orphan = fixture_repository_root / "unowned-new-root.txt"
    orphan.write_text("adversarial staged path\n", encoding="utf-8")
    subprocess.run(["git", "add", orphan.name], cwd=fixture_repository_root, check=True)

    completed_process = subprocess.run(
        ["uv", "run", "--frozen", "pre-commit", "run", "ownership-governance"],
        cwd=fixture_repository_root,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PRE_COMMIT_HOME": str(tmp_path / "pre-commit-cache")},
    )

    assert completed_process.returncode == 1
    assert "unowned-new-root.txt: repository path has no CODEOWNER" in (
        completed_process.stdout + completed_process.stderr
    )


def test_policy_rejects_catch_all_path_ownership(tmp_path: Path) -> None:
    """Reject catch-all ownership patterns in the register and CODEOWNERS file."""
    fixture_repository_root, register, codeowners = _policy_fixture(tmp_path)
    register.write_text(
        register.read_text(encoding="utf-8").replace(
            "patterns = [\n",
            'patterns = [\n    "*",\n',
            1,
        ),
        encoding="utf-8",
    )
    codeowners.write_text(
        codeowners.read_text(encoding="utf-8").replace(
            "# Generated manually from docs/governance/domain-ownership.toml; "
            "validated by ownership-check.\n",
            "# Generated manually from docs/governance/domain-ownership.toml; "
            "validated by ownership-check.\n* @lixuanguang\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(OwnershipGovernanceError, match="catch-all CODEOWNERS pattern"):
        validate_repository(fixture_repository_root, repository_paths=("orphan.txt",))


def test_policy_rejects_broader_pattern_after_narrow_security_pattern(
    tmp_path: Path,
) -> None:
    """Reject a broader ownership pattern that follows a narrow security pattern."""
    fixture_repository_root, register, codeowners = _policy_fixture(tmp_path)
    policy = register.read_text(encoding="utf-8")
    policy = policy.replace(
        'patterns = ["/trading/"]',
        'patterns = ["/trading/", "/platform/secrets/"]',
    ).replace(
        'patterns = ["/platform/secrets/", "/secrets/"]',
        'patterns = ["/secrets/"]',
    )
    register.write_text(policy, encoding="utf-8")

    entries = codeowners.read_text(encoding="utf-8")
    entries = entries.replace("/platform/secrets/ @lixuanguang\n", "")
    entries = entries.replace(
        "/trading/ @lixuanguang\n",
        "/trading/ @lixuanguang\n/platform/secrets/ @lixuanguang\n",
    )
    codeowners.write_text(entries, encoding="utf-8")

    with pytest.raises(OwnershipGovernanceError, match="broader CODEOWNERS pattern"):
        validate_repository(fixture_repository_root, repository_paths=())


def test_partial_ownership_policy_requires_registered_findings(tmp_path: Path) -> None:
    """Reject a partial ownership policy that registers an unknown finding."""
    fixture_repository_root, register, _ = _policy_fixture(tmp_path)
    policy = register.read_text(encoding="utf-8").replace(
        'finding_id = "A03-F02"',
        'finding_id = "A03-OTHER"',
    )
    register.write_text(policy, encoding="utf-8")

    with pytest.raises(OwnershipGovernanceError, match="partial status requires findings"):
        validate_repository(fixture_repository_root, repository_paths=())


def test_solo_bootstrap_policy_cannot_claim_validated_status(tmp_path: Path) -> None:
    """Reject solo-bootstrap ownership policy text that claims validated status."""
    fixture_repository_root, register, _ = _policy_fixture(tmp_path)
    policy = register.read_text(encoding="utf-8").split("[[findings]]", maxsplit=1)[0]
    policy = policy.replace(
        'package_status = "partial"',
        'package_status = "validated"\nfindings = []',
    ).replace(
        'verification_status = "pending"\nevidence = ""',
        'verification_status = "verified"\n'
        'evidence = "https://forge.example/protected-main-evidence"',
    )
    register.write_text(policy, encoding="utf-8")

    with pytest.raises(OwnershipGovernanceError, match=r"solo_bootstrap.*cannot claim validated"):
        validate_repository(fixture_repository_root, repository_paths=())
