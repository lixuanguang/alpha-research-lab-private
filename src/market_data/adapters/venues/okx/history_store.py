"""Publish historical OKX bytes with original discovery and download provenance."""

from __future__ import annotations

# standard library imports
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

# third party library imports
from msgspec.structs import replace

# project library imports
from market_data.adapters.venues.okx.history_discovery import OKXArchiveDiscovery
from market_data.adapters.venues.okx.history_reader import OKXArchiveReader
from market_data.contracts import OKXArchiveRequest, RawObject
from market_data.storage import RawFiles, RawStore
from serialization import DomainCodec, DurableDirectory


class OKXArchiveStore:
    """Own a unique download directory; only a durable manifest admits a complete archive."""

    def __init__(self, root: Path) -> None:
        """Bind a caller-owned directory without starting network or disk work.

        Args:
            root: Explicit new download or completed archive directory.
        """
        self.root = root
        self.codec = DomainCodec()

    def start(self, request: OKXArchiveRequest, index: bytes) -> None:
        """Persist original public discovery and the bound request before download.

        Args:
            request: Exact archive selection and discovery receipt metadata.
            index: Original index bytes matching the request hash.

        Raises:
            ValueError: The discovery bytes differ from their admitted binding.
        """
        if (
            hashlib.sha256(index).hexdigest() != request.index_sha256
            or OKXArchiveDiscovery.select_url(request.config, index) != request.url
        ):
            raise ValueError("OKX discovery bytes differ from request")
        self.root.mkdir(parents=True, exist_ok=False)
        self._write("index.json", index)
        self._write("request.json", self.codec.encode_json(request))
        DurableDirectory.sync(self.root.parent)

    def finish(self, request: OKXArchiveRequest, received: datetime) -> RawObject:
        """Publish validated archive bytes through the existing content-addressed raw store.

        Args:
            request: Independently expected immutable archive binding.
            received: Original UTC instant at complete download receipt.

        Returns:
            Original raw descriptor after durable manifest publication.
        """
        descriptor = RawFiles.describe(
            self.root / "download.part",
            request=request.binding,
            retrieval_reference=f"okx-history:{request.identity}",
            ts_received=received,
            ts_ingested=max(received, datetime.now(UTC)),
        )
        RawStore(self.root).publish(
            self.root / "download.part", descriptor=descriptor, request=request.binding
        )
        descriptor = replace(descriptor, ts_ingested=max(received, datetime.now(UTC)))
        self._write("manifest.pending", self.codec.encode_json(descriptor))
        os.replace(self.root / "manifest.pending", self.root / "manifest.json")
        DurableDirectory.sync(self.root)
        return descriptor

    def replay(self) -> dict[str, object]:
        """Verify request, index and raw byte identity before deterministic offline replay.

        Returns:
            Archive provenance and bounded replay evidence without any network access.

        Raises:
            ValueError: Persisted discovery or source bytes fail identity verification.
        """
        request = self.codec.decode_json(
            (self.root / "request.json").read_bytes(), OKXArchiveRequest
        )
        index = (self.root / "index.json").read_bytes()
        if (
            hashlib.sha256(index).hexdigest() != request.index_sha256
            or OKXArchiveDiscovery.select_url(request.config, index) != request.url
        ):
            raise ValueError("saved OKX archive discovery differs from request")
        descriptor = self.codec.decode_json((self.root / "manifest.json").read_bytes(), RawObject)
        with RawStore(self.root).open(descriptor=descriptor, request=request.binding):
            pass
        summary = OKXArchiveReader(request.config).replay(self.root / descriptor.sha256)
        return {
            **summary,
            "saved_input_identity": descriptor.sha256,
            "saved_bytes": descriptor.size_bytes,
            "request_identity": request.identity,
            "index_identity": request.index_sha256,
            "download_received": descriptor.ts_received.isoformat(),
            "archive_directory": str(self.root.absolute()),
        }

    def _write(self, name: str, raw: bytes) -> None:
        """Write new metadata and synchronize its directory before exposing completion."""
        with (self.root / name).open("xb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        DurableDirectory.sync(self.root)
