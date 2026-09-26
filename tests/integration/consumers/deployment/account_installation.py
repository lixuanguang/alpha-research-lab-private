"""Qualify a real signed shared-account release through install, upgrade and rollback.

Copy this consumer outside the checkout and run it with the installed governance
interpreter. Both inputs are independently signed execution releases with the
same account configuration and the account-journal-v2 state contract. The
optional request is one caller-authored local ``post`` fact; without it, this
consumer authors an identified one-unit funding transfer after its account stop.
No step has executable venue authority.
"""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import json
import sqlite3
import subprocess  # nosec B404  # [owner=platform; rationale=isolated installed interpreter package inspection; expires=2027-03-01]
import sys
from collections.abc import Sequence
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

# third party library imports
from pydantic import BaseModel, ConfigDict

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
    StateEnvelope,
)
from alpha_research_governance.dependency_admission.selected_closure import SelectedClosureFacts

_REQUIRED_MODULES = ("accounting", "applications.execute", "execution", "runtime", "telemetry")
_FORBIDDEN_MODULES = (
    "applications.explore",
    "clearml",
    "feast",
    "IPython",
    "jupyterlab",
    "market_data",
    "matplotlib",
    "notebook",
    "pandas",
    "plotly",
    "QuantLib",
    "research",
    "simulation",
    "sklearn",
    "statsmodels",
    "torch",
    "vectorbt",
    "weasyprint",
)


class AcceptanceArguments(argparse.Namespace):
    """Hold explicit local paths; none confers executable account authority."""

    policy: Path
    initial: Path
    upgrade: Path
    target: Path
    output: Path
    request: Path | None


class AccountProjection(BaseModel):
    """Read only fields needed to prove retained account controls and postings."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    ledger: LedgerProjection
    phase: Literal["running", "stopped", "faulted"]
    active_control_identity: str | None = None
    fault: str | None = None


class CurrencyProjection(BaseModel):
    """Retain the configured exact currency for an authored local transfer."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    code: str
    minor_unit: str


class PostingProjection(BaseModel):
    """Identify a durable posting without reinterpreting account economics."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    identity: str


class LedgerProjection(BaseModel):
    """Project one account's currencies and durable source posting identities."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    account_id: str
    currencies: tuple[CurrencyProjection, ...]
    postings: tuple[PostingProjection, ...]


class ControlRequestProjection(BaseModel):
    """Identify the original durable account stop request."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    identity: str
    account_id: str
    kind: str


class ControlProjection(BaseModel):
    """Require an applied stop to remain in the account result history."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    request: ControlRequestProjection
    status: Literal["applied", "rejected"]
    phase: Literal["running", "stopped", "faulted"]


class AccountResultProjection(BaseModel):
    """Read the installed CLI's bounded non-submitting account result."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    accounts: tuple[AccountProjection, ...]
    controls: tuple[ControlProjection, ...]
    control: ControlProjection | None = None
    journal_path: str | None = None
    submission_attempted: Literal[False]


class OpeningAccountProjection(BaseModel):
    """Select the sole paper account declared in one signed configuration."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    account_id: str


class ConfigurationProjection(BaseModel):
    """Check the signed account scope before any installed state is created."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    schema_version: Literal["account-runtime-v1"]
    mode: Literal["paper", "shadow"]
    opening_at: datetime
    accounts: tuple[OpeningAccountProjection, ...]


class LatePostingProjection(BaseModel):
    """Validate a caller-authored local posting selected for durable preservation."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    identity: str
    account_id: str
    known_at: datetime


