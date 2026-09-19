"""Publish and inspect a saved book prefix using installed APIs outside the checkout."""

from __future__ import annotations

# standard library imports
import json
import sys
from pathlib import Path
from unittest.mock import patch

# project library imports
import alpha_research
from alpha_research.data.book_datasets import BookDatasetManifest, BookHistory
from alpha_research.data.live.journal import CaptureRecord
from alpha_research.data.live.quality import ContinuousQuality
from alpha_research.data.raw_store import RawStore
from alpha_research.data.snapshots import SnapshotStore
from alpha_research.data.venues.okx.book import OKXBook
from alpha_research.pipelines.dataset import publish_book_dataset
from alpha_research.serialization import DomainCodec


def main() -> None:
    """Retain small publication, quality-transition and refusal outputs for the notebook."""
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    output.mkdir()
    raw, snapshots = output / "raw", output / "snapshots"
    raw.mkdir()
    snapshots.mkdir()
    codec = DomainCodec()
    identity = publish_book_dataset(
        (source,), RawStore(raw), snapshots, max_records=32, max_bytes=64_000_000
    )
    store = SnapshotStore(snapshots, RawStore(raw), manifest_type=BookDatasetManifest)
    manifest = store.read(identity, max_bytes=64_000_000)
    path = snapshots / identity / manifest.partitions[0].sha256
    history = codec.decode_json(path.read_bytes(), BookHistory)
    assert (
        publish_book_dataset(
            (source,), RawStore(raw), snapshots, max_records=32, max_bytes=64_000_000
        )
        == identity
    )
    failures: list[str] = []
    try:
        publish_book_dataset(
            (source,), RawStore(raw), snapshots, max_records=1, max_bytes=64_000_000
        )
    except ValueError as error:
        failures.append(str(error))
    with patch(
        "alpha_research.data.snapshots.os.rename", side_effect=OSError("publication interrupted")
    ):
        try:
            publish_book_dataset(
                (source,), RawStore(raw), snapshots, max_records=31, max_bytes=64_000_000
            )
        except OSError as error:
            failures.append(str(error))
    assert store.read(identity, max_bytes=64_000_000) == manifest
    assert [p.name for p in snapshots.iterdir()] == [identity]
    quality = ContinuousQuality("synthetic-book", lateness_ns=2, freshness_ns=5)
    transitions: list[dict[str, object]] = []
    for record, outcome, ready in (
        (CaptureRecord(kind="session", epoch=0, received_ns=1), "session", False),
        (CaptureRecord(kind="frame", epoch=0, received_ns=2), "snapshot", True),
        (CaptureRecord(kind="frame", epoch=0, received_ns=8), "heartbeat", True),
        (CaptureRecord(kind="gap", epoch=0, received_ns=9, reason="unknown_loss"), "gap", False),
        (CaptureRecord(kind="session", epoch=1, received_ns=10), "session", False),
        (CaptureRecord(kind="frame", epoch=1, received_ns=11), "snapshot", True),
        (CaptureRecord(kind="end", epoch=1, received_ns=12), "end", True),
    ):
        quality.observe(record, outcome, ready=ready)
        transitions.append(quality.summary())
        try:
            quality.require_usable(now_ns=record.received_ns)
        except ValueError as error:
            failures.append(str(error))
    assert len(failures) == 9
    lateness = ContinuousQuality("synthetic-late", lateness_ns=2, freshness_ns=10)
    late_rows: list[dict[str, object]] = []
    for receipt, source_ns, outcome in (
        (100, 90, "snapshot"),
        (101, 89, "update"),
        (102, 87, "update"),
    ):
        accepted = lateness.observe(
            CaptureRecord(kind="frame", epoch=0, received_ns=receipt),
            outcome,
            ready=True,
            source_ns=source_ns,
        )
        late_rows.append(
            {
                "receipt_ns": receipt,
                "source_ns": source_ns,
                "within_lateness": accepted,
                "status": lateness.status,
                "source_watermark_ns": lateness.source_watermark_ns,
            }
        )
    assert [row["within_lateness"] for row in late_rows] == [True, True, False]
    book = OKXBook("BTC-USDT")
    book.apply(b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}')
    book.apply(
        b'{"arg":{"channel":"books","instId":"BTC-USDT"},"action":"snapshot","data":[{"prevSeqId":-1,"seqId":1,"bids":[["100","2","0","1"]],"asks":[]}]}'
    )
    book.apply(
        b'{"arg":{"channel":"books","instId":"BTC-USDT"},"action":"update","data":[{"prevSeqId":1,"seqId":2,"bids":[["100","0","0","0"]],"asks":[]}]}'
    )
    assert book.bids == {}
    before = book.identity
    invalid_price = ""
    try:
        book.apply(
            b'{"arg":{"channel":"books","instId":"BTC-USDT"},"action":"update","data":[{"prevSeqId":2,"seqId":3,"bids":[["0","1","0","1"]],"asks":[]}]}'
        )
    except ValueError as error:
        invalid_price = str(error)
    assert invalid_price and book.identity == before
    summary = {
        "installed_package": str(Path(alpha_research.__file__).resolve()),
        "snapshot_identity": identity,
        "raw_identity": history.input.raw.sha256,
        "scope": manifest.scope,
        "observations": len(history.observations),
        "boundaries": [
            {
                "position": row.position,
                "epoch": row.epoch,
                "receipt_ns": row.received_ns,
                "outcome": row.outcome,
                "status": row.status,
                "orders": len(row.orders),
                "levels": len(row.bids) + len(row.asks),
                "sequence": row.sequence,
            }
            for row in history.observations[:8]
        ],
        "transitions": transitions,
        "refusals": failures,
        "lateness": late_rows,
        "depth_rules": {
            "zero_quantity_remaining_levels": len(book.bids),
            "zero_price_refusal": invalid_price,
            "failed_message_preserved_state": book.identity == before,
        },
    }
    (output / "result.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
