"""Fail-closed contract tests for the declarative developer environment."""

from __future__ import annotations

# standard library imports
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

EXPECTED_SYSTEMS = ["aarch64-darwin", "x86_64-linux"]
EXPECTED_TOOLS = {
    "developer_environment.bazel": "9.1.0",
    "developer_environment.bazelisk": "1.29.0",
    "developer_environment.cosign": "3.1.3",
    "developer_environment.git": "2.55.0",
    "developer_environment.gnumake": "4.4.1",
    "developer_environment.nix": "2.34.8",
    "developer_environment.python": "3.12.14",
    "developer_environment.syft": "1.51.1",
    "developer_environment.uv": "0.12.7",
}
EXPECTED_NIXPKGS_REVISION = "34ab99075ac4f7e40cf037eef32cb1c360bb85e9"
EXPECTED_NIXPKGS_NAR_HASH = "sha256-hn1oU2rue2SYK8dAr8+WNZWtbsz1S2W5mnHlSEuh3bo="


def _roadmap_named_implementation_tokens(text: str) -> list[str]:
    patterns = (
        re.compile(r"\b[A-L][0-9]{2}_[A-Z][A-Z0-9_]*\b"),
        re.compile(r"//:[a-l][0-9]{2}[a-z0-9_]*\b"),
        re.compile(
            r"\b[a-l][0-9]{2}-[a-z0-9-]*(?:test|tests|shell|toolchain|environment)"
            r"[a-z0-9-]*\b"
        ),
    )
    return sorted({match.group() for pattern in patterns for match in pattern.finditer(text)})


def _repository_root() -> Path:
    runfiles = Path(os.environ["TEST_SRCDIR"])
    return runfiles / os.environ["TEST_WORKSPACE"]


