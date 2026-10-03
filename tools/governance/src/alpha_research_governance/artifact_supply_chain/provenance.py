"""Bind release inventories to retained source, audited admission and exact wheel bytes."""

from __future__ import annotations

# standard library imports
import configparser
import hashlib
import io
import tomllib
import zipfile
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, cast

# third party library imports
from pydantic import TypeAdapter

# project library imports
from alpha_research_governance._models import ImmutableModel
from alpha_research_governance.artifact_supply_chain.bundles import VerifiedRelease
from alpha_research_governance.artifact_supply_chain.records import ReleaseFile
from alpha_research_governance.dependency_admission import DependencyPolicy, PipAuditReport
from alpha_research_governance.dependency_admission.selected_closure import (
    SelectedClosureAdmission,
    SelectedClosureFacts,
)
from alpha_research_governance.dependency_admission.wheel_archive import WheelArchive


class SourceSnapshot(ImmutableModel):
    """Retain source input identities separately from a possibly dirty base commit."""

    schema_version: Literal["release-source"] = "release-source"
    files: tuple[ReleaseFile, ...]


class _EntryPoints(configparser.ConfigParser):
    """Preserve case in executable names instead of applying INI option normalization."""

    def optionxform(self, optionstr: str) -> str:
        """Retain the exact command spelling installed from the wheel."""
        return optionstr


class ReleaseProvenance:
    """Recheck signed admission and source correspondence without the build checkout."""

    @classmethod
    def verify(cls, release: VerifiedRelease, *, now: datetime) -> SelectedClosureFacts:
        """Reject a signed but incomplete or inconsistent build before installation.

        Trusted builders attest the audit and source build. Verification independently
        checks retained bytes, audit coverage, policy dates and local wheel/source
        correspondence; it does not claim reproducible native dependency builds.
        """
        facts = SelectedClosureFacts.model_validate_json(release.content("provenance/closure.json"))
        if (
            facts.root_name != release.manifest.root_distribution
            or facts.target != "darwin_arm64_cp314"
            or release.manifest.runtime.platform != "darwin_arm64"
            or now.date() > facts.review_due_on
            or release.manifest.valid_until.date() > facts.review_due_on
        ):
            raise ValueError("release closure target, root or policy lifetime is incompatible")
        for name, expected in (
            ("provenance/uv.lock", facts.root_lock_sha256),
            ("provenance/selected.lock", facts.selected_lock_sha256),
            ("provenance/dependency-admission.toml", facts.policy_sha256),
        ):
            if hashlib.sha256(release.content(name)).hexdigest() != expected:
                raise ValueError("release admission identity differs from retained inputs")
        source = SourceSnapshot.model_validate_json(release.content("provenance/source.json"))
        observed_source = tuple(
            ReleaseFile.describe(name.removeprefix("source/"), content)
            for name, content in release.contents
            if name.startswith("source/")
        )
        if source.files != observed_source or not source.files:
            raise ValueError("release source snapshot is missing or inconsistent")
        cls._configuration(release)
        by_filename = {wheel.filename: wheel for wheel in facts.wheels}
        if len(by_filename) != len(facts.wheels):
            raise ValueError("release closure contains duplicate wheel identities")
        observed_wheels = {
            name.removeprefix("wheels/")
            for name, _ in release.contents
            if name.startswith("wheels/")
        }
        if observed_wheels != by_filename.keys():
            raise ValueError("release wheel inventory differs from admitted closure")
        with TemporaryDirectory(prefix="ar-provenance-") as temporary:
            directory = Path(temporary)
            policy_path = directory / "dependency-admission.toml"
            policy_path.write_bytes(release.content("provenance/dependency-admission.toml"))
            policy = DependencyPolicy.load(policy_path)
            if policy.review_due_on != facts.review_due_on or now.date() > policy.review_due_on:
                raise ValueError("retained dependency policy is expired")
            audit = directory / "audit.json"
            audit.write_bytes(release.content("provenance/audit.json"))
            PipAuditReport.assess(audit, policy)
            disallowed = {item.name for item in policy.wheel_only_allowances}
            if disallowed.intersection(wheel.name for wheel in facts.wheels):
                raise ValueError("release includes a development-only dependency")
            wheels: list[Path] = []
            for filename, expected_wheel in by_filename.items():
                wheel_path = directory / filename
                wheel_path.write_bytes(release.content("wheels/" + filename))
                wheels.append(wheel_path)
                if WheelArchive.inspect(wheel_path) != expected_wheel:
                    raise ValueError("release wheel metadata differs from admitted bytes")
                if expected_wheel.name.startswith("alpha-research-"):
                    cls._local_source(release, filename, expected_wheel.name)
            root_lock = directory / "root.lock"
            selected_lock = directory / "selected.lock"
            root_lock.write_bytes(release.content("provenance/uv.lock"))
            selected_lock.write_bytes(release.content("provenance/selected.lock"))
            SelectedClosureAdmission.verify_retained(
                facts,
                root_lock=root_lock,
                selected_lock=selected_lock,
                policy=policy,
                wheels=wheels,
            )
        return facts

    @staticmethod
    def _configuration(release: VerifiedRelease) -> None:
        """Bind executable configuration mode/schema to the signed runtime declaration."""
        config = TypeAdapter(dict[str, object]).validate_json(
            release.content("configuration/config.json")
        )
        runtime = release.manifest.runtime
        if config.get("schema_version") != runtime.config_schema:
            raise ValueError("configuration schema differs from signed release")
        if runtime.application == "execution" and config.get("mode") != runtime.mode:
            raise ValueError("execution configuration mode differs from signed release")

    @staticmethod
    def _local_source(release: VerifiedRelease, filename: str, distribution: str) -> None:
        """Compare every installed local payload file to its retained monorepo source."""
        package = distribution.removeprefix("alpha-research-")
        if package not in {"contracts", "collector", "execution"}:
            raise ValueError("unknown local release distribution")
        source = TypeAdapter(dict[str, object]).validate_python(
            cast(
                object,
                tomllib.loads(
                    release.content(f"source/packages/{package}/pyproject.toml").decode()
                ),
            )
        )
        project = TypeAdapter(dict[str, object]).validate_python(source.get("project"))
        scripts = TypeAdapter(dict[str, str]).validate_python(project.get("scripts", {}))
        if project.get("name") != distribution:
            raise ValueError("local wheel and source project identities differ")
        with zipfile.ZipFile(io.BytesIO(release.content("wheels/" + filename))) as archive:
            entrypoints = [
                name for name in archive.namelist() if name.endswith(".dist-info/entry_points.txt")
            ]
            observed: dict[str, str] = {}
            for entrypoint in entrypoints:
                parser = _EntryPoints(interpolation=None)
                parser.read_string(archive.read(entrypoint).decode())
                if parser.sections() != ["console_scripts"]:
                    raise ValueError("local wheel contains unapproved entrypoint groups")
                observed = dict(parser.items("console_scripts"))
            if len(entrypoints) > 1 or observed != scripts:
                raise ValueError("local wheel entrypoints differ from retained source")
            for member in archive.infolist():
                if member.is_dir() or member.filename.split("/", 1)[0].endswith(".dist-info"):
                    continue
                source_name = "source/src/" + member.filename
                if archive.read(member) != release.content(source_name):
                    raise ValueError("local wheel differs from retained source snapshot")
