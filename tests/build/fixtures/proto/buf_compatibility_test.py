"""Prove the pinned Buf policy accepts additive and rejects breaking schema changes."""

from __future__ import annotations

# standard library imports
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(buf: Path, module: Path, baseline: Path) -> subprocess.CompletedProcess[str]:
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
