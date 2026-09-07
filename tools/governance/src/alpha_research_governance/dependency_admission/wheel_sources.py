"""Validate retained QuantLib publication attestations at the native boundary.

The active profile authenticates publisher identity and trusted-root signatures
for every locked wheel while retaining an explicit, expiring source-to-wheel
gap. The retired source-bound alternative is deliberately not represented here.
"""

from __future__ import annotations

# standard library imports
import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import subprocess  # nosec B404  # [owner=platform; rationale=pinned Cosign verification only; expires=2027-03-01]
import tempfile
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import urlsplit

# third party library imports
from pydantic import TypeAdapter, ValidationError

# project library imports
from alpha_research_governance.dependency_admission.models import (
    BootstrapWheelAdmission,
    DependencyAdmissionError,
    EvidenceFile,
    PythonPackageAdmission,
)

_COSIGN_VERSION = "3.1.3"
_PUBLICATION_TYPE = "https://docs.pypi.org/attestations/publish/v1"
_MAX_EVIDENCE_BYTES = 5_000_000
_MAX_WHEELS = 100


def _https(value: str) -> None:
    """Require a credential-free HTTPS identity URL."""
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
    """Require a canonical relative POSIX path for repository evidence."""
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {".", ".."} for part in path.parts)
        or path.as_posix() != value
        or re.fullmatch(r"[A-Za-z0-9_./-]+", value) is None
    ):
        raise DependencyAdmissionError(["source evidence path must be canonical and relative"])


def _object(value: object) -> dict[str, object]:
    """Narrow one decoded JSON object without changing its values."""
    if not isinstance(value, dict):
        raise DependencyAdmissionError(["provenance requires JSON objects"])
    return cast(dict[str, object], value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON members while preserving decoded insertion order."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DependencyAdmissionError(["duplicate provenance JSON key"])
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    """Reject non-finite JSON constants at the provenance boundary."""
    raise DependencyAdmissionError([f"non-finite provenance JSON constant: {value}"])


def _json_object(content: bytes) -> dict[str, object]:
    """Decode a strict JSON object with duplicate and explicit-constant checks.

    JSON numeric overflow keeps the standard decoder's behavior; only explicit
    ``NaN`` and infinity constants are rejected.
    """
    try:
        parsed: object = json.loads(
            content, object_pairs_hook=_unique_object, parse_constant=_reject_json_constant
        )
        return _object(parsed)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise DependencyAdmissionError(["invalid provenance JSON"]) from error


def _statement(bundle: bytes) -> dict[str, object]:
    """Decode a supported Sigstore v0.3 DSSE bundle into its statement."""
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


def _check_publication_statement(statement: dict[str, object], filename: str, digest: str) -> None:
    """Require the exact PyPI publication type and single-wheel subject."""
    if (
        set(statement) != {"_type", "predicateType", "subject", "predicate"}
        or statement.get("_type") != "https://in-toto.io/Statement/v1"
        or statement.get("predicateType") != _PUBLICATION_TYPE
        or statement.get("subject") != [{"name": filename, "digest": {"sha256": digest}}]
    ):
        raise DependencyAdmissionError(["provenance type or exact wheel subject mismatch"])
    if statement["predicate"] not in (None, {}):
        raise DependencyAdmissionError(["unsupported publication predicate body"])


def _read_evidence(root: Path, record: EvidenceFile) -> bytes:
    """Read one bounded, canonical, non-symlink evidence file and verify its digest.

    Appended path components are checked for symlinks, while the supplied root
    and its ancestors are intentionally not checked; replacement between those
    checks and the read remains a time-of-check/time-of-use limitation.
    """
    _relative_path(record.path)
    path = root
    try:
        for part in PurePosixPath(record.path).parts:
            path /= part
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


def _cosign(arguments: list[str], executable: str) -> str:
    """Run Cosign without a shell and return a bounded diagnostic."""
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


def _validate_bootstrap_records(
    records: tuple[BootstrapWheelAdmission, ...],
    packages: tuple[PythonPackageAdmission, ...],
    approved_licenses: set[str],
) -> None:
    """Validate bootstrap identities, source claims, wheel names, URLs, and paths."""
    admitted = {package.name: package for package in packages}
    names = [record.name for record in records]
    if len(names) != len(set(names)):
        raise DependencyAdmissionError(["duplicate bootstrap wheel admission"])
    for record in records:
        package = admitted.get(record.name)
        if package is None or record.version != package.version or not package.native_artifacts:
            raise DependencyAdmissionError(
                ["bootstrap wheels must match an exact native admission"]
            )
        if not 1 <= len(record.sources) <= 100 or not 1 <= len(record.wheels) <= _MAX_WHEELS:
            raise DependencyAdmissionError(["wheel source and artifact counts are out of bounds"])
        for identity in (record.certificate_identity, record.oidc_issuer):
            _https(identity)
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
        package_name = re.sub(r"[-_.]+", "_", record.name)
        for wheel in record.wheels:
            components = wheel.filename.split("-")
            if (
                re.fullmatch(r"[A-Za-z0-9_+.\-]+\.whl", wheel.filename) is None
                or len(components) not in {5, 6}
                or components[0].lower() != package_name
                or components[1] != record.version
            ):
                raise DependencyAdmissionError(["invalid wheel filename"])
        for evidence in (
            record.trusted_root,
            *(wheel.bundle for wheel in record.wheels),
            record.source_review,
            record.security_review,
            record.native_inventory,
            record.compatibility_report,
        ):
            _relative_path(evidence.path)


def parse_bootstrap_wheels(
    value: object,
    packages: tuple[PythonPackageAdmission, ...],
    approved_licenses: set[str],
    *,
    as_of_date: date,
    review_due_on: date,
) -> tuple[BootstrapWheelAdmission, ...]:
    """Parse and validate bounded publication evidence for isolated bootstrap use.

    Args:
        value: JSON-serializable raw bootstrap record sequence from policy input.
        packages: Validated package admissions used for exact identity and native checks.
        approved_licenses: License expressions admitted for source archives.
        as_of_date: Policy assessment date, inclusive for review evidence.
        review_due_on: Policy review deadline, inclusive for bootstrap expiry.

    Returns:
        Parsed immutable bootstrap records in input order.

    Raises:
        DependencyAdmissionError: If serialization, model, identity, path, license,
            or bounded review-window validation fails.
        ValueError: If URL parsing rejects malformed authority syntax.
    """
    try:
        records = TypeAdapter(tuple[BootstrapWheelAdmission, ...]).validate_json(json.dumps(value))
    except (ValidationError, ValueError, TypeError) as error:
        raise DependencyAdmissionError(["invalid bootstrap wheel admission fields"]) from error
    _validate_bootstrap_records(records, packages, approved_licenses)
    finding_ids = [record.finding_id for record in records]
    if len(finding_ids) != len(set(finding_ids)):
        raise DependencyAdmissionError(["duplicate bootstrap finding identity"])
    for record in records:
        if not (
            as_of_date <= record.reviewed_on < record.expires_on <= review_due_on
            and record.expires_on <= record.reviewed_on + timedelta(days=30)
        ):
            raise DependencyAdmissionError(
                ["bootstrap review must expire within 30 days and policy review"]
            )
    return records


def _verify_wheel_set(
    root: Path, locked: dict[str, object], record: BootstrapWheelAdmission
) -> None:
    """Verify locked wheel identities, publication claims, trust root, and signatures."""
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
    with tempfile.TemporaryDirectory(prefix="wheel-source-verification-") as temporary:
        directory = Path(temporary)
        trust_path = directory / "trusted-root.json"
        trust_path.write_bytes(trust)
        if (
            re.search(
                rf"(?m)^\s*GitVersion:\s+v{re.escape(_COSIGN_VERSION)}\s*$",
                _cosign(["version"], executable),
            )
            is None
        ):
            raise DependencyAdmissionError([f"Cosign must be exactly {_COSIGN_VERSION}"])
        for wheel in record.wheels:
            bundle = _read_evidence(root, wheel.bundle)
            _check_publication_statement(_statement(bundle), wheel.filename, wheel.sha256)
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
                    _PUBLICATION_TYPE,
                    "--digest",
                    wheel.sha256,
                    "--digestAlg",
                    "sha256",
                ],
                executable,
            )


