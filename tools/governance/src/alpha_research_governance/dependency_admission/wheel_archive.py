"""Inspect complete wheel bytes before they enter a selected release closure."""

from __future__ import annotations

# standard library imports
import base64
import csv
import hashlib
import io
import stat
import zipfile
import zlib
from pathlib import Path, PurePosixPath

# third party library imports
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.tags import Tag, parse_tag
from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename

# project library imports
from alpha_research_governance._models import ImmutableModel
from alpha_research_governance.dependency_admission.models import DependencyAdmissionError


class WheelIdentity(ImmutableModel):
    """Record validated wheel bytes and their actual dependency metadata."""

    name: str
    version: str
    filename: str
    sha256: str
    size_bytes: int
    tags: tuple[str, ...]
    requires_python: str
    provides_extras: tuple[str, ...]
    requires_dist: tuple[str, ...]


class WheelArchive:
    """Verify wheel structure, metadata and complete RECORD content without installation."""

    _MAX_WHEEL_BYTES = 256 * 1024 * 1024
    _MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
    _MAX_MEMBERS = 50_000
    _MAX_METADATA_BYTES = 8 * 1024 * 1024

    @classmethod
    def inspect(cls, path: Path) -> WheelIdentity:
        """Inspect a bounded regular wheel and return its verified metadata.

        Args:
            path: Local wheel archive; symlinks and non-wheel files are rejected.

        Returns:
            Immutable facts for an archive whose RECORD covers every member.

        Raises:
            DependencyAdmissionError: Bytes, paths, RECORD, metadata or tags are invalid.
            OSError: The wheel cannot be read.
        """
        if path.is_symlink() or not path.is_file() or path.suffix != ".whl":
            raise DependencyAdmissionError([f"wheel is not a regular .whl file: {path}"])
        if path.stat().st_size > cls._MAX_WHEEL_BYTES:
            raise DependencyAdmissionError([f"wheel exceeds size limit: {path.name}"])
        payload = path.read_bytes()
        if len(payload) > cls._MAX_WHEEL_BYTES:
            raise DependencyAdmissionError([f"wheel exceeds size limit: {path.name}"])
        try:
            name, version, _, filename_tags = parse_wheel_filename(path.name)
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                members = cls._members(archive)
                prefix = f"{name.replace('-', '_')}-{version}.dist-info/"
                metadata_path = prefix + "METADATA"
                wheel_path = prefix + "WHEEL"
                record_path = prefix + "RECORD"
                if not {metadata_path, wheel_path, record_path} <= set(members):
                    raise ValueError("wheel has missing or mismatched dist-info metadata")
                dist_info_roots = {
                    name.split("/", 1)[0]
                    for name in members
                    if name.split("/", 1)[0].endswith(".dist-info")
                }
                if dist_info_roots != {prefix.removesuffix("/")}:
                    raise ValueError("wheel contains an unexpected dist-info directory")
                metadata = cls._headers(
                    cls._small_member(archive, members[metadata_path], metadata_path)
                )
                wheel_headers = cls._headers(
                    cls._small_member(archive, members[wheel_path], wheel_path)
                )
                record = cls._small_member(archive, members[record_path], record_path)
                cls._verify_record(archive, members, record_path, record)
            metadata_name = cls._single(metadata, "name")
            metadata_version = cls._single(metadata, "version")
            if canonicalize_name(metadata_name, validate=True) != name or metadata_version != str(
                version
            ):
                raise ValueError("wheel filename and METADATA identity differ")
            if cls._single(wheel_headers, "wheel-version") != "1.0":
                raise ValueError("unsupported WHEEL version")
            if cls._single(wheel_headers, "root-is-purelib") not in {"true", "false"}:
                raise ValueError("WHEEL must declare Root-Is-Purelib")
            declared_tags: set[Tag] = set()
            for declared in wheel_headers.get("tag", ()):
                declared_tags.update(parse_tag(declared))
            if declared_tags != filename_tags:
                raise ValueError("WHEEL compatibility tags differ from filename")
            requires_python = cls._single(metadata, "requires-python", default="")
            if requires_python:
                SpecifierSet(requires_python)
            requires_dist = metadata.get("requires-dist", ())
            for requirement in requires_dist:
                parsed = Requirement(requirement)
                if parsed.url is not None:
                    raise ValueError("wheel declares an unpinned direct-URL dependency")
            extras = tuple(
                sorted(
                    canonicalize_name(extra, validate=True)
                    for extra in metadata.get("provides-extra", ())
                )
            )
            if len(extras) != len(set(extras)):
                raise ValueError("wheel declares duplicate extras")
        except (
            ValueError,
            UnicodeError,
            zipfile.BadZipFile,
            csv.Error,
            InvalidWheelFilename,
            InvalidRequirement,
            InvalidSpecifier,
            EOFError,
            RuntimeError,
            zlib.error,
        ) as error:
            raise DependencyAdmissionError([f"invalid wheel {path.name}: {error}"]) from error
        return WheelIdentity(
            name=name,
            version=str(version),
            filename=path.name,
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
            tags=tuple(sorted(str(tag) for tag in declared_tags)),
            requires_python=requires_python,
            provides_extras=extras,
            requires_dist=requires_dist,
        )

    @staticmethod
    def _safe_path(name: str) -> str:
        """Reject traversal and path spellings that can change during installation."""
        path = PurePosixPath(name.rstrip("/"))
        if (
            not name
            or path.is_absolute()
            or path.as_posix() != name.rstrip("/")
            or any(part in {".", ".."} for part in path.parts)
            or "\\" in name
            or ":" in name
            or any(ord(character) < 32 for character in name)
        ):
            raise ValueError("unsafe wheel member path")
        return path.as_posix()

    @classmethod
    def _members(cls, archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
        """Check all member names and types before opening any content."""
        members: dict[str, zipfile.ZipInfo] = {}
        spellings: set[str] = set()
        total = 0
        for member in archive.infolist():
            name = cls._safe_path(member.filename)
            folded = name.casefold()
            total += member.file_size
            mode = stat.S_IFMT(member.external_attr >> 16)
            if (
                name in members
                or folded in spellings
                or len(spellings) >= cls._MAX_MEMBERS
                or total > cls._MAX_EXPANDED_BYTES
                or member.orig_filename != member.filename
                or member.flag_bits & 0x61
                or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                or (member.is_dir() and mode not in {0, stat.S_IFDIR})
                or (not member.is_dir() and mode not in {0, stat.S_IFREG})
            ):
                raise ValueError("duplicate, special or oversized wheel member")
            spellings.add(folded)
            if member.is_dir():
                continue
            parts = PurePosixPath(name).parts
            if (
                name.endswith(".pth")
                or parts[-1] in {"sitecustomize.py", "usercustomize.py"}
                or (len(parts) > 2 and parts[0].endswith(".data") and parts[1] == "scripts")
            ):
                raise ValueError("wheel contains an installation hook or script")
            members[name] = member
        return members

    @classmethod
    def _small_member(cls, archive: zipfile.ZipFile, member: zipfile.ZipInfo, name: str) -> bytes:
        """Read one bounded metadata file."""
        if member.file_size > cls._MAX_METADATA_BYTES:
            raise ValueError(f"oversized wheel metadata: {name}")
        result = archive.read(member)
        if len(result) != member.file_size:
            raise ValueError(f"truncated wheel metadata: {name}")
        return result

    @staticmethod
    def _headers(payload: bytes) -> dict[str, tuple[str, ...]]:
        """Read RFC 822 style headers with continuation lines and strict identities."""
        header_text = payload.decode("utf-8").replace("\r\n", "\n").split("\n\n", 1)[0]
        values: dict[str, list[str]] = {}
        key = ""
        for line in header_text.split("\n"):
            if not line:
                continue
            if line.startswith((" ", "\t")):
                if not key:
                    raise ValueError("wheel metadata has an orphan continuation")
                values[key][-1] += " " + line.strip()
                continue
            raw_key, separator, value = line.partition(":")
            if not separator or not raw_key or not raw_key.replace("-", "").isalnum():
                raise ValueError("wheel metadata has a malformed header")
            key = raw_key.lower()
            values.setdefault(key, []).append(value.strip())
        return {name: tuple(items) for name, items in values.items()}

    @staticmethod
    def _single(
        headers: dict[str, tuple[str, ...]], key: str, *, default: str | None = None
    ) -> str:
        """Require one scalar header or its explicitly optional default."""
        values = headers.get(key, ())
        if not values and default is not None:
            return default
        if len(values) != 1 or not values[0]:
            raise ValueError(f"wheel metadata requires one {key} header")
        return values[0]

    @staticmethod
    def _verify_record(
        archive: zipfile.ZipFile,
        members: dict[str, zipfile.ZipInfo],
        record_path: str,
        payload: bytes,
    ) -> None:
        """Require a complete SHA-256 and byte-size record for every wheel file."""
        rows = list(csv.reader(io.StringIO(payload.decode("utf-8")), strict=True))
        if any(len(row) != 3 for row in rows):
            raise ValueError("malformed wheel RECORD")
        entries = {row[0]: (row[1], row[2]) for row in rows}
        if len(entries) != len(rows) or set(entries) != set(members):
            raise ValueError("wheel RECORD inventory differs")
        if entries[record_path] != ("", ""):
            raise ValueError("wheel RECORD must leave its own digest empty")
        for name, member in members.items():
            if name == record_path:
                continue
            digest = hashlib.sha256()
            size = 0
            with archive.open(member) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    if size > member.file_size:
                        raise ValueError("wheel member exceeds declared size")
            expected = "sha256=" + base64.urlsafe_b64encode(digest.digest()).decode().rstrip("=")
            if entries[name] != (expected, str(size)) or size != member.file_size:
                raise ValueError(f"wheel RECORD digest or size differs: {name}")
