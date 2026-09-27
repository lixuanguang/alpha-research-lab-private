"""Exercise local release switching, state preservation and installation fences."""

from __future__ import annotations

# standard library imports
import base64
import hashlib
import json
import platform
import sqlite3
import sys
import sysconfig
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event
from typing import Literal, cast
from unittest.mock import patch

# third party library imports
import pytest
from pydantic import TypeAdapter

# project library imports
from alpha_research_governance.artifact_supply_chain.bundles import ReleaseRegistry, VerifiedRelease
from alpha_research_governance.artifact_supply_chain.installation import (
    InstallationReceipt,
    LocalInstallation,
)
from alpha_research_governance.artifact_supply_chain.provenance import ReleaseProvenance
from alpha_research_governance.artifact_supply_chain.records import (
    InstallationPolicy,
    ReleaseFile,
    ReleaseManifest,
    ReleaseRuntime,
    StateEnvelope,
    TrustedBuilder,
)
from applications.execute.accounts import (
    AccountExecutionApplication,
    AccountExecutionRequest,
    AccountExecutionResult,
)
from configuration import AccountConfiguration, OpeningAccount, PaperExecutionScenario
from configuration.paper_activation import PaperDeployment, PaperStrategyIdentity
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec

_NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


class InstallationScenario:
    """Supply validated release values while isolating wheel installation I/O."""

    def __init__(self, root: Path) -> None:
        """Bind a private target and two lookup tables for candidate releases."""
        self.root = root
        public_wire = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes(range(32))
        public_key = "ssh-ed25519 " + base64.b64encode(public_wire).decode("ascii")
        builder = TrustedBuilder(
            identity="installation-builder",
            public_key=public_key,
            origins=("local-builder",),
            roots=("alpha-research-collector", "alpha-research-execution"),
            valid_from=_NOW - timedelta(days=1),
            valid_until=_NOW + timedelta(days=2),
        )
        self.policy = InstallationPolicy(
            target="darwin_arm64",
            python_executable="/pinned/python",
            python_sha256="0" * 64,
            uv_executable="/pinned/uv",
            uv_sha256="0" * 64,
            ssh_keygen_executable="/pinned/ssh-keygen",
            ssh_keygen_sha256="0" * 64,
            builders=(builder,),
            config_schemas=("config-v1", "account-runtime-v1"),
            state_schemas=("state-v1", "state-v2", "account-journal-v2", "account-journal-v3"),
        )
        self.installation = LocalInstallation(root / "target", self.policy)
        self.candidates: dict[str, VerifiedRelease] = {}
        self.identities: dict[str, VerifiedRelease] = {}

    def candidate(
        self,
        name: str,
        *,
        config: bytes,
        state_schema: str = "state-v1",
        application: Literal["collector", "execution"] = "collector",
        config_schema: str = "config-v1",
        mode: Literal["collection", "research", "paper", "shadow"] | None = None,
        initial_state: bool = True,
    ) -> Path:
        """Create a complete inert release and register its mocked verified identity."""
        initial = b"initial state\n"
        initial_files = (ReleaseFile.describe("checkpoint.bin", initial),) if initial_state else ()
        envelope = StateEnvelope(
            schema_version=state_schema,
            application=application,
            files=initial_files,
        )
        payloads = {
            "configuration/config.json": config,
            "provenance/audit.json": b"{}\n",
            "provenance/closure.json": b"{}\n",
            "provenance/dependency-admission.toml": b"admitted = true\n",
            "provenance/source.json": b"{}\n",
            "provenance/uv.lock": b"version = 1\n",
            "state/state.json": envelope.model_dump_json().encode(),
            "wheels/collector.whl": b"inert wheel fixture\n",
        }
        if initial_state:
            payloads["state/checkpoint.bin"] = initial
        contents = tuple(sorted(payloads.items()))
        manifest = ReleaseManifest(
            name=name,
            builder="installation-builder",
            origin="local-builder",
            created_at=_NOW - timedelta(hours=1),
            valid_until=_NOW + timedelta(days=1),
            source_commit="a" * 40,
            source_dirty=False,
            build_commands=(("uv", "build", "--offline"),),
            runtime=ReleaseRuntime(
                python_version="3.14.7",
                platform="darwin_arm64",
                contract_version="1",
                application=application,
                mode=mode or ("collection" if application == "collector" else "research"),
                config_schema=config_schema,
                state_schema=state_schema,
            ),
            root_distribution=(
                "alpha-research-collector"
                if application == "collector"
                else "alpha-research-execution"
            ),
            files=tuple(ReleaseFile.describe(path, content) for path, content in contents),
        )
        release = VerifiedRelease(manifest, manifest.encoded(), b"mocked signature", contents)
        directory = self.root / name
        directory.mkdir()
        self.candidates[directory.name] = release
        self.identities[release.identity] = release
        return directory

    def verify(
        self,
        directory: Path,
        policy: InstallationPolicy,
        *,
        now: datetime,
        expected_identity: str | None = None,
    ) -> VerifiedRelease:
        """Select only the fixture release requested by installation or retained run."""
        assert policy == self.policy
        assert now == _NOW
        if expected_identity is None:
            return self.candidates[directory.name]
        return self.identities[expected_identity]

    @contextmanager
    def isolated_installation(self, *, inspect_application: bool = False) -> Iterator[None]:
        """Keep tests on local pointer and state logic without creating a real venv."""
        with (
            patch.object(ReleaseRegistry, "verify", side_effect=self.verify),
            patch.object(ReleaseProvenance, "verify", return_value=None),
            patch.object(LocalInstallation, "_require_tools", return_value=None),
            patch.object(LocalInstallation, "_install_wheels", return_value=None),
        ):
            if inspect_application:
                yield
            else:
                with patch.object(LocalInstallation, "_inspect_application", return_value=None):
                    yield


