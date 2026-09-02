"""Select changed Bazel owners and their reverse dependencies."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree  # nosec B405  # [owner=platform; rationale=bounded Bazel XML rejects declarations and entities; expires=2027-02-28]
from collections.abc import Mapping
from pathlib import PurePosixPath

from alpha_research_governance.ci_policy.models import (
    AffectedSelection,
    ChangedPath,
    CIPolicy,
    CIPolicyError,
)

_TARGET_LABEL = re.compile(r"^//(?:[A-Za-z0-9._/-]*)(?::[A-Za-z0-9._/+@=-]+)?$")
_STATUS = re.compile(r"^(?:[ACDMTUXB]|[RC][0-9]{1,3})$")
_MAXIMUM_QUERY_XML_BYTES = 16 * 1024 * 1024


def normalize_changed_paths(records: tuple[tuple[str, str], ...]) -> tuple[ChangedPath, ...]:
    """Validate and deterministically normalize Git name-status records."""
    normalized: list[ChangedPath] = []
    for status, raw_path in records:
        path = PurePosixPath(raw_path)
        if _STATUS.fullmatch(status) is None or (
            status.startswith(("R", "C")) and int(status[1:]) > 100
        ):
            raise CIPolicyError([f"unsupported Git change status: {status}"])
        if (
            path.is_absolute()
            or path.as_posix() != raw_path
            or not path.parts
            or ".." in path.parts
            or "\0" in raw_path
        ):
            raise CIPolicyError([f"changed path is not repository-relative: {raw_path}"])
        normalized.append(ChangedPath(status=status, path=raw_path))
    unique = {(item.status, item.path): item for item in normalized}
    return tuple(unique[key] for key in sorted(unique))


def parse_git_name_status(payload: bytes, *, maximum_changed_files: int) -> tuple[ChangedPath, ...]:
    """Parse ``git diff --name-status -z`` output, retaining both rename paths."""
    fields = payload.decode("utf-8", errors="strict").split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    records: list[tuple[str, str]] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        path_count = 2 if status.startswith(("R", "C")) else 1
        if index + path_count > len(fields):
            raise CIPolicyError(["Git name-status output is truncated"])
        for path in fields[index : index + path_count]:
            records.append((status, path))
        index += path_count
    if len(records) > maximum_changed_files:
        raise CIPolicyError(
            [f"changed path count {len(records)} exceeds limit {maximum_changed_files}"]
        )
    return normalize_changed_paths(tuple(records))


def _repository_path_from_bazel_source_label(label: str) -> str | None:
    if not label.startswith("//") or label.endswith(":BUILD"):
        return None
    package_and_name = label[2:]
    if ":" not in package_and_name:
        return package_and_name
    package, name = package_and_name.split(":", 1)
    if not package:
        return name
    return f"{package}/{name}"


def bazel_source_owners_from_query_xml(payload: str) -> dict[str, tuple[str, ...]]:
    """Build a source-to-rule owner map from Bazel XML query output."""
    encoded = payload.encode("utf-8")
    if len(encoded) > _MAXIMUM_QUERY_XML_BYTES:
        raise CIPolicyError(["Bazel query XML exceeds the governed byte limit"])
    lowered = encoded.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise CIPolicyError(["Bazel query XML cannot contain declarations or entities"])
    try:
        root = ElementTree.fromstring(payload)  # nosec B314  # [owner=platform; rationale=bounded input rejects DTD and entity declarations; expires=2027-02-28]
    except ElementTree.ParseError as error:
        raise CIPolicyError([f"invalid Bazel query XML: {error}"]) from error
    owners: dict[str, set[str]] = {}
    for rule in root.findall("rule"):
        target = rule.get("name", "")
        if _TARGET_LABEL.fullmatch(target) is None:
            raise CIPolicyError([f"invalid Bazel target label in query output: {target}"])
        for source in rule.findall("./list[@name='srcs']/label"):
            source_path = _repository_path_from_bazel_source_label(source.get("value", ""))
            if source_path is not None:
                owners.setdefault(source_path, set()).add(target)
    return {path: tuple(sorted(targets)) for path, targets in sorted(owners.items())}


def select_bazel_owners_for_changes(
    changes: tuple[ChangedPath, ...],
    owner_map: Mapping[str, tuple[str, ...]],
    policy: CIPolicy,
) -> AffectedSelection:
    """Select direct owners or broaden safely when a path cannot be resolved."""
    paths = tuple(sorted({item.path for item in changes}))
    if not paths:
        return AffectedSelection(
            changed_paths=(),
            owner_targets=(),
            build_targets=(),
            test_targets=(),
            force_full=False,
            reason="no_changed_paths",
        )
    if any(
        path == foundational or path.startswith(f"{foundational}/")
        for path in paths
        for foundational in policy.foundational_paths
    ):
        return AffectedSelection(
            changed_paths=paths,
            owner_targets=(),
            build_targets=("//...",),
            test_targets=("//...",),
            force_full=True,
            reason="foundational_change",
        )
    unresolved = tuple(path for path in paths if path not in owner_map)
    if unresolved:
        return AffectedSelection(
            changed_paths=paths,
            owner_targets=(),
            build_targets=("//...",),
            test_targets=("//...",),
            force_full=True,
            reason=f"unowned_paths:{','.join(unresolved)}",
        )
    owners = tuple(sorted({owner for path in paths for owner in owner_map[path]}))
    return AffectedSelection(
        changed_paths=paths,
        owner_targets=owners,
        build_targets=(),
        test_targets=(),
        force_full=False,
        reason="bazel_owner_rdeps",
    )


def attach_bazel_reverse_dependencies(
    selection: AffectedSelection,
    *,
    build_targets: tuple[str, ...],
    test_targets: tuple[str, ...],
) -> AffectedSelection:
    """Attach validated reverse-dependency query results to an owner selection."""
    if selection.force_full or not selection.owner_targets:
        return selection
    invalid = [
        target
        for target in (*build_targets, *test_targets)
        if _TARGET_LABEL.fullmatch(target) is None
    ]
    if invalid:
        raise CIPolicyError([f"invalid reverse-dependency target labels: {invalid}"])
    if not build_targets:
        raise CIPolicyError(["Bazel reverse-dependency query returned no build targets"])
    return selection.model_copy(
        update={
            "build_targets": tuple(sorted(set(build_targets))),
            "test_targets": tuple(sorted(set(test_targets))),
        }
    )
