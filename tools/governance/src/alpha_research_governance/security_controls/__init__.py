"""Canonical threat and regulatory control-map API and command."""

from __future__ import annotations

# standard library imports
import json
import sys
from collections.abc import Sequence
from pathlib import Path

# project library imports
from alpha_research_governance.security_controls.models import (
    AuthoritySource,
    EvidenceSource,
    JurisdictionProfile,
    ProtectedAsset,
    RegulatoryMapping,
    SecurityControl,
    SecurityControlError,
    SecurityControlMap,
    ThreatScenario,
    TrustBoundary,
)
from alpha_research_governance.security_controls.registry import (
    APPLICABLE_GATE_IDS,
    JURISDICTION_IDS,
    SECURITY_CONTROL_DEPENDENCY_PACKAGE_IDS,
    THREAT_CATEGORIES,
    SecurityControlMapLoader,
    load_control_map,
    validate_repository,
)

__all__ = [
    "APPLICABLE_GATE_IDS",
    "JURISDICTION_IDS",
    "SECURITY_CONTROL_DEPENDENCY_PACKAGE_IDS",
    "THREAT_CATEGORIES",
    "AuthoritySource",
    "EvidenceSource",
    "JurisdictionProfile",
    "ProtectedAsset",
    "RegulatoryMapping",
    "SecurityControl",
    "SecurityControlError",
    "SecurityControlMap",
    "SecurityControlMapLoader",
    "ThreatScenario",
    "TrustBoundary",
    "load_control_map",
    "main",
    "validate_repository",
]

_USAGE = (
    "usage: python -m alpha_research_governance.security_controls [repository-root] [--json] "
    "[--threat-category CATEGORY | --control-owner-role ROLE | --jurisdiction ID]"
)


def _parse_arguments(arguments: Sequence[str]) -> tuple[Path, bool, dict[str, str]]:
    """Parse security-control CLI tokens and derive the requested output mode.

    Args:
        arguments: Ordered command-line tokens containing at most one repository root,
            the ``--json`` flag, and at most one selection filter.

    Returns:
        A tuple containing the selected repository root (defaulting to the current
        working directory), whether JSON output is required, and the supplied exact
        ``--threat-category``, ``--control-owner-role`` or ``--jurisdiction`` filter.

    Raises:
        SecurityControlError: If an option is duplicated or unknown, a value is missing,
            more than one selection filter is supplied, or more than one positional
            repository root is supplied. Filter values are retained for ``main`` to
            validate where a registry of allowed values exists.
    """
    repository_root: Path | None = None
    should_emit_json = False
    filters: dict[str, str] = {}
    index = 0
    allowed = {"--control-owner-role", "--jurisdiction", "--threat-category"}
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--json":
            if should_emit_json:
                raise SecurityControlError([_USAGE])
            should_emit_json = True
            index += 1
            continue
        if argument in allowed:
            if filters or index + 1 >= len(arguments) or arguments[index + 1].startswith("--"):
                raise SecurityControlError([_USAGE])
            filters[argument] = arguments[index + 1]
            index += 2
            continue
        if argument.startswith("--") or repository_root is not None:
            raise SecurityControlError([_USAGE])
        repository_root = Path(argument)
        index += 1
    return (
        Path.cwd() if repository_root is None else repository_root,
        should_emit_json or bool(filters),
        filters,
    )


