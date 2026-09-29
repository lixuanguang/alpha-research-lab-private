"""Qualify bounded adverse native capture cases without paper account authority.

Run this copied consumer with the installed runtime interpreter. Each invocation
selects one adverse mode and captures all four prepared sources concurrently.
Its evidence is source-component evidence, not a loaded four-owner result.
"""

from __future__ import annotations

# standard library imports
import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

# third party library imports
import msgspec
from capacity_inputs import CapacityNativeFixture, CapacityVariant, CapacityWorkload

# project library imports
from configuration import PaperServiceConfiguration, PaperServiceSource
from market_data.adapters.sources import BookAdapters
from market_data.adapters.transport import VenueSubscriptions
from market_data.collection import CaptureRunner, CaptureRunResult
from market_data.contracts import CaptureCursor, CaptureRequest, RawObject
from market_data.replay import SavedCapture
from runtime import InstalledIdentity
from serialization import DomainCodec
from telemetry import RuntimeMeasurementJournal


class _Measurement(msgspec.Struct, frozen=True, kw_only=True):
    """Read only bounded queue and receipt fields from retained measurement rows."""

    kind: str
    pending_records: int | None = None
    queued_bytes: int | None = None
    oldest_age_ns: int | None = None
    receipt_to_durable_ns: int | None = None
    raw_bytes: int | None = None