class PointerInterruption:
    """Interrupt only the final active-pointer publication after state exists."""

    def __init__(self, write: Callable[[Path, bytes], None]) -> None:
        """Retain the original atomic writer for staged receipt publication."""
        self.write = write

    def interrupt(self, path: Path, content: bytes) -> None:
        """Publish the retained receipt but fail before selecting the installation."""
        if path.name == "current.json":
            raise OSError("simulated pointer interruption")
        self.write(path, content)


class BlockingApplication:
    """Hold the installation fence while a simulated installed command runs."""

    def __init__(self) -> None:
        """Create bounded coordination events for a concurrently attempted switch."""
        self.started = Event()
        self.release = Event()

    def run(self, arguments: list[str], *, cwd: Path) -> bytes:
        """Keep a run active until the test attempts a competing installation."""
        assert arguments[-1] == "replay"
        assert cwd.is_dir()
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("simulated workload was not released")
        return b"completed\n"


class RecordedApplication:
    """Capture the exact installed argv after release and state verification."""

    def __init__(self) -> None:
        """Start with no installed invocations."""
        self.calls: list[tuple[list[str], Path]] = []

    def run(self, arguments: list[str], *, cwd: Path) -> bytes:
        """Record one invocation without executing a stub wheel entrypoint."""
        self.calls.append((arguments, cwd))
        return b"accepted\n"


class AccountInstalledApplication:
    """Exercise actual account decoding behind the mock signed wheel installation."""

    def __init__(self) -> None:
        """Retain installed invocations for argument-binding assertions."""
        self.calls: list[list[str]] = []

    def run(self, arguments: list[str], *, cwd: Path) -> bytes:
        """Apply only the account CLI shape using the real account application."""
        assert cwd.is_dir()
        assert arguments[0].endswith("/venv/bin/alpha-execute")
        assert arguments[1] == "account"
        self.calls.append(arguments)
        config = Path(arguments[arguments.index("--config") + 1])
        journal = Path(arguments[arguments.index("--journal") + 1])
        request = (
            Path(arguments[arguments.index("--request") + 1]) if "--request" in arguments else None
        )
        release_identity = (
            arguments[arguments.index("--release-identity") + 1]
            if "--release-identity" in arguments
            else None
        )
        return DomainCodec().encode_json(
            AccountExecutionApplication().run(
                config_path=config,
                journal_path=journal,
                request_path=request,
                release_identity=release_identity,
            )
        )


class PinnedToolProbe:
    """Supply digest-pinned local tool files with controlled subprocess reports."""

    def __init__(self, root: Path) -> None:
        """Create only inert regular files; tests replace every tool invocation."""
        host_target = f"{sys.platform}_{platform.machine()}"
        host_version = (
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        )
        if (
            host_target not in {"darwin_arm64", "linux_x86_64"}
            or host_version != (3, 14, 7)
            or cast(object, sysconfig.get_config_var("Py_GIL_DISABLED")) not in {None, 0}
        ):
            pytest.skip("selected-tool tests require the supported standard CPython host")
        target: Literal["darwin_arm64", "linux_x86_64"] = (
            "darwin_arm64" if host_target == "darwin_arm64" else "linux_x86_64"
        )
        scenario = InstallationScenario(root)
        tools = root / "pinned-tools"
        tools.mkdir()
        self.python = tools / "python"
        self.uv = tools / "uv"
        self.ssh_keygen = tools / "ssh-keygen"
        self.python.write_bytes(b"pinned Python fixture")
        self.uv.write_bytes(b"pinned uv fixture")
        self.ssh_keygen.write_bytes(b"pinned OpenSSH fixture")
        original = scenario.policy
        policy = InstallationPolicy(
            target=target,
            python_executable=str(self.python),
            python_sha256=hashlib.sha256(self.python.read_bytes()).hexdigest(),
            uv_executable=str(self.uv),
            uv_sha256=hashlib.sha256(self.uv.read_bytes()).hexdigest(),
            ssh_keygen_executable=str(self.ssh_keygen),
            ssh_keygen_sha256=hashlib.sha256(self.ssh_keygen.read_bytes()).hexdigest(),
            builders=original.builders,
            config_schemas=original.config_schemas,
            state_schemas=original.state_schemas,
        )
        self.installation = LocalInstallation(root / "target", policy)
        self.runtime = ReleaseRuntime(
            python_version="3.14.7",
            platform=target,
            contract_version="1",
            application="collector",
            mode="collection",
            config_schema="config-v1",
            state_schema="state-v1",
        )
        self.python_facts: tuple[str, ...] = (
            "cpython",
            "3.14.7",
            sys.platform,
            platform.machine(),
            "0",
        )
        self.uv_report = b"uv 0.12.7 (fixture build)\n"
        self.calls: list[tuple[list[str], Path]] = []

    def respond(self, arguments: list[str], *, cwd: Path) -> bytes:
        """Return selected interpreter or uv facts without executing fixture files."""
        self.calls.append((arguments, cwd))
        if arguments[0] == str(self.python):
            return ("\n".join(self.python_facts) + "\n").encode()
        if arguments[0] == str(self.uv):
            return self.uv_report
        raise AssertionError("unexpected selected installation tool")


