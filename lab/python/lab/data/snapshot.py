"""Data snapshot manager for reproducible backtests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import pandas as pd

from lab.core.paths import data_dir
from lab.core.registry import compute_stable_frame_hash


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pkg_version(name: str) -> str:
    try:
        return str(version(name))
    except PackageNotFoundError:
        return "not_installed"


def _canonical_date(value: str) -> str:
    return str(pd.Timestamp(value).date())


def _canonical_payload(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _macro_bundle_digest(
    macro_files: list[Path],
) -> tuple[str, list[dict[str, str]]]:
    entries: list[dict[str, str]] = []
    for path in sorted(macro_files, key=lambda p: p.name):
        file_hash = _sha256_file(path)
        frame = pd.read_parquet(path)
        if isinstance(frame, pd.Series):
            frame = frame.to_frame(name=path.stem)
        frame_hash = compute_stable_frame_hash(pd.DataFrame(frame))
        entries.append(
            {
                "file": path.name,
                "sha256": file_hash,
                "frame_hash": frame_hash,
            }
        )
    digest = _sha256_bytes(_canonical_payload({"macro_files": entries}))
    return digest, entries


def compute_data_snapshot_manifest(
    *,
    source_name: str,
    tickers: list[str],
    start: str,
    end: str,
    adjustment_policy: dict[str, Any],
    close_path: Path,
    macro_files: list[Path],
    source_versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build deterministic snapshot manifest with ID and hash provenance."""
    close_path = Path(close_path).resolve()
    if not close_path.exists():
        raise FileNotFoundError(f"Close file not found for snapshot: {close_path}")
    for path in macro_files:
        if not Path(path).exists():
            raise FileNotFoundError(f"Macro file not found for snapshot: {path}")

    close_frame = pd.read_parquet(close_path)
    close_frame_hash = compute_stable_frame_hash(pd.DataFrame(close_frame))
    close_file_hash = _sha256_file(close_path)
    macro_bundle_hash, macro_entries = _macro_bundle_digest([Path(p).resolve() for p in macro_files])

    versions = {
        "yfinance": _pkg_version("yfinance"),
        "fredapi": _pkg_version("fredapi"),
    }
    if source_versions:
        versions.update({str(k): str(v) for k, v in source_versions.items()})

    identity_payload = {
        "source": {
            "name": str(source_name).strip().lower(),
            "versions": dict(sorted(versions.items())),
        },
        "universe": {
            "tickers": sorted({str(t).strip() for t in tickers if str(t).strip()}),
            "start": _canonical_date(start),
            "end": _canonical_date(end),
        },
        "adjustment_policy": dict(sorted((adjustment_policy or {}).items())),
        "hashes": {
            "close_file_sha256": close_file_hash,
            "close_frame_hash": close_frame_hash,
            "macro_bundle_sha256": macro_bundle_hash,
        },
        "macro_files": macro_entries,
    }
    snapshot_id = _sha256_bytes(_canonical_payload(identity_payload))

    return {
        "snapshot_id": snapshot_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        **identity_payload,
        "paths": {
            "close_file": str(close_path),
            "macro_files": [str(Path(p).resolve()) for p in macro_files],
        },
    }


def snapshots_root(root: Path | None = None) -> Path:
    base = root if root is not None else data_dir() / "snapshots"
    base.mkdir(parents=True, exist_ok=True)
    return base


def write_snapshot_manifest(
    manifest: dict[str, Any],
    *,
    root: Path | None = None,
) -> Path:
    snapshot_id = str(manifest.get("snapshot_id", "")).strip()
    if not snapshot_id:
        raise ValueError("Snapshot manifest missing non-empty snapshot_id.")
    path = snapshots_root(root) / f"{snapshot_id}.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return path


def create_data_snapshot(
    *,
    source_name: str,
    tickers: list[str],
    start: str,
    end: str,
    adjustment_policy: dict[str, Any],
    close_path: Path,
    macro_files: list[Path],
    source_versions: dict[str, str] | None = None,
    root: Path | None = None,
) -> tuple[str, Path, dict[str, Any]]:
    """Compute snapshot ID, persist manifest, and return `(id, path, manifest)`."""
    manifest = compute_data_snapshot_manifest(
        source_name=source_name,
        tickers=tickers,
        start=start,
        end=end,
        adjustment_policy=adjustment_policy,
        close_path=close_path,
        macro_files=macro_files,
        source_versions=source_versions,
    )
    path = write_snapshot_manifest(manifest, root=root)
    return str(manifest["snapshot_id"]), path, manifest
