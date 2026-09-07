"""Fail-closed structural checks for the pinned B02 build graph."""

from __future__ import annotations

# standard library imports
import hashlib
import json
import os
import re
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import Final

# third party library imports
from pydantic import BaseModel, ConfigDict

_EXPECTED_BUILD_PINS: Final[tuple[str, ...]] = (
    'bazel_dep(name = "rules_python", version = "2.2.0")',
    'bazel_dep(name = "rules_buf", version = "0.5.4")',
    'bazel_dep(name = "bazel_skylib", version = "1.8.2")',
    'python_version = "3.12.14"',
    'runtime_manifest_sha = "0e27ff80c0075aa29730035faf2b94a00498f348131c6e8997cbbb5b77584966"',
    'requirements_lock = "//:requirements.bazel.txt"',
    'uv_lock = "//:uv.lock"',
    'sha256 = "c6ddd4f90a2829ea04efbfbbbc44f8f5d4a0f2dda3bec5ec3fbb652c2d394c06"',
    'version = "v1.72.0"',
)
_REQUIRED_SANDBOX_FLAGS: Final[tuple[str, ...]] = (
    "--incompatible_strict_action_env",
    "--incompatible_default_to_explicit_init_py",
    "--experimental_convenience_symlinks=ignore",
    "--spawn_strategy=sandboxed",
    "--strategy=Genrule=sandboxed",
)
_EXPECTED_DEPENDENCY_IDS: Final[frozenset[str]] = frozenset(
    {
        "b02.bazel",
        "b02.bazel_skylib",
        "b02.bazelisk",
        "b02.buf",
        "b02.python_build_standalone",
        "b02.rules_buf",
        "b02.rules_python",
        "b02.setup_bazel",
        "b02.upload_artifact",
    }
)
_DEPENDENCY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "dependency_id",
        "license",
        "maintenance_review",
        "name",
        "purpose",
        "rollback",
        "source_digest",
        "source_url",
        "supported_platforms",
        "transitive_native_dependencies",
        "version",
        "vulnerability_review",
    }
)
_DIGEST_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:sha256|sha256-manifest):[0-9a-f]{64}$"
    r"|^git-commit:[0-9a-f]{40}$"
    r"|^release-artifacts:[a-z0-9_-]+=[0-9a-f]{64}"
    r"(?:,[a-z0-9_-]+=[0-9a-f]{64})+$"
)
_EXPECTED_EVIDENCE_GATES: Final[frozenset[str]] = frozenset(
    {
        "QG01",
        "QG02",
        "QG03",
        "QG04",
        "QG05",
        "QG06",
        "QG09",
        "QG10",
        "QG11",
        "QG12",
        "QG13",
        "QG14",
    }
)


