"""Exercise verified source admission with independent tiny archives and deliberate corruption."""

from __future__ import annotations

# standard library imports
import base64
import csv
import hashlib
import http.client
import io
import tarfile
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest

# project library imports
from alpha_research_governance.dependency_admission import load_policy, validate_repository
from alpha_research_governance.dependency_admission.models import (
    DependencyAdmissionError,
    SourceArchiveAdmission,
)
from alpha_research_governance.dependency_admission.policy import _python_lock_findings
from alpha_research_governance.dependency_admission.source_archives import SourceArchiveVerifier

_ROOT = Path(__file__).parents[2]
_POLICY = _ROOT / "docs/architecture/dependency-admission.toml"


class TestSourceArchives:
    """Keep source verification independent of network, SDK imports and the real archive."""

    @staticmethod
    def _archives(case: str = "valid") -> tuple[SourceArchiveAdmission, bytes, bytes]:
        """Build a complete pure-wheel example with code, a resource and generated metadata."""
        commit, version = "a" * 40, "2.1.12"
        prefix = f"clearml-{version}.dist-info/"
        source = {
            "clearml/__init__.py": b"VALUE = 1\n",
            "clearml/version.py": b'__version__ = "2.1.12"\n',
            "clearml/default.conf": b"setting = true\n",
            "LICENSE": b"Authored test license\n",
            "setup.py": b'setup(entry_points={"console_scripts": ["clearml-init = clearml:main"]})',
        }
        wheel = {name: payload for name, payload in source.items() if name.startswith("clearml/")}
        wheel.update(
            {
                prefix + "LICENSE": source["LICENSE"],
                prefix + "METADATA": b"Metadata-Version: 2.1\nName: clearml\nVersion: 2.1.12\n\n",
                prefix + "WHEEL": (
                    b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\n"
                    b"Tag: py2-none-any\nTag: py3-none-any\n"
                ),
                prefix + "top_level.txt": b"clearml\n",
                prefix + "entry_points.txt": b"[console_scripts]\nclearml-init = clearml:main\n",
            }
        )
        if case == "changed-runtime":
            wheel["clearml/__init__.py"] = b"VALUE = 2\n"
        elif case == "missing-resource":
            del wheel["clearml/default.conf"]
        elif case == "extra-runtime":
            wheel["clearml/injected.py"] = b"VALUE = 3\n"
        elif case == "extra-install-hook":
            wheel["injected.pth"] = b"import os\n"
        elif case == "metadata-version":
            wheel[prefix + "METADATA"] = b"Name: clearml\nVersion: 9.9.9\n\n"
        elif case == "entrypoint":
            wheel[prefix + "entry_points.txt"] = (
                b"[console_scripts]\nclearml-init = clearml:other\n"
            )
        elif case == "license":
            wheel[prefix + "LICENSE"] = b"Different license\n"
        elif case == "native":
            wheel[prefix + "WHEEL"] = b"Root-Is-Purelib: false\n"
        elif case == "traversal":
            source["../escape.py"] = b"escaped\n"
        elif case == "wheel-traversal":
            wheel["../escape.py"] = b"escaped\n"
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        for name, payload in wheel.items():
            digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode().rstrip("=")
            writer.writerow((name, "sha256=" + digest, str(len(payload))))
        writer.writerow((prefix + "RECORD", "", ""))
        wheel[prefix + "RECORD"] = output.getvalue().encode()
        if case == "record":
            wheel[prefix + "RECORD"] = wheel[prefix + "RECORD"].replace(b"sha256=", b"sha512=", 1)
        source_buffer, wheel_buffer = io.BytesIO(), io.BytesIO()
        with tarfile.open(fileobj=source_buffer, mode="w:gz") as archive:
            for name, payload in source.items():
                member = tarfile.TarInfo(f"clearml-{commit}/{name}")
                member.size = len(payload)
                if case == "source-link" and name == "clearml/__init__.py":
                    member.type, member.linkname, member.size = tarfile.SYMTYPE, "/etc/passwd", 0
                archive.addfile(member, io.BytesIO(payload))
                if case == "duplicate-source" and name == "clearml/__init__.py":
                    archive.addfile(member, io.BytesIO(payload))
        with zipfile.ZipFile(wheel_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in wheel.items():
                zip_member = zipfile.ZipInfo(name)
                if case == "wheel-link" and name == "clearml/__init__.py":
                    zip_member.external_attr = 0o120777 << 16
                archive.writestr(zip_member, payload)
                if case == "duplicate-wheel" and name == "clearml/__init__.py":
                    with pytest.warns(UserWarning, match="Duplicate"):
                        archive.writestr(zip_member, payload)
        source_bytes, wheel_bytes = source_buffer.getvalue(), wheel_buffer.getvalue()
        binding = SourceArchiveAdmission(
            name="clearml",
            version=version,
            commit=commit,
            source_sha256=hashlib.sha256(source_bytes).hexdigest(),
            wheel_sha256=hashlib.sha256(wheel_bytes).hexdigest(),
            wheel_url="https://files.pythonhosted.org/packages/example/clearml-2.1.12-py2.py3-none-any.whl",
        )
        return binding, source_bytes, wheel_bytes

    def test_complete_comparison_and_rehashed_offline_cache(self, tmp_path: Path) -> None:
        """Verify source code/resources, then reuse bytes offline and reject cache corruption."""
        binding, source, wheel = self._archives()
        verifier = SourceArchiveVerifier(tmp_path)
        downloads = (source, wheel)
        with patch.object(SourceArchiveVerifier, "_download", side_effect=downloads) as fetch:
            assert verifier.verify(binding) == 3
            assert fetch.call_count == 2
        with patch.object(
            SourceArchiveVerifier, "_download", side_effect=AssertionError("network")
        ):
            assert verifier.verify(binding) == 3
            (tmp_path / binding.wheel_sha256).write_bytes(b"corrupt cached bytes")
            with pytest.raises(DependencyAdmissionError, match="digest mismatch"):
                verifier.verify(binding)

    @pytest.mark.parametrize(
        "case",
        [
            "changed-runtime",
            "missing-resource",
            "extra-runtime",
            "extra-install-hook",
            "metadata-version",
            "entrypoint",
            "license",
            "native",
            "record",
            "traversal",
            "wheel-traversal",
            "source-link",
            "wheel-link",
            "duplicate-source",
            "duplicate-wheel",
        ],
    )
    def test_source_and_packaging_mismatches_block_admission(
        self, tmp_path: Path, case: str
    ) -> None:
        """Even correctly pinned archives cannot authorize changed runtime or unsafe packaging."""
        binding, source, wheel = self._archives(case)
        downloads = (source, wheel)
        with patch.object(SourceArchiveVerifier, "_download", side_effect=downloads):
            with pytest.raises(DependencyAdmissionError, match="source comparison failed"):
                SourceArchiveVerifier(tmp_path).verify(binding)

    def test_download_digest_failure_is_not_cached(self, tmp_path: Path) -> None:
        """Refuse downloaded bytes whose hash differs from the reviewed identity."""
        binding, _, _ = self._archives()
        with patch.object(SourceArchiveVerifier, "_download", return_value=b"changed"):
            with pytest.raises(DependencyAdmissionError, match="digest mismatch"):
                SourceArchiveVerifier(tmp_path).verify(binding)
        assert not tuple(tmp_path.iterdir())

    def test_download_failure_never_authorizes_source(self, tmp_path: Path) -> None:
        """Surface an unavailable source and retain no success marker or partial cache entry."""
        binding, _, _ = self._archives()
        with patch.object(http.client.HTTPSConnection, "request", side_effect=OSError("offline")):
            with pytest.raises(DependencyAdmissionError, match="download unavailable"):
                SourceArchiveVerifier(tmp_path).verify(binding)
        assert not tuple(tmp_path.iterdir())

    def test_archive_expansion_limit(self, tmp_path: Path) -> None:
        """Refuse expanded payloads beyond the memory budget before comparing contents."""
        binding, source, wheel = self._archives()
        downloads = (source, wheel)
        with patch.object(SourceArchiveVerifier, "_download", side_effect=downloads):
            with patch.object(SourceArchiveVerifier, "_MAX_EXPANDED_BYTES", 1):
                with pytest.raises(DependencyAdmissionError, match="oversized"):
                    SourceArchiveVerifier(tmp_path).verify(binding)

    def test_repository_gate_requires_actual_verification(self) -> None:
        """A valid policy cannot bypass a failed artifact comparison."""
        with patch.object(
            SourceArchiveVerifier, "verify", side_effect=DependencyAdmissionError(["mismatch"])
        ):
            with pytest.raises(DependencyAdmissionError, match="mismatch"):
                validate_repository(_ROOT, validation_date=date(2026, 9, 20))

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ('name = "clearml"', 'name = "other"'),
            ('version = "2.1.12"', 'version = "2.1.11"'),
            ('commit = "559467f550c0d23dc3506ee551386c3b59e6b091"', 'commit = "main"'),
            (
                'source_sha256 = "'
                + "56fabf73b333d28c6bd6cf031215aa8ae387746b7088f08f5a54b89a4c98f7fa"
                + '"',
                'source_sha256 = "bad"',
            ),
            ('wheel_url = "https://files.pythonhosted.org', 'wheel_url = "https://evil.invalid'),
        ],
    )
    def test_policy_rejects_unbound_archive_identity(
        self, tmp_path: Path, old: str, new: str
    ) -> None:
        """Keep the reviewed upstream, exact package version and immutable digests mandatory."""
        path = tmp_path / "policy.toml"
        path.write_text(_POLICY.read_text().replace(old, new, 1))
        with pytest.raises(DependencyAdmissionError):
            load_policy(path)

    def test_duplicate_source_bindings_are_rejected(self, tmp_path: Path) -> None:
        """Refuse ambiguous source authorizations."""
        content = _POLICY.read_text()
        binding = content.split("[[source_archives]]", 1)[1].split("[[wheel_only_allowances]]", 1)[
            0
        ]
        path = tmp_path / "policy.toml"
        path.write_text(content + "\n[[source_archives]]" + binding)
        with pytest.raises(DependencyAdmissionError, match="duplicate source"):
            load_policy(path)

    def test_archive_binding_cannot_override_lock(self, tmp_path: Path) -> None:
        """Reject changed wheel hashes even when the upstream archive still matches its pin."""
        lock = (_ROOT / "uv.lock").read_text()
        binding = load_policy(_POLICY).source_archives[0]
        (tmp_path / "uv.lock").write_text(lock.replace(binding.wheel_sha256, "b" * 64))
        findings = _python_lock_findings(
            tmp_path, load_policy(_POLICY), validation_date=date(2026, 9, 20)
        )
        assert any("source archive must bind the exact locked wheel" in item for item in findings)

    def test_no_binding_restores_the_source_distribution_requirement(self, tmp_path: Path) -> None:
        """Removing an alternate source record never creates implicit wheel-only permission."""
        before, binding = _POLICY.read_text().split("[[source_archives]]", 1)
        _, allowance = binding.split("[[wheel_only_allowances]]", 1)
        path = tmp_path / "policy.toml"
        path.write_text("source_archives = []\n" + before + "[[wheel_only_allowances]]" + allowance)
        findings = _python_lock_findings(
            _ROOT, load_policy(path), validation_date=date(2026, 9, 20)
        )
        assert "clearml lacks a digest-bound source distribution" in findings

    def test_native_classification_cannot_use_archive_comparison(self, tmp_path: Path) -> None:
        """Prevent the pure-file comparison from authorizing a native dependency."""
        path = tmp_path / "policy.toml"
        path.write_text(
            _POLICY.read_text().replace(
                "native_python_packages = [", 'native_python_packages = ["clearml",', 1
            )
        )
        with pytest.raises(DependencyAdmissionError, match="exact pure package"):
            load_policy(path)

    @pytest.mark.parametrize("status", [302, 404])
    def test_redirects_and_failed_http_statuses_are_not_followed(
        self, tmp_path: Path, status: int
    ) -> None:
        """Refuse redirect and missing artifacts instead of changing the reviewed origin."""
        binding, _, _ = self._archives()
        reply = _DownloadReply(status)
        with patch.object(http.client.HTTPSConnection, "request") as request:
            with patch.object(http.client.HTTPSConnection, "getresponse", return_value=reply):
                with pytest.raises(DependencyAdmissionError, match=f"HTTP {status}"):
                    SourceArchiveVerifier(tmp_path).verify(binding)
        assert request.call_count == 1
        assert not tuple(tmp_path.iterdir())

    def test_download_size_bound(self, tmp_path: Path) -> None:
        """Stop an oversized response before accepting or publishing downloaded bytes."""
        binding, _, _ = self._archives()
        with patch.object(http.client.HTTPSConnection, "request"):
            with patch.object(
                http.client.HTTPSConnection, "getresponse", return_value=_DownloadReply(200)
            ):
                with patch.object(SourceArchiveVerifier, "_MAX_ARCHIVE_BYTES", 1):
                    with pytest.raises(DependencyAdmissionError, match="size/time bound"):
                        SourceArchiveVerifier(tmp_path).verify(binding)
        assert not tuple(tmp_path.iterdir())


class _DownloadReply:
    """Supply a response with an explicit status and an oversized constant chunk."""

    def __init__(self, status: int) -> None:
        """Bind the status for a mocked HTTPS response."""
        self.status = status

    def read(self, size: int) -> bytes:
        """Return a finite chunk while the caller owns its aggregate transfer bound."""
        return b"x" * min(size, 64)