class LateRequestProjection(BaseModel):
    """Restrict optional input to one identified normalized account posting."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    action: Literal["post"]
    posting: LatePostingProjection


class InstalledPackages(ImmutableModel):
    """Retain the actual isolated execution wheel closure and module boundary."""

    contracts_version: str
    execution_version: str
    distributions: dict[str, str]
    present_required_modules: tuple[str, ...]
    present_forbidden_modules: tuple[str, ...]


class PhaseEvidence(ImmutableModel):
    """Bind one selected release to exact durable account and installed packages."""

    release: Digest
    slot: str
    configuration_sha256: Digest
    journal_configuration_sha256: Digest
    state_payload_sha256: Digest
    account_id: str
    phase: Literal["running", "stopped", "faulted"]
    fault: str | None
    active_control_identity: str | None
    posting_ids: tuple[str, ...]
    packages: InstalledPackages


class AccountInstallationResult(ImmutableModel):
    """Retain actual signed and mutable-state evidence without private keys."""

    schema_version: Literal["account-installation-acceptance-v1"] = (
        "account-installation-acceptance-v1"
    )
    checked_at: datetime
    stop_request_path: str
    stop_request_sha256: Digest
    late_request_path: str
    late_request_sha256: Digest
    late_posting_identity: str
    initial: PhaseEvidence
    upgrade: PhaseEvidence
    rollback: PhaseEvidence
    configuration_override_rejected: Literal[True] = True
    submission_attempted: Literal[False] = False


class InstalledEnvironmentProbe:
    """Check the selected slot's actual isolated Python against signed closure facts."""

    program = """
import json
import sys
from importlib.metadata import distributions, version
from importlib.util import find_spec

required, forbidden = json.loads(sys.argv[1])
installed = {
    item.metadata["Name"].lower().replace("_", "-"): item.version
    for item in distributions()
}
print(json.dumps({
    "contracts_version": version("alpha-research-contracts"),
    "execution_version": version("alpha-research-execution"),
    "distributions": installed,
    "present_required_modules": [name for name in required if find_spec(name) is not None],
    "present_forbidden_modules": [name for name in forbidden if find_spec(name) is not None],
}, sort_keys=True))
"""

    @classmethod
    def inspect(
        cls, target: Path, receipt: InstallationReceipt, facts: SelectedClosureFacts
    ) -> InstalledPackages:
        """Require only admitted wheel bytes and the lean account runtime surface."""
        interpreter = target / receipt.slot / "venv/bin/python"
        completed = subprocess.run(  # nosec B603  # [owner=platform; rationale=verified venv Python with isolated metadata-only script; expires=2027-03-01]
            [
                str(interpreter),
                "-I",
                "-B",
                "-c",
                cls.program,
                json.dumps((_REQUIRED_MODULES, _FORBIDDEN_MODULES)),
            ],
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
                "isolated account package inspection failed: "
                + completed.stderr.decode(errors="replace")[-2000:]
            )
        observed = InstalledPackages.model_validate_json(completed.stdout)
        expected = {wheel.name: wheel.version for wheel in facts.wheels}
        if observed.distributions != expected:
            raise ValueError("installed account distributions differ from signed wheel closure")
        if observed.present_required_modules != _REQUIRED_MODULES:
            raise ValueError("installed account closure lacks its accounting or runtime module")
        if observed.present_forbidden_modules:
            raise ValueError("installed account closure exposes research or reporting modules")
        if (
            observed.contracts_version != expected.get("alpha-research-contracts")
            or observed.execution_version != facts.root_version
            or facts.root_name != "alpha-research-execution"
        ):
            raise ValueError("installed account package versions differ from signed facts")
        return observed


