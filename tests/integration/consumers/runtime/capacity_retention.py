"""Check a 2b day's native retention once its declared retention period has elapsed.

Run this from the attempt's frozen consumers with the installed research interpreter,
at least 72 hours after the day ended. Every source recording is replayed again from
its retained records and must equal its source's retained live summary; occupied
space is reported against the profile's ceilings, and the monitoring store's event
count is projected to its seven-day window.
"""

from __future__ import annotations

# standard library imports
import argparse
import sqlite3
import sys
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar, cast

# third party library imports
import msgspec

# project library imports
from market_data.adapters.sources import BookAdapters
from market_data.books import CaptureReplay
from market_data.storage import CaptureRecording
from serialization import DomainCodec

_GIB = 1024**3


class _Arguments(argparse.Namespace):
    """Carry the attempt's day directory, output and the declared retention period."""

    day: Path
    output: Path
    hours: int


class DayRetention:
    """Re-verify every retained recording of one day and report its occupied space."""

    # The profile's provisional occupied-space ceilings, in bytes.
    ceilings: ClassVar[dict[str, int]] = {
        "raw_capture": 160 * _GIB,
        "canonical": 120 * _GIB,
        "features_telemetry": 32 * _GIB,
        "scratch": 8 * _GIB,
    }
    telemetry_events_ceiling: ClassVar[int] = 8_000_000

    def __init__(self, day: Path, hours: int) -> None:
        """Bind a completed day directory and the retention period it must have aged."""
        if not day.is_absolute() or not (day / "summary.json").is_file():
            raise ValueError("retention requires an absolute completed day directory")
        self.day, self.hours = day, hours
        self.codec = DomainCodec()

    def aged(self) -> dict[str, object]:
        """Report how long ago the day's summary was retained."""
        ended = datetime.fromtimestamp((self.day / "summary.json").stat().st_mtime, UTC)
        elapsed = datetime.now(UTC) - ended
        return {
            "ended_at": ended,
            "elapsed_hours": elapsed / timedelta(hours=1),
            "required_hours": self.hours,
            "status": "pass" if elapsed >= timedelta(hours=self.hours) else "fail",
        }

    def recordings(self) -> dict[str, object]:
        """Replay every recording and compare it with its retained live summary."""
        results: dict[str, object] = {}
        for run in sorted(
            path for path in (self.day / "operating/runs").iterdir() if path.is_dir()
        ):
            for source in sorted(path for path in run.iterdir() if path.is_dir()):
                for recording in CaptureRecording.discover(source):
                    results[f"{source.name}/{recording.key}"] = self._replay(recording)
        return results

    def _replay(self, recording: CaptureRecording) -> dict[str, object]:
        """Replay one recording and compare each retained summary field it reproduces."""
        started = time.monotonic()
        summary_path = recording.root.parent / "source-result.json"
        if not recording.completed or not summary_path.is_file():
            return {"status": "fail", "reason": "recording incomplete or summary missing"}
        retained = msgspec.json.decode(summary_path.read_bytes(), type=dict[str, msgspec.Raw])
        replay = CaptureReplay(recording.request.config, book_factory=BookAdapters.create)
        records = 0
        for record in recording.records(completed=True):
            replay.apply(record)
            records += 1
        differing = sorted(
            key
            for key, value in replay.summary().items()
            if key in retained and retained[key] != msgspec.Raw(self.codec.encode_json(value))
        )
        compared = sum(1 for key in replay.summary() if key in retained)
        return {
            "status": "pass" if compared and not differing else "fail",
            "records": records,
            "segments": len(recording.cursor().segments),
            "compared_fields": compared,
            "differing_fields": differing,
            "seconds": time.monotonic() - started,
        }

    def occupied(self) -> dict[str, object]:
        """Classify every retained file of the day and grade each class's ceiling."""
        classes = dict.fromkeys(self.ceilings, 0)
        for path in self.day.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            classes[self._class(path.relative_to(self.day))] += path.stat().st_blocks * 512
        return {
            "occupied_bytes": classes,
            "ceilings": self.ceilings,
            "status": "pass"
            if all(classes[name] <= ceiling for name, ceiling in self.ceilings.items())
            else "fail",
        }

    @staticmethod
    def _class(relative: Path) -> str:
        """Name a retained file's occupied-space class from its place in the day."""
        parts = relative.parts
        if parts[:2] == ("operating", "runs") and len(parts) >= 6:
            return "raw_capture"
        if parts[:2] == ("operating", "runs") or relative.name.startswith("final-"):
            return "canonical"
        if parts[0] in ("reads", "measurements") or "monitoring" in parts:
            return "features_telemetry"
        return "scratch"

    def telemetry(self) -> dict[str, object]:
        """Count the monitoring store's events and project them to its seven-day window."""
        stores = tuple(self.day.rglob("monitoring/telemetry.sqlite3"))
        events = 0
        for store in stores:
            with closing(sqlite3.connect(f"file:{store}?mode=ro", uri=True)) as connection:
                row = cast(tuple[int], connection.execute("SELECT count(*) FROM events").fetchone())
                events += row[0]
        projected = events * 7
        return {
            "stores": [str(path) for path in stores],
            "events": events,
            "projected_seven_day_events": projected,
            "ceiling": self.telemetry_events_ceiling,
            "status": "pass" if stores and projected <= self.telemetry_events_ceiling else "fail",
        }

    def write(self, output: Path) -> dict[str, object]:
        """Retain every check; the attempt's retention passes only if all of them pass."""
        aged, recordings = self.aged(), self.recordings()
        occupied, telemetry = self.occupied(), self.telemetry()
        passed = (
            aged["status"] == "pass"
            and bool(recordings)
            and all(
                cast(dict[str, object], item).get("status") == "pass"
                for item in recordings.values()
            )
            and occupied["status"] == "pass"
            and telemetry["status"] == "pass"
        )
        report: dict[str, object] = {
            "schema_version": "runtime-capacity-day-retention",
            "day": str(self.day),
            "aged": aged,
            "recordings": recordings,
            "occupied": occupied,
            "telemetry": telemetry,
            "passed": passed,
        }
        output.write_bytes(self.codec.encode_json(report))
        return report


def main() -> None:
    """Check one day's retention into a fresh output file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hours", type=int, default=72)
    args = parser.parse_args(namespace=_Arguments())
    if args.output.exists():
        raise SystemExit("retention output already exists")
    report = DayRetention(args.day, args.hours).write(args.output)
    print(f"retention {'passed' if report['passed'] else 'failed'}: {args.output}")
    if report["passed"] is not True:
        sys.exit(1)


if __name__ == "__main__":
    main()
