"""Exercise pinned Buf lint and deterministic descriptor generation."""

from __future__ import annotations

# standard library imports
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(completed.stdout + completed.stderr)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: buf_toolchain_test.py BUF CONFIG", file=sys.stderr)
        return 2
    buf = Path(sys.argv[1]).resolve(strict=True)
    package = Path(sys.argv[2]).resolve(strict=True).parent

    with tempfile.TemporaryDirectory(prefix="alpha-buf-toolchain-test-") as temporary_directory:
        temporary = Path(temporary_directory)
        environment = {
            "BUF_CACHE_DIR": str(temporary / "cache"),
            "HOME": str(temporary / "home"),
            "LC_ALL": "C.UTF-8",
            "PATH": "",
            "TZ": "UTC",
        }
        _run([str(buf), "lint", "."], cwd=package, environment=environment)
        descriptor_digests: list[str] = []
        for index in range(2):
            descriptor = temporary / f"schema-{index}.binpb"
            _run(
                [str(buf), "build", ".", "--output", str(descriptor)],
                cwd=package,
                environment=environment,
            )
            descriptor_digests.append(hashlib.sha256(descriptor.read_bytes()).hexdigest())
        if len(set(descriptor_digests)) != 1:
            print("Buf descriptor generation is not deterministic", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
