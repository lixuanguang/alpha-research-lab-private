"""Verify ClearML's locked wheel against immutable upstream bytes without executing either."""

from __future__ import annotations

# standard library imports
import ast
import base64
import configparser
import csv
import hashlib
import http.client
import io
import json
import os
import stat
import tarfile
import tempfile
import time
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

# third party library imports
from pydantic import TypeAdapter, ValidationError

# project library imports
from alpha_research_governance.dependency_admission.models import (
    DependencyAdmissionError,
    PythonPackageAdmission,
    SourceArchiveAdmission,
)


class SourceArchiveVerifier:
    """Own bounded downloads, digest checks and complete runtime comparison for ClearML.

    The only alternate origin is clearml/clearml on GitHub, addressed by commit.
    Cache entries are untrusted bytes, rehashed and compared on every invocation.
    No upstream code is imported, executed or extracted into the filesystem.
    """

    _MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
    _MAX_EXPANDED_BYTES = 64 * 1024 * 1024
    _MAX_MEMBERS = 4096

    def __init__(self, cache: Path) -> None:
        """Bind an expendable content-addressed download cache.

        Args:
            cache: Local cache directory; created only when fetching missing artifacts.
        """
        self._cache = cache

    @staticmethod
    def parse_admissions(
        value: object, packages: tuple[PythonPackageAdmission, ...]
    ) -> tuple[SourceArchiveAdmission, ...]:
        """Admit only exact pure ClearML identities, with no implicit allowance.

        Args:
            value: Decoded source_archives policy array.
            packages: Exact package and license admissions.

        Returns:
            Validated immutable source bindings.

        Raises:
            DependencyAdmissionError: Fields, uniqueness or admitted package identity differ.
        """
        try:
            records = TypeAdapter(tuple[SourceArchiveAdmission, ...]).validate_json(
                json.dumps(value)
            )
        except (ValidationError, ValueError, TypeError) as error:
            raise DependencyAdmissionError(["invalid source-archive admission fields"]) from error
        admitted = {package.name: package for package in packages}
        if len({record.name for record in records}) != len(records):
            raise DependencyAdmissionError(["duplicate source-archive admission"])
        for record in records:
            package = admitted.get(record.name)
            if package is None or package.version != record.version or package.native_artifacts:
                raise DependencyAdmissionError(["source archive must match an exact pure package"])
        return records

    def verify(self, binding: SourceArchiveAdmission) -> int:
        """Verify both archive digests, runtime file equality and wheel packaging records.

        Args:
            binding: Policy record already matched against the complete locked wheel list.

        Returns:
            Number of byte-identical runtime files, including package resources.

        Raises:
            DependencyAdmissionError: Download, digest, archive or source comparison fails.
            OSError: The local cache cannot be read or published.
        """
        binding = SourceArchiveAdmission.model_validate(binding)
        source_url = f"https://codeload.github.com/clearml/clearml/tar.gz/{binding.commit}"
        source = self._artifact(source_url, binding.source_sha256)
        wheel = self._artifact(binding.wheel_url, binding.wheel_sha256)
        try:
            source_files = self._source_files(source, binding.commit)
            wheel_files = self._wheel_files(wheel)
            prefix = f"clearml-{binding.version}.dist-info/"
            metadata = {
                prefix + name
                for name in (
                    "LICENSE",
                    "METADATA",
                    "WHEEL",
                    "entry_points.txt",
                    "top_level.txt",
                    "RECORD",
                )
            }
            runtime = {
                name: payload
                for name, payload in wheel_files.items()
                if name.startswith("clearml/")
            }
            expected = {
                name: payload
                for name, payload in source_files.items()
                if name.startswith("clearml/")
            }
            if not expected or runtime != expected:
                raise ValueError("runtime file set or bytes differ from upstream source")
            if set(wheel_files) != set(runtime) | metadata:
                raise ValueError("wheel contains missing or unexpected packaging files")
            self._packaging(source_files, wheel_files, binding.version)
        except (
            ValueError,
            KeyError,
            UnicodeError,
            tarfile.TarError,
            zipfile.BadZipFile,
            configparser.Error,
            csv.Error,
            SyntaxError,
            EOFError,
            zlib.error,
        ) as error:
            raise DependencyAdmissionError(
                [f"ClearML source comparison failed: {error}"]
            ) from error
        return len(runtime)

    def _artifact(self, url: str, digest: str) -> bytes:
        """Hash cache hits and bounded downloads; never accept a marker in place of bytes."""
        path = self._cache / digest
        if path.is_symlink():
            raise DependencyAdmissionError(["source cache entry must not be a symlink"])
        if path.exists():
            with path.open("rb") as stream:
                payload = stream.read(self._MAX_ARCHIVE_BYTES + 1)
        else:
            payload = self._download(url)
        if len(payload) > self._MAX_ARCHIVE_BYTES or hashlib.sha256(payload).hexdigest() != digest:
            raise DependencyAdmissionError(["source archive or wheel size/digest mismatch"])
        if not path.exists():
            self._cache.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self._cache) as temporary:
                staging = Path(temporary) / "artifact"
                staging.write_bytes(payload)
                # Interrupted cache staging never authorizes admission.
                os.replace(staging, path)
        return payload

    @classmethod
    def _download(cls, url: str) -> bytes:
        """Fetch only reviewed HTTPS hosts with size/time bounds and no redirect following."""
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in ("codeload.github.com", "files.pythonhosted.org")
            or parsed.netloc != parsed.hostname
            or parsed.query
            or parsed.fragment
        ):
            raise DependencyAdmissionError(["unapproved source archive download origin"])
        connection = http.client.HTTPSConnection(parsed.hostname, timeout=15)
        started = time.monotonic()
        try:
            connection.request(
                "GET", parsed.path, headers={"User-Agent": "alpha-dependency-admission"}
            )
            response = connection.getresponse()
            if response.status != 200:
                raise DependencyAdmissionError([f"source download returned HTTP {response.status}"])
            chunks: list[bytes] = []
            size = 0
            while chunk := response.read(65536):
                chunks.append(chunk)
                size += len(chunk)
                if size > cls._MAX_ARCHIVE_BYTES or time.monotonic() - started > 60:
                    raise DependencyAdmissionError(["source download exceeded size/time bound"])
            return b"".join(chunks)
        except (OSError, http.client.HTTPException) as error:
            raise DependencyAdmissionError(["source archive download unavailable"]) from error
        finally:
            connection.close()

    @staticmethod
    def _path(name: str) -> str:
        """Reject traversal, absolute, duplicate-spelling and platform-specific archive names."""
        path = PurePosixPath(name.rstrip("/"))
        if (
            not name
            or path.is_absolute()
            or path.as_posix() != name.rstrip("/")
            or any(part in (".", "..") for part in path.parts)
            or "\\" in name
            or ":" in name
            or any(ord(character) < 32 for character in name)
        ):
            raise ValueError("unsafe archive member path")
        return path.as_posix()

    @classmethod
    def _source_files(cls, payload: bytes, commit: str) -> dict[str, bytes]:
        """Read regular runtime files and packaging inputs; ignore unexecuted examples/docs."""
        result: dict[str, bytes] = {}
        seen: set[str] = set()
        total = 0
        root = f"clearml-{commit}"
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            for member in archive:
                name = cls._path(member.name)
                total += member.size
                if (
                    name in seen
                    or len(seen) >= cls._MAX_MEMBERS
                    or total > cls._MAX_EXPANDED_BYTES
                    or member.size < 0
                ):
                    raise ValueError("duplicate or oversized source archive")
                seen.add(name)
                if name != root and not name.startswith(root + "/"):
                    raise ValueError("source archive root differs from admitted commit")
                relative = name.removeprefix(root + "/")
                selected = relative.startswith("clearml/") or relative in ("LICENSE", "setup.py")
                if member.isdir() or not selected:
                    continue
                if not member.isfile() or member.issparse():
                    raise ValueError("selected source member is not an ordinary file")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("source member is missing")
                with stream:
                    result[relative] = stream.read()
        return result

    @classmethod
    def _wheel_files(cls, payload: bytes) -> dict[str, bytes]:
        """Reject duplicate paths, symlinks, native extras and unbounded decompression."""
        seen: set[str] = set()
        total = 0
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            for member in members:
                name = cls._path(member.filename)
                total += member.file_size
                mode = stat.S_IFMT(member.external_attr >> 16)
                if (
                    name in seen
                    or len(seen) >= cls._MAX_MEMBERS
                    or total > cls._MAX_EXPANDED_BYTES
                    or member.is_dir()
                    or member.orig_filename != member.filename
                    or member.flag_bits & 0x61
                    or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    or mode not in (0, stat.S_IFREG)
                ):
                    raise ValueError("duplicate, special or oversized wheel member")
                seen.add(name)
            return {member.filename: archive.read(member) for member in members}

    @staticmethod
    def _packaging(source: dict[str, bytes], wheel: dict[str, bytes], version: str) -> None:
        """Check generated metadata explicitly and compare license/entry points to source."""
        prefix = f"clearml-{version}.dist-info/"
        if (
            wheel[prefix + "LICENSE"] != source["LICENSE"]
            or wheel[prefix + "top_level.txt"] != b"clearml\n"
        ):
            raise ValueError("wheel license or top-level package differs from source")
        headers = wheel[prefix + "METADATA"].decode().split("\n\n", 1)[0].splitlines()
        for field, expected in (("Name", "clearml"), ("Version", version)):
            if [line for line in headers if line.startswith(field + ":")] != [
                f"{field}: {expected}"
            ]:
                raise ValueError("wheel metadata identity differs from admission")
        wheel_headers = wheel[prefix + "WHEEL"].decode().splitlines()
        if [line for line in wheel_headers if line.startswith("Root-Is-Purelib:")] != [
            "Root-Is-Purelib: true"
        ]:
            raise ValueError("source comparison requires a pure Python wheel")
        if sorted(line for line in wheel_headers if line.startswith("Tag:")) != [
            "Tag: py2-none-any",
            "Tag: py3-none-any",
        ]:
            raise ValueError("unexpected wheel compatibility tags")
        config = configparser.ConfigParser(interpolation=None)
        config.read_string(wheel[prefix + "entry_points.txt"].decode())
        entries = sorted(f"{key} = {value}" for key, value in config.items("console_scripts"))
        authored: list[list[str]] = []
        for node in ast.walk(ast.parse(source["setup.py"])):
            if (
                isinstance(node, ast.keyword)
                and node.arg == "entry_points"
                and isinstance(node.value, ast.Dict)
            ):
                for key, value in zip(node.value.keys, node.value.values, strict=True):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "console_scripts"
                        and isinstance(value, ast.List)
                    ):
                        if not all(
                            isinstance(item, ast.Constant) and isinstance(item.value, str)
                            for item in value.elts
                        ):
                            raise ValueError("source entry points must be literal")
                        authored.append(
                            sorted(
                                item.value
                                for item in value.elts
                                if isinstance(item, ast.Constant) and isinstance(item.value, str)
                            )
                        )
        if config.sections() != ["console_scripts"] or config.defaults() or authored != [entries]:
            raise ValueError("wheel entry points differ from source")
        record_path = prefix + "RECORD"
        rows = list(csv.reader(io.StringIO(wheel[record_path].decode()), strict=True))
        if any(len(row) != 3 for row in rows) or len({row[0] for row in rows}) != len(rows):
            raise ValueError("malformed wheel RECORD")
        if {row[0] for row in rows} != set(wheel):
            raise ValueError("wheel RECORD inventory differs")
        for name, digest, size in rows:
            if name == record_path:
                if digest or size:
                    raise ValueError("wheel RECORD must leave its own digest empty")
                continue
            expected_digest = (
                base64.urlsafe_b64encode(hashlib.sha256(wheel[name]).digest()).decode().rstrip("=")
            )
            if digest != "sha256=" + expected_digest or size != str(len(wheel[name])):
                raise ValueError("wheel RECORD digest or size differs")
