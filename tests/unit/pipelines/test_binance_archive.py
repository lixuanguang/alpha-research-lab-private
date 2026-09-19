"""Verify daily archive contracts, publisher checksums and shared command recovery."""

from __future__ import annotations

# standard library imports
import hashlib
import socket
from datetime import timedelta
from http.client import HTTPResponse, HTTPSConnection, IncompleteRead
from io import BufferedReader, BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from applications.acquire import main
from configuration import Configuration
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.providers.binance import BinanceArchiveTransport
from market_data.adapters.providers.tardis import TardisTransport
from market_data.contracts import SourceRequest, TransientFetchError
from market_data.storage import RawStore
from reference_data.catalogs import CatalogSnapshot
from runtime import ImplementationIdentity
from serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()
_NAME = "BTCUSDT-trades-2024-06-01"


class _ArchiveHTTP:
    """Supply real parsed HTTP responses for checksum and ZIP without source access."""

    def __init__(
        self,
        payload: bytes,
        *,
        checksum: bytes | None = None,
        status: int = 200,
        headers: str | None = None,
    ) -> None:
        """Bind synthetic response bytes and optional HTTP or checksum faults."""
        self.payload = payload
        self.checksum = (
            checksum
            if checksum is not None
            else (f"{hashlib.sha256(payload).hexdigest()}  {_NAME}.zip\n".encode())
        )
        self.status = status
        self.headers = headers
        self.paths: list[str] = []

    @staticmethod
    def archive(*, name: str = _NAME + ".csv", content: bytes = b"synthetic trade\n") -> bytes:
        """Make a complete deflated ZIP for integrity tests, without asserting CSV semantics."""
        with BytesIO() as output:
            with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr(name, content)
            return output.getvalue()

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        """Assert that no authentication header is sent and retain endpoint construction."""
        assert method == "GET" and headers == {"Accept-Encoding": "identity"}
        self.paths.append(path)

    def respond(self) -> HTTPResponse:
        """Parse independent checksum and archive HTTP responses with the standard library."""
        body = self.checksum if self.paths[-1].endswith(".CHECKSUM") else self.payload
        headers = self.headers if self.headers is not None else f"Content-Length: {len(body)}\r\n"
        wire = f"HTTP/1.1 {self.status} Synthetic\r\n{headers}\r\n".encode() + body
        with socket.socket() as sock:
            response = HTTPResponse(sock)
        assert response.fp is not None
        response.fp.close()
        response.fp = BufferedReader(BytesIO(wire))
        response.begin()
        return response