def verify_bootstrap_wheels(
    root: Path,
    locked: dict[str, object],
    record: BootstrapWheelAdmission,
    *,
    validation_date: date,
) -> None:
    """Verify bounded publication evidence in ordered, fail-closed stages.

    Date and non-empty digest-bound review reports are checked before the exact
    wheel set, PyPI publication subjects, trusted root, Cosign version, and
    signatures. Publication authentication identifies the publisher while the
    record continues to state that source-to-wheel binding is unverified.

    Args:
        root: Repository or fixture root containing retained evidence files.
        locked: Parsed lock record for the package, including its wheel list.
        record: Model-validated bootstrap admission with review evidence.
        validation_date: Date evaluated inclusively against review and expiry dates.

    Raises:
        DependencyAdmissionError: If dates, evidence, lock identities, publication
            claims, Cosign identity/version, or signatures fail.
        OSError: If staging writes or other uncaught filesystem operations fail.
        ValueError: If URL parsing rejects malformed authority syntax in the lock.
    """
    if not record.reviewed_on <= validation_date <= record.expires_on:
        raise DependencyAdmissionError(
            [f"bootstrap finding {record.finding_id} is expired or not yet effective"]
        )
    for report in (
        record.source_review,
        record.security_review,
        record.native_inventory,
        record.compatibility_report,
    ):
        if not _read_evidence(root, report).strip():
            raise DependencyAdmissionError(["bootstrap review report is empty"])
    _verify_wheel_set(root, locked, record)
