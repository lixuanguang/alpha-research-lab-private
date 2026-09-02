"""Validate canonical ownership, independent review, and CODEOWNERS coverage."""

from __future__ import annotations

import re
import shutil

# Platform-owned Git discovery boundary; review the suppression at its stated expiry.
import subprocess  # nosec B404  # [owner=platform; rationale=required typed Git boundary; expires=2026-12-31]
import sys
import tomllib
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import cast

_REQUIRED_DOMAINS = {
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
_REQUIRED_OPEN_FINDING_IDS = ("A03-F01", "A03-F02", "A03-F03")
_ROLE = re.compile(r"^[a-z][a-z0-9_]*$")
_PRINCIPAL = re.compile(r"^@[A-Za-z0-9][A-Za-z0-9-]*(?:/[A-Za-z0-9][A-Za-z0-9-]*)?$")


class OwnershipGovernanceError(ValueError):
    """Report one or more deterministic ownership-governance findings."""

    def __init__(self, findings: Sequence[str]) -> None:
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


def _optional_table(container: dict[str, object], key: str) -> dict[str, object] | None:
    value = container.get(key)
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def _optional_table_list(container: dict[str, object], key: str) -> list[dict[str, object]] | None:
    value = container.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        return None
    return cast(list[dict[str, object]], value)


def _optional_string_list(
    container: dict[str, object], key: str, *, context: str, findings: list[str]
) -> list[str]:
    value = container.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        findings.append(f"{context}: {key} must be an array of strings")
        return []
    return cast(list[str], value)


def _load_registry(path: Path) -> dict[str, object]:
    try:
        parsed_document: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise OwnershipGovernanceError([f"{path}: invalid TOML: {error}"]) from error
    if not isinstance(parsed_document, dict):
        raise OwnershipGovernanceError([f"{path}: registry root must be a TOML table"])
    return cast(dict[str, object], parsed_document)


def _parse_codeowners(path: Path) -> tuple[tuple[str, tuple[str, ...]], ...]:
    findings: list[str] = []
    entries: list[tuple[str, tuple[str, ...]]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            findings.append(f"{path}:{line_number}: pattern requires at least one owner")
            continue
        pattern, *owners = parts
        if pattern != "*" and (not pattern.startswith("/") or "*" in pattern):
            findings.append(f"{path}:{line_number}: use only '*' or absolute exact/prefix patterns")
        if any(_PRINCIPAL.fullmatch(owner) is None for owner in owners):
            findings.append(f"{path}:{line_number}: owner principals must use @user or @org/team")
        entries.append((pattern, tuple(owners)))
    if findings:
        raise OwnershipGovernanceError(findings)
    return tuple(entries)


def _matches(pattern: str, repository_path: str) -> bool:
    if pattern == "*":
        return True
    normalized = pattern.removeprefix("/")
    return (
        repository_path.startswith(normalized)
        if pattern.endswith("/")
        else repository_path == normalized
    )


def _prefix_pattern_contains(broader: str, narrower: str) -> bool:
    """Return whether a directory pattern contains a different narrower pattern."""
    if broader == "*" or not broader.endswith("/") or broader == narrower:
        return False
    return narrower.removeprefix("/").startswith(broader.removeprefix("/"))


def _repository_paths(repository_root: Path) -> tuple[str, ...]:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise OwnershipGovernanceError(["git executable is unavailable"])
    # Fixed Git argv without a shell; review the suppression at its stated expiry.
    git_process = subprocess.run(  # nosec B603  # [owner=platform; rationale=argument vector has no shell; expires=2026-12-31]
        [git_executable, "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if git_process.returncode != 0:
        message = git_process.stderr.decode("utf-8", errors="replace").strip()
        raise OwnershipGovernanceError([f"git ls-files failed: {message}"])
    return tuple(path.decode("utf-8") for path in git_process.stdout.split(b"\0") if path)


def validate_repository(
    repository_root: Path, *, repository_paths: Iterable[str] | None = None
) -> tuple[str, ...]:
    """Validate the ownership register, its CODEOWNERS mirror, and repository coverage."""
    resolved_repository_root = repository_root.resolve()
    registry_path = resolved_repository_root / "docs" / "governance" / "domain-ownership.toml"
    registry = _load_registry(registry_path)
    findings: list[str] = []

    expected_scalar_values: dict[str, object] = {
        "schema_version": 1,
        "roadmap_package": "A03",
        "operating_track": "solo_bootstrap",
        "unmatched_path_policy": "reject",
        "author_may_satisfy_independent_review": False,
    }
    for key, expected in expected_scalar_values.items():
        if registry.get(key) != expected:
            findings.append(f"{registry_path}: {key} must be {expected!r}")

    package_status = registry.get("package_status")
    forge = _optional_table(registry, "forge_enforcement")
    if forge is None:
        findings.append(f"{registry_path}: forge_enforcement must be a TOML table")
        forge = {}
    for key in ("require_code_owner_review", "require_approval_after_last_push"):
        if forge.get(key) is not True:
            findings.append(f"{registry_path}: forge_enforcement.{key} must be true")
    if forge.get("protected_branch") != "main":
        findings.append(f"{registry_path}: forge_enforcement.protected_branch must be 'main'")

    open_findings = _optional_table_list(registry, "findings")
    if open_findings is None:
        findings.append(f"{registry_path}: findings must be an array of TOML tables")
        open_findings = []
    if package_status == "validated":
        if forge.get("verification_status") != "verified" or not forge.get("evidence"):
            findings.append(f"{registry_path}: validated status requires verified forge evidence")
        if registry.get("operating_track") == "solo_bootstrap":
            findings.append(
                f"{registry_path}: solo_bootstrap packages cannot claim validated status"
            )
        if open_findings:
            findings.append(f"{registry_path}: validated status cannot retain open findings")
    elif package_status != "partial" or not open_findings:
        findings.append(f"{registry_path}: package_status must be partial with open findings")
    for finding in open_findings:
        if any(
            not isinstance(finding.get(key), str) or not finding.get(key)
            for key in (
                "finding_id",
                "owner_role",
                "unavailable_evidence",
                "closure_condition",
            )
        ):
            findings.append(
                f"{registry_path}: each finding requires an id, owner, evidence, and closure"
            )
    finding_ids = tuple(
        cast(str, finding["finding_id"])
        for finding in open_findings
        if isinstance(finding.get("finding_id"), str)
    )
    if package_status == "partial" and finding_ids != _REQUIRED_OPEN_FINDING_IDS:
        findings.append(
            f"{registry_path}: partial status requires findings "
            f"{list(_REQUIRED_OPEN_FINDING_IDS)!r}"
        )

    domains = _optional_table_list(registry, "domains")
    if domains is None:
        findings.append(f"{registry_path}: domains must be an array of TOML tables")
        domains = []
    domain_ids: list[str] = []
    expected_entries: list[tuple[str, tuple[str, ...]]] = []
    seen_patterns: set[str] = set()
    for index, domain in enumerate(domains, start=1):
        context = f"{registry_path}: domain {index}"
        domain_id = domain.get("domain_id")
        accountable_role = domain.get("accountable_role")
        if not isinstance(domain_id, str) or _ROLE.fullmatch(domain_id) is None:
            findings.append(f"{context}: domain_id must be lower_snake_case")
            continue
        domain_ids.append(domain_id)
        context = f"{registry_path}: domain {domain_id}"
        if not isinstance(accountable_role, str) or _ROLE.fullmatch(accountable_role) is None:
            findings.append(f"{context}: accountable_role must be lower_snake_case")
            accountable_role = ""
        patterns = _optional_string_list(domain, "patterns", context=context, findings=findings)
        codeowners = _optional_string_list(domain, "codeowners", context=context, findings=findings)
        required = _optional_string_list(
            domain, "required_review_roles", context=context, findings=findings
        )
        independent = _optional_string_list(
            domain, "independent_review_roles", context=context, findings=findings
        )
        escalation = _optional_string_list(
            domain, "escalation_roles", context=context, findings=findings
        )
        if not patterns or not codeowners or not escalation:
            findings.append(
                f"{context}: patterns, codeowners, and escalation_roles cannot be empty"
            )
        if "*" in patterns:
            findings.append(
                f"{context}: catch-all CODEOWNERS pattern '*' is incompatible with "
                "unmatched_path_policy 'reject'"
            )
        if accountable_role not in required:
            findings.append(f"{context}: accountable_role must be a required reviewer")
        if not set(independent) <= set(required):
            findings.append(f"{context}: independent reviewers must also be required reviewers")
        if accountable_role in independent:
            findings.append(f"{context}: accountable_role cannot satisfy independent review")
        if any(_ROLE.fullmatch(role) is None for role in required + independent + escalation):
            findings.append(f"{context}: review and escalation roles must be lower_snake_case")
        if any(_PRINCIPAL.fullmatch(owner) is None for owner in codeowners):
            findings.append(f"{context}: codeowners must use @user or @org/team principals")
        for pattern in patterns:
            if pattern in seen_patterns:
                findings.append(f"{context}: duplicate CODEOWNERS pattern {pattern!r}")
            seen_patterns.add(pattern)
            expected_entries.append((pattern, tuple(codeowners)))

    ordered_patterns = tuple(pattern for pattern, _ in expected_entries)
    for narrower_index, narrower in enumerate(ordered_patterns):
        for broader in ordered_patterns[narrower_index + 1 :]:
            if _prefix_pattern_contains(broader, narrower):
                findings.append(
                    f"{registry_path}: broader CODEOWNERS pattern {broader!r} must precede "
                    f"narrower pattern {narrower!r} so last-match routing stays fail-closed"
                )

    domain_set = set(domain_ids)
    if domain_set != _REQUIRED_DOMAINS or len(domain_ids) != len(domain_set):
        findings.append(f"{registry_path}: domains must be exactly {sorted(_REQUIRED_DOMAINS)!r}")

    codeowners_value = registry.get("codeowners_path")
    if not isinstance(codeowners_value, str) or not codeowners_value:
        findings.append(f"{registry_path}: codeowners_path must be a non-empty string")
    else:
        codeowners_path = (resolved_repository_root / codeowners_value).resolve()
        try:
            codeowners_path.relative_to(resolved_repository_root)
            actual_entries = _parse_codeowners(codeowners_path)
        except ValueError:
            findings.append(f"{registry_path}: codeowners_path must stay inside the repository")
            actual_entries = ()
        except OwnershipGovernanceError as error:
            findings.extend(error.findings)
            actual_entries = ()
        if actual_entries != tuple(expected_entries):
            findings.append(f"{codeowners_path}: entries must exactly match the ordered register")
        paths = (
            tuple(repository_paths)
            if repository_paths is not None
            else _repository_paths(resolved_repository_root)
        )
        actual_patterns = tuple(pattern for pattern, _ in actual_entries)
        for path in paths:
            if not any(_matches(pattern, path) for pattern in actual_patterns):
                findings.append(f"{path}: repository path has no CODEOWNER")

    if findings:
        raise OwnershipGovernanceError(findings)
    return tuple(domain_ids)


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the ownership-governance checker from the command line."""
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    if len(cli_arguments) > 1:
        print(
            "usage: python -m alpha_research_governance.ownership_governance [repository-root]",
            file=sys.stderr,
        )
        return 2
    repository_root = Path(cli_arguments[0]) if cli_arguments else Path.cwd()
    try:
        domains = validate_repository(repository_root)
    except (OwnershipGovernanceError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Ownership governance passed for {len(domains)} domains.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