class TestBinanceArchive:
    """Protect explicit source/time semantics and the complete acquisition consumer."""

    @pytest.fixture()
    def request_partition(self) -> SourceRequest:
        """Resolve the maintained public-archive selection through its real JSON contracts.

        Returns:
            The sole daily source request retaining its narrower research selection.
        """
        configuration = Configuration.read(_ROOT / "configs/data-jobs/binance-archive.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        return SourceRequest.partition(
            configuration.resolve(
                "btc-archive", catalog, implementation_identity=ImplementationIdentity.sha256()
            )
        )[0]

    @staticmethod
    def _fetch(request: SourceRequest, *, max_bytes: int = 4096) -> bytes:
        """Call the installed adapter with explicit bounded public-source admission."""
        return BinanceArchiveTransport(
            HTTPSConnection("data.binance.vision"), timeout_seconds=1, max_bytes=max_bytes
        ).fetch(
            request, permitted_rights_reference=request.manifest.job.rights_reference, api_key=None
        )

    def test_daily_object_retains_narrow_selection_and_roundtrips(
        self, request_partition: SourceRequest
    ) -> None:
        """A selected hour means one full-day source object, with no capture-time claim."""
        request = request_partition
        assert len(SourceRequest.partition(request.manifest)) == 1
        assert request.end - request.start == timedelta(days=1)
        assert request.manifest.job.end - request.manifest.job.start == timedelta(hours=1)
        assert request.manifest.job.capture_policy == "exchange-time-only-v1"
        assert _CODEC.decode_json(_CODEC.encode_json(request), SourceRequest) == request
        later = replace(request.manifest.job, start=request.start + timedelta(minutes=15))
        narrowed = SourceRequest.partition(replace(request.manifest, job=later))[0]
        assert narrowed.start == request.start and narrowed.end == request.end
        assert narrowed.identity != request.identity
        shorter = replace(request.manifest.job, end=request.start + timedelta(minutes=30))
        assert (
            SourceRequest.partition(replace(request.manifest, job=shorter))[0].identity
            != request.identity
        )
        both = replace(request.manifest, instruments=request.manifest.catalog.instruments)
        assert [item.instrument.symbol for item in SourceRequest.partition(both)] == [
            "BTCUSDT",
            "ETHUSDT",
        ]
        with pytest.raises(ValueError, match="offset"):
            replace(request, offset_minutes=1)
        with pytest.raises(ValueError, match="UTC day"):
            replace(later, end=request.end + timedelta(minutes=1))
        with pytest.raises(ValueError, match="UTC day"):
            replace(later, mode="fixture", pipeline="dataset.inspect")
        with pytest.raises(ValueError, match="unsupported source"):
            replace(later, capture_policy="source-capture-v1")
        old_catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        with pytest.raises(ValueError, match="instrument source"):
            replace(
                request.manifest, catalog=old_catalog, instruments=(old_catalog.instruments[0],)
            )

    def test_exact_download_uses_checksum_and_no_credentials(
        self, request_partition: SourceRequest
    ) -> None:
        """Require SHA-256 from the exact archive's public sidecar before returning bytes."""
        exchange = _ArchiveHTTP(_ArchiveHTTP.archive())
        with (
            patch.object(HTTPSConnection, "request", exchange.request),
            patch.object(HTTPSConnection, "getresponse", exchange.respond),
        ):
            assert self._fetch(request_partition) == exchange.payload
        path = f"/data/spot/daily/trades/BTCUSDT/{_NAME}.zip"
        assert exchange.paths == [path + ".CHECKSUM", path]

    @pytest.mark.parametrize(
        "checksum",
        [
            b"",
            b"x" * 1025,
            b"private response",
            b"0" * 64 + b"  other.zip\n",
            b"0" * 64 + f"  {_NAME}.zip\n".encode(),
        ],
    )
    def test_bad_checksum_fails(self, request_partition: SourceRequest, checksum: bytes) -> None:
        """Reject absent, oversized, malformed, wrong-name and mismatched publisher evidence."""
        exchange = _ArchiveHTTP(_ArchiveHTTP.archive(), checksum=checksum)
        with (
            patch.object(HTTPSConnection, "request", exchange.request),
            patch.object(HTTPSConnection, "getresponse", exchange.respond),
            pytest.raises(ValueError),
        ):
            self._fetch(request_partition)

    @pytest.mark.parametrize(
        "case", ["not-zip", "truncated", "wrong-member", "expanded-limit", "crc", "empty"]
    )
    def test_bad_zip_fails_even_with_matching_sha(
        self, request_partition: SourceRequest, case: str
    ) -> None:
        """Publisher digest does not replace container, member, CRC or expansion validation."""
        payload = _ArchiveHTTP.archive()
        if case == "not-zip":
            payload = b"not zip"
        elif case == "truncated":
            payload = payload[:-12]
        elif case == "wrong-member":
            payload = _ArchiveHTTP.archive(name="../wrong.csv")
        elif case == "expanded-limit":
            payload = _ArchiveHTTP.archive(content=b"x" * 4097)
        elif case == "empty":
            payload = _ArchiveHTTP.archive(content=b"")
        elif case == "crc":
            mutated = bytearray(payload)
            mutated[mutated.index(b"PK\x01\x02") + 16] ^= 1
            payload = bytes(mutated)
        exchange = _ArchiveHTTP(payload)
        with (
            patch.object(HTTPSConnection, "request", exchange.request),
            patch.object(HTTPSConnection, "getresponse", exchange.respond),
            pytest.raises(ValueError),
        ):
            self._fetch(request_partition)

    @pytest.mark.parametrize(
        "status, error",
        [
            (403, PermissionError),
            (404, OSError),
            (302, OSError),
            (429, TransientFetchError),
            (503, TransientFetchError),
        ],
    )
    def test_http_status(
        self, request_partition: SourceRequest, status: int, error: type[Exception]
    ) -> None:
        """Refuse redirects, sanitize response bodies and classify transient failures."""
        exchange = _ArchiveHTTP(b"private body", status=status)
        with (
            patch.object(HTTPSConnection, "request", exchange.request),
            patch.object(HTTPSConnection, "getresponse", exchange.respond),
            pytest.raises(error, match=str(status)),
        ):
            self._fetch(request_partition)

    @pytest.mark.parametrize(
        "headers",
        ["Content-Encoding: gzip\r\n", "Content-Length: bad\r\n", "Content-Length: 999\r\n"],
    )
    def test_invalid_http_headers(self, request_partition: SourceRequest, headers: str) -> None:
        """Require original identity-encoded bytes with consistent declared response length."""
        exchange = _ArchiveHTTP(_ArchiveHTTP.archive(), headers=headers)
        with (
            patch.object(HTTPSConnection, "request", exchange.request),
            patch.object(HTTPSConnection, "getresponse", exchange.respond),
            pytest.raises(ValueError),
        ):
            self._fetch(request_partition)

    @pytest.mark.parametrize("failure", [TimeoutError("secret"), IncompleteRead(b"secret")])
    def test_network_failures_are_retryable(
        self, request_partition: SourceRequest, failure: Exception
    ) -> None:
        """Do not leak network exception details into the safe retry classification."""
        with (
            patch.object(HTTPSConnection, "request", side_effect=failure),
            pytest.raises(TransientFetchError, match="network/protocol"),
        ):
            self._fetch(request_partition)

    def test_preflight_rejects_credential_and_wrong_transport(
        self, request_partition: SourceRequest
    ) -> None:
        """An archive request cannot reach Tardis or leak credentials to public storage."""
        with patch.object(
            HTTPSConnection, "request", side_effect=AssertionError("unexpected HTTP")
        ):
            transport = BinanceArchiveTransport(
                HTTPSConnection("data.binance.vision"), timeout_seconds=1, max_bytes=4096
            )
            with pytest.raises(ValueError, match="credential"):
                transport.fetch(
                    request_partition,
                    permitted_rights_reference=request_partition.manifest.job.rights_reference,
                    api_key="secret",
                )
            with pytest.raises(ValueError, match="rights"):
                transport.fetch(
                    request_partition, permitted_rights_reference="pending", api_key=None
                )
            with pytest.raises(ValueError, match="historical"):
                TardisTransport(
                    HTTPSConnection("api.tardis.dev"), timeout_seconds=1, max_bytes=4096
                ).fetch(
                    request_partition,
                    permitted_rights_reference=request_partition.manifest.job.rights_reference,
                    api_key=None,
                )
            with pytest.raises(ValueError, match=r"data\.binance\.vision"):
                BinanceArchiveTransport(
                    HTTPSConnection("example.com"), timeout_seconds=1, max_bytes=4096
                )
            with pytest.raises(ValueError, match="timeout"):
                BinanceArchiveTransport(
                    HTTPSConnection("data.binance.vision"),
                    timeout_seconds=float("nan"),
                    max_bytes=4096,
                )
            with pytest.raises(ValueError, match="max_bytes"):
                BinanceArchiveTransport(
                    HTTPSConnection("data.binance.vision"), timeout_seconds=1, max_bytes=0
                )

    def test_command_recovers_published_archive_without_fetch_then_rejects_mutation(
        self, request_partition: SourceRequest, tmp_path: Path
    ) -> None:
        """Reuse MR06 receipts and checkpoints for real ZIP payloads through the CLI consumer."""
        config = _ROOT / "configs/data-jobs/binance-archive.json"
        catalog = _ROOT / "configs/reference/binance-archive-spot.json"
        raw = tmp_path / "raw"
        raw.mkdir()
        checkpoint = tmp_path / "manifest.json"
        args = [
            "--config",
            str(config),
            "--catalog",
            str(catalog),
            "--job",
            "btc-archive",
            "--store",
            str(raw),
            "--manifest",
            str(checkpoint),
            "--rights-reference",
            request_partition.manifest.job.rights_reference,
            "--timeout-seconds",
            "1",
            "--max-bytes",
            "4096",
        ]
        exchange = _ArchiveHTTP(_ArchiveHTTP.archive())
        with (
            patch.object(HTTPSConnection, "request", exchange.request),
            patch.object(HTTPSConnection, "getresponse", exchange.respond),
            patch.object(RawStore, "publish", side_effect=KeyboardInterrupt),
        ):
            assert main(args) == 130
        pending = _CODEC.decode_json(checkpoint.read_bytes(), AcquisitionManifest).pending
        assert pending is not None and not list(raw.iterdir())
        # Simulate the publication that could finish just before process death.
        (raw / pending.sha256).write_bytes(exchange.payload)
        with patch.object(
            HTTPSConnection, "request", side_effect=AssertionError("unexpected fetch")
        ):
            assert main(args) == 0
            saved = checkpoint.read_bytes()
            assert main(args) == 0 and checkpoint.read_bytes() == saved
            (raw / pending.sha256).write_bytes(b"mutated")
            assert main(args) == 3 and checkpoint.read_bytes() == saved
            (raw / pending.sha256).unlink()
            assert main(args) == 4
