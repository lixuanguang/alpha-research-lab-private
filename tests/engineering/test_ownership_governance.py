"""Deterministic tests for the A03 ownership and CODEOWNERS policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from alpha_research.ownership_governance import (
    OwnershipGovernanceError,
    main,
    validate_repository,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
REGISTER_PATH = REPOSITORY_ROOT / "docs" / "governance" / "domain-ownership.toml"


def _policy_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    governance = tmp_path / "docs" / "governance"
    governance.mkdir(parents=True)
    register = governance / "domain-ownership.toml"
    codeowners = tmp_path / "CODEOWNERS"
    register.write_text(REGISTER_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    codeowners.write_text((REPOSITORY_ROOT / "CODEOWNERS").read_text(encoding="utf-8"))
    return tmp_path, register, codeowners


def test_repository_ownership_policy_is_valid_and_complete() -> None:
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
    root, register, _ = _policy_fixture(tmp_path)
    policy = register.read_text(encoding="utf-8").replace(
        'independent_review_roles = ["data_quality"]',
        'independent_review_roles = ["domain_architecture"]',
        1,
    )
    register.write_text(policy, encoding="utf-8")

    with pytest.raises(OwnershipGovernanceError, match="cannot satisfy independent review"):
        validate_repository(root, repository_paths=())


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "author_may_satisfy_independent_review = false",
            "author_may_satisfy_independent_review = true",
            "author_may_satisfy_independent_review",
        ),
        ('domain_id = "assets"', 'domain_id = "unowned_domain"', "domains must be exactly"),
        ('package_status = "partial"', 'package_status = "validated"', "forge evidence"),
    ],
)
def test_policy_rejects_invalid_control_boundaries(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    root, register, _ = _policy_fixture(tmp_path)
    register.write_text(register.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")

    with pytest.raises(OwnershipGovernanceError, match=message):
        validate_repository(root, repository_paths=())


def test_codeowners_must_match_the_ordered_register(tmp_path: Path) -> None:
    root, _, codeowners = _policy_fixture(tmp_path)
    codeowners.write_text(
        codeowners.read_text(encoding="utf-8").replace(
            "/risk/ @lixuanguang", "/risk/ @different-owner"
        ),
        encoding="utf-8",
    )

    with pytest.raises(OwnershipGovernanceError, match="exactly match"):
        validate_repository(root, repository_paths=())


def test_policy_rejects_an_orphaned_repository_path(tmp_path: Path) -> None:
    root, register, codeowners = _policy_fixture(tmp_path)
    register.write_text(
        register.read_text(encoding="utf-8").replace(
            'patterns = ["*", "/.github/", "/core/", "/src/", "/tests/"]',
            'patterns = ["/.github/", "/core/", "/src/", "/tests/"]',
        ),
        encoding="utf-8",
    )
    codeowners.write_text(
        codeowners.read_text(encoding="utf-8").replace("* @lixuanguang\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(OwnershipGovernanceError, match="orphan.txt.*no CODEOWNER"):
        validate_repository(root, repository_paths=("orphan.txt",))


def test_command_fails_closed_when_policy_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path)]) == 1
    assert "domain-ownership.toml" in capsys.readouterr().err
