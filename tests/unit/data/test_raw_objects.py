"""Protect saved-byte integrity, request attribution and original receipt clocks."""

from __future__ import annotations

# standard library imports
import gzip
import hashlib
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from alpha_research.configuration import Configuration
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.requests import SourceRequest
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()
_RECEIVED = datetime(2026, 9, 14, tzinfo=UTC)
_INGESTED = _RECEIVED + timedelta(microseconds=1)


class TestRawObject:
    """Verify exact stored representations independently of decoding and publication."""

    @pytest.fixture()
    def source_request(self) -> SourceRequest:
        """Resolve the retained two-instrument fixture through existing configuration.

        Returns:
            First BTC minute request, with ETH available in the same manifest.
        """
        configuration = Configuration.read(_ROOT / "configs/data-jobs/fixture-inspection.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        return SourceRequest.partition(configuration.resolve("both-fixture", catalog))[0]

    @pytest.fixture()
    def raw_object(self, tmp_path: Path, source_request: SourceRequest) -> RawObject:
        """Describe a fixed byte vector with explicit original acquisition metadata.

        Args:
            tmp_path: Isolated saved-file directory for this test.
            source_request: Expected source partition from the fixture configuration.

        Returns:
            Descriptor of the three retained bytes with fixed original timestamps.
        """
        path = tmp_path / "saved.bin"
        path.write_bytes(b"abc")
        return RawObject.from_file(
            path,
            request=source_request,
            retrieval_reference="synthetic:raw-object-v1",
            ts_received=_RECEIVED,
            ts_ingested=_INGESTED,
        )

    def test_known_digest_round_trip_and_repeated_verification(
        self, tmp_path: Path, source_request: SourceRequest, raw_object: RawObject
    ) -> None:
        """Preserve immutable metadata and a standard SHA-256 vector across reopenings."""
        assert (
            raw_object.sha256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )
        assert raw_object.size_bytes == 3
        assert raw_object.request_identity == source_request.identity
        encoded = _CODEC.encode_json(raw_object)
        restored = _CODEC.decode_json(encoded, RawObject)
        assert restored == raw_object
        for _ in range(2):
            assert restored.verify(tmp_path / "saved.bin", request=source_request) is restored
        assert restored.ts_received == _RECEIVED
        assert restored.ts_ingested == _INGESTED
        assert restored.retrieval_reference == "synthetic:raw-object-v1"
        assert _CODEC.encode_json(restored) == encoded
        with pytest.raises(AttributeError):
            setattr(restored, "size_bytes", 0)

    def test_hashes_compressed_representation_including_header(
        self, tmp_path: Path, source_request: SourceRequest
    ) -> None:
        """Distinguish gzip bytes with identical decompressed contents and byte sizes."""
        payload = (_ROOT / "tests/fixtures/market_data/tardis/btcusdt.txt").read_bytes()
        compressed = gzip.compress(payload, mtime=0)
        path = tmp_path / "saved.gz"
        path.write_bytes(compressed)
        descriptor = RawObject.from_file(
            path,
            request=source_request,
            retrieval_reference="synthetic:gzip-fixture-v1",
            ts_received=_RECEIVED,
            ts_ingested=_INGESTED,
        )
        assert descriptor.sha256 == hashlib.sha256(compressed).hexdigest()
        assert descriptor.sha256 != hashlib.sha256(payload).hexdigest()
        assert descriptor.size_bytes == len(compressed)
        descriptor.verify(path, request=source_request)
        changed_header = compressed[:4] + b"\x01" + compressed[5:]
        assert gzip.decompress(changed_header) == payload
        path.write_bytes(changed_header)
        with pytest.raises(ValueError, match="SHA-256 mismatch"):
            descriptor.verify(path, request=source_request)

    @pytest.mark.parametrize(
        ("payload", "message"),
        [(b"abd", "SHA-256 mismatch"), (b"ab", "size mismatch"), (b"abcd", "size mismatch")],
    )
    def test_changed_bytes_fail_and_original_bytes_recover(
        self,
        tmp_path: Path,
        source_request: SourceRequest,
        raw_object: RawObject,
        payload: bytes,
        message: str,
    ) -> None:
        """Reject mutation, truncation and appended bytes without poisoning later checks."""
        path = tmp_path / "saved.bin"
        path.write_bytes(payload)
        with pytest.raises(ValueError, match=message):
            raw_object.verify(path, request=source_request)
        path.write_bytes(b"abc")
        assert raw_object.verify(path, request=source_request) is raw_object

    def test_wrong_request_fails_before_file_access(
        self, tmp_path: Path, source_request: SourceRequest, raw_object: RawObject
    ) -> None:
        """Reject another minute, instrument or policy even when object bytes match."""
        other_requests = (
            replace(source_request, offset_minutes=1),
            replace(source_request, instrument=source_request.manifest.instruments[1]),
            replace(
                source_request,
                manifest=replace(
                    source_request.manifest,
                    job=replace(source_request.manifest.job, source_revision="changed"),
                ),
            ),
        )
        for other in other_requests:
            for path in (tmp_path / "saved.bin", tmp_path / "absent.bin"):
                with pytest.raises(ValueError, match="request identity mismatch"):
                    raw_object.verify(path, request=other)
        renamed = replace(
            source_request,
            manifest=replace(
                source_request.manifest, job=replace(source_request.manifest.job, name="renamed")
            ),
        )
        raw_object.verify(tmp_path / "saved.bin", request=renamed)

    @pytest.mark.parametrize(
        "payload", [b"", b"\x00\xff\r\n" * 262_145], ids=["empty", "multiple-chunks"]
    )
    def test_empty_and_multichunk_binary_files(
        self, tmp_path: Path, source_request: SourceRequest, payload: bytes
    ) -> None:
        """Count all bytes across a read boundary without text or compression assumptions."""
        path = tmp_path / "binary"
        path.write_bytes(payload)
        descriptor = RawObject.from_file(
            path,
            request=source_request,
            retrieval_reference="synthetic:binary",
            ts_received=_RECEIVED,
            ts_ingested=_RECEIVED,
        )
        assert descriptor.size_bytes == len(payload)
        assert descriptor.sha256 == hashlib.sha256(payload).hexdigest()
        descriptor.verify(path, request=source_request)

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("schema_version", "2", "schema"),
            ("sha256", "a" * 63, "sha256"),
            ("sha256", "G" * 64, "sha256"),
            ("sha256", 123, "sha256"),
            ("request_identity", "z" * 64, "request_identity"),
            ("size_bytes", -1, "size_bytes"),
            ("size_bytes", True, "size_bytes"),
            ("size_bytes", 3.0, "size_bytes"),
            ("retrieval_reference", "", "retrieval_reference"),
            ("retrieval_reference", " secret ", "retrieval_reference"),
            ("retrieval_reference", "line\nbreak", "retrieval_reference"),
            ("retrieval_reference", "x" * 257, "retrieval_reference"),
            ("retrieval_reference", None, "retrieval_reference"),
            ("ts_received", datetime(2026, 9, 14), "ts_received"),
            ("ts_received", "2026-09-14T00:00:00Z", "ts_received"),
            ("ts_ingested", _INGESTED.astimezone(timezone(timedelta(hours=8))), "ts_ingested"),
            ("ts_ingested", _RECEIVED - timedelta(microseconds=1), "precede"),
        ],
    )
    def test_invalid_fields_and_unsafe_copies_fail(
        self,
        tmp_path: Path,
        source_request: SourceRequest,
        raw_object: RawObject,
        field: str,
        value: object,
        message: str,
    ) -> None:
        """Retain constructor validation and revalidate descriptors at the file boundary."""
        with pytest.raises(ValueError, match=message):
            replace(raw_object, **{field: value})
        msgspec.structs.force_setattr(raw_object, field, value)
        with pytest.raises(ValueError, match=message):
            raw_object.verify(tmp_path / "absent.bin", request=source_request)

    @pytest.mark.parametrize(
        ("before", "after"),
        [
            ('"schema_version":"1"', '"schema_version":"2"'),
            ('"size_bytes":3', '"size_bytes":"3"'),
            ('"size_bytes":3', '"size_bytes":true'),
            ('"size_bytes":3', '"size_bytes":-1'),
            ('"size_bytes":3', '"size_bytes":3,"unknown":1'),
            ('"size_bytes":3,', ""),
            ('"ts_ingested":"2026-09-14T00:00:00.000001Z"', '"ts_ingested":null'),
        ],
    )
    def test_strict_serialized_boundary(
        self, raw_object: RawObject, before: str, after: str
    ) -> None:
        """Reject unsupported schemas, unknown/missing fields and coerced wire types."""
        payload = _CODEC.encode_json(raw_object).decode()
        assert before in payload
        with pytest.raises(ValueError):
            _CODEC.decode_json(payload.replace(before, after, 1), RawObject)
        assert _CODEC.decode_json(_CODEC.encode_json(raw_object), RawObject) == raw_object

    def test_missing_file_and_unsafe_expected_request(
        self, tmp_path: Path, source_request: SourceRequest, raw_object: RawObject
    ) -> None:
        """Propagate actionable local I/O errors and reject tampered request invariants."""
        with pytest.raises(FileNotFoundError):
            raw_object.verify(tmp_path / "absent.bin", request=source_request)
        msgspec.structs.force_setattr(source_request, "offset_minutes", True)
        with pytest.raises(ValueError, match="offset"):
            raw_object.verify(tmp_path / "saved.bin", request=source_request)
        with pytest.raises(ValueError, match="offset"):
            RawObject.from_file(
                tmp_path / "absent.bin",
                request=source_request,
                retrieval_reference="synthetic:invalid-request",
                ts_received=_RECEIVED,
                ts_ingested=_INGESTED,
            )
