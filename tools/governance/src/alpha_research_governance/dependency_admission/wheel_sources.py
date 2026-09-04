"""Verify the narrow wheel-only source admission profile without trusting producer claims."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import subprocess  # nosec B404  # [owner=platform; rationale=pinned Cosign verification only; expires=2027-03-01]
import tempfile
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import urlsplit

from pydantic import TypeAdapter, ValidationError

from alpha_research_governance.dependency_admission.models import (
    DependencyAdmissionError,
    EvidenceFile,
    PythonPackageAdmission,
    WheelSourceAdmission,
)

_COSIGN_VERSION = "3.1.3"
_PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
_MAX_EVIDENCE_BYTES = 5_000_000
_MAX_WHEELS = 100


def _https(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or re.search(r"[\s\x00-\x1f]", value)
    ):
        raise DependencyAdmissionError(["source evidence requires credential-free HTTPS URLs"])


def _relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {".", ".."} for part in path.parts)
        or path.as_posix() != value
        or re.fullmatch(r"[A-Za-z0-9_./-]+", value) is None
    ):
        raise DependencyAdmissionError(["source evidence path must be canonical and relative"])


def parse_wheel_sources(
    value: object,
    packages: tuple[PythonPackageAdmission, ...],
    approved_licenses: set[str],
) -> tuple[WheelSourceAdmission, ...]:
    """Parse explicit alternatives; absent records never exempt a missing source archive."""
    try:
        records = TypeAdapter(tuple[WheelSourceAdmission, ...]).validate_json(json.dumps(value))
    except (ValidationError, ValueError, TypeError) as error:
        raise DependencyAdmissionError(["invalid wheel source admission fields"]) from error
    admitted = {package.name: package for package in packages}
    names = [record.name for record in records]
    if len(names) != len(set(names)):
        raise DependencyAdmissionError(["duplicate wheel source admission"])
    for record in records:
        package = admitted.get(record.name)
        if package is None or record.version != package.version or not package.native_artifacts:
            raise DependencyAdmissionError(["wheel sources must match an exact native admission"])
        if record.owner_role != "platform":
            raise DependencyAdmissionError(["wheel source admission requires Platform ownership"])
        if not 1 <= len(record.sources) <= 100 or not 1 <= len(record.wheels) <= _MAX_WHEELS:
            raise DependencyAdmissionError(["wheel source and artifact counts are out of bounds"])
        for url in (
            record.builder_id,
            record.build_type,
            record.certificate_identity,
            record.oidc_issuer,
        ):
            _https(url)
        for source in record.sources:
            _https(source.uri)
            if source.revision not in urlsplit(source.uri).path.split("/"):
                raise DependencyAdmissionError(["source URI must contain its immutable revision"])
            if source.license_expression not in approved_licenses:
                raise DependencyAdmissionError(["source archive license is not admitted"])
        for values in (
            [source.uri for source in record.sources],
            [wheel.filename for wheel in record.wheels],
            [wheel.bundle.path for wheel in record.wheels],
        ):
            if len(values) != len(set(values)):
                raise DependencyAdmissionError(["duplicate source or wheel evidence identity"])
        for wheel in record.wheels:
            components = wheel.filename.split("-")
            if (
                re.fullmatch(r"[A-Za-z0-9_+.\-]+\.whl", wheel.filename) is None
                or len(components) not in {5, 6}
                or components[0].lower() != re.sub(r"[-_.]+", "_", record.name)
                or components[1] != record.version
            ):
                raise DependencyAdmissionError(["invalid wheel filename"])
        for evidence in (record.trusted_root, *(wheel.bundle for wheel in record.wheels)):
            _relative_path(evidence.path)
    return records


def _read_evidence(root: Path, record: EvidenceFile) -> bytes:
    # Reject symlinks at every component, including links that stay within the checkout.
    _relative_path(record.path)
    path = root
    try:
        for part in PurePosixPath(record.path).parts:
            path = path / part
            if path.is_symlink():
                raise DependencyAdmissionError(["source evidence must not traverse symlinks"])
        if not path.is_file():
            raise DependencyAdmissionError([f"missing regular source evidence: {record.path}"])
        with path.open("rb") as stream:
            content = stream.read(_MAX_EVIDENCE_BYTES + 1)
    except OSError as error:
        raise DependencyAdmissionError([f"cannot read source evidence: {record.path}"]) from error
    if len(content) > _MAX_EVIDENCE_BYTES:
        raise DependencyAdmissionError(["source evidence exceeds the size bound"])
    if hashlib.sha256(content).hexdigest() != record.sha256:
        raise DependencyAdmissionError([f"source evidence digest mismatch: {record.path}"])
    return content


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DependencyAdmissionError(["duplicate provenance JSON key"])
        result[key] = value
    return result


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise DependencyAdmissionError(["provenance requires JSON objects"])
    return cast(dict[str, object], value)


def _json_object(content: bytes) -> dict[str, object]:
    try:
        return _object(
            json.loads(
                content, object_pairs_hook=_unique_object, parse_constant=_reject_json_constant
            )
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise DependencyAdmissionError(["invalid provenance JSON"]) from error


def _reject_json_constant(value: str) -> object:
    raise DependencyAdmissionError([f"non-finite provenance JSON constant: {value}"])


def _statement(bundle: bytes) -> dict[str, object]:
    document = _json_object(bundle)
    if (
        set(document) != {"mediaType", "verificationMaterial", "dsseEnvelope"}
        or document.get("mediaType") != "application/vnd.dev.sigstore.bundle.v0.3+json"
    ):
        raise DependencyAdmissionError(["only Sigstore v0.3 DSSE bundles are supported"])
    envelope = _object(document["dsseEnvelope"])
    if (
        set(envelope) != {"payloadType", "payload", "signatures"}
        or envelope.get("payloadType") != "application/vnd.in-toto+json"
    ):
        raise DependencyAdmissionError(["invalid in-toto envelope"])
    payload = envelope.get("payload")
    if not isinstance(payload, str):
        raise DependencyAdmissionError(["missing DSSE payload"])
    try:
        return _json_object(base64.b64decode(payload, validate=True))
    except (ValueError, binascii.Error) as error:
        raise DependencyAdmissionError(["invalid DSSE payload encoding"]) from error


def _check_statement(
    statement: dict[str, object], record: WheelSourceAdmission, filename: str, digest: str
) -> None:
    if (
        set(statement) != {"_type", "predicateType", "subject", "predicate"}
        or statement.get("_type") != "https://in-toto.io/Statement/v1"
        or statement.get("predicateType") != _PREDICATE_TYPE
        or statement.get("subject") != [{"name": filename, "digest": {"sha256": digest}}]
    ):
        raise DependencyAdmissionError(["provenance type or exact wheel subject mismatch"])
    predicate = _object(statement["predicate"])
    if set(predicate) != {"buildDefinition", "runDetails"}:
        raise DependencyAdmissionError(["unsupported SLSA predicate fields"])
    build = _object(predicate["buildDefinition"])
    run = _object(predicate["runDetails"])
    if set(build) != {
        "buildType",
        "externalParameters",
        "internalParameters",
        "resolvedDependencies",
    } or set(run) - {"builder", "metadata", "byproducts"}:
        raise DependencyAdmissionError(["unsupported SLSA build or run fields"])
    if build["buildType"] != record.build_type or _object(run.get("builder")) != {
        "id": record.builder_id
    }:
        raise DependencyAdmissionError(["provenance builder or build type mismatch"])
    parameters = {key: _object(build[key]) for key in ("externalParameters", "internalParameters")}
    try:
        canonical = json.dumps(parameters, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except ValueError as error:
        raise DependencyAdmissionError(["non-finite provenance build parameters"]) from error
    if hashlib.sha256(canonical.encode()).hexdigest() != record.build_parameters_sha256:
        raise DependencyAdmissionError(["provenance build parameters mismatch"])
    expected = [
        {"uri": source.uri, "digest": {"sha256": source.sha256, "gitCommit": source.revision}}
        for source in record.sources
    ]
    if build["resolvedDependencies"] != expected:
        raise DependencyAdmissionError(["provenance source materials mismatch"])


def _cosign(arguments: list[str], executable: str) -> str:
    # Keep diagnostics bounded; the verifier uses pinned local trust material and no shell.
    try:
        with tempfile.TemporaryFile(mode="w+") as output:
            result = subprocess.run(  # nosec B603  # [owner=platform; rationale=fixed Cosign argv with pinned local inputs; expires=2027-03-01]
                [executable, *arguments],
                stdout=output,
                stderr=output,
                text=True,
                check=False,
                timeout=60,
                env={"PATH": os.environ.get("PATH", "")},
            )
            output.seek(0)
            diagnostic = output.read(4000)
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as error:
        raise DependencyAdmissionError(["Cosign verification unavailable or timed out"]) from error
    if result.returncode != 0:
        raise DependencyAdmissionError([f"Cosign verification failed: {diagnostic.strip()}"])
    return diagnostic


def verify_wheel_sources(
    root: Path, locked: dict[str, object], record: WheelSourceAdmission
) -> None:
    """Check every locked wheel's materials and authenticate the same bytes with Cosign."""
    if "sdist" in locked:
        raise DependencyAdmissionError(["wheel-only admission cannot replace an existing sdist"])
    wheels = locked.get("wheels")
    if not isinstance(wheels, list):
        raise DependencyAdmissionError(["wheel-only admission requires locked wheels"])
    observed: dict[str, str] = {}
    for wheel in wheels:
        item = _object(wheel)
        url, digest = item.get("url"), item.get("hash")
        if not isinstance(url, str) or not isinstance(digest, str):
            raise DependencyAdmissionError(["wheel lock requires URL and digest"])
        _https(url)
        if urlsplit(url).hostname != "files.pythonhosted.org":
            raise DependencyAdmissionError(["wheel artifact uses an unapproved source"])
        filename = urlsplit(url).path.rsplit("/", 1)[-1]
        if filename in observed:
            raise DependencyAdmissionError(["duplicate locked wheel identity"])
        observed[filename] = digest
    expected = {wheel.filename: f"sha256:{wheel.sha256}" for wheel in record.wheels}
    if observed != expected:
        raise DependencyAdmissionError(["provenance must cover the exact locked wheel set"])
    trust = _read_evidence(root, record.trusted_root)
    executable = shutil.which("cosign")
    if executable is None:
        raise DependencyAdmissionError(["Cosign verification unavailable: executable not found"])
    try:
        executable = str(Path(executable).resolve(strict=True))
    except (OSError, RuntimeError) as error:
        raise DependencyAdmissionError(["Cosign executable cannot be resolved"]) from error
    # Private copies prevent a caller from swapping a file after semantic validation.
    with tempfile.TemporaryDirectory(prefix="wheel-source-verification-") as temporary:
        directory = Path(temporary)
        trust_path = directory / "trusted-root.json"
        trust_path.write_bytes(trust)
        if (
            re.search(r"(?m)^\s*GitVersion:\s+v3\.1\.3\s*$", _cosign(["version"], executable))
            is None
        ):
            raise DependencyAdmissionError([f"Cosign must be exactly {_COSIGN_VERSION}"])
        for wheel in record.wheels:
            bundle = _read_evidence(root, wheel.bundle)
            _check_statement(_statement(bundle), record, wheel.filename, wheel.sha256)
            bundle_path = directory / "bundle.json"
            bundle_path.write_bytes(bundle)
            _cosign(
                [
                    "verify-blob-attestation",
                    "--check-claims=true",
                    "--trusted-root",
                    str(trust_path),
                    "--bundle",
                    str(bundle_path),
                    "--certificate-identity",
                    record.certificate_identity,
                    "--certificate-oidc-issuer",
                    record.oidc_issuer,
                    "--type",
                    _PREDICATE_TYPE,
                    "--digest",
                    wheel.sha256,
                    "--digestAlg",
                    "sha256",
                ],
                executable,
            )
