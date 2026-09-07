"""Verify the narrow wheel-only source admission profile without trusting producer claims."""

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
    WheelEvidenceAdmission,
    WheelSourceAdmission,
)

_COSIGN_VERSION = "3.1.3"
_PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
_PUBLICATION_TYPE = "https://docs.pypi.org/attestations/publish/v1"
_MAX_EVIDENCE_BYTES = 5_000_000
_MAX_WHEELS = 100


def _https(value: str) -> None:
    """Require a credential-free HTTPS URL with no query or fragment.

    This is a syntactic check only; it does not resolve the host or perform any
    network request. Userinfo, whitespace, ASCII controls, queries, and fragments are
    rejected so the URL can be retained as source or signer identity evidence.

    Args:
        value: URL text to inspect.

    Raises:
        DependencyAdmissionError: If the URL is not HTTPS, has no hostname, or
            contains credentials, a query, a fragment, whitespace, or ASCII controls.
        ValueError: If ``urlsplit`` rejects malformed URL authority syntax.
    """
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
    """Require a canonical, relative POSIX path for repository evidence.

    The check rejects absolute paths, empty paths, ``.`` or ``..`` components,
    non-canonical slash formatting, and characters outside letters, digits,
    underscore, dot, slash, and hyphen. It performs no filesystem lookup and
    does not itself check symlink traversal.

    Args:
        value: Repository-relative path text to inspect.

    Raises:
        DependencyAdmissionError: If ``value`` is not a canonical relative path.
    """
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {".", ".."} for part in path.parts)
        or path.as_posix() != value
        or re.fullmatch(r"[A-Za-z0-9_./-]+", value) is None
    ):
        raise DependencyAdmissionError(["source evidence path must be canonical and relative"])


