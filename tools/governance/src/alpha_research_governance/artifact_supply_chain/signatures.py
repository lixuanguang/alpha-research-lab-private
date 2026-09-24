"""Sign and authenticate release bytes with the target's pinned OpenSSH executable."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import subprocess  # nosec B404  # [owner=platform; rationale=pinned shell-free signature tool; expires=2027-03-01]
from pathlib import Path
from tempfile import TemporaryDirectory

# project library imports
from alpha_research_governance.artifact_supply_chain.records import TrustedBuilder


class ReleaseSignatures:
    """Bind OpenSSH signatures to the release namespace and a provisioned public key."""

    namespace = "alpha-research-release-v1"

    def __init__(self, executable: Path, sha256: str) -> None:
        """Bind an absolute tool path and its independently provisioned digest."""
        self.executable = executable
        self.sha256 = sha256

    def sign(self, payload: bytes, private_key: Path) -> bytes:
        """Sign exact bytes with an operator-selected local key, without retaining the key.

        The key must be a regular owner-only file. Noninteractive keys belong in
        a protected builder environment; this operation never changes target trust.
        """
        if private_key.is_symlink() or private_key.stat().st_mode & 0o077:
            raise ValueError("signing key must be an owner-only regular file")
        if not private_key.is_file():
            raise ValueError("signing key must be a regular file")
        return self._run(["-Y", "sign", "-f", str(private_key), "-n", self.namespace], payload)

    def verify(self, payload: bytes, signature: bytes, builder: TrustedBuilder) -> None:
        """Reject any signature not authenticating the payload under this scoped key."""
        with TemporaryDirectory(prefix="ar-signature-") as temporary:
            directory = Path(temporary)
            allowed = directory / "allowed-signers"
            detached = directory / "release.sig"
            allowed.write_text(f"{builder.identity} {builder.public_key}\n", encoding="ascii")
            detached.write_bytes(signature)
            self._run(
                [
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed),
                    "-I",
                    builder.identity,
                    "-n",
                    self.namespace,
                    "-s",
                    str(detached),
                ],
                payload,
            )

    def _run(self, arguments: list[str], payload: bytes) -> bytes:
        """Run only the pinned signature binary with a bounded clean environment."""
        if not self.executable.is_absolute() or not self.executable.is_file():
            raise ValueError("signature tool is missing or not absolute")
        if hashlib.sha256(self.executable.read_bytes()).hexdigest() != self.sha256:
            raise ValueError("signature tool digest changed")
        environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": "/nonexistent"}
        try:
            completed = subprocess.run(  # nosec B603  # [owner=platform; rationale=digest-pinned signature argv without shell; expires=2027-03-01]
                [str(self.executable), *arguments],
                input=payload,
                capture_output=True,
                timeout=30,
                check=False,
                env=environment,
                cwd=os.devnull.rsplit("/", 1)[0],
            )
        except subprocess.TimeoutExpired as error:
            raise ValueError("release signature operation timed out") from error
        if completed.returncode != 0:
            raise ValueError("release signature verification or signing failed")
        return completed.stdout
