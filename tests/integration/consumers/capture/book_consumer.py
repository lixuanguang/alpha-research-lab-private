"""Publish and inspect a saved book prefix using installed APIs outside the checkout."""

from __future__ import annotations

# standard library imports
import json
import sys
from pathlib import Path
from unittest.mock import patch

# project library imports
import market_data
from market_data.adapters.sources import SourceAdapters
from market_data.adapters.venues.okx import OKXBook
from market_data.contracts import CaptureRecord
from market_data.datasets import (
    BookDatasetManifest,
    BookSnapshot,
    DatasetPublication,
    SnapshotStore,
)
from market_data.storage import RawStore
from market_data.validation import ContinuousQuality
from runtime import ImplementationIdentity


def main() -> None:
    """Retain small publication, quality-transition and refusal outputs for the notebook."""
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    output.mkdir()
    raw, snapshots = output / "raw", output / "snapshots"
    raw.mkdir()
    snapshots.mkdir()
    identity = (
        DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256())
        .publish_captures((source,), RawStore(raw), snapshots, max_records=32, max_bytes=64_000_000)
        .book
    )
    store = SnapshotStore(
        snapshots, RawStore(raw), readers=SourceAdapters(), manifest_type=BookDatasetManifest
    )
    manifest = store.read(identity, max_bytes=64_000_000)
    snapshot = BookSnapshot.read(
        snapshots,
        RawStore(raw),
        readers=SourceAdapters(),
        identity=identity,
        max_bytes=64_000_000,
    )
    selected = manifest.partitions[0].selection
    observations = tuple(snapshot.observations(selected.request.identity))
    assert (
        DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256())
        .publish_captures((source,), RawStore(raw), snapshots, max_records=32, max_bytes=64_000_000)
        .book
        == identity
    )
    failures: list[str] = []
    try:
        DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).publish_captures(
            (source,), RawStore(raw), snapshots, max_records=1, max_bytes=64_000_000
        ).book
    except ValueError as error:
        failures.append(str(error))
    with patch(
        "market_data.datasets.snapshots.os.rename", side_effect=OSError("publication interrupted")
    ):
        try:
            DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).publish_captures(
                (source,), RawStore(raw), snapshots, max_records=31, max_bytes=64_000_000
            ).book
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
        "installed_package": str(Path(market_data.__file__).resolve()),
        "snapshot_identity": identity,
        "raw_identity": selected.raw.sha256,
        "scope": manifest.scope,
        "observations": len(observations),
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
            for row in observations[:8]
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
