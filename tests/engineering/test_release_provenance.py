"""Reject semantically inconsistent bytes inside an otherwise inventoried release."""

from __future__ import annotations

# standard library imports
import hashlib
import io
import zipfile
from datetime import UTC, datetime, timedelta

# third party library imports
import pytest

# project library imports
from alpha_research_governance.artifact_supply_chain.builds import ReleaseBuilder
from alpha_research_governance.artifact_supply_chain.bundles import VerifiedRelease
from alpha_research_governance.artifact_supply_chain.provenance import (
    ReleaseProvenance,
    SourceSnapshot,
)
from alpha_research_governance.artifact_supply_chain.records import (
    ReleaseFile,
    ReleaseManifest,
    ReleaseRuntime,
    StateEnvelope,
)
from alpha_research_governance.dependency_admission.models import DependencyAdmissionError
from alpha_research_governance.dependency_admission.selected_closure import SelectedClosureFacts


class TestReleaseProvenance:
    """Exercise retained release semantics after manifest and signature validation."""

    @staticmethod
    def _sha256(content: bytes) -> str:
        """Identify fixture inputs independently of the production fact builder."""
        return hashlib.sha256(content).hexdigest()

    @classmethod
    def _release(cls) -> tuple[VerifiedRelease, datetime]:
        """Make a small inventory with valid policy, source and audit inputs."""
        now = datetime.now(UTC)
        review = now.date() + timedelta(days=15)
        root_lock = b'version = 1\nrevision = 3\nrequires-python = "==3.14.*"\n'
        selected_lock = root_lock + (
            b'\n[[package]]\nname = "alpha-research-collector"\nversion = "0.1.0"\n'
            b'source = { editable = "." }\n'
        )
        policy = (
            "schema_version = 5\n"
            f'as_of_date = "{now.date().isoformat()}"\n'
            f'review_due_on = "{review.isoformat()}"\n'
            "native_python_packages = []\n"
            "wheel_only_allowances = []\n"
            "source_archives = []\n"
            'license_groups = [{disposition = "approved", license_expression = "MIT", '
            'packages = ["example==1.0"]}]\n'
            "[lock_digests]\n"
            f'"uv.lock" = "{cls._sha256(root_lock)}"\n'
            f'"packages/collector/uv.lock" = "{cls._sha256(selected_lock)}"\n'
            f'"packages/execution/uv.lock" = "{cls._sha256(selected_lock)}"\n'
            f'"packages/paper-services/uv.lock" = "{cls._sha256(selected_lock)}"\n'
            "[pip_audit]\n"
            'command_mode = "exact_locked_graph"\n'
            'failure_policy = "block_unresolved_findings_or_skips"\n'
            'service = "pypi"\n'
            'version = "2.10.1"\n'
        ).encode()
        source_bytes = b"retained source\n"
        source = SourceSnapshot(files=(ReleaseFile.describe("README.txt", source_bytes),))
        facts = SelectedClosureFacts(
            root_name="alpha-research-collector",
            root_version="0.1.0",
            target="darwin_arm64_cp314",
            marker_environment=(),
            policy_sha256=cls._sha256(policy),
            root_lock_sha256=cls._sha256(root_lock),
            selected_lock_sha256=cls._sha256(selected_lock),
            review_due_on=review,
            wheels=(),
            edges=(),
        )
        state = StateEnvelope(schema_version="state", application="collector", files=())
        contents = (
            ("configuration/config.json", b'{"schema_version":"config"}\n'),
            (
                "provenance/audit.json",
                b'{"dependencies":[{"name":"example","version":"1.0","vulns":[]}],"fixes":[]}\n',
            ),
            ("provenance/closure.json", facts.model_dump_json().encode()),
            ("provenance/dependency-admission.toml", policy),
            ("provenance/selected.lock", selected_lock),
            ("provenance/source.json", source.model_dump_json().encode()),
            ("provenance/uv.lock", root_lock),
            ("source/README.txt", source_bytes),
            ("state/state.json", state.model_dump_json().encode()),
        )
        manifest = ReleaseManifest(
            name="collector-release",
            builder="trusted-builder",
            origin="local-builder",
            created_at=now - timedelta(hours=1),
            valid_until=now + timedelta(days=1),
            source_commit="a" * 40,
            source_dirty=False,
            build_commands=(("uv", "build", "--offline"),),
            runtime=ReleaseRuntime(
                python_version="3.14.7",
                platform="darwin_arm64",
                contract_version="1",
                application="collector",
                mode="collection",
                config_schema="config",
                state_schema="state",
            ),
            root_distribution="alpha-research-collector",
            files=tuple(ReleaseFile.describe(name, content) for name, content in contents),
        )
        return VerifiedRelease(manifest, manifest.encoded(), b"test-signature", contents), now

    @staticmethod
    def _replace(release: VerifiedRelease, name: str, content: bytes) -> VerifiedRelease:
        """Re-inventory a deliberate semantic change as an authenticated input."""
        contents = tuple(
            sorted(
                (
                    path,
                    content if path == name else original,
                )
                for path, original in release.contents
            )
        )
        if name not in {path for path, _ in contents}:
            contents = tuple(sorted((*contents, (name, content))))
        original = release.manifest
        manifest = ReleaseManifest(
            name=original.name,
            builder=original.builder,
            origin=original.origin,
            created_at=original.created_at,
            valid_until=original.valid_until,
            source_commit=original.source_commit,
            source_dirty=original.source_dirty,
            build_commands=original.build_commands,
            runtime=original.runtime,
            root_distribution=original.root_distribution,
            files=tuple(ReleaseFile.describe(path, payload) for path, payload in contents),
        )
        return VerifiedRelease(manifest, manifest.encoded(), release.signature, contents)

    @staticmethod
    def _wheel(*, payload: bytes, command: str) -> bytes:
        """Build a tiny source-comparable wheel with a console entrypoint."""
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("collector_pkg/__init__.py", payload)
            archive.writestr(
                "alpha_research_collector-0.1.0.dist-info/entry_points.txt",
                "[console_scripts]\nalpha-collect = " + command + "\n",
            )
        return output.getvalue()

    @classmethod
    def _local_source_release(cls) -> tuple[VerifiedRelease, str]:
        """Retain one matching local project, wheel payload and script declaration."""
        release, _ = cls._release()
        filename = "alpha_research_collector-0.1.0-py3-none-any.whl"
        release = cls._replace(
            release,
            "source/packages/collector/pyproject.toml",
            b'[project]\nname = "alpha-research-collector"\n'
            b'[project.scripts]\nalpha-collect = "collector_pkg:main"\n',
        )
        release = cls._replace(
            release, "source/src/collector_pkg/__init__.py", b"def main(): pass\n"
        )
        release = cls._replace(
            release,
            "wheels/" + filename,
            cls._wheel(payload=b"def main(): pass\n", command="collector_pkg:main"),
        )
        return release, filename

    def test_retained_source_snapshot_must_match_inventory(self) -> None:
        """A re-inventoried source edit cannot borrow an older source attestation."""
        release, now = self._release()
        changed = self._replace(release, "source/README.txt", b"changed source\n")
        with pytest.raises(ValueError, match="source snapshot is missing or inconsistent"):
            ReleaseProvenance.verify(changed, now=now)

    def test_selected_lock_must_match_signed_closure_fact(self) -> None:
        """A re-inventoried selected lock cannot borrow the prior closure digest."""
        release, now = self._release()
        changed = self._replace(
            release, "provenance/selected.lock", b"version = 1\n# changed lock\n"
        )
        with pytest.raises(ValueError, match="admission identity differs from retained inputs"):
            ReleaseProvenance.verify(changed, now=now)

    def test_pip_audit_must_cover_admitted_package(self) -> None:
        """An otherwise retained release cannot omit a locked package's scan."""
        release, now = self._release()
        changed = self._replace(
            release, "provenance/audit.json", b'{"dependencies":[],"fixes":[]}\n'
        )
        with pytest.raises(DependencyAdmissionError, match="pip-audit coverage differs"):
            ReleaseProvenance.verify(changed, now=now)

    def test_wheel_payload_must_equal_retained_local_source(self) -> None:
        """Even a wheel owned by the right project cannot replace its source bytes."""
        release, filename = self._local_source_release()
        ReleaseProvenance._local_source(
            release, filename, "alpha-research-collector", "packages/collector"
        )
        changed = self._replace(
            release,
            "wheels/" + filename,
            self._wheel(payload=b"def main(): return 'different'\n", command="collector_pkg:main"),
        )
        with pytest.raises(ValueError, match="local wheel differs from retained source snapshot"):
            ReleaseProvenance._local_source(
                changed, filename, "alpha-research-collector", "packages/collector"
            )

    def test_wheel_entrypoint_must_equal_retained_project(self) -> None:
        """A wheel cannot silently choose another executable target."""
        release, filename = self._local_source_release()
        ReleaseProvenance._local_source(
            release, filename, "alpha-research-collector", "packages/collector"
        )
        changed = self._replace(
            release,
            "wheels/" + filename,
            self._wheel(payload=b"def main(): pass\n", command="collector_pkg:other"),
        )
        with pytest.raises(ValueError, match="entrypoints differ from retained source"):
            ReleaseProvenance._local_source(
                changed, filename, "alpha-research-collector", "packages/collector"
            )

    @classmethod
    def _extension_release(cls, *, entry_points: str) -> tuple[VerifiedRelease, str]:
        """Retain one extension project, its src-layout source and a matching wheel."""
        release, _ = cls._release()
        filename = "engineering_candidates-0.1.0-py3-none-any.whl"
        release = cls._replace(
            release,
            "source/extensions/engineering-candidates/pyproject.toml",
            b'[project]\nname = "engineering-candidates"\n'
            b'[project.entry-points."alpha_research.candidate_components"]\n'
            b'engineering-candidates = "engineering_candidates:ComponentProvider"\n',
        )
        payload = b"class ComponentProvider: pass\n"
        release = cls._replace(
            release,
            "source/extensions/engineering-candidates/src/engineering_candidates/__init__.py",
            payload,
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("engineering_candidates/__init__.py", payload)
            archive.writestr(
                "engineering_candidates-0.1.0.dist-info/entry_points.txt", entry_points
            )
        return cls._replace(release, "wheels/" + filename, output.getvalue()), filename

    def test_extension_wheel_matches_its_own_source_and_registration(self) -> None:
        """An extension maps to extensions/<name>/src and may only register a provider."""
        project = "extensions/engineering-candidates"
        provider = (
            "[alpha_research.candidate_components]\n"
            "engineering-candidates = engineering_candidates:ComponentProvider\n"
        )
        release, filename = self._extension_release(entry_points=provider)
        ReleaseProvenance._local_source(release, filename, "engineering-candidates", project)
        script, _ = self._extension_release(
            entry_points=provider + "[console_scripts]\nrun = engineering_candidates:main\n"
        )
        with pytest.raises(ValueError, match="entrypoints differ"):
            ReleaseProvenance._local_source(script, filename, "engineering-candidates", project)
        with pytest.raises(ValueError, match="unknown local release distribution"):
            ReleaseProvenance._local_source(release, filename, "engineering-candidates", "tools/x")

    def test_external_sources_are_signed_in_the_order_verification_reads(self) -> None:
        """External extension files sort among the repository's, as the release lists them."""
        repository = (("extensions/a/pyproject.toml", b"a"), ("packages/b/pyproject.toml", b"b"))
        external = (("external/qr/pyproject.toml", b"q"),)
        sources = ReleaseBuilder.release_sources(repository, external)
        assert [name for name, _ in sources] == [
            "extensions/a/pyproject.toml",
            "external/qr/pyproject.toml",
            "packages/b/pyproject.toml",
        ]
        snapshot = SourceSnapshot(
            files=tuple(ReleaseFile.describe(name, content) for name, content in sources)
        )
        listed = tuple(
            ReleaseFile.describe(name.removeprefix("source/"), content)
            for name, content in sorted(("source/" + name, content) for name, content in sources)
        )
        assert snapshot.files == listed

    def test_external_extension_wheel_matches_its_signed_external_source(self) -> None:
        """An extension built outside the repository maps to source/external/<name>/src."""
        provider = (
            "[alpha_research.candidate_components]\n"
            "engineering-candidates = engineering_candidates:ComponentProvider\n"
        )
        release, filename = self._extension_release(entry_points=provider)
        for name, content in tuple(release.contents):
            if name.startswith("source/extensions/engineering-candidates/"):
                release = self._replace(
                    release,
                    name.replace("source/extensions/", "source/external/", 1),
                    content,
                )
        ReleaseProvenance._local_source(
            release, filename, "engineering-candidates", "external/engineering-candidates"
        )
        with pytest.raises(ValueError, match="identities differ"):
            ReleaseProvenance._local_source(
                release, filename, "other-extension", "external/engineering-candidates"
            )
