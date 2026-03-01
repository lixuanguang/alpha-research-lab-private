"""Bronze-tier raw payload writer."""

from __future__ import annotations

import gzip
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

_PARTITION_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_FILE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class BronzeWriter:
    """Writes raw venue payloads to bronze tier as compressed JSONL."""

    def __init__(self, storage_root: Path, compression: str = "gzip") -> None:
        if compression != "gzip":
            raise ValueError("Only `gzip` compression is currently supported")
        self._storage_root = storage_root

    def write_raw_events(
        self,
        events: list[dict[str, Any]],
        *,
        venue: str,
        event_type: str,
        run_id: str,
    ) -> Path:
        """Write raw payloads to bronze/{event_type}/venue={venue}/date={date}/run_{id}.jsonl.gz."""
        normalized_venue = _normalize_partition_value(venue, field_name="venue")
        normalized_event_type = _normalize_partition_value(event_type, field_name="event_type")
        safe_run_id = _normalize_file_token(run_id, field_name="run_id")
        now = datetime.now(tz=UTC)
        date_str = now.date().isoformat()

        output_dir = (
            self._storage_root
            / "bronze"
            / normalized_event_type
            / f"venue={normalized_venue}"
            / f"date={date_str}"
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / f"run_{safe_run_id}.jsonl.gz"
        with gzip.open(output_path, mode="at", encoding="utf-8") as handle:
            for payload in events:
                row = {
                    "run_id": safe_run_id,
                    "venue": normalized_venue,
                    "event_type": normalized_event_type,
                    "ts_record": now.isoformat(),
                    "payload": payload,
                }
                handle.write(_json_dumps(row))
                handle.write("\n")

        return output_path

    def write_market_snapshot(
        self,
        markets: list[dict[str, Any]],
        *,
        venue: str,
        run_id: str,
    ) -> Path:
        """Write raw market metadata snapshot to bronze/metadata/."""
        normalized_venue = _normalize_partition_value(venue, field_name="venue")
        safe_run_id = _normalize_file_token(run_id, field_name="run_id")
        now = datetime.now(tz=UTC)
        date_str = now.date().isoformat()

        output_dir = (
            self._storage_root
            / "bronze"
            / "metadata"
            / f"venue={normalized_venue}"
            / f"date={date_str}"
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        ts_token = now.strftime("%Y%m%dT%H%M%SZ")
        output_path = output_dir / f"markets_snapshot_{ts_token}_run_{safe_run_id}.json.gz"
        with gzip.open(output_path, mode="wt", encoding="utf-8") as handle:
            handle.write(
                _json_dumps(
                    {
                        "run_id": safe_run_id,
                        "venue": normalized_venue,
                        "ts_record": now.isoformat(),
                        "markets": markets,
                    }
                )
            )

        return output_path


def _normalize_partition_value(value: str, *, field_name: str) -> str:
    cleaned = value.strip().lower()
    if not cleaned:
        raise ValueError(f"`{field_name}` must be non-empty")
    if _PARTITION_TOKEN_RE.fullmatch(cleaned) is None:
        raise ValueError(
            f"`{field_name}` contains unsupported characters; use [a-z0-9._-] without spaces"
        )
    return cleaned


def _normalize_file_token(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"`{field_name}` must be non-empty")
    if _FILE_TOKEN_RE.fullmatch(cleaned) is None:
        raise ValueError(
            f"`{field_name}` contains unsupported characters; use [A-Za-z0-9._-] without spaces"
        )
    return cleaned


def _json_dumps(value: object) -> str:
    return json.dumps(value, default=_json_default, separators=(",", ":"), sort_keys=True)


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


__all__ = ["BronzeWriter"]