class WheelEvidenceService:
    """Own wheel evidence verification for one repository root."""

    def __init__(self, repository_root: Path) -> None:
        """Bind WheelEvidenceService collaborators without filesystem or process I/O.

        Args:
            repository_root: Repository root used by later verification operations.
        """
        self.repository_root = repository_root

    def _verify_wheel_evidence(
        self, locked: dict[str, object], record: WheelEvidenceAdmission
    ) -> None:
        """Verify shared lock coverage, attestation claims, and Cosign signatures.

        The lock must omit ``sdist`` and contain wheel URLs hosted on ``files.pythonhosted.org``
        with unique filenames. Its exact filename-to-digest mapping must equal the
        supplied ``record.wheels`` mapping; the supplied digests are compared and
        passed to Cosign rather than recomputed from downloaded wheel bytes. After the
        lock checks, the trust-root evidence is read, the PATH-discovered Cosign executable is
        resolved, the trust root is copied into a private temporary directory, and the
        reported Cosign version is checked. Only then is each bundle read in wheel
        order, its statement claims checked, and its private copy sent to the signature
        call.

        Args:
            locked: Parsed package-lock object expected to contain a wheel list.
            record: Parser-admitted, model-validated wheel admission whose expected
                digests and identities are compared with the lock and attestation claims.

        Raises:
            DependencyAdmissionError: If the lock is not wheel-only, its wheel set or
                wheel artifact host is unapproved, local evidence is invalid, Cosign
                is unavailable or unpinned, statements mismatch, or any signature
                fails. Helper-level process and evidence failures are translated and
                chained.
            OSError: If temporary staging writes or other uncaught filesystem operations
                fail outside those helper boundaries.
            ValueError: If URL parsing rejects malformed authority syntax in the lock.
        """
        root = self.repository_root
        if "sdist" in locked:
            raise DependencyAdmissionError(
                ["wheel-only admission cannot replace an existing sdist"]
            )
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
            raise DependencyAdmissionError(
                ["Cosign verification unavailable: executable not found"]
            )
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
                        _PUBLICATION_TYPE
                        if isinstance(record, BootstrapWheelAdmission)
                        else _PREDICATE_TYPE,
                        "--digest",
                        wheel.sha256,
                        "--digestAlg",
                        "sha256",
                    ],
                    executable,
                )

    def verify_wheel_sources(self, locked: dict[str, object], record: WheelSourceAdmission) -> None:
        """Verify a source-bound wheel admission against the complete locked wheel set.

        The lock must omit ``sdist`` and contain wheels from ``files.pythonhosted.org`` with exactly
        the filenames and supplied ``sha256:`` digests declared by ``record``. The
        record must already have been admitted by ``parse_wheel_sources``; this
        verifier does not repeat that parser's full cross-record validation. After
        lock checks, it reads the retained trust root, resolves the PATH-discovered Cosign
        executable, stages the private trust root, and checks the reported version
        before reading any wheel bundle. Each bundle's in-toto/SLSA claims are checked
        before its signature call. It authenticates the supplied wheel digest; this
        function does not download or hash wheel or source-archive bytes. Cosign is
        invoked without a shell and with a PATH-only environment, but no offline flag
        is added by this module.

        Args:
            locked: Parsed lock record for one package, including its ``wheels`` list.
            record: Admission previously returned by ``parse_wheel_sources``; the
                verifier assumes its parser-level cross-record checks have passed.

        Raises:
            DependencyAdmissionError: If the lock, local evidence, attestation claims,
                Cosign path/version, or signature verification fails. Evidence and
                Cosign process failures are translated at their helper boundaries.
            OSError: If temporary staging or other uncaught filesystem operations fail.
            ValueError: If URL parsing rejects malformed authority syntax in the lock.
        """
        self._verify_wheel_evidence(locked, record)

    def verify_bootstrap_wheels(
        self,
        locked: dict[str, object],
        record: BootstrapWheelAdmission,
        *,
        validation_date: date,
    ) -> None:
        """Verify a bounded publication-only bootstrap admission in ordered stages.

        The caller-supplied ``validation_date`` must be within the inclusive
        ``reviewed_on`` through ``expires_on`` interval. Date checking runs first,
        followed by non-empty digest-checked reads of the four review reports in their
        fixed order; only then does the shared lock, publication-subject, and Cosign
        verification run. The record must already have been admitted by
        ``parse_bootstrap_wheels``; this verifier does not repeat that parser's full
        cross-record validation. Bootstrap publication authentication does not prove
        the missing source-to-wheel binding. This function authenticates supplied
        wheel digests and does not download or hash wheel or source-archive bytes.

        Args:
            locked: Parsed lock record for one package, including its ``wheels`` list.
            record: Admission previously returned by ``parse_bootstrap_wheels`` with
                bounded review evidence; parser-level checks are assumed complete.
            validation_date: Caller-supplied date evaluated inclusively against the
                record's review and expiry dates.

        Raises:
            DependencyAdmissionError: If the review window, review evidence, lock,
                publication statement, Cosign identity/version, or signature check
                fails. Evidence and Cosign process failures are translated at their
                helper boundaries.
            OSError: If temporary staging or other uncaught filesystem operations fail.
            ValueError: If URL parsing rejects malformed authority syntax in the lock.
        """
        if not record.reviewed_on <= validation_date <= record.expires_on:
            raise DependencyAdmissionError(
                [f"bootstrap finding {record.finding_id} is expired or not yet effective"]
            )
        for report in _bootstrap_reports(record):
            if not _read_evidence(self.repository_root, report).strip():
                raise DependencyAdmissionError(["bootstrap review report is empty"])
        self._verify_wheel_evidence(locked, record)


