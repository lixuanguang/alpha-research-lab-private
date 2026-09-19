"""Inject disconnect and exact repeats into permitted saved Bitfinex frames using installed APIs."""

from __future__ import annotations

# standard library imports
import asyncio
import shutil
import sys
from pathlib import Path

# third party library imports
from msgspec.structs import replace

# project library imports
from alpha_research.data.book_datasets import BookCapture, BookInput
from alpha_research.data.live.config import CaptureConfig, CaptureRequest
from alpha_research.data.live.journal import CaptureJournal
from alpha_research.data.live.replay import CaptureReplay
from alpha_research.data.live.transport import FeedSocket, VenueTransport
from alpha_research.pipelines.live import InstalledIdentity, collect
from alpha_research.serialization import DomainCodec


class _Socket:
    """Retain a finite original frame sequence with an explicit injected disconnect."""

    def __init__(self, frames: tuple[bytes, ...]) -> None:
        """Bind immutable saved source frames."""
        self._frames = iter(frames)

    async def recv(self) -> bytes:
        """Yield one original message, then simulate transport loss."""
        await asyncio.sleep(0)
        raw = next(self._frames, None)
        if raw is None:
            raise OSError("injected disconnect after saved input")
        return raw

    async def send(self, message: str) -> None:
        """Accept the collector's native subscription without contacting the source."""

    async def close(self) -> None:
        """Close the finite fixture socket with no external resources."""


class _Transport(VenueTransport):
    """Replay original public bytes at the transport seam; local receipts are new observations."""

    def __init__(self, config: CaptureConfig, frames: tuple[bytes, ...]) -> None:
        """Bind two scripted sessions selected explicitly by the probe."""
        super().__init__(config)
        self._frames = frames

    async def open(self, timeout: float) -> FeedSocket:
        """Provide the next reset session of exact saved venue messages."""
        return _Socket(self._frames)


def main() -> None:
    """Run duplicate/reconnect and first-divergence examples without another venue connection."""
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    output.mkdir()
    snapshots = output / "snapshots"
    snapshots.mkdir()
    codec = DomainCodec()
    request = codec.decode_json((source / "request.json").read_bytes(), CaptureRequest)
    assert request.config.venue == "bitfinex"
    replay, frames = CaptureReplay(request.config), []
    for record in CaptureJournal(source, request).records():
        outcome = replay.apply(record)
        if record.kind == "frame":
            frames.append(record.raw)
        if outcome == "update":
            break
    assert outcome == "update", "saved input needs one synchronized update"
    frames.append(frames[-1])
    config = replace(request.config, max_messages=len(frames) * 2, retries=1)
    result = asyncio.run(
        collect(
            config,
            output / "captures",
            implementation_identity=InstalledIdentity.sha256(),
            transport=_Transport(config, tuple(frames)),
            snapshot_directory=snapshots,
            snapshot_records=32,
        )
    )
    assert result["canonical_parity"] and result["duplicates"] == 2 and result["epochs"] == 2
    assert result["gaps"] and result["synchronized"]
    # Corrupt only the experimental live-side receipt to prove first-event diagnosis.
    selected = BookInput.read(source, max_records=32)
    assert selected.capture is not None
    changed = BookCapture(selected.capture.config, 32)
    changed_root = output / "divergence"
    changed_root.mkdir()
    for name in ("request.json", "manifest.json", selected.raw.sha256):
        shutil.copyfile(source / name, changed_root / name)
    for index, record in enumerate(CaptureJournal(source, selected.capture).records()):
        changed.apply(replace(record, received_ns=record.received_ns + 1) if index == 0 else record)
    failure = ""
    try:
        changed.verify(changed_root)
    except ValueError as error:
        failure = str(error)
    assert "raw position 0" in failure
    assert (changed_root / "first-divergence.json").is_file()
    report = {
        "mode": "controlled saved-frame replay with new local receipts; no venue connection",
        "original_raw_identity": selected.raw.sha256,
        "capture": result,
        "divergence_refusal": failure,
        "first_divergence_retained": True,
    }
    (output / "result.json").write_bytes(codec.encode_json(report))
    print(codec.encode_json(report).decode())


if __name__ == "__main__":
    main()
