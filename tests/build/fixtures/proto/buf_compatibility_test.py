"""Prove the pinned Buf policy accepts additive and rejects breaking schema changes."""

from __future__ import annotations

# standard library imports
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(buf: Path, module: Path, baseline: Path) -> subprocess.CompletedProcess[str]:
    """Run Buf breaking analysis against a baseline module and capture its result.

    The child process receives cache and home paths under ``module.parent``, an
    empty ``PATH``, the ``C.UTF-8`` locale, and the UTC timezone. Buf may write
    cache or home data at those paths. A nonzero Buf exit status remains in the
    returned result because the caller checks whether each compatibility case
    has the expected status.

    Args:
        buf: Path to the Buf executable.
        module: Candidate schema module directory to compare.
        baseline: Baseline schema module directory for comparison.

    Returns:
        The completed Buf process with captured text output and exit status.

    Raises:
        OSError: If the Buf process cannot be started.
        UnicodeDecodeError: If captured Buf output cannot be decoded as text.
    """
    environment = {
        "BUF_CACHE_DIR": str(module.parent / "cache"),
        "HOME": str(module.parent / "home"),
        "LC_ALL": "C.UTF-8",
        "PATH": "",
        "TZ": "UTC",
    }
    return subprocess.run(
        [str(buf), "breaking", str(module), "--against", str(baseline)],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def main() -> int:
    """Check additive and removal cases against the Buf file-compatibility policy.

    The command-line paths must identify an executable, configuration file, and
    Protobuf file. The function creates three temporary module copies, adds a
    field to one copy, removes the existing ``target`` field from another, and
    runs Buf against the unchanged copy. It returns success only when the
    additive invocation exits successfully and the removal invocation exits
    nonzero; it does not inspect the nonzero diagnostic's contents. Temporary
    files and any Buf cache or home data are removed when the context exits.
    Usage and explicit compatibility-failure diagnostics are written to stderr.

    Returns:
        ``0`` when the observed statuses match the expected compatibility
        behavior, ``1`` when a case has an unexpected status, or ``2`` when the
        invocation does not contain exactly three paths after the program name.

    Raises:
        OSError: If an input path, temporary fixture operation, or Buf process
            cannot be accessed or started.
        UnicodeDecodeError: If fixture source is not valid UTF-8 or captured Buf
            output cannot be decoded as text.
    """
    if len(sys.argv) != 4:
        print("usage: buf_compatibility_test.py BUF CONFIG PROTO", file=sys.stderr)
        return 2
    buf = Path(sys.argv[1]).resolve(strict=True)
    config = Path(sys.argv[2]).resolve(strict=True)
    proto = Path(sys.argv[3]).resolve(strict=True)

    with tempfile.TemporaryDirectory(
        prefix="continuous-integration-buf-compatibility-"
    ) as temporary_directory:
        temporary = Path(temporary_directory)
        baseline = temporary / "baseline"
        additive = temporary / "additive"
        breaking = temporary / "breaking"
        for module in (baseline, additive, breaking):
            schema_directory = module / "alpha_research" / "build" / "v1"
            schema_directory.mkdir(parents=True)
            shutil.copyfile(config, module / "buf.yaml")
            shutil.copyfile(proto, schema_directory / proto.name)

        additive_proto = additive / "alpha_research" / "build" / "v1" / proto.name
        additive_text = additive_proto.read_text(encoding="utf-8")
        additive_proto.write_text(
            additive_text.replace("}\n", "  string additive_probe = 3;\n}\n"),
            encoding="utf-8",
        )
        compatible = _run(buf, additive, baseline)
        if compatible.returncode:
            print(compatible.stdout + compatible.stderr, file=sys.stderr)
            return 1

        breaking_proto = breaking / "alpha_research" / "build" / "v1" / proto.name
        breaking_text = breaking_proto.read_text(encoding="utf-8")
        breaking_proto.write_text(
            breaking_text.replace("  string target = 1;\n", ""),
            encoding="utf-8",
        )
        incompatible = _run(buf, breaking, baseline)
        if incompatible.returncode == 0:
            print("Buf accepted a removed schema field", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