def parse_wheel_sources(
    value: object,
    packages: tuple[PythonPackageAdmission, ...],
    approved_licenses: set[str],
) -> tuple[WheelSourceAdmission, ...]:
    """Parse authenticated source-binding alternatives for native packages.

    ``value`` is serialized to JSON and validated as a tuple of
    ``WheelSourceAdmission`` records. Each record must match an already validated
    native package, Platform ownership, approved source licenses, canonical local
    evidence paths, HTTPS identities, bounded source and wheel counts, and unique
    evidence identities. An empty sequence is accepted; absence leaves a package
    without an alternative source admission and therefore cannot excuse a missing source archive.
    This parser validates claims and shapes only; it does not download or hash
    source archives or wheel bytes and does not verify attestations.

    Args:
        value: JSON-serializable raw record sequence, usually decoded from policy
            input. Values such as arbitrary Python datetime objects are not valid
            inputs because ``json.dumps`` runs before model validation.
        packages: Already validated package admissions used for exact name,
            version, and native-artifact checks.
        approved_licenses: License expressions admitted for source archives.

    Returns:
        Parsed wheel-source records in input order.

    Raises:
        DependencyAdmissionError: If JSON serialization or model validation fails,
            or a record violates the cross-record admission and license checks.
            Serialization and Pydantic validation failures are translated and
            chained from their original exceptions.
        ValueError: If URL parsing rejects malformed authority syntax during
            cross-record validation.
    """
    try:
        records = TypeAdapter(tuple[WheelSourceAdmission, ...]).validate_json(json.dumps(value))
    except (ValidationError, ValueError, TypeError) as error:
        raise DependencyAdmissionError(["invalid wheel source admission fields"]) from error
    _validate_wheel_records(records, packages, approved_licenses)
    return records


def parse_bootstrap_wheels(
    value: object,
    packages: tuple[PythonPackageAdmission, ...],
    approved_licenses: set[str],
    *,
    as_of_date: date,
    review_due_on: date,
) -> tuple[BootstrapWheelAdmission, ...]:
    """Parse bounded publication-only wheel admissions for bootstrap use.

    ``value`` is serialized to JSON and validated as a tuple of
    ``BootstrapWheelAdmission`` records before shared package, license, source,
    wheel, signer, and path checks run. The caller supplies both policy dates:
    ``as_of_date <= reviewed_on < expires_on <= review_due_on`` must hold, and
    expiry must be no later than 30 days after review. The expiry date itself is
    included by these upper bounds. Finding IDs must be unique, and all four
    review-report paths must be canonical. An empty sequence is accepted. Parsing
    records the explicit source-to-wheel gap; it does not download or hash source
    archives or wheel bytes and does not verify publication attestations.

    Args:
        value: JSON-serializable raw bootstrap record sequence. Arbitrary Python
            objects that ``json.dumps`` cannot encode are rejected before model
            validation.
        packages: Already validated package admissions used for exact name,
            version, and native-artifact checks.
        approved_licenses: License expressions admitted for source archives.
        as_of_date: Caller-supplied policy assessment date, inclusive for review.
        review_due_on: Caller-supplied policy review deadline, inclusive for expiry.

    Returns:
        Parsed bootstrap records in input order.

    Raises:
        DependencyAdmissionError: If JSON serialization or model validation fails,
            records duplicate finding IDs, shared admission checks fail, a report
            path is unsafe, or the caller-supplied review window is violated.
            Serialization and Pydantic validation failures are translated and
            chained from their original exceptions.
        ValueError: If URL parsing rejects malformed authority syntax during
            cross-record validation.
    """
    try:
        records = TypeAdapter(tuple[BootstrapWheelAdmission, ...]).validate_json(json.dumps(value))
    except (ValidationError, ValueError, TypeError) as error:
        raise DependencyAdmissionError(["invalid bootstrap wheel admission fields"]) from error
    _validate_wheel_records(records, packages, approved_licenses)
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
        for report in _bootstrap_reports(record):
            _relative_path(report.path)
    return records


