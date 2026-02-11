"""Disk cache for raw/normalized price ingestion outputs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


def _stable_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _canonical_start_end(value: str) -> str:
    return str(pd.Timestamp(value).date())


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".bin", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def write_parquet_if_changed(
    df: pd.DataFrame,
    path: Path,
    *,
    index: bool,
) -> bool:
    """Write parquet atomically; skip replacement if bytes are unchanged.

    Returns True when the target file content changed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".tmp_{path.name}"
    try:
        df.to_parquet(tmp, index=index)
        new_bytes = tmp.read_bytes()
        if path.exists():
            old_bytes = path.read_bytes()
            if old_bytes == new_bytes:
                return False
        _atomic_write_bytes(path, new_bytes)
        return True
    finally:
        if tmp.exists():
            tmp.unlink()


@dataclass(frozen=True)
class CacheKey:
    source: str
    start: str
    end: str
    tickers_hash: str
    params_hash: str

    @property
    def id(self) -> str:
        return f"{self.source}_{self.start}_{self.end}_{self.tickers_hash[:12]}_{self.params_hash[:12]}"

    @property
    def short_hash(self) -> str:
        return _stable_hash(
            {
                "source": self.source,
                "start": self.start,
                "end": self.end,
                "tickers_hash": self.tickers_hash,
                "params_hash": self.params_hash,
            }
        )[:12]


class PriceCache:
    """Cache raw and normalized close-price panels as parquet."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def key(
        self,
        *,
        source: str,
        tickers: list[str],
        start: str,
        end: str,
        params: dict[str, Any] | None = None,
    ) -> CacheKey:
        clean_tickers = [str(t).strip() for t in tickers if str(t).strip()]
        tickers_hash = _stable_hash(clean_tickers)
        params_hash = _stable_hash(params or {})
        return CacheKey(
            source=str(source).strip().lower(),
            start=_canonical_start_end(start),
            end=_canonical_start_end(end),
            tickers_hash=tickers_hash,
            params_hash=params_hash,
        )

    def _raw_path(self, key: CacheKey) -> Path:
        return self.root / f"{key.id}_raw.parquet"

    def _norm_path(self, key: CacheKey) -> Path:
        return self.root / f"{key.id}_normalized.parquet"

    def has(self, key: CacheKey) -> bool:
        return self._raw_path(key).exists() and self._norm_path(key).exists()

    def load(self, key: CacheKey) -> tuple[pd.DataFrame, pd.DataFrame] | None:
        raw_path = self._raw_path(key)
        norm_path = self._norm_path(key)
        if not raw_path.exists() or not norm_path.exists():
            return None
        raw = pd.read_parquet(raw_path)
        norm = pd.read_parquet(norm_path)
        return raw, norm

    def store(
        self,
        key: CacheKey,
        *,
        raw: pd.DataFrame,
        normalized: pd.DataFrame,
    ) -> None:
        # Write both files atomically; callers should only invoke this after full success.
        write_parquet_if_changed(raw, self._raw_path(key), index=True)
        write_parquet_if_changed(normalized, self._norm_path(key), index=True)