class _ValidationReport(BaseModel):
    """Capture one validator invocation's fatal or aggregate findings."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        strict=True,
        validate_default=True,
    )

    fatal_error: str | None = None
    governance_errors: tuple[str, ...] = ()


def _repository_root() -> Path:
    """Construct the repository path from Bazel's runfiles environment.

    Returns:
        The workspace directory under the runfiles directory named by
        ``TEST_SRCDIR``.

    Raises:
        KeyError: If ``TEST_SRCDIR`` or ``TEST_WORKSPACE`` is unset.
    """
    runfiles = Path(os.environ["TEST_SRCDIR"])
    workspace = os.environ["TEST_WORKSPACE"]
    return runfiles / workspace


def _table_from_object(value: object) -> dict[str, object] | None:
    """Copy a parser-produced mapping after validating its string-key boundary.

    Args:
        value: Untyped TOML or JSON parser output.

    Returns:
        A new string-keyed table, or ``None`` when the value is not a table or
        contains a non-string key.
    """
    if not isinstance(value, dict):
        return None
    table: dict[str, object] = {}
    for raw_key in value:
        key: object = raw_key
        if not isinstance(key, str):
            return None
        raw_value: object = value[raw_key]
        table[key] = raw_value
    return table


def _list_from_object(value: object) -> list[object] | None:
    """Copy a parser-produced list into a precisely typed boundary value.

    Args:
        value: Untyped TOML or JSON parser output.

    Returns:
        A list containing the original values, or ``None`` when ``value`` is
        not a list.
    """
    if not isinstance(value, list):
        return None
    values: list[object] = []
    for raw_value in value:
        value_as_object: object = raw_value
        values.append(value_as_object)
    return values


def _load_toml_table(path: Path) -> dict[str, object]:
    """Read a UTF-8 TOML file and require a string-keyed root table.

    Args:
        path: TOML file to read.

    Returns:
        The parsed root table.

    Raises:
        OSError: If the file cannot be read.
        UnicodeDecodeError: If the file is not valid UTF-8.
        tomllib.TOMLDecodeError: If the file is not valid TOML.
        TypeError: If the parser does not return a table with string keys.
    """
    parsed_document: object = tomllib.loads(path.read_text(encoding="utf-8"))
    table = _table_from_object(parsed_document)
    if table is None:
        raise TypeError(f"{path} must contain a TOML table")
    return table


def _load_json_document(text: str) -> object:
    """Decode JSON text without changing the historical validation order.

    Args:
        text: JSON text to decode.

    Returns:
        The parser-produced JSON value. Root-shape validation happens at the
        point where the lock-file contract first needs mapping access.

    Raises:
        json.JSONDecodeError: If ``text`` is not valid JSON.
    """
    parsed_document: object = json.loads(text)
    return parsed_document


def _require_json_table(value: object) -> dict[str, object]:
    """Narrow a JSON value at the lock-file mapping access boundary.

    Args:
        value: Decoded JSON value expected to be an object.

    Returns:
        A string-keyed JSON object.

    Raises:
        AttributeError: If the JSON root has no mapping ``get`` contract.
    """
    table = _table_from_object(value)
    if table is None:
        value_type = type(value).__name__
        raise AttributeError(f"'{value_type}' object has no attribute 'get'")
    return table


def _report_artifact_path(bundle_root: Path, value: object) -> Path | None:
    """Construct a lexical report path after applying the confinement check.

    This remains a small stateless path predicate because it owns no repository
    context and performs no I/O.

    Args:
        bundle_root: Root directory of the evidence bundle.
        value: Candidate artifact path read from the manifest.

    Returns:
        A candidate path under ``bundle_root/reports`` for a normalized POSIX
        value, or ``None`` for a non-string or rejected value. The check is
        lexical; it does not resolve symlinks or inspect the filesystem.
    """
    if not isinstance(value, str):
        return None
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or relative.as_posix() != value
        or not relative.parts
        or relative.parts[0] != "reports"
        or ".." in relative.parts
    ):
        return None
    return bundle_root.joinpath(*relative.parts)


class BuildGraphValidator:
    """Validate the B02 build graph and its repository-local evidence.

    The repository root is the complete construction context. Each call to
    :meth:`validate` allocates its own findings, so a failed invocation cannot
    contaminate a later invocation on the same validator instance.
    """

    def __init__(self, root: Path) -> None:
        """Bind the repository root without reading files.

        Args:
            root: Repository root containing the B02 build and evidence files.
        """
        self._root: Path = root

    def validate(self) -> _ValidationReport:
        """Run the ordered build, CI, dependency, and evidence checks.

        Returns:
            A report containing the first historical fail-fast error, or all
            ordered dependency and evidence findings when those phases run.

        Raises:
            OSError: If a required repository file cannot be read.
            UnicodeDecodeError: If a required text file is not valid UTF-8.
            json.JSONDecodeError: If ``MODULE.bazel.lock`` is not valid JSON.
            tomllib.TOMLDecodeError: If a checked file is not valid TOML.
            AttributeError: If the lock file has no mapping ``get`` contract.
        """
        fatal_error = self._build_input_error()
        if fatal_error is not None:
            return _ValidationReport(fatal_error=fatal_error)
        fatal_error = self._ci_error()
        if fatal_error is not None:
            return _ValidationReport(fatal_error=fatal_error)
        errors = self._dependency_record_errors()
        errors.extend(self._evidence_errors())
        return _ValidationReport(governance_errors=tuple(errors))

    def _build_input_error(self) -> str | None:
        """Validate pinned module, Bazel, sandbox, and lock-file inputs."""
        module = (self._root / "MODULE.bazel").read_text(encoding="utf-8")
        bazelrc = (self._root / ".bazelrc").read_text(encoding="utf-8")
        module_lock_value = _load_json_document(
            (self._root / "MODULE.bazel.lock").read_text(encoding="utf-8")
        )

        missing = [pin for pin in _EXPECTED_BUILD_PINS if pin not in module]
        if missing:
            return f"missing pinned build inputs: {missing}"
        if (self._root / ".bazelversion").read_text(encoding="utf-8").strip() != "9.1.0":
            return "Bazel version must be pinned to 9.1.0"
        if any(flag not in bazelrc for flag in _REQUIRED_SANDBOX_FLAGS):
            return "Bazel sandbox or strict-environment controls are missing"
        if re.search(r'python\.toolchain\([^)]*python_version\s*=\s*"3\.12"', module, re.S):
            return "Python toolchain must pin the full patch version"
        module_lock = _require_json_table(module_lock_value)
        if module_lock.get("lockFileVersion") != 26:
            return "MODULE.bazel.lock must use the Bazel 9 lock format"
        return None

    def _ci_error(self) -> str | None:
        """Validate reviewed CI setup and the authoritative host-exclusion lane."""
        continuous_integration = (self._root / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        if (
            "bazel-contrib/setup-bazel@c5acdfb288317d0b5c0bbd7a396a3dc868bb0f86"
            not in continuous_integration
        ):
            return "CI Bazel setup must be pinned to the reviewed action commit"
        if 'bazelisk-version: "1.29.0"' not in continuous_integration:
            return "CI Bazelisk version must be exact"
        if "make ci-full" not in continuous_integration:
            return "CI must execute the authoritative full lane containing the canonical B02 graph"

        makefile = (self._root / "Makefile").read_text(encoding="utf-8")
        if (
            "UNDECLARED_HOST_SECRET=synthetic-host-only $(BAZEL) test "
            "--config=ci //:hermetic_build_tests" not in makefile
        ):
            return "Bazel tests must exercise host-environment exclusion"
        return None

    def _dependency_record_errors(self) -> list[str]:
        """Validate the declared B02 dependency contract and collect errors.

        Returns:
            Validation error messages, or an empty list when the checked fields
            satisfy the B02 contract.

        Raises:
            OSError: If the dependency record cannot be read.
            UnicodeDecodeError: If the dependency record is not valid UTF-8.
            tomllib.TOMLDecodeError: If the dependency record is not valid TOML.
        """
        path = self._root / "docs/architecture/build-tool-dependencies.toml"
        document = _load_toml_table(path)
        errors: list[str] = []
        if document.get("roadmap_package") != "B02":
            errors.append("dependency record must belong to B02")
        if document.get("admission_owner_package") != "B07":
            errors.append("provisional dependencies must remain B07-owned")
        if document.get("runtime_installation_allowed") is not False:
            errors.append("production runtime package installation must be prohibited")

        dependencies = _list_from_object(document.get("dependencies"))
        if dependencies is None:
            return [*errors, "dependencies must be an array of tables"]
        observed_ids: set[str] = set()
        for index, raw_dependency in enumerate(dependencies, 1):
            dependency = _table_from_object(raw_dependency)
            if dependency is None:
                errors.append(f"dependencies[{index}] must be a table")
                continue
            if set(dependency) != _DEPENDENCY_FIELDS:
                errors.append(f"dependencies[{index}] fields drifted")
                continue
            errors.extend(self._dependency_errors(index, dependency, observed_ids))
        if observed_ids != _EXPECTED_DEPENDENCY_IDS:
            errors.append("dependency record does not contain the exact B02 tool set")
        return errors

    def _dependency_errors(
        self, index: int, dependency: dict[str, object], observed_ids: set[str]
    ) -> list[str]:
        """Validate one already-shaped dependency table in field order.

        Args:
            index: One-based dependency index used in diagnostics.
            dependency: String-keyed table with the exact required fields.
            observed_ids: Invocation-local identifiers used for duplicate checks.

        Returns:
            Ordered errors for the dependency, preserving the historical early
            return after an invalid or duplicate identifier.
        """
        errors: list[str] = []
        dependency_id = dependency["dependency_id"]
        if not isinstance(dependency_id, str) or dependency_id in observed_ids:
            errors.append(f"dependencies[{index}] has an invalid or duplicate ID")
            return errors
        observed_ids.add(dependency_id)
        version = dependency["version"]
        if not isinstance(version, str) or not version or "latest" in version.lower():
            errors.append(f"{dependency_id}: version must be an exact non-floating pin")
        source_url = dependency["source_url"]
        if not isinstance(source_url, str) or not source_url.startswith("https://"):
            errors.append(f"{dependency_id}: source URL must be HTTPS")
        digest = dependency["source_digest"]
        if not isinstance(digest, str) or _DIGEST_PATTERN.fullmatch(digest) is None:
            errors.append(f"{dependency_id}: source digest is not immutable")
        for field in (
            "license",
            "maintenance_review",
            "name",
            "purpose",
            "rollback",
            "vulnerability_review",
        ):
            if not isinstance(dependency[field], str) or not dependency[field]:
                errors.append(f"{dependency_id}: {field} must be populated")
        platforms = _list_from_object(dependency["supported_platforms"])
        if platforms is None or not platforms:
            errors.append(f"{dependency_id}: supported platforms must be populated")
        if _list_from_object(dependency["transitive_native_dependencies"]) is None:
            errors.append(f"{dependency_id}: transitive dependencies must be an array")
        return errors

    def _evidence_errors(self) -> list[str]:
        """Validate selected B02 evidence fields and report-file digests.

        Returns:
            Validation error messages, or an empty list when selected identity,
            gates, artifact paths, report files, and SHA-256 digests pass.

        Raises:
            OSError: If the manifest or a report cannot be read.
            UnicodeDecodeError: If the manifest is not valid UTF-8.
            tomllib.TOMLDecodeError: If the manifest is not valid TOML.
        """
        bundle_root = self._root / "docs/governance/evidence/examples/b02-r2-partial"
        manifest = _load_toml_table(bundle_root / "manifest.toml")
        errors: list[str] = []
        if _report_artifact_path(bundle_root, "reports/../../outside.txt") is not None:
            errors.append("artifact path traversal must fail closed")
        if manifest.get("roadmap_id") != "B02" or manifest.get("bundle_status") != "partial":
            errors.append("evidence identity or partial status drifted")
        if manifest.get("open_finding_ids") != ["B02-F01", "B02-F02", "B02-F03"]:
            errors.append("evidence must retain the exact B02 findings")
        change = _table_from_object(manifest.get("change"))
        if change is None or change.get("declared_class") != "R2":
            errors.append("evidence must bind the R2 classification")
        elif change.get("computationally_material") is not True:
            errors.append("B02 evidence must declare computational materiality")

        gates = _list_from_object(manifest.get("gates"))
        gate_tables: list[dict[str, object]] = []
        gate_ids: set[str] = set()
        invalid_gate = False
        if gates is not None:
            for raw_gate in gates:
                gate = _table_from_object(raw_gate)
                if gate is None:
                    invalid_gate = True
                    continue
                gate_tables.append(gate)
                gate_id = gate.get("gate_id")
                if not isinstance(gate_id, str):
                    invalid_gate = True
                    continue
                gate_ids.add(gate_id)
        if gates is None or invalid_gate or gate_ids != _EXPECTED_EVIDENCE_GATES:
            errors.append("evidence must bind the exact applicable R2 gates")
        elif any(gate.get("status") != "passed" for gate in gate_tables):
            errors.append("repository-local B02 gate evidence must pass")

        artifacts = _list_from_object(manifest.get("artifacts"))
        if artifacts is None or len(artifacts) != 4:
            errors.append("evidence must contain the four required artifact classes")
        else:
            for raw_artifact in artifacts:
                artifact = _table_from_object(raw_artifact)
                if artifact is None:
                    errors.append("artifact entry must be a table")
                    continue
                relative = artifact.get("path")
                digest = artifact.get("sha256")
                artifact_path = _report_artifact_path(bundle_root, relative)
                if artifact_path is None:
                    errors.append("artifact path must remain inside reports/")
                    continue
                if not artifact_path.is_file():
                    errors.append(f"missing evidence artifact: {relative}")
                    continue
                actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                if digest != actual:
                    errors.append(f"evidence digest mismatch: {relative}")
        return errors


def main() -> int:
    """Check pinned B02 build inputs and local evidence fixtures.

    Read build and CI configuration together with local dependency and evidence
    files from the repository path supplied by Bazel runfiles.

    Returns:
        Zero when all checked contracts pass; one after reporting a contract
        mismatch to standard error.

    Raises:
        KeyError: If Bazel does not provide ``TEST_SRCDIR`` or
            ``TEST_WORKSPACE``.
        OSError: If a required repository file cannot be read.
        UnicodeDecodeError: If a required text file is not valid UTF-8.
        json.JSONDecodeError: If ``MODULE.bazel.lock`` is not valid JSON.
        tomllib.TOMLDecodeError: If a checked file is not valid TOML.
        AttributeError: If the lock file has no mapping ``get`` contract.
    """
    report = BuildGraphValidator(_repository_root()).validate()
    if report.fatal_error is not None:
        print(report.fatal_error, file=sys.stderr)
        return 1
    if report.governance_errors:
        print("B02 governance errors:\n- " + "\n- ".join(report.governance_errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