def _bootstrap_reports(record: BootstrapWheelAdmission) -> tuple[EvidenceFile, ...]:
    """Return bootstrap reports in the order used for pre-verification checks.

    Args:
        record: Model-validated bootstrap admission containing the four reports.

    Returns:
        A tuple ordered as source review, security review, native inventory, and
        compatibility report.
    """
    return (
        record.source_review,
        record.security_review,
        record.native_inventory,
        record.compatibility_report,
    )


def _validate_wheel_records(
    records: tuple[WheelEvidenceAdmission, ...],
    packages: tuple[PythonPackageAdmission, ...],
    approved_licenses: set[str],
) -> None:
    """Validate cross-record constraints shared by both wheel profiles.

    Records are expected to have passed model validation. This helper enforces
    exact admitted package identity and native status, Platform ownership, source
    and wheel count bounds, HTTPS identities, approved source licenses, unique
    source/filename/evidence paths, canonical wheel filenames, and canonical
    repository-relative evidence paths. It inspects claims only and performs no
    filesystem, network, digest, or signature operation.

    Args:
        records: Parsed wheel admission records to validate in their input order.
        packages: Already validated package admissions keyed by normalized name.
        approved_licenses: License expressions accepted for source archives.

    Raises:
        DependencyAdmissionError: If a record is duplicated, does not match an
            admitted native package, violates ownership/count/URL/license rules,
            repeats an evidence identity, or has an invalid filename or path.
        ValueError: If URL parsing rejects malformed authority syntax.
    """
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
        urls: tuple[str, ...] = (record.certificate_identity, record.oidc_issuer)
        if isinstance(record, WheelSourceAdmission):
            urls += (record.builder_id, record.build_type)
        for url in urls:
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


def _read_evidence(root: Path, record: EvidenceFile) -> bytes:
    """Read and digest-check one repository-local evidence file.

    The declared path is checked component by component after ``root`` is joined,
    rejecting symlinks in those appended components before reading at most
    ``_MAX_EVIDENCE_BYTES + 1`` bytes. The root itself and ancestors above it are
    not checked for symlinks, and replacement between checks and open/read remains
    a time-of-check/time-of-use race. This helper reads local bytes only; it does
    not download evidence.

    Args:
        root: Repository or fixture root beneath which the declared path is read.
        record: Model-validated path and expected lowercase SHA-256 identity.

    Returns:
        The complete evidence content when it is at most 5,000,000 bytes and its
        digest equals ``record.sha256``.

    Raises:
        DependencyAdmissionError: If the path is non-canonical, traverses an
            appended symlink, is missing or non-regular, exceeds the size bound,
            or has a digest mismatch. Filesystem read errors are translated and
            chained from ``OSError``.
    """
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
    """Build a JSON object while rejecting duplicate member names.

    Args:
        pairs: Object members in decoder order.

    Returns:
        A dictionary preserving the first-seen insertion order of unique keys.

    Raises:
        DependencyAdmissionError: If a key occurs more than once.
    """
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DependencyAdmissionError(["duplicate provenance JSON key"])
        result[key] = value
    return result


def _object(value: object) -> dict[str, object]:
    """Require a decoded JSON value to be an object without copying it.

    Args:
        value: Decoded JSON value expected to be a dictionary.

    Returns:
        The same dictionary object, typed for field inspection.

    Raises:
        DependencyAdmissionError: If ``value`` is not a JSON object.
    """
    if not isinstance(value, dict):
        raise DependencyAdmissionError(["provenance requires JSON objects"])
    return cast(dict[str, object], value)


