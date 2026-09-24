"""Install authenticated operating releases offline and switch compatible local state."""

from __future__ import annotations

# standard library imports
import fcntl
import hashlib
import os
import platform
import re
import stat
import subprocess  # nosec B404  # [owner=platform; rationale=verified offline installer and installed command argv; expires=2027-03-01]
import sys
import sysconfig
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Literal, cast
from uuid import uuid4

# project library imports
from alpha_research_governance._models import ImmutableModel
from alpha_research_governance.artifact_supply_chain.bundles import ReleaseRegistry, VerifiedRelease
from alpha_research_governance.artifact_supply_chain.provenance import ReleaseProvenance
from alpha_research_governance.artifact_supply_chain.records import (
    Digest,
    InstallationPolicy,
    ReleaseFile,
    ReleaseRuntime,
    StateEnvelope,
)


class InstallationReceipt(ImmutableModel):
    """Record one complete immutable environment and its preserved local state binding."""

    schema_version: Literal["installation-receipt-v1"] = "installation-receipt-v1"
    release: Digest
    slot: str
    runtime: ReleaseRuntime
    previous_release: Digest | None
    files: tuple[ReleaseFile, ...]


class LocalInstallation:
    """Own the quiescence lock, immutable environments and one atomic active pointer.

    Installation never starts a service. Runs through this owner hold the same
    exclusive fence as installation. Rollback restores prior code/configuration
    while retaining current state; unsupported schema migrations fail closed.
    """

    def __init__(self, root: Path, policy: InstallationPolicy) -> None:
        """Bind an explicit local target and independently provisioned trust policy."""
        self.root = root.absolute()
        self.policy = InstallationPolicy.model_validate(policy)

    def install(self, directory: Path, *, now: datetime) -> InstallationReceipt:
        """Verify, stage, validate and atomically select a pinned operating release.

        The target must be quiescent. Failed installations leave the old active
        pointer and state unchanged and retain their incomplete slot for diagnosis.
        Identical retries verify the active environment without reinstalling it.
        """
        verified = ReleaseRegistry.verify(directory, self.policy, now=now)
        ReleaseProvenance.verify(verified, now=now)
        self._require_tools(verified.manifest.runtime)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise ValueError("installation target cannot be a symlink")
        with self._fence() as fence:
            fcntl.flock(fence.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            previous = self.current()
            initial_state_exists = self._require_state(
                verified.manifest.runtime, previous, initial_release=verified
            )
            if previous is not None and previous.release == verified.identity:
                self._verify_installation(previous)
                return previous
            slot = "releases/" + verified.identity + "-" + uuid4().hex[:12]
            destination = self.root / slot
            destination.mkdir(parents=True, mode=0o700)
            self._write_bundle(destination / "bundle", verified)
            self._install_wheels(destination, verified)
            self._inspect_application(destination, verified.manifest.runtime)
            files = self._describe_installation(destination)
            receipt = InstallationReceipt(
                release=verified.identity,
                slot=slot,
                runtime=verified.manifest.runtime,
                previous_release=None if previous is None else previous.release,
                files=files,
            )
            self._atomic_write(destination / "receipt.json", receipt.model_dump_json().encode())
            if previous is None and not initial_state_exists:
                self._initialize_state(verified)
            self._atomic_write(self.root / "current.json", receipt.model_dump_json().encode())
            return receipt

    def current(self) -> InstallationReceipt | None:
        """Read the selected local environment without executing its code."""
        pointer = self.root / "current.json"
        if not pointer.exists() and not pointer.is_symlink():
            return None
        receipt = InstallationReceipt.model_validate_json(
            ReleaseRegistry.read_regular(pointer, 8_388_608)
        )
        ReleaseFile.require_path(receipt.slot)
        if not receipt.slot.startswith("releases/") or len(Path(receipt.slot).parts) != 2:
            raise ValueError("invalid installed release slot")
        retained = ReleaseRegistry.read_regular(
            self.root / receipt.slot / "receipt.json", 8_388_608
        )
        if retained != receipt.model_dump_json().encode():
            raise ValueError("active receipt differs from retained installation")
        return receipt

    def run(self, arguments: tuple[str, ...], *, now: datetime) -> bytes:
        """Run the verified installed application under the installation/state fence.

        Arguments are passed directly to the selected application, never a shell.
        No inherited credential, Python-path or installer environment is forwarded.
        """
        with self._fence() as fence:
            fcntl.flock(fence.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            receipt = self.current()
            if receipt is None:
                raise ValueError("no operating release is installed")
            self._verify_installation(receipt)
            destination = self.root / receipt.slot
            bundle = destination / "bundle"
            verified = ReleaseRegistry.verify(
                bundle, self.policy, now=now, expected_identity=receipt.release
            )
            ReleaseProvenance.verify(verified, now=now)
            if verified.manifest.runtime != receipt.runtime:
                raise ValueError("installed receipt runtime differs from signed release")
            self._require_tools(verified.manifest.runtime)
            self._require_state(receipt.runtime, receipt)
            executable = destination / "venv/bin" / self._command(receipt.runtime)
            configuration = bundle / "configuration/config.json"
            invocation = self._bound_arguments(receipt.runtime, arguments, configuration)
            return self._run([str(executable), *invocation], cwd=self.root)

    def _require_tools(self, runtime: ReleaseRuntime) -> None:
        """Reject target drift before a verifier or installer can execute."""
        target = f"{sys.platform}_{platform.machine()}"
        version = (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
        if (
            target != runtime.platform
            or version != (3, 14, 7)
            or sys.implementation.name != "cpython"
        ):
            raise ValueError("host does not match the declared release target")
        if cast(object, sysconfig.get_config_var("Py_GIL_DISABLED")):
            raise ValueError("free-threaded Python is not admitted")
        for name, expected in (
            (self.policy.python_executable, self.policy.python_sha256),
            (self.policy.uv_executable, self.policy.uv_sha256),
            (self.policy.ssh_keygen_executable, self.policy.ssh_keygen_sha256),
        ):
            path = Path(name)
            if not path.is_absolute() or not path.is_file():
                raise ValueError("installation tool is absent or not absolute")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("installation tool digest changed")
        observed = self._run(
            [
                self.policy.python_executable,
                "-I",
                "-B",
                "-c",
                "import platform,sys,sysconfig; "
                "print(sys.implementation.name); "
                "print(sys.version.split()[0]); "
                "print(sys.platform); "
                "print(platform.machine()); "
                "print(sysconfig.get_config_var('Py_GIL_DISABLED'))",
            ],
            cwd=Path("/"),
        )
        python_facts = observed.decode("ascii").splitlines()
        system, machine = runtime.platform.split("_", 1)
        if (
            len(python_facts) != 5
            or python_facts[:4] != ["cpython", "3.14.7", system, machine]
            or python_facts[4] not in {"0", "None"}
        ):
            raise ValueError("selected installation Python differs from signed runtime")
        uv_version = self._run(
            [self.policy.uv_executable, "--version"],
            cwd=Path("/"),
        ).decode("ascii")
        if re.fullmatch(r"uv 0\.12\.7(?: \([^\n]*\))?\n?", uv_version) is None:
            raise ValueError("selected installation uv has an incompatible version")

    def _fence(self) -> BinaryIO:
        """Open a regular local lock without following a substituted symlink."""
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("installation target must be a regular directory")
        descriptor = os.open(
            self.root / ".installation.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError("installation lock must be a regular file")
        return os.fdopen(descriptor, "r+b")

    def _require_state(
        self,
        runtime: ReleaseRuntime,
        previous: InstallationReceipt | None,
        *,
        initial_release: VerifiedRelease | None = None,
    ) -> bool:
        """Preserve compatible state or recognize an exact interrupted first install."""
        state = self.root / "state"
        if previous is None:
            if not state.exists() and not state.is_symlink():
                return False
            if initial_release is None:
                raise ValueError("unbound state exists; recover the prior installation first")
            expected = tuple(
                (name.removeprefix("state/"), content)
                for name, content in initial_release.contents
                if name.startswith("state/")
            )
            if ReleaseRegistry.inventory(state) != tuple(name for name, _ in expected):
                raise ValueError("unbound state differs from authenticated initial state")
            expected_directories = {
                parent.as_posix()
                for name, _ in expected
                for parent in Path(name).parents
                if parent != Path(".")
            }
            actual_directories = {
                path.relative_to(state).as_posix() for path in state.rglob("*") if path.is_dir()
            }
            if actual_directories != expected_directories:
                raise ValueError("unbound state differs from authenticated initial state")
            for name, content in expected:
                if ReleaseRegistry.read_regular(state / name, len(content)) != content:
                    raise ValueError("unbound state differs from authenticated initial state")
            return True
        if (
            previous.runtime.application != runtime.application
            or previous.runtime.state_schema != runtime.state_schema
            or previous.runtime.mode != runtime.mode
        ):
            raise ValueError("current state is incompatible with the requested release")
        ReleaseRegistry.inventory(state)
        envelope = StateEnvelope.model_validate_json(
            ReleaseRegistry.read_regular(state / "state.json", 4_194_304)
        )
        if (
            envelope.schema_version != runtime.state_schema
            or envelope.application != runtime.application
        ):
            raise ValueError("current state schema differs from its installed binding")
        return False

    def _initialize_state(self, release: VerifiedRelease) -> None:
        """Publish initial state once without overwriting any existing application state."""
        staging = self.root / (".state-" + uuid4().hex)
        staging.mkdir(mode=0o700)
        for name, content in release.contents:
            if name.startswith("state/"):
                destination = staging / name.removeprefix("state/")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
        state = self.root / "state"
        if state.exists() or state.is_symlink():
            raise ValueError("initial state appeared during publication")
        staging.rename(state)

    @staticmethod
    def _write_bundle(destination: Path, release: VerifiedRelease) -> None:
        """Copy authenticated in-memory bytes into a private installation slot."""
        destination.mkdir()
        for name, content in (
            *release.contents,
            ("release.json", release.manifest_bytes),
            ("release.sig", release.signature),
        ):
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def _install_wheels(self, destination: Path, release: VerifiedRelease) -> None:
        """Install only verified wheel files with offline hash enforcement."""
        requirements: list[str] = []
        for record in release.manifest.files:
            if record.path.startswith("wheels/") and record.path.endswith(".whl"):
                wheel = destination / "bundle" / record.path
                requirements.append(f"{wheel.as_uri()} --hash=sha256:{record.sha256}")
        if not requirements:
            raise ValueError("release has no wheel inventory")
        path = destination / "requirements.txt"
        path.write_text("\n".join(requirements) + "\n", encoding="utf-8")
        uv = self.policy.uv_executable
        venv = destination / "venv"
        self._run(
            [
                uv,
                "venv",
                "--no-config",
                "--no-project",
                "--offline",
                "--no-python-downloads",
                "--python",
                self.policy.python_executable,
                str(venv),
            ],
            cwd=destination,
        )
        self._run(
            [
                uv,
                "pip",
                "install",
                "--no-config",
                "--offline",
                "--no-index",
                "--no-deps",
                "--require-hashes",
                "--no-cache",
                "--link-mode",
                "copy",
                "--python",
                str(venv / "bin/python"),
                "--requirement",
                str(path),
            ],
            cwd=destination,
        )
        self._run(
            [uv, "pip", "check", "--no-config", "--python", str(venv / "bin/python")],
            cwd=destination,
        )

    def _inspect_application(self, destination: Path, runtime: ReleaseRuntime) -> None:
        """Exercise the actual installed application before changing the active pointer."""
        executable = destination / "venv/bin" / self._command(runtime)
        arguments = [str(executable), "--help"]
        if runtime.application == "execution":
            arguments = [
                str(executable),
                "inspect",
                "--config",
                str(destination / "bundle/configuration/config.json"),
            ]
        self._run(arguments, cwd=destination)

    @staticmethod
    def _command(runtime: ReleaseRuntime) -> str:
        """Select the installed entrypoint belonging to this signed application."""
        return "alpha-collect" if runtime.application == "collector" else "alpha-execute"

    @staticmethod
    def _bound_arguments(
        runtime: ReleaseRuntime, arguments: tuple[str, ...], configuration: Path
    ) -> list[str]:
        """Select only installed commands and bind config consumers to signed bytes."""
        if not arguments:
            raise ValueError("installed run requires an application command")
        action = arguments[0]
        configured = (
            {"capture", "probe"} if runtime.application == "collector" else {"inspect", "admit"}
        )
        if action in configured:
            for argument in arguments[1:]:
                option = argument.partition("=")[0]
                if option.startswith("--") and "--config".startswith(option):
                    raise ValueError("installed run cannot override signed configuration")
            return [*arguments, "--config", str(configuration)]
        if runtime.application == "collector" and action == "replay":
            return list(arguments)
        raise ValueError("unsupported installed application command")

    @staticmethod
    def _describe_installation(directory: Path) -> tuple[ReleaseFile, ...]:
        """Pin all installed regular files and expected interpreter links."""
        records: list[ReleaseFile] = []
        for path in sorted(directory.rglob("*")):
            name = path.relative_to(directory).as_posix()
            if path.is_symlink():
                if not name.startswith("venv/bin/python") or not path.resolve().is_file():
                    raise ValueError("unexpected symlink in installed environment")
                content = os.readlink(path).encode()
            else:
                if path.is_dir() or name == "receipt.json":
                    continue
                content = ReleaseRegistry.read_regular(path, 268_435_456)
            records.append(ReleaseFile.describe(name, content))
        return tuple(records)

    def _verify_installation(self, receipt: InstallationReceipt) -> None:
        """Reject any altered executable, configuration, dependency or retained release file."""
        if self._describe_installation(self.root / receipt.slot) != receipt.files:
            raise ValueError("installed environment differs from its verified receipt")

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        """Publish one fsynced local record, retaining the old record on write failure."""
        temporary = path.with_name("." + path.name + "-" + uuid4().hex)
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _run(arguments: list[str], *, cwd: Path) -> bytes:
        """Execute bounded shell-free argv without inherited credentials or path injection."""
        environment = {
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "HOME": str(cwd),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        try:
            result = subprocess.run(  # nosec B603  # [owner=platform; rationale=pinned tools or verified installed entrypoint argv; expires=2027-03-01]
                arguments,
                cwd=cwd,
                env=environment,
                check=False,
                capture_output=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired as error:
            raise ValueError("installation or installed consumer timed out") from error
        if result.returncode != 0:
            raise ValueError(
                f"installation command failed: {result.stderr.decode(errors='replace')[-2000:]}"
            )
        return result.stdout
