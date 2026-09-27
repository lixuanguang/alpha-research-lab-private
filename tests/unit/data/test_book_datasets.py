"""Verify saved native book admission, immutable publication and explicit refusals."""

from __future__ import annotations

# standard library imports
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from configuration import CaptureConfig, OKXHistoryConfig, UniverseSelection
from market_data.adapters.sources import SourceAdapters
from market_data.adapters.venues.okx import OKXArchiveStore
from market_data.contracts import BookObservation, CaptureRecord, CaptureRequest, OKXArchiveRequest
from market_data.datasets import (
    BookDatasetManifest,
    BookHistory,
    BookInput,
    BookPartition,
    BookSnapshot,
    DatasetPublication,
    SnapshotStore,
)
from market_data.storage import CaptureJournal, RawStore
from runtime import ImplementationIdentity
from serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()
_LIMIT = 1_048_576
_ACK = b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}'


class TestBookDatasets:
    """Use actual storage and decoders with independently hand-authored native messages."""

    @staticmethod
    def _frame(action: str, previous: int, sequence: int, bids: str, asks: str = "[]") -> bytes:
        """Build one whole native OKX message with explicit sequence linkage."""
        return (
            '{"arg":{"channel":"books","instId":"BTC-USDT"},"action":"'
            + action
            + '","data":[{"prevSeqId":'
            + str(previous)
            + ',"seqId":'
            + str(sequence)
            + ',"bids":'
            + bids
            + ',"asks":'
            + asks
            + "}]}"
        ).encode()

    @classmethod
    def _capture(
        cls,
        root: Path,
        *,
        invalid: bool = False,
        gap: bool = False,
        universes: UniverseSelection | None = None,
    ) -> Path:
        """Retain snapshot, absolute size update and deletion with exact receipt lineage."""
        config = CaptureConfig.read(_ROOT / "configs/live/okx-btc-usdt.json")
        request = CaptureRequest(
            config=config,
            recording_id="00000000-0000-0000-0000-000000000001",
            implementation_identity="a" * 64,
            universes=universes,
        )
        journal = CaptureJournal(root, request)
        journal.start()
        journal.append(CaptureRecord(kind="session", epoch=0, received_ns=1))
        frames = (
            _ACK,
            cls._frame("snapshot", -1, 10, '[["100","0.300000000000000001","0","2"]]'),
            cls._frame("update", 10, 11, '[["100","0.2","0","1"]]'),
            cls._frame(
                "update",
                11,
                12,
                '[["100","0","0","0"]]' if not invalid else '[["100","NaN","0","1"]]',
            ),
        )
        for index, frame in enumerate(frames, 2):
            journal.append(CaptureRecord(kind="frame", epoch=0, received_ns=index, raw=frame))
        if gap:
            journal.append(CaptureRecord(kind="gap", epoch=0, received_ns=6, reason="unknown_loss"))
        journal.append(CaptureRecord(kind="end", epoch=0, received_ns=7, reason="message_limit"))
        journal.finish(1)
        return root

    @staticmethod
    def _archive(root: Path, *, records: int = 2) -> Path:
        """Create distinct exact L2 rows with absent sequence and original receipt clocks."""
        config = OKXHistoryConfig.read(_ROOT / "configs/history/okx-btc-usdt.json")
        if records > config.max_records:
            config = replace(config, max_records=records)
        url = (
            "https://static.okx.com/cdn/okx/match/orderbook/pro/L2/400lv/daily/"
            f"{config.day:%Y%m%d}/{config.filename}"
        )
        index = _CODEC.encode_json(
            {
                "code": "0",
                "data": [
                    {
                        "dateAggrType": "daily",
                        "details": [
                            {
                                "instId": config.symbol,
                                "instType": "SPOT",
                                "groupDetails": [
                                    {
                                        "filename": config.filename,
                                        "dateTs": str(config.start_ms),
                                        "sizeMB": "0.001",
                                        "url": url,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        request = OKXArchiveRequest(
            config=config,
            implementation_identity="b" * 64,
            index_sha256=hashlib.sha256(index).hexdigest(),
            url=url,
            index_received=datetime(2026, 9, 9, tzinfo=UTC),
        )
        store = OKXArchiveStore(root)
        store.start(request, index)
        rows = b'{"instId":"BTC-USDT","action":"snapshot","bids":[["100","2","1"]],"asks":[]}\n'
        if records == 2:
            rows += b'{"instId":"BTC-USDT","action":"update","bids":[["100","0","0"]],"asks":[]}\n'
        else:
            rows += b"".join(
                b'{"instId":"BTC-USDT","action":"update","bids":[["100","'
                + str(index).encode()
                + b'","1"]],"asks":[]}\n'
                for index in range(1, records)
            )
        with tarfile.open(root / "download.part", "w:gz") as archive:
            member = tarfile.TarInfo(config.filename.removesuffix(".tar.gz") + ".data")
            member.size = len(rows)
            archive.addfile(member, io.BytesIO(rows))
        store.finish(request, datetime(2026, 9, 9, tzinfo=UTC))
        return root

    @staticmethod
    def _observations(
        root: Path, manifest: BookDatasetManifest, index: int = 0
    ) -> tuple[BookObservation, ...]:
        """Stream the admitted canonical history after the snapshot has verified."""
        snapshot = BookSnapshot.read(
            root,
            RawStore(root.parent / "raw"),
            readers=SourceAdapters(),
            identity=manifest.identity,
            max_bytes=_LIMIT,
        )
        request_identity = manifest.partitions[index].selection.request.identity
        return tuple(snapshot.observations(request_identity))

    def test_publication_reopen_identity_and_distinct_source_clocks(self, tmp_path: Path) -> None:
        """Publish both source modes without inventing archive availability or order IDs."""
        live, archive = (
            self._capture(tmp_path / "live", gap=True),
            self._archive(tmp_path / "archive"),
        )
        raw, snapshots = tmp_path / "raw", tmp_path / "snapshots"
        raw.mkdir()
        snapshots.mkdir()
        inputs = (live, archive)
        identity = DatasetPublication(
            SourceAdapters(), ImplementationIdentity.sha256()
        ).publish_books(inputs, RawStore(raw), snapshots, max_records=64, max_bytes=_LIMIT)
        store = SnapshotStore(
            snapshots, RawStore(raw), readers=SourceAdapters(), manifest_type=BookDatasetManifest
        )
        manifest = store.read(identity, max_bytes=_LIMIT)
        assert (
            DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).publish_books(
                inputs, RawStore(raw), snapshots, max_records=64, max_bytes=_LIMIT
            )
            == identity
        )
        observed = self._observations(snapshots, manifest)
        assert [row.position for row in observed] == list(range(7))
        assert observed[2].bids[0][1].size == Decimal("0.300000000000000001")
        assert observed[3].bids[0][1].size == Decimal("0.2")
        assert observed[4].outcome == "update" and observed[4].bids == ()
        assert observed[5].status == "recovering" and observed[6].status == "unavailable"
        assert all(row.orders == () for row in observed)
        historical = self._observations(snapshots, manifest, 1)
        assert all(
            row.received_ns is None and row.epoch is None and row.sequence is None
            for row in historical
        )
        assert historical[0].bids[0][1].size == 2 and historical[1].bids == ()
        changed = DatasetPublication(
            SourceAdapters(), ImplementationIdentity.sha256()
        ).publish_books(inputs, RawStore(raw), snapshots, max_records=4, max_bytes=_LIMIT)
        assert changed != identity
        assert store.read(identity, max_bytes=_LIMIT) == manifest
        with pytest.raises(ValueError):
            SnapshotStore(snapshots, RawStore(raw), readers=SourceAdapters()).read(
                identity, max_bytes=_LIMIT
            )

    def test_invalid_input_and_failed_publication_preserve_prior(self, tmp_path: Path) -> None:
        """No malformed or partially staged book history can become a visible snapshot."""
        live = self._capture(tmp_path / "live")
        raw, snapshots = tmp_path / "raw", tmp_path / "snapshots"
        raw.mkdir()
        snapshots.mkdir()
        identity = DatasetPublication(
            SourceAdapters(), ImplementationIdentity.sha256()
        ).publish_books((live,), RawStore(raw), snapshots, max_records=64, max_bytes=_LIMIT)
        invalid = self._capture(tmp_path / "bad", invalid=True)
        with pytest.raises(ValueError, match="publication refused"):
            DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).publish_books(
                (invalid,), RawStore(raw), snapshots, max_records=64, max_bytes=_LIMIT
            )
        with patch("market_data.datasets.snapshots.os.rename", side_effect=OSError("interrupted")):
            with pytest.raises(OSError, match="interrupted"):
                DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).publish_books(
                    (live,), RawStore(raw), snapshots, max_records=4, max_bytes=_LIMIT
                )
        assert [path.name for path in snapshots.iterdir()] == [identity]
        selected = BookInput.read(live, max_records=64)
        assert (
            selected.admit(RawStore(raw), readers=SourceAdapters(), max_bytes=1).scope == "rejected"
        )
        with pytest.raises(ValueError, match="bounded prefix"):
            replace(selected, max_records=0)
        with pytest.raises(ValueError, match="duplicate book"):
            DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).publish_books(
                (live, live), RawStore(raw), snapshots, max_records=64, max_bytes=_LIMIT
            )
        (raw / selected.raw.sha256).chmod(0o644)
        (raw / selected.raw.sha256).write_bytes(b"corrupt")
        with pytest.raises(ValueError):
            SnapshotStore(
                snapshots,
                RawStore(raw),
                readers=SourceAdapters(),
                manifest_type=BookDatasetManifest,
            ).read(identity, max_bytes=_LIMIT)

    def test_stream_publication_exceeds_legacy_prefix_without_retaining_history(
        self, tmp_path: Path
    ) -> None:
        """Admit 10,001 distinct raw rows and reconstruct exact final state from v2 lines."""
        archive = self._archive(tmp_path / "archive", records=10_001)
        raw, snapshots = tmp_path / "raw", tmp_path / "snapshots"
        raw.mkdir()
        snapshots.mkdir()
        identity = DatasetPublication(SourceAdapters(), "a" * 64).publish_books(
            (archive,), RawStore(raw), snapshots, max_records=10_001, max_bytes=16_000_000
        )
        snapshot = BookSnapshot.read(
            snapshots,
            RawStore(raw),
            readers=SourceAdapters(),
            identity=identity,
            max_bytes=16_000_000,
        )
        selected = BookInput.read(archive, max_records=10_001)
        assert snapshot.schema_version == "book-dataset-v2"
        assert snapshot.selection(selected.request.identity).raw == selected.raw
        count = 0
        last: BookObservation | None = None
        for row in snapshot.observations(selected.request.identity):
            count += 1
            last = row
        assert count == 10_001 and last is not None
        assert last.position == 10_000
        assert last.bids[0][1].size == Decimal("10000")
        assert last.received_ns is None and last.epoch is None
        with pytest.raises(ValueError, match="legacy book envelope"):
            selected.admit(RawStore(raw), readers=SourceAdapters(), max_bytes=16_000_000)
        with pytest.raises(ValueError, match="bounded prefix"):
            BookInput.read(archive, max_records=1_000_001)

    def test_snapshot_session_isolates_evidence_and_refuses_replaced_file(
        self, tmp_path: Path
    ) -> None:
        """An admitted session cannot leak mutable evidence or skip a replaced partition."""
        archive = self._archive(tmp_path / "archive")
        raw, snapshots = tmp_path / "raw", tmp_path / "snapshots"
        raw.mkdir()
        snapshots.mkdir()
        identity = DatasetPublication(SourceAdapters(), "a" * 64).publish_books(
            (archive,), RawStore(raw), snapshots, max_records=2, max_bytes=_LIMIT
        )
        session = BookSnapshot.read(
            snapshots,
            RawStore(raw),
            readers=SourceAdapters(),
            identity=identity,
            max_bytes=_LIMIT,
        )
        request_identity = BookInput.read(archive, max_records=2).request.identity
        assert session.admission_report(request_identity).record_count == 2
        selected = session.selection(request_identity)
        force_setattr(selected, "max_records", 1)
        assert session.selection(request_identity).max_records == 2
        partition = session.partition(request_identity)
        path = snapshots / identity / partition.sha256
        replacement = tmp_path / "replacement"
        shutil.copyfile(path, replacement)
        os.replace(replacement, path)
        with pytest.raises(ValueError, match="changed after admission"):
            session.verify_partition(request_identity)
        with pytest.raises(ValueError, match="changed after admission"):
            next(session.observations(request_identity))

    def test_legacy_snapshot_remains_readable_with_exact_bytes(self, tmp_path: Path) -> None:
        """The new reader preserves old v1 envelopes and their canonical digest."""
        archive = self._archive(tmp_path / "archive")
        raw, snapshots = tmp_path / "raw", tmp_path / "snapshots"
        raw.mkdir()
        snapshots.mkdir()
        selected = BookInput.read(archive, max_records=2)
        RawStore(raw).publish(
            archive / selected.raw.sha256,
            descriptor=selected.raw,
            request=selected.request.binding,
        )
        payload = selected.admit(RawStore(raw), readers=SourceAdapters(), max_bytes=_LIMIT)
        canonical = payload.require_canonical()
        manifest = BookDatasetManifest(
            normalization_identity="a" * 64,
            partitions=(BookPartition(hashlib.sha256(canonical).hexdigest(), selected),),
        )
        identity = SnapshotStore(
            snapshots,
            RawStore(raw),
            readers=SourceAdapters(),
            manifest_type=BookDatasetManifest,
        ).publish(manifest, (canonical,), max_bytes=_LIMIT)
        session = BookSnapshot.read(
            snapshots,
            RawStore(raw),
            readers=SourceAdapters(),
            identity=identity,
            max_bytes=_LIMIT,
        )
        assert session.schema_version == "book-dataset-v1"
        assert session.legacy_canonical(selected.request.identity) == canonical
        assert (
            tuple(session.observations(selected.request.identity))
            == _CODEC.decode_json(canonical, BookHistory).observations
        )

    @pytest.mark.integration
    def test_installed_book_consumer(self, tmp_path: Path) -> None:
        """Run the retained notebook consumer under isolated installed imports."""
        capture = self._capture(tmp_path / "capture", gap=True)
        script = tmp_path / "book_consumer.py"
        shutil.copyfile(_ROOT / "tests/integration/consumers/capture/book_consumer.py", script)
        result = subprocess.run(
            [sys.executable, "-I", str(script), str(capture), str(tmp_path / "result")],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
