"""Regression tests for retained native publication evidence boundaries."""

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

# third party library imports
import pytest
from pydantic import TypeAdapter

# project library imports
from alpha_research_governance.dependency_admission import load_policy
from alpha_research_governance.dependency_admission.models import (
    BootstrapWheelAdmission,
    DependencyAdmissionError,
    EvidenceFile,
    WheelProvenance,
)
from alpha_research_governance.dependency_admission.wheel_sources import verify_bootstrap_wheels

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs/architecture/dependency-admission.toml"
LOCK_PATH = REPOSITORY_ROOT / "uv.lock"


def _successful_cosign(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    """Return deterministic Cosign version and publication verification success."""
    output = kwargs["stdout"]
    assert isinstance(output, io.TextIOBase)
    output.write("GitVersion:    v3.1.3\n" if command[1:] == ["version"] else "Verified OK\n")
    return subprocess.CompletedProcess(command, 0)


def _bootstrap_fixture(root: Path) -> tuple[BootstrapWheelAdmission, dict[str, object]]:
    """Copy retained QuantLib evidence and build its exact lock fragment."""
    policy = load_policy(POLICY_PATH)
    record = policy.bootstrap_wheel_admissions[0]
    assert record.finding_id == "quantlib-wheel-binding"
    evidence: tuple[EvidenceFile, ...] = (
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


def _record_with_wrong_subject(
    root: Path, record: BootstrapWheelAdmission
) -> BootstrapWheelAdmission:
    """Rewrite one copied bundle with a different exact publication subject."""
    wheel = record.wheels[0]
    path = root / wheel.bundle.path
    document = TypeAdapter(dict[str, object]).validate_json(path.read_bytes())
    envelope = TypeAdapter(dict[str, object]).validate_python(document["dsseEnvelope"])
    payload = envelope["payload"]
    assert isinstance(payload, str)
    statement = TypeAdapter(dict[str, object]).validate_json(base64.b64decode(payload))
    statement["subject"] = [{"name": "other-package.whl", "digest": {"sha256": wheel.sha256}}]
    envelope["payload"] = base64.b64encode(json.dumps(statement).encode()).decode()
    document["dsseEnvelope"] = envelope
    content = json.dumps(document).encode()
    path.write_bytes(content)
    rewritten = WheelProvenance(
        filename=wheel.filename,
        sha256=wheel.sha256,
        bundle=EvidenceFile(path=wheel.bundle.path, sha256=hashlib.sha256(content).hexdigest()),
    )
    return BootstrapWheelAdmission(
        name=record.name,
        version=record.version,
        rationale=record.rationale,
        sources=record.sources,
        certificate_identity=record.certificate_identity,
        oidc_issuer=record.oidc_issuer,
        trusted_root=record.trusted_root,
        wheels=(rewritten, *record.wheels[1:]),
        usage=record.usage,
        source_to_wheel_binding=record.source_to_wheel_binding,
        finding_id=record.finding_id,
        reviewed_on=record.reviewed_on,
        expires_on=record.expires_on,
        residual_risk=record.residual_risk,
        closure_condition=record.closure_condition,
        source_review=record.source_review,
        security_review=record.security_review,
        native_inventory=record.native_inventory,
        compatibility_report=record.compatibility_report,
    )


@pytest.fixture()
def cosign_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Resolve Cosign to a temporary placeholder while execution is mocked.

    Args:
        tmp_path: Isolated temporary test directory.
        monkeypatch: Fixture used to replace executable discovery.

    Returns:
        Temporary executable path supplied to the verifier.
    """
    executable = tmp_path / "cosign"
    executable.write_text("synthetic executable path", encoding="utf-8")

    def find_cosign(_name: str) -> str:
        """Return the fixture executable for the requested binary name.

        Args:
            _name: Executable name requested by the verifier.

        Returns:
            Fixture executable path.
        """
        return str(executable)

    monkeypatch.setattr(
        "alpha_research_governance.dependency_admission.wheel_sources.shutil.which",
        find_cosign,
    )
    return executable


class TestQuantLibBootstrapVerification:
    """Exercise publication identity, trusted-root staging, and expiry."""

    def test_publication_identity_and_trust_are_verified(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cosign_path: Path,
    ) -> None:
        """Pass exact publisher and staged trust-root identities to Cosign."""
        record, locked = _bootstrap_fixture(tmp_path)
        calls: list[list[str]] = []

        def inspect(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            """Record Cosign argv and return deterministic success.

            Args:
                command: Complete Cosign argument vector.
                kwargs: Process options supplied by the verifier.

            Returns:
                Successful synthetic process result.
            """
            calls.append(command)
            assert kwargs["env"] == {"PATH": os.environ.get("PATH", "")}
            return _successful_cosign(command, **kwargs)

        monkeypatch.setattr(subprocess, "run", inspect)
        verify_bootstrap_wheels(tmp_path, locked, record, validation_date=date(2026, 9, 7))

        assert len(calls) == len(record.wheels) + 1
        for command in calls[1:]:
            assert (
                command[command.index("--certificate-identity") + 1] == record.certificate_identity
            )
            assert command[command.index("--certificate-oidc-issuer") + 1] == record.oidc_issuer
            assert command[command.index("--trusted-root") + 1] != record.trusted_root.path
        assert calls[0][0] == str(cosign_path)

    def test_tampered_or_symlinked_trust_root_is_rejected(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cosign_path: Path,
    ) -> None:
        """Reject changed or symlinked local trust evidence before Cosign."""
        record, locked = _bootstrap_fixture(tmp_path)
        trust = tmp_path / record.trusted_root.path
        trust.write_bytes(b"tampered")
        monkeypatch.setattr(subprocess, "run", _successful_cosign)
        with pytest.raises(DependencyAdmissionError, match="digest mismatch"):
            verify_bootstrap_wheels(tmp_path, locked, record, validation_date=date(2026, 9, 7))
        trust.write_bytes((REPOSITORY_ROOT / record.trusted_root.path).read_bytes())
        trust.unlink()
        trust.symlink_to(tmp_path / record.wheels[0].bundle.path)
        with pytest.raises(DependencyAdmissionError, match="symlinks"):
            verify_bootstrap_wheels(tmp_path, locked, record, validation_date=date(2026, 9, 7))

    def test_wrong_publication_subject_is_rejected(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cosign_path: Path,
    ) -> None:
        """Reject a validly hashed bundle whose statement names another wheel."""
        record, locked = _bootstrap_fixture(tmp_path)
        record = _record_with_wrong_subject(tmp_path, record)
        monkeypatch.setattr(subprocess, "run", _successful_cosign)
        with pytest.raises(DependencyAdmissionError, match="subject mismatch"):
            verify_bootstrap_wheels(tmp_path, locked, record, validation_date=date(2026, 9, 7))

    def test_cosign_signature_failure_is_rejected(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cosign_path: Path,
    ) -> None:
        """Propagate a failed native signature verification as an admission error."""
        record, locked = _bootstrap_fixture(tmp_path)

        def reject_signature(
            command: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            """Pass version discovery but fail the publication signature check.

            Args:
                command: Complete Cosign argument vector.
                kwargs: Process options supplied by the verifier.

            Returns:
                Version success or signature failure process result.
            """
            if command[1:] == ["version"]:
                return _successful_cosign(command, **kwargs)
            return subprocess.CompletedProcess(command, 1)

        monkeypatch.setattr(subprocess, "run", reject_signature)
        with pytest.raises(DependencyAdmissionError, match="Cosign verification failed"):
            verify_bootstrap_wheels(tmp_path, locked, record, validation_date=date(2026, 9, 7))

    def test_bootstrap_admission_expires_after_bounded_review(self, tmp_path: Path) -> None:
        """Reject QuantLib bootstrap use after its explicit review deadline."""
        record, locked = _bootstrap_fixture(tmp_path)
        with pytest.raises(DependencyAdmissionError, match="expired or not yet effective"):
            verify_bootstrap_wheels(tmp_path, locked, record, validation_date=date(2026, 10, 5))
