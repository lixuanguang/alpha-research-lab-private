"""Fail-closed structural checks for the pinned B02 build graph."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tomllib
from pathlib import Path


def _repository_root() -> Path:
    runfiles = Path(os.environ["TEST_SRCDIR"])
    workspace = os.environ["TEST_WORKSPACE"]
    return runfiles / workspace


def _dependency_record_errors(root: Path) -> list[str]:
    path = root / "docs/architecture/build-tool-dependencies.toml"
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if document.get("roadmap_package") != "B02":
        errors.append("dependency record must belong to B02")
    if document.get("admission_owner_package") != "B07":
        errors.append("provisional dependencies must remain B07-owned")
    if document.get("runtime_installation_allowed") is not False:
        errors.append("production runtime package installation must be prohibited")

    dependencies = document.get("dependencies")
    if not isinstance(dependencies, list):
        return [*errors, "dependencies must be an array of tables"]
    expected_ids = {
        "b02.bazel",
        "b02.bazel_skylib",
        "b02.bazelisk",
        "b02.buf",
        "b02.python_build_standalone",
        "b02.rules_buf",
        "b02.rules_python",
        "b02.setup_bazel",
    }
    observed_ids: set[str] = set()
    digest_pattern = re.compile(
        r"^(?:sha256|sha256-manifest):[0-9a-f]{64}$"
        r"|^git-commit:[0-9a-f]{40}$"
        r"|^release-artifacts:[a-z0-9_-]+=[0-9a-f]{64}"
        r"(?:,[a-z0-9_-]+=[0-9a-f]{64})+$"
    )
    required_fields = {
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
    for index, dependency in enumerate(dependencies, 1):
        if not isinstance(dependency, dict):
            errors.append(f"dependencies[{index}] must be a table")
            continue
        if set(dependency) != required_fields:
            errors.append(f"dependencies[{index}] fields drifted")
            continue
        dependency_id = dependency["dependency_id"]
        if not isinstance(dependency_id, str) or dependency_id in observed_ids:
            errors.append(f"dependencies[{index}] has an invalid or duplicate ID")
            continue
        observed_ids.add(dependency_id)
        version = dependency["version"]
        if not isinstance(version, str) or not version or "latest" in version.lower():
            errors.append(f"{dependency_id}: version must be an exact non-floating pin")
        source_url = dependency["source_url"]
        if not isinstance(source_url, str) or not source_url.startswith("https://"):
            errors.append(f"{dependency_id}: source URL must be HTTPS")
        digest = dependency["source_digest"]
        if not isinstance(digest, str) or digest_pattern.fullmatch(digest) is None:
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
        platforms = dependency["supported_platforms"]
        if not isinstance(platforms, list) or not platforms:
            errors.append(f"{dependency_id}: supported platforms must be populated")
        if not isinstance(dependency["transitive_native_dependencies"], list):
            errors.append(f"{dependency_id}: transitive dependencies must be an array")
    if observed_ids != expected_ids:
        errors.append("dependency record does not contain the exact B02 tool set")
    return errors


def _evidence_errors(root: Path) -> list[str]:
    bundle_root = root / "docs/governance/evidence/examples/b02-r2-partial"
    manifest = tomllib.loads((bundle_root / "manifest.toml").read_text(encoding="utf-8"))
    errors: list[str] = []
    expected_gates = {
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
    if manifest.get("roadmap_id") != "B02" or manifest.get("bundle_status") != "partial":
        errors.append("evidence identity or partial status drifted")
    if manifest.get("open_finding_ids") != ["B02-F01", "B02-F02", "B02-F03"]:
        errors.append("evidence must retain the exact B02 findings")
    change = manifest.get("change")
    if not isinstance(change, dict) or change.get("declared_class") != "R2":
        errors.append("evidence must bind the R2 classification")
    elif change.get("computationally_material") is not True:
        errors.append("B02 evidence must declare computational materiality")
    gates = manifest.get("gates")
    if (
        not isinstance(gates, list)
        or {gate.get("gate_id") for gate in gates if isinstance(gate, dict)} != expected_gates
    ):
        errors.append("evidence must bind the exact applicable R2 gates")
    elif any(gate.get("status") != "passed" for gate in gates if isinstance(gate, dict)):
        errors.append("repository-local B02 gate evidence must pass")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 4:
        errors.append("evidence must contain the four required artifact classes")
    else:
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                errors.append("artifact entry must be a table")
                continue
            relative = artifact.get("path")
            digest = artifact.get("sha256")
            if not isinstance(relative, str) or not relative.startswith("reports/"):
                errors.append("artifact path must remain inside reports/")
                continue
            artifact_path = bundle_root / relative
            if not artifact_path.is_file():
                errors.append(f"missing evidence artifact: {relative}")
                continue
            actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            if digest != actual:
                errors.append(f"evidence digest mismatch: {relative}")
    return errors


def main() -> int:
    root = _repository_root()
    module = (root / "MODULE.bazel").read_text(encoding="utf-8")
    bazelrc = (root / ".bazelrc").read_text(encoding="utf-8")
    module_lock = json.loads((root / "MODULE.bazel.lock").read_text(encoding="utf-8"))

    expected_pins = (
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
    missing = [pin for pin in expected_pins if pin not in module]
    if missing:
        print(f"missing pinned build inputs: {missing}", file=sys.stderr)
        return 1

    if (root / ".bazelversion").read_text(encoding="utf-8").strip() != "9.1.0":
        print("Bazel version must be pinned to 9.1.0", file=sys.stderr)
        return 1

    required_sandbox_flags = (
        "--incompatible_strict_action_env",
        "--incompatible_default_to_explicit_init_py",
        "--experimental_convenience_symlinks=ignore",
        "--spawn_strategy=sandboxed",
        "--strategy=Genrule=sandboxed",
    )
    if any(flag not in bazelrc for flag in required_sandbox_flags):
        print("Bazel sandbox or strict-environment controls are missing", file=sys.stderr)
        return 1

    if re.search(r"python\.toolchain\([^)]*python_version\s*=\s*\"3\.12\"", module, re.S):
        print("Python toolchain must pin the full patch version", file=sys.stderr)
        return 1

    if module_lock.get("lockFileVersion") != 26:
        print("MODULE.bazel.lock must use the Bazel 9 lock format", file=sys.stderr)
        return 1

    continuous_integration = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    if (
        "bazel-contrib/setup-bazel@c5acdfb288317d0b5c0bbd7a396a3dc868bb0f86"
        not in continuous_integration
    ):
        print("CI Bazel setup must be pinned to the reviewed action commit", file=sys.stderr)
        return 1
    if 'bazelisk-version: "1.29.0"' not in continuous_integration:
        print("CI Bazelisk version must be exact", file=sys.stderr)
        return 1
    if "run: make bazel-check" not in continuous_integration:
        print("CI must execute the canonical B02 graph", file=sys.stderr)
        return 1

    makefile = (root / "Makefile").read_text(encoding="utf-8")
    if (
        "UNDECLARED_HOST_SECRET=synthetic-host-only $(BAZEL) test "
        "--config=ci //:hermetic_build_tests" not in makefile
    ):
        print("Bazel tests must exercise host-environment exclusion", file=sys.stderr)
        return 1

    errors = _dependency_record_errors(root) + _evidence_errors(root)
    if errors:
        print("B02 governance errors:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