def _json_object(content: bytes) -> dict[str, object]:
    """Decode one JSON object with duplicate-key and explicit-constant checks.

    Args:
        content: JSON bytes expected to decode to an object. ``json.loads`` may
            accept UTF-8, UTF-16, or UTF-32 byte encodings.

    Returns:
        The decoded object with duplicate keys rejected and member order retained.

    Raises:
        DependencyAdmissionError: If decoding fails, the top-level value is not
            an object, a key is duplicated, or an explicit ``NaN``/``Infinity``
            token is present. These failures are translated to the stable
            invalid-JSON finding and chained from the underlying parser or
            validation error. Other numeric behavior, including overflow, remains
            the behavior of ``json.loads``.
    """
    try:
        return _object(
            json.loads(
                content, object_pairs_hook=_unique_object, parse_constant=_reject_json_constant
            )
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise DependencyAdmissionError(["invalid provenance JSON"]) from error


def _reject_json_constant(value: str) -> object:
    """Reject a JSON ``NaN`` or infinity token during strict decoding.

    Args:
        value: Non-finite token reported by ``json.loads``.

    Raises:
        DependencyAdmissionError: Always, identifying the rejected token.
    """
    raise DependencyAdmissionError([f"non-finite provenance JSON constant: {value}"])


def _statement(bundle: bytes) -> dict[str, object]:
    """Decode a supported Sigstore v0.3 DSSE bundle into its in-toto statement.

    The outer bundle and envelope must have their exact supported fields and media
    types. The payload is base64 with validation enabled and is passed to
    ``_json_object``; its JSON byte decoding therefore follows the standard
    library's UTF-8/UTF-16/UTF-32 behavior. Signatures and verification-material
    contents are left for Cosign. A decoded payload's JSON or object validation
    error is reported as an invalid DSSE payload encoding because the payload
    decode block catches ``ValueError`` as well as base64 errors.

    Args:
        bundle: Sigstore bundle JSON bytes.

    Returns:
        The decoded in-toto statement object for semantic claim checks.

    Raises:
        DependencyAdmissionError: If the outer bundle, envelope, payload type,
            payload encoding, or decoded JSON shape is unsupported or malformed.
            Payload-block validation failures are translated to the stable payload
            encoding finding and chained from their causes.
    """
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
    statement: dict[str, object], record: WheelEvidenceAdmission, filename: str, digest: str
) -> None:
    """Check an attestation statement against a supplied wheel admission claim.

    Both profiles require the in-toto type and an exact single-wheel subject whose
    supplied SHA-256 digest equals ``digest``. Bootstrap records accept only a
    ``None`` or empty publication predicate, while source records require the
    exact SLSA build fields, builder, canonical build-parameter digest, and ordered
    source materials. This function checks claims only; it does not authenticate
    signatures or download or hash wheel/source bytes.

    Args:
        statement: Model-independent in-toto statement decoded from a bundle.
        record: Parsed wheel admission whose expected identities and claims are used.
        filename: Locked wheel filename expected in the statement subject.
        digest: Supplied lowercase wheel digest expected in the subject.

    Raises:
        DependencyAdmissionError: If the statement type, subject, profile-specific
            predicate, builder, parameters, or source materials do not match.
    """
    predicate_type = (
        _PUBLICATION_TYPE if isinstance(record, BootstrapWheelAdmission) else _PREDICATE_TYPE
    )
    if (
        set(statement) != {"_type", "predicateType", "subject", "predicate"}
        or statement.get("_type") != "https://in-toto.io/Statement/v1"
        or statement.get("predicateType") != predicate_type
        or statement.get("subject") != [{"name": filename, "digest": {"sha256": digest}}]
    ):
        raise DependencyAdmissionError(["provenance type or exact wheel subject mismatch"])
    if isinstance(record, BootstrapWheelAdmission):
        if statement["predicate"] not in (None, {}):
            raise DependencyAdmissionError(["unsupported publication predicate body"])
        return
    if not isinstance(record, WheelSourceAdmission):
        raise DependencyAdmissionError(["unsupported wheel admission profile"])
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
    """Run the supplied Cosign executable with bounded returned diagnostics.

    The command uses the supplied argv without a shell, writes combined stdout and
    stderr to a temporary file, passes only the current ``PATH`` in its environment,
    and uses a 60-second subprocess timeout. The child may write an unbounded amount
    to the temporary file; after completion this helper reads only the first 4,000
    text characters for its returned diagnostic or failure message. Local
    trusted-root and bundle arguments do not imply offline execution because no
    offline flag is added here. Executable discovery and version pinning are
    performed by the caller.

    Args:
        arguments: Fixed Cosign arguments supplied by the caller.
        executable: Resolved Cosign executable path.

    Returns:
        The first 4,000 characters of combined process output when the exit status
        is zero.

    Raises:
        DependencyAdmissionError: If process startup/output handling fails, the
            process times out, or Cosign exits nonzero. Startup, Unicode, and
            timeout failures are translated and chained; a nonzero status retains
            the bounded diagnostic text.
    """
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
    """Verify a source-bound wheel admission against the complete locked wheel set.

    The lock must omit ``sdist`` and contain wheels from ``files.pythonhosted.org`` with exactly
    the filenames and supplied ``sha256:`` digests declared by ``record``. The
    record must already have been admitted by ``parse_wheel_sources``; this
    verifier does not repeat that parser's full cross-record validation. After
    lock checks, it reads the retained trust root, resolves the PATH-discovered Cosign
    executable, stages the private trust root, and checks the reported version
    before reading any wheel bundle. Each bundle's in-toto/SLSA claims are checked
    before its signature call. It authenticates the supplied wheel digest; this
    function does not download or hash wheel or source-archive bytes. Cosign is
    invoked without a shell and with a PATH-only environment, but no offline flag
    is added by this module.

    Args:
        root: Repository or fixture root containing retained evidence files.
        locked: Parsed lock record for one package, including its ``wheels`` list.
        record: Admission previously returned by ``parse_wheel_sources``; the
            verifier assumes its parser-level cross-record checks have passed.

    Returns:
        ``None`` after the locked wheel evidence verifies.

    Raises:
        DependencyAdmissionError: If the lock, local evidence, attestation claims,
            Cosign path/version, or signature verification fails. Evidence and
            Cosign process failures are translated at their helper boundaries.
        OSError: If temporary staging or other uncaught filesystem operations fail.
        ValueError: If URL parsing rejects malformed authority syntax in the lock.
    """
    return WheelEvidenceService(root).verify_wheel_sources(locked, record)


