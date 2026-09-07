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
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Protocol

EXPECTED_SYSTEMS: list[str] = ["aarch64-darwin", "x86_64-linux"]
EXPECTED_TOOLS: dict[str, str] = {
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
EXPECTED_NIXPKGS_REVISION: str = "34ab99075ac4f7e40cf037eef32cb1c360bb85e9"
EXPECTED_NIXPKGS_NAR_HASH: str = "sha256-hn1oU2rue2SYK8dAr8+WNZWtbsz1S2W5mnHlSEuh3bo="


class _DocumentLoader(Protocol):
    """Describe a standard-library decoder at an untyped data boundary."""

    def __call__(self, source: str, /) -> object:
        """Decode text into an object that requires runtime narrowing.

        Args:
            source: Document text to decode.

        Returns:
            Raw decoder output for immediate runtime validation.
        """


_JSON_LOADS: _DocumentLoader = json.loads
_TOML_LOADS: _DocumentLoader = tomllib.loads


def _object_mapping(value: object) -> dict[object, object] | None:
    """Copy a raw dictionary into a mapping whose values remain unknown.

    Args:
        value: Raw decoder output.

    Returns:
        A dictionary with explicit object keys and values, or ``None`` when the
        boundary value is not a dictionary.
    """
    if not isinstance(value, dict):
        return None
    result: dict[object, object] = {}
    for key, item in value.items():
        result[key] = item
    return result


def _string_mapping(value: object) -> dict[str, object] | None:
    """Narrow a raw dictionary to string-keyed data for controlled mutation.

    Args:
        value: Raw decoder output or nested dictionary.

    Returns:
        A copied string-keyed dictionary, or ``None`` when a key is not a
        string or the value is not a dictionary.
    """
    mapping = _object_mapping(value)
    if mapping is None:
        return None
    result: dict[str, object] = {}
    for key, item in mapping.items():
        if not isinstance(key, str):
            return None
        result[key] = item
    return result


def _object_list(value: object) -> list[object] | None:
    """Narrow a raw list without allowing decoder ``Any`` to escape.

    Args:
        value: Raw decoder output or nested value.

    Returns:
        A copied list of unknown values, or ``None`` when the value is not a
        list.
    """
    if not isinstance(value, list):
        return None
    result: list[object] = []
    for item in value:
        result.append(item)
    return result


def _roadmap_named_implementation_tokens(text: str) -> list[str]:
    """Find roadmap selectors that must not become implementation target names.

    Args:
        text: Flake or bootstrap source text.

    Returns:
        Sorted distinct roadmap selector tokens found in ``text``.
    """
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
    """Resolve the repository data tree supplied by Bazel runfiles.

    Returns:
        The workspace directory under Bazel's ``TEST_SRCDIR``.

    Raises:
        KeyError: If Bazel does not provide ``TEST_SRCDIR`` or
            ``TEST_WORKSPACE``.
    """
    runfiles = Path(os.environ["TEST_SRCDIR"])
    return runfiles / os.environ["TEST_WORKSPACE"]


def _assert_script_failure(script: Path, argument: str, expected: str) -> None:
    """Require the bootstrap command to fail with the intended diagnostic.

    Args:
        script: Bootstrap script to execute.
        argument: Deliberately invalid command argument.
        expected: Required substring in standard error.

    Raises:
        AssertionError: If the command succeeds or emits another diagnostic.
    """
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
    """Narrow an artifact name to a normalized path confined to reports.

    Args:
        bundle_root: Root directory of the evidence bundle.
        value: Raw manifest artifact path.

    Returns:
        A candidate path under ``bundle_root/reports`` or ``None`` when the
        value is not a normalized, confined POSIX path.
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


class DeveloperEnvironmentContractChecker:
    """Validate the pinned developer environment and its local evidence.

    The checker binds a repository root without performing I/O in its
    constructor. Each ``run`` call reloads all documents and creates fresh
    invocation-local findings, so a failed invocation cannot affect a later
    invocation on the same instance.
    """

    def __init__(self, root: Path) -> None:
        """Bind the repository context used by later validation calls.

        Args:
            root: Repository root containing the developer-environment files.
        """
        self._root: Path = root

    def run(self) -> int:
        """Run all contract checks in the historical acceptance order.

        Returns:
            Zero when every contract passes, or one after reporting findings to
            standard error.

        Raises:
            AssertionError: If a required valid fixture cannot be used for its
                malformed-input probes, or a bootstrap probe succeeds.
            OSError: If a required repository file cannot be read.
            UnicodeDecodeError: If a required text file is not valid UTF-8.
            json.JSONDecodeError: If ``flake.lock`` is not valid JSON.
            tomllib.TOMLDecodeError: If a required TOML file is not valid TOML.
        """
        errors: list[str] = []
        contract = self._read_toml("environments/dev/toolchain.toml")
        lock = self._read_json("flake.lock")
        errors.extend(self._contract_errors(contract))
        errors.extend(self._flake_lock_errors(lock))
        errors.extend(self._evidence_errors())

        errors.extend(self._check_environment_files())
        contract_record = _string_mapping(contract)
        assert contract_record is not None
        errors.extend(self._mutation_probe_errors(contract_record))
        errors.extend(self._malformed_input_errors())
        errors.extend(self._bootstrap_errors())

        if errors:
            print(
                "developer-environment errors:\n- " + "\n- ".join(errors),
                file=sys.stderr,
            )
            return 1
        return 0

    def _read_toml(self, relative_path: str) -> object:
        """Read and decode a TOML document at the repository boundary.

        Args:
            relative_path: Repository-relative document path.

        Returns:
            Raw decoder output for immediate validation by the caller.
        """
        return _TOML_LOADS((self._root / relative_path).read_text(encoding="utf-8"))

    def _read_json(self, relative_path: str) -> object:
        """Read and decode a JSON document at the repository boundary.

        Args:
            relative_path: Repository-relative document path.

        Returns:
            Raw decoder output for immediate validation by the caller.
        """
        return _JSON_LOADS((self._root / relative_path).read_text(encoding="utf-8"))

    def _contract_errors(self, document: object) -> list[str]:
        """Validate the TOML contract and its exact pinned tool records.

        Args:
            document: Raw TOML decoder output.

        Returns:
            Ordered contract findings.
        """
        record = _object_mapping(document)
        if record is None:
            return ["developer-environment contract must be a table"]
        errors: list[str] = []
        exact_header: dict[str, object] = {
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
            if record.get(field) != expected:
                errors.append(f"{field} must equal {expected!r}")

        tools = _object_list(record.get("tools"))
        if tools is None:
            return [*errors, "tools must be an array of tables"]
        observed: dict[str, str] = {}
        required_fields: set[str] = {
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
        for index, raw_tool in enumerate(tools, 1):
            errors.extend(
                self._tool_errors(
                    index,
                    raw_tool,
                    required_fields,
                    digest_pattern,
                    observed,
                )
            )
        if observed != EXPECTED_TOOLS:
            errors.append("tool contract does not contain the exact developer-environment tool set")
        return errors

    def _tool_errors(
        self,
        index: int,
        raw_tool: object,
        required_fields: set[str],
        digest_pattern: re.Pattern[str],
        observed: dict[str, str],
    ) -> list[str]:
        """Validate one tool record while preserving contract error order.

        Args:
            index: One-based tool position used in diagnostics.
            raw_tool: Raw tool table from the contract.
            required_fields: Exact fields required by the contract.
            digest_pattern: Accepted immutable source digest pattern.
            observed: Tool versions collected by the surrounding validation.

        Returns:
            Ordered findings for this tool. Valid IDs and versions are added to
            ``observed`` before their remaining fields are checked.
        """
        tool = _object_mapping(raw_tool)
        if tool is None or set(tool) != required_fields:
            return [f"tools[{index}] fields drifted"]
        tool_id = tool.get("tool_id")
        version = tool.get("version")
        if not isinstance(tool_id, str) or tool_id in observed:
            return [f"tools[{index}] has an invalid or duplicate ID"]
        if not isinstance(version, str) or not version or "latest" in version.lower():
            return [f"{tool_id}: version must be exact and non-floating"]
        observed[tool_id] = version
        errors: list[str] = []
        if tool.get("supported_systems") != EXPECTED_SYSTEMS:
            errors.append(f"{tool_id}: supported systems drifted")
        digest = tool.get("source_digest")
        if not isinstance(digest, str) or digest_pattern.fullmatch(digest) is None:
            errors.append(f"{tool_id}: source digest is not immutable")
        source_url = tool.get("source_url")
        if not isinstance(source_url, str) or not source_url.startswith("https://"):
            errors.append(f"{tool_id}: source URL must be HTTPS")
        if not isinstance(tool.get("transitive_native_dependencies"), list):
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
            field_value = tool.get(field)
            if not isinstance(field_value, str) or not field_value:
                errors.append(f"{tool_id}: {field} must be populated")
        return errors

    def _flake_lock_errors(self, document: object) -> list[str]:
        """Validate the raw flake-lock structure and reviewed nixpkgs identity.

        Args:
            document: Raw JSON decoder output.

        Returns:
            Ordered lock findings.
        """
        record = _object_mapping(document)
        if record is None:
            return ["flake lock structure is incomplete"]
        nodes = _object_mapping(record.get("nodes"))
        if nodes is None:
            return ["flake lock structure is incomplete"]
        nixpkgs = _object_mapping(nodes.get("nixpkgs"))
        root = _object_mapping(nodes.get("root"))
        if nixpkgs is None or root is None:
            return ["flake lock structure is incomplete"]
        locked = _object_mapping(nixpkgs.get("locked"))
        original = _object_mapping(nixpkgs.get("original"))
        root_inputs = _object_mapping(root.get("inputs"))
        if locked is None or original is None or root_inputs is None:
            return ["flake lock structure is incomplete"]
        errors: list[str] = []
        if record.get("version") != 7:
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

    def _evidence_errors(self) -> list[str]:
        """Validate local evidence identities, gates and report digests.

        Returns:
            Ordered evidence findings.

        Raises:
            OSError: If the evidence manifest or report cannot be read.
            UnicodeDecodeError: If the manifest is not valid UTF-8.
            tomllib.TOMLDecodeError: If the manifest is not valid TOML.
        """
        bundle_root = self._root / "docs/governance/evidence/examples/b03-r2-partial"
        manifest_path = bundle_root / "manifest.toml"
        if not manifest_path.is_file():
            return ["developer-environment evidence manifest is missing"]
        manifest = _object_mapping(_TOML_LOADS(manifest_path.read_text(encoding="utf-8")))
        assert manifest is not None
        errors: list[str] = []
        if _report_artifact_path(bundle_root, "reports/../../outside.txt") is not None:
            errors.append("artifact path traversal must fail closed")
        expected_gates: set[str] = {
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
        expected_change: dict[str, object] = {
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
        errors.extend(self._gate_errors(manifest.get("gates"), expected_gates))
        artifacts = _object_list(manifest.get("artifacts"))
        if artifacts is None or len(artifacts) != 4:
            errors.append("evidence must contain four artifact classes")
        else:
            for raw_artifact in artifacts:
                artifact = _object_mapping(raw_artifact)
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
                if digest != hashlib.sha256(artifact_path.read_bytes()).hexdigest():
                    errors.append(f"evidence digest mismatch: {relative}")
        return errors

    def _gate_errors(self, raw_gates: object, expected_gates: set[str]) -> list[str]:
        """Validate gate entries without allowing malformed IDs to escape.

        Args:
            raw_gates: Raw manifest gate collection.
            expected_gates: Exact set of gate IDs required by the evidence
                profile.

        Returns:
            One applicable-gates finding for a malformed or incomplete set, one
            status finding for complete IDs with a failed gate, or an empty
            list for a complete passed set.
        """
        gates = _object_list(raw_gates)
        if gates is None:
            return ["evidence must bind the exact applicable R2 gates"]
        records: list[dict[object, object]] = []
        gate_ids: set[str] = set()
        for raw_gate in gates:
            gate = _object_mapping(raw_gate)
            if gate is None:
                return ["evidence must bind the exact applicable R2 gates"]
            gate_id = gate.get("gate_id")
            if not isinstance(gate_id, str):
                return ["evidence must bind the exact applicable R2 gates"]
            records.append(gate)
            gate_ids.add(gate_id)
        if gate_ids != expected_gates:
            return ["evidence must bind the exact applicable R2 gates"]
        if any(record.get("status") != "passed" for record in records):
            return ["repository-local developer-environment gate evidence must pass"]
        return []

    def _check_environment_files(self) -> list[str]:
        """Check exact flake, Python, Bazel and direnv contract fragments.

        Returns:
            Ordered environment-file findings for this invocation.
        """
        errors: list[str] = []
        flake = (self._root / "flake.nix").read_text(encoding="utf-8")
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
        if (self._root / ".python-version").read_text(encoding="utf-8").strip() != "3.12.14":
            errors.append("Python version drifted from the developer-environment toolchain")
        if (self._root / ".bazelversion").read_text(encoding="utf-8").strip() != "9.1.0":
            errors.append("Bazel version drifted from the developer-environment toolchain")
        if (self._root / ".envrc").read_text(
            encoding="utf-8"
        ).strip() != "use flake --no-write-lock-file":
            errors.append("direnv must consume the locked flake without rewriting it")
        return errors

    def _mutation_probe_errors(self, contract: dict[str, object]) -> list[str]:
        """Exercise duplicate, unsupported and floating contract mutations.

        Args:
            contract: Validated string-keyed contract fixture.

        Returns:
            Ordered mutation-probe findings for this invocation.
        """
        errors: list[str] = []
        duplicate = deepcopy(contract)
        duplicate_tools = _object_list(duplicate.get("tools"))
        assert duplicate_tools is not None and duplicate_tools
        duplicate_tool = _object_mapping(duplicate_tools[0])
        assert duplicate_tool is not None
        duplicate_tools.append(duplicate_tool.copy())
        duplicate["tools"] = duplicate_tools
        if not any("duplicate ID" in error for error in self._contract_errors(duplicate)):
            errors.append("duplicate tool IDs must fail closed")

        unsupported = deepcopy(contract)
        unsupported["supported_systems"] = [*EXPECTED_SYSTEMS, "aarch64-linux"]
        if not any("supported_systems" in error for error in self._contract_errors(unsupported)):
            errors.append("an unsupported platform must fail closed")

        floating = deepcopy(contract)
        floating_tools = _object_list(floating.get("tools"))
        assert floating_tools is not None and floating_tools
        floating_tool = _object_mapping(floating_tools[0])
        assert floating_tool is not None
        floating_tool["version"] = "latest"
        floating_tools[0] = floating_tool
        floating["tools"] = floating_tools
        if not any("non-floating" in error for error in self._contract_errors(floating)):
            errors.append("a floating tool version must fail closed")
        return errors

    def _malformed_input_errors(self) -> list[str]:
        """Exercise malformed contract and flake-lock root shapes.

        Returns:
            Ordered malformed-input findings for this invocation.
        """
        errors: list[str] = []
        malformed_values: tuple[object, ...] = (None, [], "invalid", 7, True)
        for malformed in malformed_values:
            if not self._contract_errors(malformed) or not self._contract_errors(
                {"tools": malformed}
            ):
                errors.append("malformed contract tables must fail closed")
            malformed_locks: tuple[object, ...] = (
                malformed,
                {},
                {"nodes": malformed},
                {"nodes": {"nixpkgs": malformed, "root": {"inputs": {}}}},
                {"nodes": {"nixpkgs": {}, "root": malformed}},
                {
                    "nodes": {
                        "nixpkgs": {"locked": malformed, "original": {}},
                        "root": {"inputs": {}},
                    }
                },
                {
                    "nodes": {
                        "nixpkgs": {"locked": {}, "original": malformed},
                        "root": {"inputs": {}},
                    }
                },
                {
                    "nodes": {
                        "nixpkgs": {"locked": {}, "original": {}},
                        "root": {"inputs": malformed},
                    }
                },
            )
            for malformed_lock in malformed_locks:
                if self._flake_lock_errors(malformed_lock) != [
                    "flake lock structure is incomplete"
                ]:
                    errors.append("malformed flake lock tables must fail closed")
        return errors

    def _bootstrap_errors(self) -> list[str]:
        """Check bootstrap naming and its two invalid command diagnostics.

        Returns:
            Ordered bootstrap findings for this invocation.
        """
        errors: list[str] = []
        script = self._root / "environments/dev/bootstrap.sh"
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
        return errors


def main() -> int:
    """Check pinned environment files and malformed-input rejection.

    Returns:
        Zero on success, or one after writing contract errors to standard error.

    Raises:
        AssertionError: If a required valid fixture cannot be used for its
            malformed-input probes, or a bootstrap probe succeeds.
        KeyError: If Bazel does not provide its runfiles environment.
        OSError: If a required repository file cannot be read.
        UnicodeDecodeError: If a required text file is not valid UTF-8.
        json.JSONDecodeError: If ``flake.lock`` is not valid JSON.
        tomllib.TOMLDecodeError: If a required TOML file is not valid TOML.
    """
    return DeveloperEnvironmentContractChecker(_repository_root()).run()


if __name__ == "__main__":
    raise SystemExit(main())