class AccountInstallationAcceptance:
    """Exercise one local account through actual signed install and installed commands."""

    def __init__(self, arguments: AcceptanceArguments) -> None:
        """Bind explicit immutable releases and an absent destination."""
        self.policy_path = arguments.policy.absolute()
        self.initial_path = arguments.initial.absolute()
        self.upgrade_path = arguments.upgrade.absolute()
        self.target = arguments.target.absolute()
        self.output = arguments.output.absolute()
        self.request = None if arguments.request is None else arguments.request.absolute()

    def run(self) -> AccountInstallationResult:
        """Retain the same account ledger and stop across upgrade and rollback."""
        if self.target.exists() or self.target.is_symlink():
            raise ValueError("account acceptance target must be absent")
        if self.output.exists() or self.output.is_symlink():
            raise ValueError("account acceptance output must be absent")
        now = datetime.now(UTC)
        policy = InstallationPolicy.model_validate_json(
            ReleaseRegistry.read_regular(self.policy_path, 1_048_576)
        )
        initial = ReleaseRegistry.verify(self.initial_path, policy, now=now)
        upgrade = ReleaseRegistry.verify(self.upgrade_path, policy, now=now)
        if initial.identity == upgrade.identity:
            raise ValueError("account upgrade requires a distinct signed release")
        self._require_account_runtimes(initial.manifest.runtime, upgrade.manifest.runtime)
        configuration_bytes = initial.content("configuration/config.json")
        if configuration_bytes != upgrade.content("configuration/config.json"):
            raise ValueError("account upgrade must preserve exact signed configuration bytes")
        configuration = ConfigurationProjection.model_validate_json(configuration_bytes)
        if (
            configuration.mode != initial.manifest.runtime.mode
            or configuration.opening_at.tzinfo != UTC
            or len(configuration.accounts) != 1
        ):
            raise ValueError("account acceptance requires one signed paper/shadow account")
        initial_state = StateEnvelope.model_validate_json(initial.content("state/state.json"))
        upgrade_state = StateEnvelope.model_validate_json(upgrade.content("state/state.json"))
        if initial_state.files or upgrade_state.files:
            raise ValueError("account acceptance requires empty signed initial state")
        first_facts = ReleaseProvenance.verify(initial, now=now)
        second_facts = ReleaseProvenance.verify(upgrade, now=now)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        stop_path, late_path = self._request_paths()
        if any(path.exists() or path.is_symlink() for path in (stop_path, late_path)):
            raise ValueError("account acceptance request evidence already exists")

        installation = LocalInstallation(self.target, policy)
        account_id = configuration.accounts[0].account_id
        supplied_late_bytes: bytes | None = None
        if self.request is not None:
            supplied_late_bytes = ReleaseRegistry.read_regular(self.request, 1_048_576)
            supplied_late = LateRequestProjection.model_validate_json(supplied_late_bytes)
            if supplied_late.posting.account_id != account_id:
                raise ValueError("late posting belongs to another signed account")
            if supplied_late.posting.known_at.tzinfo != UTC:
                raise ValueError("late posting knowledge time must be UTC")
            stop_at = configuration.opening_at + timedelta(seconds=1)
            if supplied_late.posting.known_at <= stop_at:
                raise ValueError("caller posting must be known after the account stop")
        else:
            stop_at = max(now, configuration.opening_at) + timedelta(seconds=1)
        config_sha256 = hashlib.sha256(configuration_bytes).hexdigest()
        first = installation.install(self.initial_path, now=now)
        opened = self._read_account(installation, account_id, now=now)
        if opened.accounts[0].phase != "running" or opened.controls:
            raise ValueError("new account did not open without prior controls")
        first_packages = InstalledEnvironmentProbe.inspect(self.target, first, first_facts)
        opening = self._phase(first, opened, first_packages, config_sha256)

        stop_bytes = self._encode_request(
            {
                "action": "control",
                "control": {
                    "identity": "signed-account-installation-stop",
                    "account_id": account_id,
                    "kind": "stop",
                    "at": stop_at.isoformat().replace("+00:00", "Z"),
                    "reason": "signed account installation acceptance",
                },
            }
        )
        stop_path.write_bytes(stop_bytes)
        stopped = self._apply(installation, stop_path, account_id, now=now)
        stop_identity = "signed-account-installation-stop"
        if (
            stopped.control is None
            or stopped.control.status != "applied"
            or stopped.control.request.identity != stop_identity
            or stopped.accounts[0].phase != "stopped"
            or stopped.accounts[0].active_control_identity != stop_identity
        ):
            raise ValueError("installed account stop did not persist")
        stopped_digest = self._state_digests()[1]

        late_bytes = self._late_request(
            account_id,
            opened.accounts[0].ledger.currencies,
            stop_at + timedelta(microseconds=1),
            supplied_late_bytes,
        )
        late_path.write_bytes(late_bytes)
        late_request = LateRequestProjection.model_validate_json(late_bytes)
        if late_request.posting.identity in {
            posting.identity for posting in stopped.accounts[0].ledger.postings
        }:
            raise ValueError("late posting identity already belongs to opening account state")
        late = self._apply(installation, late_path, account_id, now=now)
        self._require_retained(late, stop_identity, late_request.posting.identity)
        if late.accounts[0].fault is None:
            raise ValueError("late posting did not retain its reconciliation requirement")
        journal_config_digest, retained_digest = self._state_digests()
        if retained_digest == stopped_digest:
            raise ValueError("late posting did not change the durable account payload")
        if journal_config_digest != opening.journal_configuration_sha256:
            raise ValueError("account posting changed the installed journal configuration")

        second = installation.install(self.upgrade_path, now=now)
        if second.previous_release != first.release or second.slot == first.slot:
            raise ValueError("account upgrade did not select a distinct signed slot")
        upgraded = self._read_account(installation, account_id, now=now)
        self._require_retained(upgraded, stop_identity, late_request.posting.identity)
        second_packages = InstalledEnvironmentProbe.inspect(self.target, second, second_facts)
        upgrade_evidence = self._phase(
            second, upgraded, second_packages, config_sha256, opening.journal_configuration_sha256
        )
        if upgrade_evidence.state_payload_sha256 != retained_digest:
            raise ValueError("account upgrade changed latest mutable state")
        self._reject_configuration_override(installation, now=now)

        rolled_back = installation.install(self.initial_path, now=now)
        if (
            rolled_back.release != first.release
            or rolled_back.previous_release != second.release
            or rolled_back.slot in {first.slot, second.slot}
        ):
            raise ValueError("account rollback did not select the prior signed release")
        restored = self._read_account(installation, account_id, now=now)
        self._require_retained(restored, stop_identity, late_request.posting.identity)
        restored_packages = InstalledEnvironmentProbe.inspect(self.target, rolled_back, first_facts)
        rollback_evidence = self._phase(
            rolled_back,
            restored,
            restored_packages,
            config_sha256,
            opening.journal_configuration_sha256,
        )
        if rollback_evidence.state_payload_sha256 != retained_digest:
            raise ValueError("account rollback rewound or altered latest mutable state")

        result = AccountInstallationResult(
            checked_at=now,
            stop_request_path=str(stop_path),
            stop_request_sha256=hashlib.sha256(stop_bytes).hexdigest(),
            late_request_path=str(late_path),
            late_request_sha256=hashlib.sha256(late_bytes).hexdigest(),
            late_posting_identity=late_request.posting.identity,
            initial=opening,
            upgrade=upgrade_evidence,
            rollback=rollback_evidence,
        )
        self.output.write_bytes(result.model_dump_json(indent=2).encode() + b"\n")
        return result

    @staticmethod
    def _require_account_runtimes(first: ReleaseRuntime, second: ReleaseRuntime) -> None:
        """Keep the acceptance on one signed non-executable account contract."""
        if (
            first.application != "execution"
            or second.application != "execution"
            or first.mode != second.mode
            or first.mode not in ("paper", "shadow")
            or first.config_schema != second.config_schema
            or first.config_schema != "account-runtime-v1"
            or first.state_schema != second.state_schema
            or first.state_schema != "account-journal-v2"
        ):
            raise ValueError("account acceptance requires compatible signed paper releases")

    def _request_paths(self) -> tuple[Path, Path]:
        """Choose absent named sidecars that retain the exact installed request bytes."""
        return (
            self.output.with_name(self.output.stem + ".stop-request.json"),
            self.output.with_name(self.output.stem + ".late-request.json"),
        )

    @staticmethod
    def _encode_request(request: dict[str, object]) -> bytes:
        """Use canonical local JSON bytes for the installed account command."""
        return (json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n").encode()

    @staticmethod
    def _late_request(
        account_id: str,
        currencies: tuple[CurrencyProjection, ...],
        at: datetime,
        supplied: bytes | None,
    ) -> bytes:
        """Use a supplied posting or an identified one-unit local funding fact."""
        if supplied is not None:
            return supplied
        if not currencies:
            raise ValueError("signed account has no declared funding currency")
        currency = currencies[0]
        instant = at.isoformat().replace("+00:00", "Z")
        return AccountInstallationAcceptance._encode_request(
            {
                "action": "post",
                "posting": {
                    "identity": "signed-account-installation-late-transfer",
                    "account_id": account_id,
                    "event_at": instant,
                    "known_at": instant,
                    "kind": "transfer",
                    "cash": {
                        "value": "1",
                        "currency": {"code": currency.code, "minor_unit": currency.minor_unit},
                    },
                },
            }
        )

    def _read_account(
        self, installation: LocalInstallation, account_id: str, *, now: datetime
    ) -> AccountResultProjection:
        """Inspect the signed account path and assert its fixed state location."""
        result = AccountResultProjection.model_validate_json(
            installation.run(("account",), now=now)
        )
        if (
            len(result.accounts) != 1
            or result.accounts[0].ledger.account_id != account_id
            or result.journal_path != str(self.target / "state/accounts.sqlite3")
        ):
            raise ValueError("installed account inspection differs from signed account scope")
        return result

    def _apply(
        self, installation: LocalInstallation, request: Path, account_id: str, *, now: datetime
    ) -> AccountResultProjection:
        """Send exact retained request bytes through the signed runner."""
        result = AccountResultProjection.model_validate_json(
            installation.run(("account", "--request", str(request)), now=now)
        )
        if (
            len(result.accounts) != 1
            or result.accounts[0].ledger.account_id != account_id
            or result.journal_path != str(self.target / "state/accounts.sqlite3")
        ):
            raise ValueError("installed account request changed the selected account scope")
        return result

    @staticmethod
    def _require_retained(
        result: AccountResultProjection, stop_identity: str, posting_identity: str
    ) -> None:
        """Require late accounting without clearing the independent account stop."""
        account = result.accounts[0]
        if (
            account.phase != "stopped"
            or account.active_control_identity != stop_identity
            or posting_identity not in {posting.identity for posting in account.ledger.postings}
            or not any(
                control.request.identity == stop_identity
                and control.request.kind == "stop"
                and control.status == "applied"
                for control in result.controls
            )
        ):
            raise ValueError("late account fact or durable protective stop was lost")

    def _state_digests(self) -> tuple[str, str]:
        """Hash the canonical firm configuration and complete account payload."""
        journal = self.target / "state/accounts.sqlite3"
        with closing(sqlite3.connect(journal.as_uri() + "?mode=ro", uri=True)) as connection:
            integrity = cast(
                tuple[object, ...] | None, connection.execute("PRAGMA quick_check").fetchone()
            )
            row = cast(
                tuple[object, ...] | None,
                connection.execute("SELECT configuration, payload FROM firm WHERE id=1").fetchone(),
            )
        if (
            integrity != ("ok",)
            or row is None
            or type(row[0]) is not bytes
            or type(row[1]) is not bytes
        ):
            raise ValueError("installed account journal is missing or malformed")
        return hashlib.sha256(row[0]).hexdigest(), hashlib.sha256(row[1]).hexdigest()

    def _phase(
        self,
        receipt: InstallationReceipt,
        result: AccountResultProjection,
        packages: InstalledPackages,
        configuration_sha256: str,
        expected_journal_configuration_sha256: str | None = None,
    ) -> PhaseEvidence:
        """Record one selected immutable slot and the latest exact account payload."""
        account = result.accounts[0]
        journal_config_digest, state_digest = self._state_digests()
        if (
            expected_journal_configuration_sha256 is not None
            and journal_config_digest != expected_journal_configuration_sha256
        ):
            raise ValueError("release switch changed the journal's bound account configuration")
        return PhaseEvidence(
            release=receipt.release,
            slot=str(self.target / receipt.slot),
            configuration_sha256=configuration_sha256,
            journal_configuration_sha256=journal_config_digest,
            state_payload_sha256=state_digest,
            account_id=account.ledger.account_id,
            phase=account.phase,
            fault=account.fault,
            active_control_identity=account.active_control_identity,
            posting_ids=tuple(posting.identity for posting in account.ledger.postings),
            packages=packages,
        )

    @staticmethod
    def _reject_configuration_override(installation: LocalInstallation, *, now: datetime) -> None:
        """Prove the signed runner will not accept a caller's config or journal path."""
        for option in ("--config", "--journal", "--conf=other", "--journ=other"):
            try:
                installation.run(("account", option, "/private/tmp/other"), now=now)
            except ValueError:
                continue
            raise ValueError("installed account path accepted a configuration or journal override")


def main(arguments: Sequence[str] | None = None) -> int:
    """Parse exact signed local inputs and retain installed account evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("policy", "initial", "upgrade", "target", "output"):
        parser.add_argument("--" + option, required=True, type=Path)
    parser.add_argument("--request", type=Path)
    parsed = parser.parse_args(arguments, namespace=AcceptanceArguments())
    result = AccountInstallationAcceptance(parsed).run()
    print(f"Signed account installation accepted: {result.rollback.release}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
