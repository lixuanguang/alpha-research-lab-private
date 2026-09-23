"""Reopen public trades, native books and non-book reference inputs through installed APIs."""

from __future__ import annotations

# standard library imports
import argparse
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# project library imports
from applications.explore import inspect_eda
from market_data.acquisition import PublicAcquisition
from market_data.adapters.sources import SourceAdapters
from market_data.datasets import (
    BookDatasetManifest,
    DatasetPublication,
    PublicTradeManifest,
    SnapshotCatalog,
)
from market_data.query import BookQuery, PublicTradeQuery, PublicTradeReader
from market_data.storage import RawStore
from research.exploration import (
    BookSelection,
    PublicTradeSelection,
    ReferenceSelection,
    ResearchSelection,
)
from runtime import ImplementationIdentity
from serialization import DomainCodec


class _Arguments(argparse.Namespace):
    """Select retained inputs and a fresh output root without source acquisition."""

    acquisition: Path
    raw: Path
    output: Path
    books: list[Path]


class _Reports:
    """Retain the ordinary application report in the reference workflow's output."""

    def __init__(self, path: Path) -> None:
        """Bind one exclusively owned JSON-lines report path."""
        self.path = path

    def write(self, record: dict[str, object]) -> None:
        """Append one explicit application attempt record without rewriting its claims."""
        with self.path.open("ab") as output:
            output.write(DomainCodec().encode_json(record) + b"\n")


def main() -> None:
    """Publish saved inputs, discover IDs, pin selection, inspect causality and replay restart."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--books", type=Path, nargs="*", default=list[Path]())
    args = parser.parse_args(namespace=_Arguments())
    args.output.mkdir(exist_ok=False)
    snapshots = args.output / "snapshots"
    snapshots.mkdir()
    codec, readers, raw = DomainCodec(), SourceAdapters(), RawStore(args.raw)
    acquisition = codec.decode_json(args.acquisition.read_bytes(), PublicAcquisition)
    command = [
        sys.executable,
        "-I",
        "-c",
        "from applications.publish_dataset import main; raise SystemExit(main())",
    ]
    published = subprocess.run(
        [
            *command,
            "public-publish",
            "--acquisition",
            str(args.acquisition),
            "--store",
            str(args.raw),
            "--snapshots",
            str(snapshots),
            "--max-bytes",
            "32000000",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    (args.output / "publication.json").write_text(published.stdout)
    if args.books:
        DatasetPublication(readers, ImplementationIdentity.sha256()).publish_books(
            tuple(args.books), raw, snapshots, max_records=1000, max_bytes=32_000_000
        )
    catalog = SnapshotCatalog(snapshots).discover(max_entries=10, max_bytes=32_000_000)
    public = next(m for m in catalog if isinstance(m, PublicTradeManifest))
    cutoff = datetime.now(UTC)
    query = PublicTradeQuery(
        snapshot_id=public.identity,
        instruments=acquisition.job.universes.research,
        start=acquisition.job.start,
        end=acquisition.job.end,
        known_at=cutoff,
        max_bytes=32_000_000,
    )
    query_path = args.output / "query.json"
    query_path.write_bytes(codec.encode_json(query))
    inspected = subprocess.run(
        [
            *command,
            "public-read",
            "--query",
            str(query_path),
            "--store",
            str(args.raw),
            "--snapshots",
            str(snapshots),
            "--max-bytes",
            "32000000",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    (args.output / "inspection.json").write_text(inspected.stdout)
    inputs: list[PublicTradeSelection | ReferenceSelection | BookSelection] = [
        PublicTradeSelection(name="public_trades", query=query),
        ReferenceSelection(name="venue_specifications", query=query),
    ]
    for manifest in catalog:
        if not isinstance(manifest, BookDatasetManifest):
            continue
        for partition in manifest.partitions:
            capture = partition.selection.capture
            if capture is None:
                raise ValueError("reference consumer requires captured receipt clocks")
            config = capture.config
            inputs.append(
                BookSelection(
                    name=f"{config.venue}_book",
                    query=BookQuery(
                        snapshot_id=manifest.identity,
                        request_identity=capture.identity,
                        instrument=config.instrument_id,
                        start=cutoff - timedelta(days=1),
                        end=cutoff,
                        known_at=cutoff,
                        columns=("bids", "asks") if config.venue == "okx" else ("orders",),
                        batch_size=100,
                        max_bytes=32_000_000,
                    ),
                )
            )
    selection_path = args.output / "selection.json"
    selection_path.write_bytes(codec.encode_json(ResearchSelection(inputs=tuple(inputs))))
    inspect_eda(
        selection_path, snapshots, raw, report=_Reports(args.output / "assembly.jsonl").write
    )
    reader = PublicTradeReader(snapshots, raw, readers=readers)
    events = tuple(reader.replay(query))
    split = len(events) // 2
    resumed = tuple(reader.replay(query, after=events[split - 1][0])) if split else events
    assert events[split:] == resumed
    result = reader.read(query)
    (args.output / "result.json").write_bytes(
        codec.encode_json(
            {
                "snapshot_id": public.identity,
                "selection": str(selection_path),
                "selected_trades": len(result.rows),
                "replayed_observations": len(events),
                "duplicate_observations": result.duplicate_observations,
                "named_inputs": len(inputs),
                "reasons": result.reasons,
                "reference_identity": result.references.identity,
                "scope": "engineering_data_plane_only",
            }
        )
    )
    print((args.output / "result.json").read_text())


if __name__ == "__main__":
    main()
