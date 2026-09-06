"""Select changed Bazel owners and their reverse dependencies."""

from __future__ import annotations

# standard library imports
import re
import xml.etree.ElementTree as ElementTree  # nosec B405  # [owner=platform; rationale=bounded Bazel XML rejects declarations and entities; expires=2027-02-28]
from collections.abc import Mapping
from pathlib import PurePosixPath

# project library imports
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
    """Validate Git name-status records and return sorted unique records.

    Args:
        records: Git status/path pairs. One-letter statuses are ``A``, ``D``,
            ``M``, ``T``, ``U``, ``X`` and ``B``; rename and copy statuses are
            ``R`` or ``C`` followed by one to three ASCII digits, with scores
            at most 100 and zero-padding accepted. A bare ``C`` passes the regex
            but raises the documented ``ValueError`` during conversion.

    Returns:
        ``ChangedPath`` records deduplicated by ``(status, path)`` and sorted
        lexically by that pair. Paths are retained after lexical validation;
        no filesystem access or path resolution occurs.

    Raises:
        CIPolicyError: If a status is unsupported, a rename or copy score is
            greater than 100, or a path is absolute, non-canonical under
            ``PurePosixPath``, empty, contains a ``..`` component or contains a
            NUL character.
        ValueError: If a bare ``C`` status reaches the existing similarity-score
            conversion and attempts ``int("")``.
    """
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
    """Parse NUL-delimited Git name-status output into changed paths.

    Args:
        payload: UTF-8 bytes from ``git diff --name-status -z``. A final NUL is
            optional. A token beginning with ``R`` or ``C`` consumes two paths.
        maximum_changed_files: Inclusive limit for expanded path records,
            counted before normalization and deduplication. The value is used
            as supplied; this function does not validate the bound itself.

    Returns:
        The sorted, unique ``ChangedPath`` records returned by
        ``normalize_changed_paths``. Both paths from a rename or copy are
        retained before that normalization.

    Raises:
        CIPolicyError: If the payload has a truncated record, exceeds the
            expanded path-count limit, or contains a status or path rejected by
            ``normalize_changed_paths``. A bare ``C`` with too few paths is
            reported as truncated.
        UnicodeDecodeError: If ``payload`` is not valid UTF-8.
        ValueError: If a bare ``C`` has two paths and reaches the existing
            similarity-score conversion, which attempts ``int("")``.
    """
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
    """Derive a repository path from a ``//`` source label when applicable.

    The leading ``//`` is stripped. A colonless remainder is returned unchanged;
    an empty package returns the name (for example, ``//:name`` becomes
    ``name``), and other labels become ``package/name``. Labels without a
    leading ``//`` or ending in ``:BUILD`` return ``None``. No label-syntax or
    repository-containment validation is performed.
    """
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
    """Build a deterministic source-to-rule map from Bazel query XML.

    Args:
        payload: Bazel query XML text. Direct ``rule`` children and their direct
            ``srcs`` labels are inspected; source labels are converted without
            additional syntax or repository-path validation. The root tag is not
            checked.

    Returns:
        A mapping from derived repository paths to sorted unique owner labels,
        with both the mapping keys and owner tuples in lexical order. Labels
        without a leading ``//`` or ending in ``:BUILD`` are skipped by the
        source-label helper.

    Raises:
        CIPolicyError: If the UTF-8 encoded payload exceeds 16 MiB, contains
            ``<!doctype`` or ``<!entity`` anywhere (case-insensitively), is
            malformed XML, or has a direct rule whose name fails the module's
            Bazel target-label syntax. Malformed XML is translated with the
            parser error as its cause.
        UnicodeEncodeError: If ``payload`` contains a character that cannot be
            encoded as UTF-8 for the byte-limit check.
    """
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
    """Select direct owners or fall back to the full Bazel graph.

    Args:
        changes: Normalized changed-path records. Only their paths are used;
            duplicate paths are collapsed before selection.
        owner_map: Mapping from repository-relative source paths to direct Bazel
            owner labels. Owner labels are not validated here.
        policy: Validated CI policy whose foundational paths determine whether a
            change requires full selection.

    Returns:
        An ``AffectedSelection`` with sorted unique changed paths. Empty input
        returns ``reason="no_changed_paths"`` with no targets and
        ``force_full=False``. A foundational path equal to a configured path or
        beneath it at a slash boundary returns the full fallback
        ``("//...",)`` for both build and test targets, no owners, and
        ``force_full=True`` before unresolved-path checks. An unresolved path
        has the same full fallback. A present owner-map key with an empty tuple
        is resolved and can produce an ownerless, non-full selection; otherwise
        resolved owners are sorted and build/test targets remain empty for later
        attachment.
    """
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
    """Validate and attach reverse-dependency query results to an owner selection.

    Args:
        selection: Owner selection to update. Full selections and selections with
            no owner targets are returned unchanged, without inspecting the
            supplied query results.
        build_targets: Build labels returned by the reverse-dependency query.
            An eligible selection requires at least one label.
        test_targets: Test labels returned by the reverse-dependency query; this
            tuple may be empty for an eligible selection.

    Returns:
        The unchanged ``selection`` for full or ownerless selections; otherwise,
        a copy with sorted unique build and test target labels attached.

    Raises:
        CIPolicyError: If an eligible selection receives a target that fails the
            module's Bazel label syntax or receives no build targets. The helper
            checks label shape only and does not verify reverse-dependency
            membership.
    """
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