def _build_security_control_payload(
    control_map: SecurityControlMap, filters: dict[str, str]
) -> dict[str, object]:
    """Build the stable JSON payload for the validated control-map selection.

    Args:
        control_map: Validated map whose records and metadata supply the payload.
        filters: Parsed selection mapping containing at most one supported filter.

    Returns:
        A fresh JSON-compatible mapping containing map metadata and all assets and
        boundaries, with threats, controls, jurisdictions and regulatory mappings
        selected by their exact filter. Authority sources are restricted to sources
        referenced by the selected jurisdiction profiles; tuple fields become lists.
    """
    category = filters.get("--threat-category")
    owner_role = filters.get("--control-owner-role")
    jurisdiction_id = filters.get("--jurisdiction")
    threats = control_map.threats if category is None else control_map.threats_by_category(category)
    controls = (
        control_map.controls if owner_role is None else control_map.controls_by_owner(owner_role)
    )
    jurisdictions = tuple(
        item
        for item in control_map.jurisdictions
        if jurisdiction_id is None or item.jurisdiction_id == jurisdiction_id
    )
    mappings = (
        control_map.regulatory_mappings
        if jurisdiction_id is None
        else control_map.mappings_for_jurisdiction(jurisdiction_id)
    )
    source_ids = {source_id for item in jurisdictions for source_id in item.source_ids}
    authority_sources = tuple(
        item for item in control_map.authority_sources if item.source_id in source_ids
    )
    return {
        "accountable_owner_role": control_map.accountable_owner_role,
        "applicable_gate_ids": list(control_map.applicable_gate_ids),
        "as_of_date": control_map.as_of_date.isoformat(),
        "assets": [item.as_json() for item in control_map.assets],
        "boundaries": [item.as_json() for item in control_map.boundaries],
        "controls": [item.as_json() for item in controls],
        "dependency_package_ids": list(control_map.dependency_package_ids),
        "evidence_sources": [item.as_json() for item in control_map.evidence_sources],
        "jurisdictions": [item.as_json() for item in jurisdictions],
        "open_finding_ids": list(control_map.finding_ids),
        "package_status": control_map.package_status,
        "risk_class": control_map.risk_class,
        "roadmap_package": control_map.roadmap_package,
        "schema_version": control_map.schema_version,
        "operating_track": control_map.operating_track,
        "regulatory_mappings": [item.as_json() for item in mappings],
        "sources": [item.as_json() for item in authority_sources],
        "threats": [item.as_json() for item in threats],
    }


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate security governance or emit a deterministic filtered control map.

    The repository root defaults to ``Path.cwd()``. The command reads the authoritative
    control map, ownership register and local evidence, writes no files, and launches no
    subprocesses. With no ``--json`` flag and no filter it prints a human summary. The
    explicit flag or any selection filter selects JSON output; category, owner and
    jurisdiction matching is exact, and the payload preserves stored order while
    restricting threats, controls, or jurisdiction-linked mappings as requested. Parser
    errors are caught as status ``2``; expected ``SecurityControlError`` and ``OSError``
    failures during validation are caught as status ``1``.

    Args:
        arguments: Optional command-line tokens. ``None`` consumes ``sys.argv[1:]``;
            otherwise provide an optional repository root, ``--json``, and at most one
            ``--threat-category CATEGORY``, ``--control-owner-role ROLE`` or
            ``--jurisdiction ID`` filter.

    Returns:
        ``0`` after printing the human validation summary or compact, sorted JSON;
        ``1`` after printing an unsupported category, jurisdiction, governance failure
        or filesystem failure to standard error; or ``2`` after printing the exact usage
        for malformed argument syntax.

    Raises:
        OSError: If resolving the default working directory or writing output fails
            outside the guarded parsing and validation blocks.
        UnicodeDecodeError: If a repository input read as UTF-8 has invalid encoding.
    """
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    try:
        repository_root, should_emit_json, filters = _parse_arguments(cli_arguments)
    except SecurityControlError as error:
        print(error, file=sys.stderr)
        return 2
    category = filters.get("--threat-category")
    jurisdiction_id = filters.get("--jurisdiction")
    if category is not None and category not in THREAT_CATEGORIES:
        print(f"unsupported threat category {category!r}", file=sys.stderr)
        return 1
    if jurisdiction_id is not None and jurisdiction_id not in JURISDICTION_IDS:
        print(f"unsupported jurisdiction {jurisdiction_id!r}", file=sys.stderr)
        return 1
    try:
        control_map = validate_repository(repository_root)
    except (OSError, SecurityControlError) as error:
        print(error, file=sys.stderr)
        return 1
    if should_emit_json:
        print(
            json.dumps(
                _build_security_control_payload(control_map, filters),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    else:
        print(
            f"Security control map passed for {len(control_map.threats)} threats, "
            f"{len(control_map.controls)} controls, and "
            f"{len(control_map.jurisdictions)} jurisdiction profiles; "
            f"package status is {control_map.package_status}."
        )
    return 0