class TestLocalInstallation:
    """Retain atomic selection, compatible state and complete local integrity."""

    @staticmethod
    def _account_configuration(opening_at: datetime) -> AccountConfiguration:
        """Provide one bounded account whose opening still requires reconciliation."""
        currency = Currency.from_code("USDT")
        dimension = Dimension(
            instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
            kind=QuantityKind.BASE_UNIT,
        )
        money = Money(value=Decimal("10000"), currency=currency)
        return AccountConfiguration(
            mode="paper",
            opening_at=opening_at,
            accounts=(OpeningAccount(account_id="shared", cash=(money,)),),
            instruments=(
                SpotLimits(
                    maximum=Quantity(value=Decimal("100"), dimension=dimension),
                    lot=Quantity(value=Decimal("1"), dimension=dimension),
                    tick=Price(value=Decimal("0.01"), currency=currency, per=dimension),
                    product="spot",
                ),
            ),
            budgets=BudgetPolicy(
                valuation_currency=currency,
                firm_maximum=money,
                accounts=(AccountLimit(account_id="shared", maximum=money),),
                instances=(
                    InstanceLimit(
                        instance_id="alpha",
                        account_id="shared",
                        maximum=money,
                        instruments=(dimension.instrument_id,),
                    ),
                ),
                max_quote_age_us=1_000_000,
                max_state_age_us=86_400_000_000,
                max_price_deviation_bps=100,
                max_order_notional=money,
            ),
        )

    def test_signed_account_run_preserves_latest_journal_on_rollback(self, tmp_path: Path) -> None:
        """Bind account requests to signed config and retain operator stops across rollback."""
        scenario = InstallationScenario(tmp_path)
        config = DomainCodec().encode_json(self._account_configuration(_NOW))
        first = scenario.candidate(
            "first-account",
            config=config,
            application="execution",
            mode="paper",
            config_schema="account-runtime-v1",
            state_schema="account-journal-v2",
            initial_state=False,
        )
        second = scenario.candidate(
            "second-account",
            config=config,
            application="execution",
            mode="paper",
            config_schema="account-runtime-v1",
            state_schema="account-journal-v2",
            initial_state=False,
        )
        changed = scenario.candidate(
            "changed-account",
            config=DomainCodec().encode_json(
                self._account_configuration(_NOW + timedelta(seconds=1))
            ),
            application="execution",
            mode="paper",
            config_schema="account-runtime-v1",
            state_schema="account-journal-v2",
            initial_state=False,
        )
        application = AccountInstalledApplication()
        request = tmp_path / "operator-stop.json"
        request.write_bytes(
            DomainCodec().encode_json(
                AccountExecutionRequest(action="block", account_id="shared", reason="operator-stop")
            )
        )
        with scenario.isolated_installation(inspect_application=True):
            with patch.object(LocalInstallation, "_run", side_effect=application.run):
                original = scenario.installation.install(first, now=_NOW)
                journal = scenario.installation.root / "state/accounts.sqlite3"
                assert journal.is_file()
                stopped = DomainCodec().decode_json(
                    scenario.installation.run(("account", "--request", str(request)), now=_NOW),
                    AccountExecutionResult,
                )
                assert stopped.accounts[0].operator_block == "operator-stop"
                updated = scenario.installation.install(second, now=_NOW)
                with pytest.raises(ValueError, match="configuration or state schema differs"):
                    scenario.installation.install(changed, now=_NOW)
                assert scenario.installation.current() == updated
                rolled_back = scenario.installation.install(first, now=_NOW)
                reopened = DomainCodec().decode_json(
                    scenario.installation.run(("account",), now=_NOW),
                    AccountExecutionResult,
                )

        assert rolled_back.release == original.release
        assert reopened.accounts[0].operator_block == "operator-stop"
        assert application.calls[-1][-2:] == ["--journal", str(journal)]
        assert application.calls[-1][-4:-2] == [
            "--config",
            str(scenario.installation.root / rolled_back.slot / "bundle/configuration/config.json"),
        ]

    def test_signed_account_run_rejects_overrides_and_lost_journal(self, tmp_path: Path) -> None:
        """Do not let a request supply another config or silently recreate lost state."""
        scenario = InstallationScenario(tmp_path)
        release = scenario.candidate(
            "account",
            config=DomainCodec().encode_json(self._account_configuration(_NOW)),
            application="execution",
            mode="paper",
            config_schema="account-runtime-v1",
            state_schema="account-journal-v2",
            initial_state=False,
        )
        application = AccountInstalledApplication()
        with scenario.isolated_installation(inspect_application=True):
            with patch.object(LocalInstallation, "_run", side_effect=application.run):
                scenario.installation.install(release, now=_NOW)
                prior_calls = len(application.calls)
                for arguments in (
                    ("account", "--config", str(tmp_path / "other.json")),
                    ("account", "--journal", str(tmp_path / "other.sqlite3")),
                    ("account", "--journ", str(tmp_path / "other.sqlite3")),
                    ("account", "--request", "relative.json"),
                    ("paper",),
                ):
                    with pytest.raises(ValueError):
                        scenario.installation.run(arguments, now=_NOW)
                assert len(application.calls) == prior_calls
                journal = scenario.installation.root / "state/accounts.sqlite3"
                journal.unlink()
                with pytest.raises(FileNotFoundError):
                    scenario.installation.run(("account",), now=_NOW)
                assert not journal.exists()

    def test_signed_v3_account_binds_release_identity_and_refuses_v2_code(
        self, tmp_path: Path
    ) -> None:
        """Carry the verified installed digest into v3 without reopening older readers."""
        scenario = InstallationScenario(tmp_path)
        config = DomainCodec().encode_json(self._account_configuration(_NOW))
        current = scenario.candidate(
            "paper-activation-account",
            config=config,
            application="execution",
            mode="paper",
            config_schema="account-runtime-v1",
            state_schema="account-journal-v3",
            initial_state=False,
        )
        legacy = scenario.candidate(
            "legacy-account",
            config=config,
            application="execution",
            mode="paper",
            config_schema="account-runtime-v1",
            state_schema="account-journal-v2",
            initial_state=False,
        )
        compatible = scenario.candidate(
            "compatible-account",
            config=config,
            application="execution",
            mode="paper",
            config_schema="account-runtime-v1",
            state_schema="account-journal-v3",
            initial_state=False,
        )
        unlisted = scenario.candidate(
            "unlisted-account",
            config=config,
            application="execution",
            mode="paper",
            config_schema="account-runtime-v1",
            state_schema="account-journal-v3",
            initial_state=False,
        )
        application = AccountInstalledApplication()
        with scenario.isolated_installation(inspect_application=True):
            with patch.object(LocalInstallation, "_run", side_effect=application.run):
                receipt = scenario.installation.install(current, now=_NOW)
                scenario.installation.run(("account",), now=_NOW)
                assert application.calls[-1][-2:] == ["--release-identity", receipt.release]
                with closing(
                    sqlite3.connect(scenario.installation.root / "state/accounts.sqlite3")
                ) as connection:
                    state = cast(
                        tuple[object, ...] | None,
                        connection.execute("SELECT payload FROM firm WHERE id=1").fetchone(),
                    )
                assert state is not None and type(state[0]) is bytes
                signed_config = self._account_configuration(_NOW)
                limit = signed_config.instruments[0]
                deployment = PaperDeployment(
                    account_id="shared",
                    configuration_sha256=hashlib.sha256(config).hexdigest(),
                    releases=(receipt.release, scenario.candidates[compatible.name].identity),
                    strategies=(
                        PaperStrategyIdentity(
                            instance_id="alpha",
                            policy_identity="test-policy",
                            candidate_identity="test-candidate",
                            model_identity="no-model",
                            feature_identity="test-feature",
                        ),
                    ),
                    input_identity="test-input",
                    scenario=PaperExecutionScenario(
                        venue="okx",
                        instrument_id=limit.maximum.dimension.instrument_id,
                        entry_delay_us=0,
                        cancel_delay_us=0,
                        adverse=Price(
                            value=Decimal("0"),
                            currency=limit.tick.currency,
                            per=limit.maximum.dimension,
                        ),
                        fee_rate=Decimal("0"),
                        take_fraction=Decimal("1"),
                        gas_inapplicable_reason="off-chain spot simulation",
                    ),
                    state_identity="paper-account-state-v1",
                )
                request = tmp_path / "paper-deployment.json"
                request.write_bytes(
                    DomainCodec().encode_json(
                        AccountExecutionRequest(action="install_paper", deployment=deployment)
                    )
                )
                activated = DomainCodec().decode_json(
                    scenario.installation.run(("account", "--request", str(request)), now=_NOW),
                    AccountExecutionResult,
                )
                assert activated.paper_activations[0].deployment == deployment
                with closing(
                    sqlite3.connect(scenario.installation.root / "state/accounts.sqlite3")
                ) as connection:
                    promoted = cast(
                        tuple[object, ...] | None,
                        connection.execute("SELECT payload FROM firm WHERE id=1").fetchone(),
                    )
                assert promoted is not None and type(promoted[0]) is bytes
                assert b'"schema_version":"account-journal-v3"' in promoted[0]
                with pytest.raises(ValueError, match="absolute request path"):
                    scenario.installation.run(
                        ("account", "--release-identity", legacy.name), now=_NOW
                    )
                with pytest.raises(ValueError, match="excludes the candidate release"):
                    scenario.installation.install(unlisted, now=_NOW)
                with pytest.raises(ValueError, match="current state is incompatible"):
                    scenario.installation.install(legacy, now=_NOW)
                assert scenario.installation.current() == receipt
                upgraded = scenario.installation.install(compatible, now=_NOW)
                assert upgraded.release == scenario.candidates[compatible.name].identity
                assert scenario.installation.install(current, now=_NOW).release == receipt.release
                assert (
                    LocalInstallation._account_record(
                        scenario.installation.root / "state/accounts.sqlite3"
                    )[1]
                    == promoted[0]
                )

    def test_account_rollback_rejects_unknown_actual_journal_schema(self, tmp_path: Path) -> None:
        """A manifest schema label cannot make an unreadable account ledger compatible."""
        scenario = InstallationScenario(tmp_path)
        config = DomainCodec().encode_json(self._account_configuration(_NOW))
        candidates = tuple(
            scenario.candidate(
                name,
                config=config,
                application="execution",
                mode="paper",
                config_schema="account-runtime-v1",
                state_schema="account-journal-v2",
                initial_state=False,
            )
            for name in ("first-account", "second-account")
        )
        application = AccountInstalledApplication()
        with scenario.isolated_installation(inspect_application=True):
            with patch.object(LocalInstallation, "_run", side_effect=application.run):
                scenario.installation.install(candidates[0], now=_NOW)
                selected = scenario.installation.install(candidates[1], now=_NOW)
                journal = scenario.installation.root / "state/accounts.sqlite3"
                with closing(sqlite3.connect(journal)) as connection:
                    row = cast(
                        tuple[object, ...] | None,
                        connection.execute("SELECT payload FROM firm WHERE id=1").fetchone(),
                    )
                    assert row is not None and type(row[0]) is bytes
                    state = TypeAdapter(dict[str, object]).validate_json(row[0])
                    state["schema_version"] = "unknown-account-journal"
                    connection.execute(
                        "UPDATE firm SET payload=? WHERE id=1",
                        (json.dumps(state, separators=(",", ":")).encode(),),
                    )
                    connection.commit()
                with pytest.raises(ValueError):
                    scenario.installation.install(candidates[0], now=_NOW)
                assert scenario.installation.current() == selected

    @pytest.mark.parametrize("changed", (False, True))
    def test_interrupted_account_install_adopts_only_pristine_initial_state(
        self, tmp_path: Path, changed: bool
    ) -> None:
        """A lost pointer cannot adopt account actions taken against orphan state."""
        scenario = InstallationScenario(tmp_path)
        release = scenario.candidate(
            "account",
            config=DomainCodec().encode_json(self._account_configuration(_NOW)),
            application="execution",
            mode="paper",
            config_schema="account-runtime-v1",
            state_schema="account-journal-v2",
            initial_state=False,
        )
        application = AccountInstalledApplication()
        interruption = PointerInterruption(LocalInstallation._atomic_write)
        with scenario.isolated_installation(inspect_application=True):
            with patch.object(LocalInstallation, "_run", side_effect=application.run):
                with patch.object(
                    LocalInstallation, "_atomic_write", side_effect=interruption.interrupt
                ):
                    with pytest.raises(OSError, match="simulated pointer interruption"):
                        scenario.installation.install(release, now=_NOW)
                journal = scenario.installation.root / "state/accounts.sqlite3"
                original_inode = journal.stat().st_ino
                if changed:
                    request = tmp_path / "orphan-stop.json"
                    request.write_bytes(
                        DomainCodec().encode_json(
                            AccountExecutionRequest(
                                action="block", account_id="shared", reason="orphan-stop"
                            )
                        )
                    )
                    staged = next((scenario.installation.root / "releases").iterdir())
                    AccountExecutionApplication().run(
                        config_path=staged / "bundle/configuration/config.json",
                        journal_path=journal,
                        request_path=request,
                    )
                    with pytest.raises(ValueError, match="unbound account state differs"):
                        scenario.installation.install(release, now=_NOW)
                    assert scenario.installation.current() is None
                else:
                    scenario.installation.install(release, now=_NOW)
                    assert scenario.installation.current() is not None
                    assert journal.stat().st_ino == original_inode

    def test_interrupted_initial_switch_recovers_exact_existing_state(self, tmp_path: Path) -> None:
        """Finish the pointer switch without replacing an identical orphan state tree."""
        scenario = InstallationScenario(tmp_path)
        first = scenario.candidate("first-release", config=b"first config\n")
        interruption = PointerInterruption(LocalInstallation._atomic_write)
        with scenario.isolated_installation():
            with patch.object(
                LocalInstallation, "_atomic_write", side_effect=interruption.interrupt
            ):
                with pytest.raises(OSError, match="simulated pointer interruption"):
                    scenario.installation.install(first, now=_NOW)
            state_file = scenario.installation.root / "state/checkpoint.bin"
            original_inode = state_file.stat().st_ino
            assert scenario.installation.current() is None

            receipt = scenario.installation.install(first, now=_NOW)

        assert scenario.installation.current() == receipt
        assert state_file.read_bytes() == b"initial state\n"
        assert state_file.stat().st_ino == original_inode

    @pytest.mark.parametrize(
        "mutation", ("changed-content", "unknown-file", "unknown-directory", "symlink")
    )
    def test_interrupted_initial_switch_rejects_changed_state(
        self, tmp_path: Path, mutation: str
    ) -> None:
        """Do not adopt or overwrite state changed after an interrupted first switch."""
        scenario = InstallationScenario(tmp_path)
        first = scenario.candidate("first-release", config=b"first config\n")
        interruption = PointerInterruption(LocalInstallation._atomic_write)
        with scenario.isolated_installation():
            with patch.object(
                LocalInstallation, "_atomic_write", side_effect=interruption.interrupt
            ):
                with pytest.raises(OSError, match="simulated pointer interruption"):
                    scenario.installation.install(first, now=_NOW)
            state = scenario.installation.root / "state"
            if mutation == "changed-content":
                (state / "checkpoint.bin").write_bytes(b"modified state\n")
            elif mutation == "unknown-file":
                (state / "unbound.bin").write_bytes(b"unknown\n")
            elif mutation == "unknown-directory":
                (state / "unbound").mkdir()
            else:
                (state / "checkpoint.bin").unlink()
                (state / "checkpoint.bin").symlink_to(tmp_path / "external-state")

            with pytest.raises((OSError, ValueError)):
                scenario.installation.install(first, now=_NOW)

        assert scenario.installation.current() is None
        assert state.exists()

    def test_staging_failure_keeps_prior_pointer_and_mutable_state(self, tmp_path: Path) -> None:
        """A failed candidate cannot change active code or the latest application state."""
        scenario = InstallationScenario(tmp_path)
        first = scenario.candidate("first-release", config=b"first config\n")
        second = scenario.candidate("second-release", config=b"second config\n")
        with scenario.isolated_installation():
            selected = scenario.installation.install(first, now=_NOW)
            state_file = scenario.installation.root / "state/checkpoint.bin"
            state_file.write_bytes(b"later state\n")
            with patch.object(
                LocalInstallation, "_inspect_application", side_effect=ValueError("inspect failed")
            ):
                with pytest.raises(ValueError, match="inspect failed"):
                    scenario.installation.install(second, now=_NOW)

        assert scenario.installation.current() == selected
        assert state_file.read_bytes() == b"later state\n"
        assert len(list((scenario.installation.root / "releases").iterdir())) == 2

    def test_rollback_restores_old_code_and_config_with_latest_state(self, tmp_path: Path) -> None:
        """Switch back to an authenticated prior release while retaining current state."""
        scenario = InstallationScenario(tmp_path)
        first = scenario.candidate("first-release", config=b"first config\n")
        second = scenario.candidate("second-release", config=b"second config\n")
        with scenario.isolated_installation():
            original = scenario.installation.install(first, now=_NOW)
            updated = scenario.installation.install(second, now=_NOW)
            state_file = scenario.installation.root / "state/checkpoint.bin"
            state_file.write_bytes(b"latest state\n")

            rolled_back = scenario.installation.install(first, now=_NOW)

        assert rolled_back.release == original.release
        assert rolled_back.previous_release == updated.release
        assert rolled_back.slot != original.slot
        assert scenario.installation.current() == rolled_back
        assert (
            scenario.installation.root / rolled_back.slot / "bundle/configuration/config.json"
        ).read_bytes() == b"first config\n"
        assert state_file.read_bytes() == b"latest state\n"

    def test_incompatible_state_schema_rejects_before_staging(self, tmp_path: Path) -> None:
        """An update cannot silently adopt state under a different schema."""
        scenario = InstallationScenario(tmp_path)
        first = scenario.candidate("first-release", config=b"first config\n")
        incompatible = scenario.candidate(
            "incompatible-release", config=b"other config\n", state_schema="state-v2"
        )
        with scenario.isolated_installation():
            selected = scenario.installation.install(first, now=_NOW)
            before = set((scenario.installation.root / "releases").iterdir())

            with pytest.raises(ValueError, match="current state is incompatible"):
                scenario.installation.install(incompatible, now=_NOW)

        assert scenario.installation.current() == selected
        assert set((scenario.installation.root / "releases").iterdir()) == before

    def test_active_run_fences_competing_installation(self, tmp_path: Path) -> None:
        """Keep the exclusive lock across an installed workload invocation."""
        scenario = InstallationScenario(tmp_path)
        first = scenario.candidate("first-release", config=b"first config\n")
        second = scenario.candidate("second-release", config=b"second config\n")
        blocker = BlockingApplication()
        with scenario.isolated_installation():
            selected = scenario.installation.install(first, now=_NOW)
            with patch.object(LocalInstallation, "_run", side_effect=blocker.run):
                with ThreadPoolExecutor(max_workers=1) as workers:
                    future = workers.submit(scenario.installation.run, ("replay",), now=_NOW)
                    try:
                        assert blocker.started.wait(timeout=5)
                        with pytest.raises(BlockingIOError):
                            scenario.installation.install(second, now=_NOW)
                    finally:
                        blocker.release.set()
                    assert future.result(timeout=5) == b"completed\n"

        assert scenario.installation.current() == selected

    def test_identical_retry_checks_retained_installed_bytes(self, tmp_path: Path) -> None:
        """A retry is idempotent only while its installed files still match receipt."""
        scenario = InstallationScenario(tmp_path)
        first = scenario.candidate("first-release", config=b"first config\n")
        with scenario.isolated_installation():
            selected = scenario.installation.install(first, now=_NOW)
            assert scenario.installation.install(first, now=_NOW) == selected
            config = scenario.installation.root / selected.slot / "bundle/configuration/config.json"
            config.write_bytes(b"corrupted config\n")

            with pytest.raises(ValueError, match="installed environment differs"):
                scenario.installation.install(first, now=_NOW)

        assert scenario.installation.current() == selected

    @pytest.mark.parametrize("mutation", ("symlink-directory", "untracked-bytecode"))
    def test_installed_directory_inventory_rejects_hidden_changes(
        self, tmp_path: Path, mutation: str
    ) -> None:
        """Track bytecode and reject symlinked directories outside the signed slot."""
        scenario = InstallationScenario(tmp_path)
        first = scenario.candidate("first-release", config=b"first config\n")
        with scenario.isolated_installation():
            selected = scenario.installation.install(first, now=_NOW)
            destination = scenario.installation.root / selected.slot
            if mutation == "symlink-directory":
                outside = tmp_path / "outside"
                outside.mkdir()
                (destination / "unexpected").symlink_to(outside, target_is_directory=True)
                message = "unexpected symlink"
            else:
                cache = destination / "venv/lib/__pycache__"
                cache.mkdir(parents=True)
                (cache / "injected.pyc").write_bytes(b"executable bytecode")
                message = "installed environment differs"

            with pytest.raises(ValueError, match=message):
                scenario.installation.install(first, now=_NOW)

    def test_lock_symlink_and_broken_pointer_are_rejected(self, tmp_path: Path) -> None:
        """Neither a substituted lock nor a broken active pointer becomes trusted state."""
        scenario = InstallationScenario(tmp_path)
        first = scenario.candidate("first-release", config=b"first config\n")
        with scenario.isolated_installation():
            scenario.installation.install(first, now=_NOW)
            pointer = scenario.installation.root / "current.json"
            pointer.unlink()
            pointer.symlink_to(tmp_path / "missing-pointer")
            with pytest.raises(OSError):
                scenario.installation.current()
            pointer.unlink()

            lock = scenario.installation.root / ".installation.lock"
            lock.unlink()
            external = tmp_path / "external-lock"
            external.write_bytes(b"preserve me")
            lock.symlink_to(external)
            with pytest.raises(OSError):
                scenario.installation.install(first, now=_NOW)

        assert external.read_bytes() == b"preserve me"

    @pytest.mark.parametrize(
        ("application", "arguments"),
        (
            ("collector", ("capture", "--output", "/private/tmp/capture")),
            ("collector", ("probe",)),
            ("execution", ("inspect",)),
            ("execution", ("admit", "--request", "/private/tmp/request.json")),
        ),
    )
    def test_config_consumers_receive_installed_signed_configuration(
        self,
        tmp_path: Path,
        application: Literal["collector", "execution"],
        arguments: tuple[str, ...],
    ) -> None:
        """Pass the installed config bytes to every command that reads configuration."""
        scenario = InstallationScenario(tmp_path)
        release = scenario.candidate(
            "configured-release", config=b"signed config\n", application=application
        )
        recorder = RecordedApplication()
        with scenario.isolated_installation():
            receipt = scenario.installation.install(release, now=_NOW)
            with patch.object(LocalInstallation, "_run", side_effect=recorder.run):
                assert scenario.installation.run(arguments, now=_NOW) == b"accepted\n"

        assert len(recorder.calls) == 1
        invocation, cwd = recorder.calls[0]
        assert invocation[0] == str(
            scenario.installation.root
            / receipt.slot
            / "venv/bin"
            / ("alpha-collect" if application == "collector" else "alpha-execute")
        )
        assert invocation[1:-2] == list(arguments)
        assert invocation[-2:] == [
            "--config",
            str(scenario.installation.root / receipt.slot / "bundle/configuration/config.json"),
        ]
        assert cwd == scenario.installation.root

    @pytest.mark.parametrize("override", ("--config", "--config=other", "--conf=other"))
    def test_run_rejects_signed_configuration_overrides(
        self, tmp_path: Path, override: str
    ) -> None:
        """Reject exact and argparse-abbreviated attempts to replace config."""
        scenario = InstallationScenario(tmp_path)
        release = scenario.candidate("configured-release", config=b"signed config\n")
        recorder = RecordedApplication()
        with scenario.isolated_installation():
            scenario.installation.install(release, now=_NOW)
            with patch.object(LocalInstallation, "_run", side_effect=recorder.run):
                with pytest.raises(ValueError, match="cannot override signed configuration"):
                    scenario.installation.run(("capture", override, "other.json"), now=_NOW)

        assert recorder.calls == []

    def test_replay_keeps_explicit_capture_reference(self, tmp_path: Path) -> None:
        """Allow retained saved-input selection without introducing a config override."""
        scenario = InstallationScenario(tmp_path)
        release = scenario.candidate("configured-release", config=b"signed config\n")
        recorder = RecordedApplication()
        with scenario.isolated_installation():
            scenario.installation.install(release, now=_NOW)
            with patch.object(LocalInstallation, "_run", side_effect=recorder.run):
                assert (
                    scenario.installation.run(
                        ("replay", "--capture", str(tmp_path / "saved-capture")), now=_NOW
                    )
                    == b"accepted\n"
                )

        assert recorder.calls[0][0][1:] == [
            "replay",
            "--capture",
            str(tmp_path / "saved-capture"),
        ]

    def test_run_rejects_missing_or_unknown_application_action(self, tmp_path: Path) -> None:
        """A run cannot bypass the signed command/config binding via another action."""
        scenario = InstallationScenario(tmp_path)
        release = scenario.candidate("configured-release", config=b"signed config\n")
        recorder = RecordedApplication()
        with scenario.isolated_installation():
            scenario.installation.install(release, now=_NOW)
            with patch.object(LocalInstallation, "_run", side_effect=recorder.run):
                with pytest.raises(ValueError, match="requires an application command"):
                    scenario.installation.run((), now=_NOW)
                with pytest.raises(ValueError, match="unsupported installed application command"):
                    scenario.installation.run(("arbitrary",), now=_NOW)

        assert recorder.calls == []

    def test_run_rejects_receipt_runtime_different_from_signed_release(
        self, tmp_path: Path
    ) -> None:
        """A locally changed receipt cannot select a different installed entrypoint."""
        scenario = InstallationScenario(tmp_path)
        release = scenario.candidate("configured-release", config=b"signed config\n")
        recorder = RecordedApplication()
        with scenario.isolated_installation():
            selected = scenario.installation.install(release, now=_NOW)
            changed = InstallationReceipt(
                release=selected.release,
                slot=selected.slot,
                runtime=ReleaseRuntime(
                    python_version="3.14.7",
                    platform="darwin_arm64",
                    contract_version="1",
                    application="execution",
                    mode="research",
                    config_schema="config-v1",
                    state_schema="state-v1",
                ),
                previous_release=selected.previous_release,
                files=selected.files,
            )
            encoded = changed.model_dump_json().encode()
            (scenario.installation.root / "current.json").write_bytes(encoded)
            (scenario.installation.root / selected.slot / "receipt.json").write_bytes(encoded)
            with patch.object(LocalInstallation, "_run", side_effect=recorder.run):
                with pytest.raises(ValueError, match="runtime differs from signed release"):
                    scenario.installation.run(("inspect",), now=_NOW)

        assert recorder.calls == []

    def test_run_rejects_symlinked_installation_root(self, tmp_path: Path) -> None:
        """A target alias cannot redirect the lock and installed command boundary."""
        scenario = InstallationScenario(tmp_path)
        scenario.installation.root.mkdir()
        alias = tmp_path / "alias"
        alias.symlink_to(scenario.installation.root, target_is_directory=True)

        with pytest.raises(ValueError, match="installation target must be a regular directory"):
            LocalInstallation(alias, scenario.policy).run(("replay",), now=_NOW)


