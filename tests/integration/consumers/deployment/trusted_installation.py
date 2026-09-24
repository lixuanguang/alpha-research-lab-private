"""Accept real signed execution releases through isolated install and rollback."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import json
import subprocess  # nosec B404  # [owner=platform; rationale=isolated installed interpreter package inspection; expires=2027-03-01]
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

# third party library imports
from pydantic import TypeAdapter

# project library imports
from alpha_research_governance._models import ImmutableModel
from alpha_research_governance.artifact_supply_chain.bundles import ReleaseRegistry
from alpha_research_governance.artifact_supply_chain.installation import (
    InstallationReceipt,
    LocalInstallation,
)
from alpha_research_governance.artifact_supply_chain.provenance import ReleaseProvenance
from alpha_research_governance.artifact_supply_chain.records import (
    Digest,
    InstallationPolicy,
    ReleaseRuntime,
)
from alpha_research_governance.dependency_admission.selected_closure import SelectedClosureFacts

_FORBIDDEN_MODULES = (
    "accounting",
    "applications.explore",
    "clearml",
    "exchange_calendars",
    "feast",
    "IPython",
    "jupyterlab",
    "market_data",
    "matplotlib",
    "notebook",
    "pandas",
    "plotly",
    "QuantLib",
    "reportlab",
    "research",
    "simulation",
    "sklearn",
    "statsmodels",
    "telemetry",
    "torch",
    "vectorbt",
    "weasyprint",
)


class AcceptanceArguments(argparse.Namespace):
    """Hold exact local inputs for an installed release acceptance run."""

    policy: Path
    initial: Path
    upgrade: Path
    target: Path
    request: Path
    upgrade_request: Path
    output: Path


class InspectionOutput(ImmutableModel):
    """Parse the actual installed execution configuration report."""

    schema_version: str
    state_schema: str
    mode: str
    environment: str
    credential_mode: str
    profile: str
    profile_identity: str
    submission_available: Literal[False]


class SuppressedAdmission(ImmutableModel):
    """Require an installed admission result with no submission attempt."""

    status: Literal["suppressed"]
    reason: Literal["submission_disabled"]
    mode: str
    specification_identity: str
    profile_identity: str
    submission_attempted: Literal[False]


class AdmissionOutcome(ImmutableModel):
    """Record the larger request's actual suppressed or rejected installed result."""

    status: Literal["suppressed", "rejected"]
    reason: str
    mode: str
    specification_identity: str
    profile_identity: str
    submission_attempted: Literal[False]


class InstalledPackages(ImmutableModel):
    """Record exact installed distributions and modules exposed by isolated Python."""

    contracts_version: str
    execution_version: str
    distributions: dict[str, str]
    present_forbidden_modules: tuple[str, ...]


class PhaseEvidence(ImmutableModel):
    """Bind one selected slot to actual installed command and package behavior."""

    release: Digest
    slot: str
    configuration_sha256: Digest
    contracts_version: str
    inspection: InspectionOutput
    admission: SuppressedAdmission
    upgrade_request_admission: AdmissionOutcome


class TrustedInstallationResult(ImmutableModel):
    """Retain concise review evidence without credentials or signing keys."""

    schema_version: Literal["trusted-installation-acceptance-v2"] = (
        "trusted-installation-acceptance-v2"
    )
    checked_at: datetime
    request_sha256: Digest
    upgrade_request_sha256: Digest
    initial: PhaseEvidence
    upgrade: PhaseEvidence
    rollback: PhaseEvidence
    preserved_state_sha256: Digest
    production_request_rejected: Literal[True] = True


