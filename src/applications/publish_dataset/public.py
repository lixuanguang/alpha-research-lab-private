"""Expose public-trade publication, catalog discovery and pinned cutoff inspection."""

from __future__ import annotations

# standard library imports
import argparse
import sys
from pathlib import Path

# project library imports
from market_data.acquisition import PublicAcquisition
from market_data.adapters.sources import SourceAdapters
from market_data.datasets import PublicTradeManifest, SnapshotCatalog, SnapshotStore
from market_data.query import PublicTradeQuery, PublicTradeReader
from market_data.storage import RawStore
from runtime import ImplementationIdentity
from serialization import DomainCodec


class _PublicDatasetArguments(argparse.Namespace):
    """Type required stores, explicit selections and bounded discovery controls."""

    action: str
    acquisition: Path
    snapshots: Path
    store: Path
    query: Path
    max_bytes: int
    max_entries: int

    def read[T](self, path: Path, target: type[T]) -> T:
        """Read strict bounded input without inferring a mutable latest selection."""
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        with path.open("rb") as source:
            payload = source.read(self.max_bytes + 1)
        if len(payload) > self.max_bytes:
            raise ValueError("dataset input exceeds max_bytes")
        return DomainCodec().decode_json(payload, target)


def public_dataset(argv: list[str]) -> int:
    """Compose discovery, atomic publication or a fully verified public cutoff query."""
    parser = argparse.ArgumentParser(prog="alpha-dataset", description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("discover", "public-publish", "public-read"):
        command = commands.add_parser(action)
        command.add_argument("--snapshots", type=Path, required=True)
        command.add_argument("--max-bytes", type=int, required=True)
        if action == "discover":
            command.add_argument("--max-entries", type=int, required=True)
        else:
            command.add_argument("--store", type=Path, required=True)
            command.add_argument(
                "--acquisition" if action == "public-publish" else "--query",
                type=Path,
                required=True,
            )
    args = parser.parse_args(argv, namespace=_PublicDatasetArguments())
    try:
        result: object
        if args.action == "discover":
            manifests = SnapshotCatalog(args.snapshots).discover(
                max_entries=args.max_entries, max_bytes=args.max_bytes
            )
            result = tuple({"snapshot_id": m.identity, "manifest": m} for m in manifests)
        elif args.action == "public-publish":
            raw, readers = RawStore(args.store), SourceAdapters()
            acquisition = args.read(args.acquisition, PublicAcquisition)
            manifest, payload = PublicTradeManifest.assemble(
                acquisition,
                raw,
                readers=readers,
                max_bytes=args.max_bytes,
                normalization_identity=ImplementationIdentity.sha256(),
            )
            identity = SnapshotStore(
                args.snapshots, raw, readers=readers, manifest_type=PublicTradeManifest
            ).publish(manifest, (payload,), max_bytes=args.max_bytes)
            result = {
                "snapshot_id": identity,
                "scope": manifest.scope,
                "canonical_bytes": len(payload),
            }
        else:
            query = args.read(args.query, PublicTradeQuery)
            if query.max_bytes > args.max_bytes:
                raise ValueError("query exceeds command byte budget")
            result = PublicTradeReader(
                args.snapshots, RawStore(args.store), readers=SourceAdapters()
            ).read(query)
        print(DomainCodec().encode_json({"status": "complete", "result": result}).decode())
        return 0
    except (ValueError, TypeError, OSError) as error:
        print(
            DomainCodec().encode_json({"status": "failed", "error": str(error)}).decode(),
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        return 130