class TestPinnedInstallationTools:
    """Match selected tool behavior to the signed runtime and pinned uv contract."""

    def test_selected_python_and_uv_report_expected_runtime(self, tmp_path: Path) -> None:
        """Probe the selected executable, not just the current caller process."""
        probe = PinnedToolProbe(tmp_path)
        with patch.object(LocalInstallation, "_run", side_effect=probe.respond):
            probe.installation._require_tools(probe.runtime)

        assert len(probe.calls) == 2
        assert probe.calls[0][0][:4] == [str(probe.python), "-I", "-B", "-c"]
        assert probe.calls[1][0] == [str(probe.uv), "--version"]

    @pytest.mark.parametrize(
        ("mutation", "message"),
        (
            ("implementation", "selected installation Python differs"),
            ("version", "selected installation Python differs"),
            ("platform", "selected installation Python differs"),
            ("machine", "selected installation Python differs"),
            ("gil", "selected installation Python differs"),
            ("uv", "selected installation uv has an incompatible version"),
        ),
    )
    def test_selected_tool_identity_mismatch_fails(
        self, tmp_path: Path, mutation: str, message: str
    ) -> None:
        """Reject a pinned tool that reports another runtime or unsupported uv."""
        probe = PinnedToolProbe(tmp_path)
        replacements = {
            "implementation": (0, "pypy"),
            "version": (1, "3.14.6"),
            "platform": (2, "linux"),
            "machine": (3, "x86_64"),
            "gil": (4, "1"),
        }
        if mutation == "uv":
            probe.uv_report = b"uv 0.13.0\n"
        else:
            index, value = replacements[mutation]
            facts = list(probe.python_facts)
            facts[index] = value
            probe.python_facts = tuple(facts)

        with patch.object(LocalInstallation, "_run", side_effect=probe.respond):
            with pytest.raises(ValueError, match=message):
                probe.installation._require_tools(probe.runtime)