def _contract_errors(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    exact_header = {
        "schema_version": 1,
        "roadmap_package": "B03",
        "operating_track": "solo_bootstrap",
        "package_status": "partial",
        "accountable_owner_role": "platform",
        "admission_owner_package": "B07",
        "as_of_date": "2026-09-03",
        "environment_kind": "nix_flake",
        "nixpkgs_revision": EXPECTED_NIXPKGS_REVISION,
        "nixpkgs_nar_hash": EXPECTED_NIXPKGS_NAR_HASH,
        "supported_systems": EXPECTED_SYSTEMS,
        "repository_verified_systems": ["aarch64-darwin"],
        "runtime_installation_allowed": False,
    }
    for field, expected in exact_header.items():
        if document.get(field) != expected:
            errors.append(f"{field} must equal {expected!r}")

    tools = document.get("tools")
    if not isinstance(tools, list):
        return [*errors, "tools must be an array of tables"]
    observed: dict[str, str] = {}
    required_fields = {
        "expected_version_output",
        "license",
        "maintenance_review",
        "name",
        "purpose",
        "rollback",
        "source",
        "source_digest",
        "source_url",
        "supported_systems",
        "tool_id",
        "transitive_native_dependencies",
        "version",
        "vulnerability_review",
    }
    digest_pattern = re.compile(
        r"^nixpkgs-revision:[0-9a-f]{40}$"
        r"|^release-artifacts:[a-z0-9_-]+=[0-9a-f]{64}"
        r"(?:,[a-z0-9_-]+=[0-9a-f]{64})+$"
    )
    for index, tool in enumerate(tools, 1):
        if not isinstance(tool, dict) or set(tool) != required_fields:
            errors.append(f"tools[{index}] fields drifted")
            continue
        tool_id = tool["tool_id"]
        version = tool["version"]
        if not isinstance(tool_id, str) or tool_id in observed:
            errors.append(f"tools[{index}] has an invalid or duplicate ID")
            continue
        if not isinstance(version, str) or not version or "latest" in version.lower():
            errors.append(f"{tool_id}: version must be exact and non-floating")
            continue
        observed[tool_id] = version
        if tool["supported_systems"] != EXPECTED_SYSTEMS:
            errors.append(f"{tool_id}: supported systems drifted")
        digest = tool["source_digest"]
        if not isinstance(digest, str) or digest_pattern.fullmatch(digest) is None:
            errors.append(f"{tool_id}: source digest is not immutable")
        source_url = tool["source_url"]
        if not isinstance(source_url, str) or not source_url.startswith("https://"):
            errors.append(f"{tool_id}: source URL must be HTTPS")
        if not isinstance(tool["transitive_native_dependencies"], list):
            errors.append(f"{tool_id}: transitive dependencies must be an array")
        for field in (
            "expected_version_output",
            "license",
            "maintenance_review",
            "name",
            "purpose",
            "rollback",
            "source",
            "vulnerability_review",
        ):
            if not isinstance(tool[field], str) or not tool[field]:
                errors.append(f"{tool_id}: {field} must be populated")
    if observed != EXPECTED_TOOLS:
        errors.append("tool contract does not contain the exact developer-environment tool set")
    return errors


def _flake_lock_errors(document: dict[str, Any]) -> list[str]:
    try:
        locked = document["nodes"]["nixpkgs"]["locked"]
        original = document["nodes"]["nixpkgs"]["original"]
        root_inputs = document["nodes"]["root"]["inputs"]
    except (KeyError, TypeError):
        return ["flake lock structure is incomplete"]
    errors: list[str] = []
    if document.get("version") != 7:
        errors.append("flake lock must use version 7")
    if root_inputs != {"nixpkgs": "nixpkgs"}:
        errors.append("flake must have only the reviewed nixpkgs input")
    if locked.get("rev") != EXPECTED_NIXPKGS_REVISION:
        errors.append("nixpkgs revision drifted")
    if locked.get("narHash") != EXPECTED_NIXPKGS_NAR_HASH:
        errors.append("nixpkgs content hash drifted")
    if original != {
        "owner": "NixOS",
        "ref": "nixos-unstable",
        "repo": "nixpkgs",
        "type": "github",
    }:
        errors.append("nixpkgs source identity drifted")
    return errors


def _assert_script_failure(script: Path, argument: str, expected: str) -> None:
    completed = subprocess.run(
        ["bash", str(script), argument],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0 or expected not in completed.stderr:
        raise AssertionError(
            f"expected bootstrap failure containing {expected!r}: "
            f"rc={completed.returncode}, stderr={completed.stderr!r}"
        )


def _report_artifact_path(bundle_root: Path, value: object) -> Path | None:
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


def _evidence_errors(root: Path) -> list[str]:
    bundle_root = root / "docs/governance/evidence/examples/b03-r2-partial"
    manifest_path = bundle_root / "manifest.toml"
    if not manifest_path.is_file():
        return ["developer-environment evidence manifest is missing"]
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if _report_artifact_path(bundle_root, "reports/../../outside.txt") is not None:
        errors.append("artifact path traversal must fail closed")
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
    if manifest.get("roadmap_id") != "B03" or manifest.get("bundle_status") != "partial":
        errors.append("evidence identity or partial status drifted")
    expected_change = {
        "capital_at_risk": False,
        "blast_radius": "shared_domain",
        "data_model_materiality": "shared_or_candidate",
        "security_privilege": "none",
        "reversibility": "compatibility_window",
        "computationally_material": True,
        "economically_or_risk_relevant": False,
        "model_or_trading_relevant": False,
        "declared_class": "R2",
    }
    if manifest.get("risk_class") != "R2" or manifest.get("change") != expected_change:
        errors.append("evidence must bind the exact A04 R2 classification")
    if manifest.get("open_finding_ids") != ["B03-F01", "B03-F02", "B03-F03"]:
        errors.append("evidence must retain the exact developer-environment findings")
    gates = manifest.get("gates")
    if (
        not isinstance(gates, list)
        or {gate.get("gate_id") for gate in gates if isinstance(gate, dict)} != expected_gates
    ):
        errors.append("evidence must bind the exact applicable R2 gates")
    elif any(gate.get("status") != "passed" for gate in gates if isinstance(gate, dict)):
        errors.append("repository-local developer-environment gate evidence must pass")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 4:
        errors.append("evidence must contain four artifact classes")
    else:
        for artifact in artifacts:
            if not isinstance(artifact, dict):
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
            if digest != hashlib.sha256(artifact_path.read_bytes()).hexdigest():
                errors.append(f"evidence digest mismatch: {relative}")
    return errors


def main() -> int:
    root = _repository_root()
    contract_path = root / "environments/dev/toolchain.toml"
    contract = tomllib.loads(contract_path.read_text(encoding="utf-8"))
    lock = json.loads((root / "flake.lock").read_text(encoding="utf-8"))
    errors = _contract_errors(contract) + _flake_lock_errors(lock) + _evidence_errors(root)

    flake = (root / "flake.nix").read_text(encoding="utf-8")
    required_flake_fragments = (
        '"aarch64-darwin"',
        '"x86_64-linux"',
        'bazel = "9.1.0";',
        'uv = "0.12.7";',
        'python = "3.12.14";',
        'CLEAN_MACHINE_DEV_SHELL = "1";',
        'UV_PYTHON_DOWNLOADS = "never";',
        "USE_BAZEL_VERSION=${toolVersions.bazel}",
        'binary = "bazel-9.1.0-darwin-arm64";',
        'binary = "bazel-9.1.0-linux-x86_64";',
    )
    missing = [fragment for fragment in required_flake_fragments if fragment not in flake]
    if missing:
        errors.append(f"flake is missing exact contract fragments: {missing}")
    roadmap_named_flake_tokens = _roadmap_named_implementation_tokens(flake)
    if roadmap_named_flake_tokens:
        errors.append(
            f"flake retains roadmap-selector implementation names: {roadmap_named_flake_tokens}"
        )
    if (root / ".python-version").read_text(encoding="utf-8").strip() != "3.12.14":
        errors.append("Python version drifted from the developer-environment toolchain")
    if (root / ".bazelversion").read_text(encoding="utf-8").strip() != "9.1.0":
        errors.append("Bazel version drifted from the developer-environment toolchain")
    if (root / ".envrc").read_text(encoding="utf-8").strip() != ("use flake --no-write-lock-file"):
        errors.append("direnv must consume the locked flake without rewriting it")

    duplicate = tomllib.loads(contract_path.read_text(encoding="utf-8"))
    duplicate["tools"].append(dict(duplicate["tools"][0]))
    if not any("duplicate ID" in error for error in _contract_errors(duplicate)):
        errors.append("duplicate tool IDs must fail closed")
    unsupported = tomllib.loads(contract_path.read_text(encoding="utf-8"))
    unsupported["supported_systems"] = [*EXPECTED_SYSTEMS, "aarch64-linux"]
    if not any("supported_systems" in error for error in _contract_errors(unsupported)):
        errors.append("an unsupported platform must fail closed")
    floating = tomllib.loads(contract_path.read_text(encoding="utf-8"))
    floating["tools"][0]["version"] = "latest"
    if not any("non-floating" in error for error in _contract_errors(floating)):
        errors.append("a floating tool version must fail closed")

    script = root / "environments/dev/bootstrap.sh"
    script_text = script.read_text(encoding="utf-8")
    required_script_fragments = (
        "CLEAN_MACHINE_DEV_SHELL",
        "//:developer_environment_tests",
    )
    missing_script_fragments = [
        fragment for fragment in required_script_fragments if fragment not in script_text
    ]
    if missing_script_fragments:
        errors.append(
            f"bootstrap is missing purpose-based contract names: {missing_script_fragments}"
        )
    roadmap_named_script_tokens = _roadmap_named_implementation_tokens(script_text)
    if roadmap_named_script_tokens:
        errors.append(
            "bootstrap retains roadmap-selector implementation names: "
            f"{roadmap_named_script_tokens}"
        )
    _assert_script_failure(script, "unknown", "usage:")
    _assert_script_failure(script, "verify", "must run inside")

    if errors:
        print("developer-environment errors:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
