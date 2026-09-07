"""Regression tests for native wheel evidence and signature boundaries."""

from __future__ import annotations

# standard library imports
import base64
import hashlib
import io
import json
import os
import subprocess
import tomllib
from datetime import date
from pathlib import Path
from typing import TypeGuard

# third party library imports
import pytest
from pydantic import BaseModel, TypeAdapter

# project library imports
from alpha_research_governance.dependency_admission import load_policy
from alpha_research_governance.dependency_admission.models import (
    BootstrapWheelAdmission,
    DependencyAdmissionError,
    EvidenceFile,
    PythonPackageAdmission,
    SourceArchive,
    WheelProvenance,
    WheelSourceAdmission,
)
from alpha_research_governance.dependency_admission.wheel_sources import (
    parse_wheel_sources,
    verify_bootstrap_wheels,
    verify_wheel_sources,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs/architecture/dependency-admission.toml"
LOCK_PATH = REPOSITORY_ROOT / "uv.lock"


def _model_payload(model: BaseModel) -> dict[str, object]:
    """Convert one validated Pydantic record to a typed JSON mapping."""
    raw: object = model.model_dump(mode="json")
    return TypeAdapter(dict[str, object]).validate_python(raw)


def _is_string_mapping(value: object) -> TypeGuard[dict[str, object]]:
    """Identify a mutable JSON object with string keys."""
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _mapping(value: object) -> dict[str, object]:
    """Narrow one nested JSON object while retaining its mutable identity."""
    if not _is_string_mapping(value):
        raise TypeError("expected a JSON object with string keys")
    return value


def _evidence_file(root: Path, filename: str, content: bytes) -> EvidenceFile:
    """Write fixture bytes and return their digest-bound evidence identity."""
    path = root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return EvidenceFile(path=filename, sha256=hashlib.sha256(content).hexdigest())


def _source_fixture(root: Path) -> tuple[WheelSourceAdmission, dict[str, object]]:
    """Build a synthetic source-bound native wheel record and matching lock fragment."""
    source = SourceArchive(
        uri="https://example.invalid/source/" + "a" * 40,
        revision="a" * 40,
        sha256="b" * 64,
        license_expression="BSD-3-Clause",
    )
    parameters: dict[str, object] = {
        "externalParameters": {"version": "2.4.6"},
        "internalParameters": {},
    }
    wheels: list[WheelProvenance] = []
    locked_wheels: list[dict[str, str]] = []
    for platform, digest in (
        ("macosx_11_0_arm64", "c" * 64),
        ("manylinux_2_28_x86_64", "d" * 64),
    ):
        filename = f"numpy-2.4.6-cp312-cp312-{platform}.whl"
        statement: dict[str, object] = {
            "_type": "https://in-toto.io/Statement/v1",
            "predicateType": "https://slsa.dev/provenance/v1",
            "subject": [{"name": filename, "digest": {"sha256": digest}}],
            "predicate": {
                "buildDefinition": {
                    "buildType": "https://example.invalid/native-wheel/v1",
                    **parameters,
                    "resolvedDependencies": [
                        {
                            "uri": source.uri,
                            "digest": {"sha256": source.sha256, "gitCommit": source.revision},
                        }
                    ],
                },
                "runDetails": {"builder": {"id": "https://example.invalid/builder"}},
            },
        }
        bundle = {
            "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
            "verificationMaterial": {},
            "dsseEnvelope": {
                "payloadType": "application/vnd.in-toto+json",
                "payload": base64.b64encode(json.dumps(statement).encode()).decode(),
                "signatures": [],
            },
        }
        bundle_path = f"bundles/{platform}.json"
        wheels.append(
            WheelProvenance(
                filename=filename,
                sha256=digest,
                bundle=_evidence_file(root, bundle_path, json.dumps(bundle).encode()),
            )
        )
        locked_wheels.append(
            {"url": "https://files.pythonhosted.org/" + filename, "hash": "sha256:" + digest}
        )
    record = WheelSourceAdmission(
        name="numpy",
        version="2.4.6",
        rationale="Synthetic native-wheel source evidence for deterministic boundary tests.",
        sources=(source,),
        wheels=tuple(wheels),
        builder_id="https://example.invalid/builder",
        build_type="https://example.invalid/native-wheel/v1",
        build_parameters_sha256=hashlib.sha256(
            json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        certificate_identity="https://example.invalid/workflow@refs/tags/v1",
        oidc_issuer="https://example.invalid/issuer",
        trusted_root=_evidence_file(root, "trust.json", b"{}"),
    )
    locked: dict[str, object] = {
        "version": "2.4.6",
        "source": {"registry": "https://pypi.org/simple"},
        "wheels": locked_wheels,
    }
    return record, locked


def _parse_source_record(value: object) -> tuple[WheelSourceAdmission, ...]:
    """Parse the synthetic source record against an exact native package admission."""
    package = PythonPackageAdmission(
        name="numpy",
        version="2.4.6",
        native_artifacts=True,
        license_expression="BSD-3-Clause",
    )
    return parse_wheel_sources(value, (package,), {"BSD-3-Clause"})


def _successful_cosign(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    """Return deterministic Cosign version and verification success output."""
    output = kwargs["stdout"]
    assert isinstance(output, io.TextIOBase)
    output.write("GitVersion:    v3.1.3\n" if command[1:] == ["version"] else "Verified OK\n")
    return subprocess.CompletedProcess(command, 0)


def _missing_cosign(_name: str) -> str | None:
    """Report that the requested Cosign executable is unavailable."""
    return None


@pytest.fixture()
def cosign_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Resolve Cosign to a temporary placeholder while subprocess execution is mocked.

    Args:
        tmp_path: Temporary directory receiving the placeholder executable.
        monkeypatch: Pytest patcher for the module's executable lookup.

    Returns:
        The placeholder executable path.
    """
    executable = tmp_path / "cosign"
    executable.write_text("synthetic executable path", encoding="utf-8")

    def find_cosign(_name: str) -> str:
        """Return the fixture executable path for the requested binary name.

        Args:
            _name: Requested executable name, ignored by the fixture.

        Returns:
            The placeholder executable path.
        """
        return str(executable)

    monkeypatch.setattr(
        "alpha_research_governance.dependency_admission.wheel_sources.shutil.which",
        find_cosign,
    )
    return executable


def _bootstrap_fixture(root: Path) -> tuple[BootstrapWheelAdmission, dict[str, object]]:
    """Copy current QuantLib bootstrap evidence and build its exact lock fragment."""
    policy = load_policy(POLICY_PATH)
    record = policy.bootstrap_wheel_admissions[0]
    assert record.finding_id == "quantlib-wheel-binding"
    evidence = (
        record.trusted_root,
        record.source_review,
        record.security_review,
        record.native_inventory,
        record.compatibility_report,
        *(wheel.bundle for wheel in record.wheels),
    )
    for item in evidence:
        target = root / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPOSITORY_ROOT / item.path).read_bytes())
    raw_lock: object = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))
    lock = TypeAdapter(dict[str, object]).validate_python(raw_lock)
    packages = TypeAdapter(list[dict[str, object]]).validate_python(lock["package"])
    quantlib = next(package for package in packages if package.get("name") == "quantlib")
    return record, {
        "version": quantlib["version"],
        "source": quantlib["source"],
        "wheels": quantlib["wheels"],
    }


class TestSourceBoundWheelVerification:
    """Exercise source provenance, local evidence, and Cosign boundaries."""

    def test_source_bound_wheels_verify_with_staged_trust_evidence(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cosign_path: Path,
    ) -> None:
        """Accept matching source claims and pass private staged files to Cosign."""
        record, locked = _source_fixture(tmp_path)
        assert _parse_source_record([_model_payload(record)]) == (record,)
        calls: list[list[str]] = []

        def inspect(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            """Record verifier argv and preserve the deterministic success result.

            Args:
                command: Cosign argument vector to record.
                kwargs: Subprocess options passed to the mocked runner.

            Returns:
                A deterministic successful process result.
            """
            calls.append(command)
            assert command[0] == str(cosign_path)
            assert kwargs["timeout"] == 60
            assert kwargs["env"] == {"PATH": os.environ.get("PATH", "")}
            return _successful_cosign(command, **kwargs)

        monkeypatch.setattr(subprocess, "run", inspect)
        verify_wheel_sources(tmp_path, locked, record)

        assert len(calls) == len(record.wheels) + 1
        assert {call[call.index("--digest") + 1] for call in calls[1:]} == {
            wheel.sha256 for wheel in record.wheels
        }

    @pytest.mark.parametrize("failure", ["signature", "missing_cosign"])
    def test_wheel_verification_rejects_signature_or_missing_cosign(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        failure: str,
        cosign_path: Path,
    ) -> None:
        """Block source admission when the verifier is absent or rejects a signature."""
        record, locked = _source_fixture(tmp_path)
        if failure == "missing_cosign":
            monkeypatch.setattr(
                "alpha_research_governance.dependency_admission.wheel_sources.shutil.which",
                _missing_cosign,
            )
        else:

            def reject_signature(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                """Return version success and signature failure for the selected case.

                Args:
                    command: Cosign argument vector under test.
                    kwargs: Subprocess options passed to the mocked runner.

                Returns:
                    Version success or signature failure according to the command.
                """
                if command[1:] == ["version"]:
                    return _successful_cosign(command, **kwargs)
                return subprocess.CompletedProcess(command, 1)

            monkeypatch.setattr(subprocess, "run", reject_signature)
        with pytest.raises(DependencyAdmissionError, match="Cosign"):
            verify_wheel_sources(tmp_path, locked, record)

    @pytest.mark.parametrize("mutation", ["wheel", "source"])
    def test_wheel_and_source_identity_must_match_admitted_claims(
        self, tmp_path: Path, mutation: str, cosign_path: Path
    ) -> None:
        """Reject a lock digest change and an immutable source revision change."""
        record, locked = _source_fixture(tmp_path)
        if mutation == "wheel":
            wheels = TypeAdapter(list[dict[str, object]]).validate_python(locked["wheels"])
            wheels[0]["hash"] = "sha256:" + "e" * 64
            locked["wheels"] = wheels
            with pytest.raises(DependencyAdmissionError, match="exact locked wheel set"):
                verify_wheel_sources(tmp_path, locked, record)
        else:
            data = _model_payload(record)
            source = _mapping(TypeAdapter(list[object]).validate_python(data["sources"])[0])
            source["uri"] = "https://example.invalid/source/main"
            with pytest.raises(DependencyAdmissionError, match="immutable revision"):
                _parse_source_record([data])

    @pytest.mark.parametrize("mutation", ["traversal", "symlink", "tamper"])
    def test_local_evidence_rejects_unsafe_paths_symlinks_and_tampering(
        self,
        tmp_path: Path,
        mutation: str,
        monkeypatch: pytest.MonkeyPatch,
        cosign_path: Path,
    ) -> None:
        """Reject path traversal, symlink traversal, and digest-tampered evidence."""
        record, locked = _source_fixture(tmp_path)
        if mutation == "traversal":
            data = _model_payload(record)
            trusted_root = _mapping(data["trusted_root"])
            trusted_root["path"] = "../outside.json"
            with pytest.raises(DependencyAdmissionError, match="canonical and relative"):
                _parse_source_record([data])
            return
        trust = tmp_path / record.trusted_root.path
        if mutation == "symlink":
            trust.unlink()
            trust.symlink_to(tmp_path / record.wheels[0].bundle.path)
        else:
            trust.write_bytes(b"tampered")
        monkeypatch.setattr(subprocess, "run", _successful_cosign)
        with pytest.raises(DependencyAdmissionError, match=r"symlinks|digest mismatch"):
            verify_wheel_sources(tmp_path, locked, record)


class TestQuantLibBootstrapVerification:
    """Exercise the retained bounded QuantLib bootstrap exception."""

    def test_quantlib_bootstrap_evidence_verifies_with_mocked_cosign(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cosign_path: Path,
    ) -> None:
        """Accept current QuantLib reports and publication bundles inside the review window."""
        record, locked = _bootstrap_fixture(tmp_path)
        calls: list[list[str]] = []

        def inspect(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            """Record publication verifier calls and return deterministic success.

            Args:
                command: Cosign argument vector to record.
                kwargs: Subprocess options passed to the mocked runner.

            Returns:
                A deterministic successful process result.
            """
            calls.append(command)
            return _successful_cosign(command, **kwargs)

        monkeypatch.setattr(subprocess, "run", inspect)
        verify_bootstrap_wheels(tmp_path, locked, record, validation_date=date(2026, 9, 7))

        assert record.finding_id == "quantlib-wheel-binding"
        assert len(calls) == len(record.wheels) + 1

    def test_bootstrap_admission_expires_after_bounded_review(self, tmp_path: Path) -> None:
        """Reject QuantLib bootstrap use after its explicit review deadline."""
        record, locked = _bootstrap_fixture(tmp_path)

        with pytest.raises(DependencyAdmissionError, match="expired or not yet effective"):
            verify_bootstrap_wheels(tmp_path, locked, record, validation_date=date(2026, 10, 5))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