def verify_bootstrap_wheels(
    root: Path,
    locked: dict[str, object],
    record: BootstrapWheelAdmission,
    *,
    validation_date: date,
) -> None:
    """Verify a bounded publication-only bootstrap admission in ordered stages.

    The caller-supplied ``validation_date`` must be within the inclusive
    ``reviewed_on`` through ``expires_on`` interval. Date checking runs first,
    followed by non-empty digest-checked reads of the four review reports in their
    fixed order; only then does the shared lock, publication-subject, and Cosign
    verification run. The record must already have been admitted by
    ``parse_bootstrap_wheels``; this verifier does not repeat that parser's full
    cross-record validation. Bootstrap publication authentication does not prove
    the missing source-to-wheel binding. This function authenticates supplied
    wheel digests and does not download or hash wheel or source-archive bytes.

    Args:
        root: Repository or fixture root containing retained evidence files.
        locked: Parsed lock record for one package, including its ``wheels`` list.
        record: Admission previously returned by ``parse_bootstrap_wheels`` with
            bounded review evidence; parser-level checks are assumed complete.
        validation_date: Caller-supplied date evaluated inclusively against the
            record's review and expiry dates.

    Returns:
        ``None`` after the bootstrap wheel evidence verifies.

    Raises:
        DependencyAdmissionError: If the review window, review evidence, lock,
            publication statement, Cosign identity/version, or signature check
            fails. Evidence and Cosign process failures are translated at their
            helper boundaries.
        OSError: If temporary staging or other uncaught filesystem operations fail.
        ValueError: If URL parsing rejects malformed authority syntax in the lock.
    """
    return WheelEvidenceService(root).verify_bootstrap_wheels(
        locked, record, validation_date=validation_date
    )
