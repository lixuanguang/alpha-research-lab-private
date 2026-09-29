"""Check captured Coinbase level3 REST snapshots against their stream bridge by sequence and time.

The adapter seeds its monotonic source clock from the REST snapshot's ``time`` and
then refuses any bridged update whose ``time`` is earlier. Coinbase documents
bridging by sequence only, so this consumer measures, on retained captures, whether
updates after the snapshot sequence can carry an earlier source time. It reads
existing capture journals only; it never contacts the venue or changes the adapter.
"""

from __future__ import annotations

# standard library imports
import argparse
from pathlib import Path
from typing import NamedTuple

# project library imports
from market_data.adapters.sources import BookAdapters
from market_data.adapters.wire import Wire
from market_data.contracts import CaptureRecord, CaptureRequest
from market_data.storage import CaptureJournal
from serialization import DomainCodec


class _Arguments(argparse.Namespace):
    """Select explicit captures, search roots and a fresh result path."""

    capture: list[Path] | None
    search: list[Path] | None
    output: Path


class _Update(NamedTuple):
    """Keep one level3 lifecycle message's sequence, source time and receipt side."""

    sequence: int
    time: str | None
    is_buffered: bool


class CoinbaseBridgeConformance:
    """Find retained Coinbase level3 captures and examine each snapshot and its bridge."""

    _max_request_bytes = 1_048_576

    def __init__(self) -> None:
        """Bind the strict codec used for capture requests and results."""
        self._codec = DomainCodec()

    def discover(
        self, roots: list[Path]
    ) -> tuple[tuple[tuple[Path, CaptureRequest], ...], dict[str, int]]:
        """Return Coinbase level3 capture journals and a count of every capture seen.

        Args:
            roots: Directories searched recursively for capture ``request.json`` files.

        Returns:
            Coinbase level3 journals with their requests, and capture counts by
            venue and channel.
        """
        found: list[tuple[Path, CaptureRequest]] = []
        venues: dict[str, int] = {}
        for root in roots:
            for path in sorted(root.rglob("request.json")):
                request = self._request(path)
                if request is None:
                    continue
                venue = f"{request.config.venue}:{request.config.channel}"
                venues[venue] = venues.get(venue, 0) + 1
                if self._is_coinbase_level3(request):
                    found.append((path.parent, request))
        return tuple(found), venues

    def request(self, root: Path) -> CaptureRequest:
        """Read one explicitly selected capture journal's request.

        Args:
            root: Capture journal directory.

        Returns:
            The journal's validated Coinbase level3 capture request.

        Raises:
            ValueError: The directory is not a Coinbase level3 capture.
        """
        request = self._request(root / "request.json")
        if request is None or not self._is_coinbase_level3(request):
            raise ValueError(f"{root} is not a Coinbase level3 capture")
        return request

    def examine(self, root: Path, request: CaptureRequest) -> list[dict[str, object]]:
        """Examine every REST snapshot retained by one capture, epoch by epoch.

        Args:
            root: Capture journal directory; an unsealed journal is read to its
                durable prefix.
            request: The journal's capture request.

        Returns:
            One finding per snapshot, in receipt order.
        """
        is_completed = (root / "manifest.json").is_file()
        epochs: dict[int, list[CaptureRecord]] = {}
        for record in CaptureJournal(root, request).records(completed=is_completed):
            epochs.setdefault(record.epoch, []).append(record)
        findings: list[dict[str, object]] = []
        for epoch, records in sorted(epochs.items()):
            snapshots = [p for p, record in enumerate(records) if record.kind == "snapshot"]
            for index, position in enumerate(snapshots):
                finding: dict[str, object] = {
                    "capture": str(root),
                    "recording_id": request.recording_id,
                    "is_completed_capture": is_completed,
                    "epoch": epoch,
                    "snapshot_index": index,
                }
                try:
                    finding.update(self._pair(request, records, position))
                except ValueError as error:
                    finding["error"] = str(error)
                findings.append(finding)
        return findings

    @staticmethod
    def summary(
        findings: list[dict[str, object]], captures: int, venues: dict[str, int]
    ) -> dict[str, object]:
        """Summarize pair findings, or say plainly that no pair was available.

        Args:
            findings: Every examined snapshot.
            captures: Number of Coinbase level3 capture journals examined.
            venues: Capture counts by venue and channel across the searched roots.

        Returns:
            Totals and a conclusion limited to what the examined pairs show.
        """
        pairs = [f for f in findings if "error" not in f and not f["is_stale_snapshot"]]
        conflicts = [f for f in pairs if f["bridged_before_snapshot_time"]]
        refused = [f for f in pairs if f["adapter_refusal"] == "source_time"]
        rescued = [f for f in refused if f["is_sequence_only_bridgeable"]]
        if not pairs:
            conclusion = (
                "no Coinbase snapshot/bridge pairs are available; whether a bridged update "
                "can carry a source time earlier than its snapshot remains unverified"
            )
        elif not conflicts:
            conclusion = (
                "no bridged update carried a source time earlier than its snapshot; "
                "the adapter's time check did not conflict with sequence bridging here"
            )
        else:
            conclusion = (
                f"{len(conflicts)} pair(s) bridged an update timed before its snapshot; "
                f"the adapter refused {len(refused)} on source time, and {len(rescued)} "
                "of those bridge by sequence alone"
            )
        return {
            "captures_by_venue": venues,
            "coinbase_level3_captures": captures,
            "snapshots_examined": len(findings),
            "unreadable_snapshots": sum("error" in f for f in findings),
            "stale_snapshots": sum(f.get("is_stale_snapshot") is True for f in findings),
            "pairs_available": len(pairs),
            "pairs_with_bridged_update_before_snapshot_time": len(conflicts),
            "pairs_refused_by_adapter_on_source_time": len(refused),
            "refused_pairs_bridgeable_by_sequence_only": len(rescued),
            "conclusion": conclusion,
        }

    def _request(self, path: Path) -> CaptureRequest | None:
        """Decode a capture request, or return None for any other request file."""
        with path.open("rb") as source:
            payload = source.read(self._max_request_bytes + 1)
        if len(payload) > self._max_request_bytes:
            return None
        try:
            return self._codec.decode_json(payload, CaptureRequest)
        except ValueError:
            return None

    @staticmethod
    def _is_coinbase_level3(request: CaptureRequest) -> bool:
        """Select captures of the native Coinbase level3 order stream."""
        return request.config.venue == "coinbase" and request.config.channel == "level3"

    def _pair(
        self, request: CaptureRequest, records: list[CaptureRecord], position: int
    ) -> dict[str, object]:
        """Measure one snapshot against the level3 messages received around it."""
        snapshot = records[position]
        fields = Wire.mapping(Wire.decode(snapshot.raw))
        snapshot_sequence = Wire.integer(fields.get("sequence"))
        snapshot_time = Wire.source_time(fields.get("time"))
        # A response that arrives after its session ended is never applied.
        is_stale = any(r.kind in ("session_end", "end") for r in records[:position])
        updates = self._updates(records, position)
        bridge = [update for update in updates if update.sequence > snapshot_sequence]
        contiguous: list[_Update] = []
        for update in bridge:
            if update.sequence != snapshot_sequence + len(contiguous) + 1:
                break
            contiguous.append(update)
        leads: list[tuple[_Update, int]] = []
        if snapshot_time is not None:
            snapshot_ns = Wire.source_nanoseconds(snapshot_time)
            leads = [
                (update, snapshot_ns - Wire.source_nanoseconds(update.time))
                for update in contiguous
                if update.time is not None and Wire.source_nanoseconds(update.time) < snapshot_ns
            ]
        known = [Wire.source_nanoseconds(u.time) for u in contiguous if u.time is not None]
        refusal, message = (
            ("stale_snapshot", None)
            if is_stale
            else self._adapter_refusal(request, records, position)
        )
        return {
            "is_stale_snapshot": is_stale,
            "snapshot_sequence": snapshot_sequence,
            "snapshot_time": snapshot_time,
            "snapshot_received_ns": snapshot.received_ns,
            "buffered_updates": sum(update.is_buffered for update in updates),
            "covered_updates": sum(u.sequence <= snapshot_sequence for u in updates),
            "first_bridge_sequence": bridge[0].sequence if bridge else None,
            "contiguous_bridge_updates": len(contiguous),
            "bridged_before_snapshot_time": len(leads),
            "buffered_before_snapshot_time": sum(update.is_buffered for update, _ in leads),
            "largest_lead_before_snapshot_ns": max((lead for _, lead in leads), default=0),
            "adapter_refusal": refusal,
            "adapter_message": message,
            # The adapter's own check without seeding its clock from the snapshot time.
            "is_sequence_only_bridgeable": bool(contiguous) and known == sorted(known),
        }

    @staticmethod
    def _updates(records: list[CaptureRecord], snapshot_position: int) -> list[_Update]:
        """Decode the epoch's level3 lifecycle frames with the schema the stream announced."""
        schema: dict[str, list[str]] = {}
        updates: list[_Update] = []
        for position, record in enumerate(records):
            if record.kind != "frame":
                continue
            value = Wire.decode(record.raw)
            if isinstance(value, dict):
                message = Wire.mapping(value)
                if message.get("type") == "level3" and not schema:
                    schema = {
                        kind: [Wire.text(field) for field in Wire.array(names)]
                        for kind, names in Wire.mapping(message.get("schema")).items()
                    }
                continue
            values = Wire.array(value)
            fields = schema.get(Wire.text(values[0])) if values else None
            if fields is None or len(fields) != len(values):
                raise ValueError(f"level3 frame at receipt {record.received_ns} has no schema")
            decoded = dict(zip(fields, values, strict=True))
            updates.append(
                _Update(
                    sequence=Wire.integer(decoded.get("sequence")),
                    time=Wire.source_time(decoded.get("time")),
                    is_buffered=position < snapshot_position,
                )
            )
        return updates

    @staticmethod
    def _adapter_refusal(
        request: CaptureRequest, records: list[CaptureRecord], snapshot_position: int
    ) -> tuple[str, str | None]:
        """Apply the epoch to a fresh adapter book until it bridges, as capture replay does."""
        book = BookAdapters.create(request.config)
        for position, record in enumerate(records):
            if record.kind not in ("frame", "snapshot"):
                continue
            try:
                book.apply(record.raw, snapshot=record.kind == "snapshot")
            except ValueError as error:
                message = str(error)
                reason = "source_time" if "source time moved backwards" in message else "other"
                return reason, message
            if position >= snapshot_position and book.ready:
                return "none", None
        return "not_synchronized", None


def main() -> None:
    """Examine selected or discovered captures and retain one JSON conformance result."""
    parser = argparse.ArgumentParser(description="Coinbase snapshot/bridge conformance")
    parser.add_argument("--capture", type=Path, action="append")
    parser.add_argument("--search", type=Path, action="append")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(namespace=_Arguments())
    if arguments.output.exists():
        raise SystemExit("conformance output must be a new path")
    searched, explicit = arguments.search or [], arguments.capture or []
    harness = CoinbaseBridgeConformance()
    discovered, venues = harness.discover(searched)
    selected = [(root, harness.request(root)) for root in explicit]
    captures = {root.resolve(): request for root, request in (*discovered, *selected)}
    findings = [
        finding
        for root, request in sorted(captures.items())
        for finding in harness.examine(root, request)
    ]
    result = {
        "searched": [str(root) for root in searched],
        "selected": [str(root) for root in explicit],
        "summary": CoinbaseBridgeConformance.summary(findings, len(captures), venues),
        "pairs": findings,
    }
    payload = DomainCodec().encode_json(result)
    arguments.output.write_bytes(payload + b"\n")
    print(payload.decode())


if __name__ == "__main__":
    main()
