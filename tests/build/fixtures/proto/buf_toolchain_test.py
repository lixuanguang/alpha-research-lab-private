"""Exercise pinned Buf lint and deterministic descriptor generation."""

from __future__ import annotations

# standard library imports
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path


class BufToolchainCheck:
    """Check Buf linting and deterministic descriptor generation."""

    _buf: Path
    _package: Path

    def __init__(self, *, _buf: Path, _package: Path) -> None:
        """Initialize a toolchain check with executable and package paths.

        Args:
            _buf: Path to the Buf executable.
            _package: Buf module working directory.
        """
        self._buf = _buf
        self._package = _package

    def _run(self, command: list[str], *, environment: dict[str, str]) -> None:
        """Run a Buf command and raise when the child exits unsuccessfully.

        Args:
            command: Executable and arguments to pass to the child process.
            environment: Environment variables to provide to the child process.

        Raises:
            OSError: If the child process cannot be started.
            UnicodeDecodeError: If captured child output cannot be decoded as text.
            RuntimeError: If the child exits with a nonzero status; its captured
                output is included in the exception message.
        """
        completed = subprocess.run(
            command,
            cwd=self._package,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            raise RuntimeError(completed.stdout + completed.stderr)

    def run(self) -> int:
        """Lint the Buf module and compare two generated descriptor digests.

        Returns:
            ``0`` when lint and both builds succeed with matching digests, or
            ``1`` when the generated digests differ.

        Raises:
            OSError: If a descriptor cannot be read or Buf cannot be started.
            UnicodeDecodeError: If captured child output cannot be decoded as text.
            RuntimeError: If lint or descriptor generation exits nonzero.
        """
        with tempfile.TemporaryDirectory(prefix="alpha-buf-toolchain-test-") as temporary_directory:
            temporary = Path(temporary_directory)
            environment = {
                "BUF_CACHE_DIR": str(temporary / "cache"),
                "HOME": str(temporary / "home"),
                "LC_ALL": "C.UTF-8",
                "PATH": "",
                "TZ": "UTC",
            }
            self._run([str(self._buf), "lint", "."], environment=environment)
            descriptor_digests: list[str] = []
            for index in range(2):
                descriptor = temporary / f"schema-{index}.binpb"
                self._run(
                    [str(self._buf), "build", ".", "--output", str(descriptor)],
                    environment=environment,
                )
                descriptor_digests.append(hashlib.sha256(descriptor.read_bytes()).hexdigest())
            if len(set(descriptor_digests)) != 1:
                print("Buf descriptor generation is not deterministic", file=sys.stderr)
                return 1
        return 0


def main() -> int:
    """Lint the Buf module and verify that descriptor generation is deterministic.

    The command-line paths must identify the Buf executable and a configuration
    file; the configuration file's parent is the module working directory. The
    function runs lint once and descriptor generation twice with an empty
    ``PATH``, temporary cache and home paths, the ``C.UTF-8`` locale, and the UTC
    timezone. It does not validate descriptor contents beyond comparing their
    SHA-256 digests. Temporary files and any Buf cache or home data are removed
    when the context exits.
    Usage and explicit digest-mismatch diagnostics are written to stderr.

    Returns:
        ``0`` when lint and both builds succeed with matching digests, ``1``
        when the generated digests differ, or ``2`` when the invocation does
        not contain exactly two paths after the program name.

    Raises:
        OSError: If an input path, temporary fixture operation, or descriptor
            read fails, or if a Buf process cannot be started.
        UnicodeDecodeError: If captured Buf output cannot be decoded as text.
        RuntimeError: If lint or descriptor generation exits nonzero.
    """
    if len(sys.argv) != 3:
        print("usage: buf_toolchain_test.py BUF CONFIG", file=sys.stderr)
        return 2
    buf = Path(sys.argv[1]).resolve(strict=True)
    package = Path(sys.argv[2]).resolve(strict=True).parent
    return BufToolchainCheck(_buf=buf, _package=package).run()


if __name__ == "__main__":
    raise SystemExit(main())