class CapacitySourceCases:
    """Run one declared adverse mode through installed native capture adapters."""

    case_seconds: ClassVar[dict[str, int]] = {
        "quiet": 35,
        "oversize": 25,
        "backpressure": 25,
        "reconnect": 55,
    }
    expected_gap: ClassVar[dict[str, str]] = {
        "quiet": "idle_timeout",
        "oversize": "frame_limit_unknown_loss",
        "backpressure": "overload_unknown_loss",
        "reconnect": "disconnect_unknown_loss",
    }

    def __init__(self, preparation: Path, output: Path, case: CapacityVariant) -> None:
        """Require exact predeclared four-source identity and a new absolute output."""
        if (
            not preparation.is_absolute()
            or not output.is_absolute()
            or case not in self.case_seconds
        ):
            raise ValueError("source case needs absolute paths and a declared adverse mode")
        self.preparation, self.output, self.case = preparation, output, case
        self.codec = DomainCodec()
        self.service = self.codec.decode_json(
            (preparation / "services-initial.json").read_bytes(), PaperServiceConfiguration
        )
        if len(self.service.sources) != 4 or len(self.service.accounts) != 4:
            raise ValueError("source case requires the prepared MR15 topology")
        workload = CapacityWorkload(
            opening_at=self.service.accounts[0].configuration.opening_at,
            socket_root=Path(self.service.accounts[0].socket_path).parent,
        )
        if self.service != workload.service_configuration():
            raise ValueError("source case differs from the prepared MR15 service input")
        self.implementation = InstalledIdentity.sha256()

    def _request(self, source: PaperServiceSource) -> CaptureRequest:
        """Reduce lifetime only; retain every original capture resource ceiling."""
        config = msgspec.structs.replace(
            source.capture, duration_seconds=self.case_seconds[self.case]
        )
        if (
            config.max_messages,
            config.max_bytes,
            config.max_frame_bytes,
            config.queue_capacity,
            config.max_orders,
            config.retries,
            config.idle_seconds,
        ) != (
            source.capture.max_messages,
            source.capture.max_bytes,
            source.capture.max_frame_bytes,
            source.capture.queue_capacity,
            source.capture.max_orders,
            source.capture.retries,
            source.capture.idle_seconds,
        ):
            raise AssertionError("source case revised an unchanged capture ceiling")
        request = CaptureRequest(
            config=config,
            recording_id=str(uuid4()),
            implementation_identity=self.implementation,
        )
        request.__post_init__()
        return request

    def _measurements(self, path: Path) -> dict[str, int]:
        """Summarize complete retained samples without percentile claims below 1,000."""
        values = {
            "queue_peak_records": 0,
            "queue_peak_bytes": 0,
            "queue_oldest_age_ns": 0,
            "receipt_to_durable_max_ns": 0,
            "receipt_to_durable_samples": 0,
            "largest_admitted_frame_bytes": 0,
        }
        if not path.exists():
            return values
        with path.open("rb") as stream:
            for line in stream:
                row = self.codec.decode_json(line, _Measurement)
                if row.kind == "queue":
                    values["queue_peak_records"] = max(
                        values["queue_peak_records"], row.pending_records or 0
                    )
                    values["queue_peak_bytes"] = max(
                        values["queue_peak_bytes"], row.queued_bytes or 0
                    )
                    values["queue_oldest_age_ns"] = max(
                        values["queue_oldest_age_ns"], row.oldest_age_ns or 0
                    )
                elif row.kind == "capture_boundary" and row.receipt_to_durable_ns is not None:
                    values["receipt_to_durable_samples"] += 1
                    values["receipt_to_durable_max_ns"] = max(
                        values["receipt_to_durable_max_ns"], row.receipt_to_durable_ns
                    )
                    values["largest_admitted_frame_bytes"] = max(
                        values["largest_admitted_frame_bytes"], row.raw_bytes or 0
                    )
        return values

    async def _capture(
        self, source: PaperServiceSource, request: CaptureRequest
    ) -> dict[str, object]:
        """Retain one source's completed or interrupted raw journal and stop reason."""
        capture_root = self.output / "captures" / source.name / request.recording_id
        measurement_path = self.output / "measurements" / f"{source.name}.jsonl"
        fixture = CapacityNativeFixture(
            source,
            variant=self.case,
            epoch_path=self.output / "fixture-epochs" / f"{source.name}.epoch",
        )
        result: CaptureRunResult | None = None
        failure: dict[str, str] | None = None
        started = time.monotonic()
        try:
            with RuntimeMeasurementJournal(measurement_path) as measurements:
                runner = CaptureRunner(
                    book_factory=BookAdapters.create,
                    transport=fixture,
                    subscriptions=VenueSubscriptions(),
                    measurements=measurements,
                )
                result = await asyncio.wait_for(
                    runner.run(request, self.output / "captures" / source.name), timeout=100
                )
        except Exception as error:
            failure = {"type": type(error).__name__, "reason": str(error)}
            (self.output / f"failure-{source.name}.json").write_bytes(
                self.codec.encode_json(failure)
            )
        elapsed = time.monotonic() - started
        cursor_path = capture_root / "cursor.json"
        manifest_path = capture_root / "manifest.json"
        cursor = (
            self.codec.decode_json(cursor_path.read_bytes(), CaptureCursor)
            if cursor_path.exists()
            else None
        )
        manifest = (
            self.codec.decode_json(manifest_path.read_bytes(), RawObject)
            if manifest_path.exists()
            else None
        )
        replay_summary: dict[str, object] | None = None
        replay_failure: str | None = None
        reasons: tuple[str, ...] = ()
        if (capture_root / "request.json").exists():
            try:
                replay = SavedCapture.read(
                    capture_root,
                    book_factory=BookAdapters.create,
                    completed=manifest is not None,
                )
                replay_summary = replay.summary()
                reasons = tuple(str(gap["reason"]) for gap in replay.gaps)
            except Exception as error:
                replay_failure = f"{type(error).__name__}: {error}"
        measurement_summary = self._measurements(measurement_path)
        native_parity = bool(
            result is not None
            and replay_summary is not None
            and result.summary.get("replay_parity") is True
            and all(result.summary.get(key) == value for key, value in replay_summary.items())
        )
        qualified = bool(
            failure is None
            and replay_failure is None
            and elapsed <= 100
            and manifest is not None
            and cursor is not None
            and cursor.request_identity == request.identity
            and cursor.offset <= request.config.max_bytes
            and measurement_summary["queue_peak_records"] <= request.config.queue_capacity
            and native_parity
            and self.expected_gap[self.case] in reasons
        )
        return {
            "source": source.name,
            "request_identity": request.identity,
            "fixture_identity": fixture.identity,
            "capture_directory": str(capture_root),
            "elapsed_seconds": elapsed,
            "cursor": cursor,
            "manifest": manifest,
            "stop_reason": None if result is None else result.summary.get("stop_reason"),
            "observed_gap_reasons": reasons,
            "native_replay_parity": native_parity,
            "replay": replay_summary,
            "measurements": measurement_summary,
            "measurement_path": str(measurement_path),
            "failure": failure,
            "replay_failure": replay_failure,
            "qualified": qualified,
        }

    async def run(self) -> dict[str, object]:
        """Run four source components concurrently and retain every partial outcome."""
        self.output.mkdir(parents=True, exist_ok=False)
        requests = tuple((source, self._request(source)) for source in self.service.sources)
        plan = {
            "schema_version": "runtime-capacity-source-case",
            "evidence_class": "source_component_only_no_account_or_four_owner_load_claim",
            "case": self.case,
            "declared_duration_seconds": self.case_seconds[self.case],
            "implementation_identity": self.implementation,
            "python": sys.executable,
            "prepared_service_identity": self.service.identity,
            "selected_at": datetime.now(UTC),
            "sources": tuple(
                {
                    "name": source.name,
                    "request": request,
                    "request_identity": request.identity,
                    "fixture_identity": CapacityNativeFixture(source, variant=self.case).identity,
                    "base_authored_distribution": CapacityNativeFixture(
                        source
                    ).authored_distribution(),
                    "adverse_slot": (
                        CapacityNativeFixture.reconnect_slot
                        if self.case == "reconnect"
                        else CapacityNativeFixture.adverse_slot
                    ),
                }
                for source, request in requests
            ),
        }
        (self.output / "case-plan.json").write_bytes(self.codec.encode_json(plan))
        results = await asyncio.gather(
            *(self._capture(source, request) for source, request in requests)
        )
        report = {
            "schema_version": "runtime-capacity-source-case-result",
            "evidence_class": "source_component_only_no_account_or_four_owner_load_claim",
            "case": self.case,
            "plan": str(self.output / "case-plan.json"),
            "sources": tuple(results),
            "qualified": all(result["qualified"] is True for result in results),
        }
        (self.output / "result.json").write_bytes(self.codec.encode_json(report))
        return report


class _Arguments(argparse.Namespace):
    """Carry typed absolute source-case CLI paths and selected adverse mode."""

    preparation: Path
    output: Path
    case: CapacityVariant


def main() -> None:
    """Run one installed-runtime adverse case with a fresh evidence directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--case", choices=("quiet", "oversize", "backpressure", "reconnect"), required=True
    )
    args = parser.parse_args(namespace=_Arguments())
    report = asyncio.run(CapacitySourceCases(args.preparation, args.output, args.case).run())
    print(DomainCodec().encode_json(report).decode())
    if report["qualified"] is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