class InstalledEnvironmentProbe:
    """Inspect package metadata from the slot's own isolated interpreter."""

    program = """
import json
import sys
from importlib.metadata import distributions, version
from importlib.util import find_spec

forbidden = json.loads(sys.argv[1])
installed = {
    item.metadata["Name"].lower().replace("_", "-"): item.version
    for item in distributions()
}
print(json.dumps({
    "contracts_version": version("alpha-research-contracts"),
    "execution_version": version("alpha-research-execution"),
    "distributions": installed,
    "present_forbidden_modules": [
        name for name in forbidden if find_spec(name) is not None
    ],
}, sort_keys=True))
"""

    @classmethod
    def inspect(
        cls, target: Path, receipt: InstallationReceipt, facts: SelectedClosureFacts
    ) -> InstalledPackages:
        """Compare the installed environment with its signed complete wheel facts."""
        interpreter = target / receipt.slot / "venv/bin/python"
        completed = subprocess.run(  # nosec B603  # [owner=platform; rationale=verified venv Python with isolated metadata-only script; expires=2027-03-01]
            [str(interpreter), "-I", "-B", "-c", cls.program, json.dumps(_FORBIDDEN_MODULES)],
            cwd=target,
            env={
                "PATH": "/usr/bin:/bin",
                "LC_ALL": "C",
                "HOME": str(target),
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            capture_output=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            raise ValueError(
                "isolated installed package inspection failed: "
                + completed.stderr.decode(errors="replace")[-2000:]
            )
        observed = InstalledPackages.model_validate_json(completed.stdout)
        expected = {wheel.name: wheel.version for wheel in facts.wheels}
        if observed.distributions != expected:
            raise ValueError("installed distributions differ from signed wheel closure")
        if observed.present_forbidden_modules:
            raise ValueError("operating environment exposes research or reporting modules")
        if (
            observed.contracts_version != expected.get("alpha-research-contracts")
            or observed.execution_version != facts.root_version
            or facts.root_name != "alpha-research-execution"
        ):
            raise ValueError("installed operating package versions differ from signed facts")
        return observed


class TrustedInstallationAcceptance:
    """Exercise the full signed execution install, upgrade and rollback boundary."""

    def __init__(self, arguments: AcceptanceArguments) -> None:
        """Bind existing inputs and an absent local target outside the build path."""
        self.policy_path = arguments.policy.absolute()
        self.initial_path = arguments.initial.absolute()
        self.upgrade_path = arguments.upgrade.absolute()
        self.target = arguments.target.absolute()
        self.request = arguments.request.absolute()
        self.upgrade_request = arguments.upgrade_request.absolute()
        self.output = arguments.output.absolute()

    def run(self) -> TrustedInstallationResult:
        """Prove real installed behavior and preserve mutable state across switches."""
        if self.target.exists() or self.target.is_symlink():
            raise ValueError("acceptance target must be absent before installation")
        now = datetime.now(UTC)
        policy = InstallationPolicy.model_validate_json(
            ReleaseRegistry.read_regular(self.policy_path, 1_048_576)
        )
        initial = ReleaseRegistry.verify(self.initial_path, policy, now=now)
        upgrade = ReleaseRegistry.verify(self.upgrade_path, policy, now=now)
        self._require_compatible_releases(initial.manifest.runtime, upgrade.manifest.runtime)
        if initial.identity == upgrade.identity:
            raise ValueError("upgrade must be a distinct signed release")
        initial_config_sha256 = hashlib.sha256(
            initial.content("configuration/config.json")
        ).hexdigest()
        upgrade_config_sha256 = hashlib.sha256(
            upgrade.content("configuration/config.json")
        ).hexdigest()
        if initial_config_sha256 == upgrade_config_sha256:
            raise ValueError("execution upgrade must change authenticated configuration")
        initial_facts = ReleaseProvenance.verify(initial, now=now)
        upgrade_facts = ReleaseProvenance.verify(upgrade, now=now)
        request_bytes = ReleaseRegistry.read_regular(self.request, 1_048_576)
        upgrade_request_bytes = ReleaseRegistry.read_regular(self.upgrade_request, 1_048_576)
        request = TypeAdapter(dict[str, object]).validate_json(request_bytes)
        upgrade_request = TypeAdapter(dict[str, object]).validate_json(upgrade_request_bytes)
        if (
            request.get("requested_mode") != initial.manifest.runtime.mode
            or upgrade_request.get("requested_mode") != initial.manifest.runtime.mode
        ):
            raise ValueError("acceptance request mode differs from the signed release")
        request_sha256 = hashlib.sha256(request_bytes).hexdigest()
        upgrade_request_sha256 = hashlib.sha256(upgrade_request_bytes).hexdigest()
        if request_sha256 == upgrade_request_sha256:
            raise ValueError("upgrade request must differ from the initial request")
        installation = LocalInstallation(self.target, policy)

        first = installation.install(self.initial_path, now=now)
        first_evidence = self._phase(
            installation,
            first,
            initial_facts,
            initial_config_sha256,
            expected_upgrade_status="rejected",
            now=now,
        )
        self._reject_production_request(installation, request, now=now)
        sentinel = self.target / "state/deployment-acceptance.sentinel"
        with sentinel.open("xb") as stream:
            stream.write(b"mutable state retained across upgrade and rollback\n")
        sentinel_sha256 = hashlib.sha256(sentinel.read_bytes()).hexdigest()

        second = installation.install(self.upgrade_path, now=now)
        if second.previous_release != first.release or second.slot == first.slot:
            raise ValueError("upgrade did not select a new slot from the initial release")
        self._require_sentinel(sentinel, sentinel_sha256)
        second_evidence = self._phase(
            installation,
            second,
            upgrade_facts,
            upgrade_config_sha256,
            expected_upgrade_status="suppressed",
            now=now,
        )

        restored = installation.install(self.initial_path, now=now)
        if (
            restored.release != first.release
            or restored.previous_release != second.release
            or restored.slot in {first.slot, second.slot}
        ):
            raise ValueError("rollback did not restore the first signed release in a new slot")
        self._require_sentinel(sentinel, sentinel_sha256)
        restored_evidence = self._phase(
            installation,
            restored,
            initial_facts,
            initial_config_sha256,
            expected_upgrade_status="rejected",
            now=now,
        )
        result = TrustedInstallationResult(
            checked_at=now,
            request_sha256=request_sha256,
            upgrade_request_sha256=upgrade_request_sha256,
            initial=first_evidence,
            upgrade=second_evidence,
            rollback=restored_evidence,
            preserved_state_sha256=sentinel_sha256,
        )
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_bytes(result.model_dump_json(indent=2).encode() + b"\n")
        return result

    @staticmethod
    def _require_compatible_releases(first: ReleaseRuntime, second: ReleaseRuntime) -> None:
        """Keep this acceptance run on one execution mode and state schema."""
        if (
            first.application != "execution"
            or second.application != "execution"
            or first.mode != second.mode
            or first.config_schema != second.config_schema
            or first.state_schema != second.state_schema
        ):
            raise ValueError("acceptance requires compatible signed execution releases")

    def _phase(
        self,
        installation: LocalInstallation,
        receipt: InstallationReceipt,
        facts: SelectedClosureFacts,
        expected_config_sha256: str,
        *,
        expected_upgrade_status: Literal["suppressed", "rejected"],
        now: datetime,
    ) -> PhaseEvidence:
        """Assert installed CLI output and exact package closure for one slot."""
        if installation.current() != receipt:
            raise ValueError("active installation differs from selected phase")
        inspection = InspectionOutput.model_validate_json(installation.run(("inspect",), now=now))
        admission = SuppressedAdmission.model_validate_json(
            installation.run(("admit", "--request", str(self.request)), now=now)
        )
        upgrade_admission = AdmissionOutcome.model_validate_json(
            installation.run(("admit", "--request", str(self.upgrade_request)), now=now)
        )
        if (
            inspection.mode != receipt.runtime.mode
            or inspection.credential_mode != receipt.runtime.mode
        ):
            raise ValueError("installed inspection mode differs from signed release")
        if inspection.schema_version != receipt.runtime.config_schema:
            raise ValueError("installed configuration schema differs from signed release")
        if inspection.state_schema != receipt.runtime.state_schema:
            raise ValueError("installed state schema differs from signed release")
        if (
            admission.mode != receipt.runtime.mode
            or admission.profile_identity != inspection.profile_identity
            or not admission.specification_identity
            or not inspection.profile_identity
        ):
            raise ValueError("installed admission differs from inspected configuration")
        if (
            upgrade_admission.status != expected_upgrade_status
            or not upgrade_admission.reason
            or upgrade_admission.mode != receipt.runtime.mode
            or upgrade_admission.profile_identity != inspection.profile_identity
            or upgrade_admission.specification_identity != admission.specification_identity
        ):
            raise ValueError("larger request outcome differs from installed configuration")
        config_sha256 = hashlib.sha256(
            (installation.root / receipt.slot / "bundle/configuration/config.json").read_bytes()
        ).hexdigest()
        if config_sha256 != expected_config_sha256:
            raise ValueError("installed configuration bytes differ from signed release")
        packages = InstalledEnvironmentProbe.inspect(installation.root, receipt, facts)
        return PhaseEvidence(
            release=receipt.release,
            slot=str(installation.root / receipt.slot),
            configuration_sha256=config_sha256,
            contracts_version=packages.contracts_version,
            inspection=inspection,
            admission=admission,
            upgrade_request_admission=upgrade_admission,
        )

    @staticmethod
    def _reject_production_request(
        installation: LocalInstallation, request: dict[str, object], *, now: datetime
    ) -> None:
        """Change only requested mode and prove the actual installed CLI rejects it."""
        production = dict(request)
        production["requested_mode"] = "production"
        with TemporaryDirectory(prefix="release-production-request-") as temporary:
            path = Path(temporary) / "production-request.json"
            path.write_text(json.dumps(production, sort_keys=True), encoding="utf-8")
            try:
                installation.run(("admit", "--request", str(path)), now=now)
            except ValueError as error:
                if "request mode differs from the installed credential mode" not in str(error):
                    raise
            else:
                raise ValueError("production request passed the installed admission boundary")

    @staticmethod
    def _require_sentinel(path: Path, sha256: str) -> None:
        """Prove application state bytes survived the complete switch."""
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
            raise ValueError("mutable application state changed during the release switch")


def main(arguments: Sequence[str] | None = None) -> int:
    """Parse explicit signed artifacts and run one offline installed acceptance."""
    parser = argparse.ArgumentParser(description=__doc__)
    for option in (
        "policy",
        "initial",
        "upgrade",
        "target",
        "request",
        "upgrade-request",
        "output",
    ):
        parser.add_argument("--" + option, required=True, type=Path)
    parsed = parser.parse_args(arguments, namespace=AcceptanceArguments())
    result = TrustedInstallationAcceptance(parsed).run()
    print(f"Trusted installation accepted: {result.rollback.release}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
