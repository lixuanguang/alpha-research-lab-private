"""Verify historical archive identity, bounded integrity, persistence and exact offline replay."""

from __future__ import annotations

# standard library imports
import hashlib
import io
import socket
import tarfile
import time
from datetime import UTC, datetime
from http.client import HTTPResponse, HTTPSConnection
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from alpha_research.data.providers.transport import TransientFetchError
from alpha_research.data.venues.okx.history_config import OKXArchiveRequest, OKXHistoryConfig
from alpha_research.data.venues.okx.history_reader import OKXArchiveReader
from alpha_research.data.venues.okx.history_store import OKXArchiveStore
from alpha_research.data.venues.okx.history_transport import OKXHistoryTransport
from alpha_research.pipelines.acquisition import acquire_history, main
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[5]
_SNAPSHOT = (
    b'{"instId":"BTC-USDT","action":"snapshot","ts":"1788825600004","bids":[["100","0.'
    b'123456789012345678901234567890","2"]],"asks":[]}\n'
)
_UPDATE = (
    b'{"instId":"BTC-USDT","action":"update","ts":"1788825600014","bids":[["100","0.2"'
    b',"1"]],"asks":[]}\n'
)


class HistoryFixture:
    """Build minimal native archive bytes and an independent public index fixture."""

    @staticmethod
    def config() -> OKXHistoryConfig:
        """Read the maintained historical example with bounded fixture settings.

        Returns:
            Exact single-day archive selection.
        """
        return replace(
            OKXHistoryConfig.read(_ROOT / "configs/history/okx-btc-usdt.json"), retries=0
        )

    @staticmethod
    def index(config: OKXHistoryConfig) -> bytes:
        """Describe the native public CDN location using the observed official schema.

        Args:
            config: Selected native instrument and day.

        Returns:
            Synthetic public metadata response bytes.
        """
        return DomainCodec().encode_json(
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
                                        "url": f"https://static.okx.com/cdn/okx/match/orderbook/pro/L2/400lv/daily/{config.day:%Y%m%d}/{config.filename}",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )

    @staticmethod
    def archive(
        config: OKXHistoryConfig, rows: bytes = _SNAPSHOT + _UPDATE, name: str | None = None
    ) -> bytes:
        """Build a complete gzip/tar object without extracting member paths.

        Args:
            config: Expected native filename binding.
            rows: Source NDJSON bytes.
            name: Optional invalid member name for failure coverage.

        Returns:
            Complete compressed archive bytes.
        """
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            member = tarfile.TarInfo(name or config.filename.removesuffix(".tar.gz") + ".data")
            member.size = len(rows)
            archive.addfile(member, io.BytesIO(rows))
        return output.getvalue()


class FixtureHistoryTransport(OKXHistoryTransport):
    """Retain the real acquisition/persistence boundary while scripting source bytes."""

    def __init__(self, config: OKXHistoryConfig, *, fail_first: bool = False) -> None:
        """Set an optional interrupted first network attempt.

        Args:
            config: Selected public archive configuration.
            fail_first: Raise a transient source error after writing a partial file.
        """
        super().__init__(config)
        self.fail_first = fail_first
        self.attempts = 0

    def index(self) -> bytes:
        """Supply independent valid public discovery metadata.

        Returns:
            Synthetic index bytes.
        """
        return HistoryFixture.index(self.config)

    def download(self, request: OKXArchiveRequest, destination: Path, deadline: float) -> None:
        """Create source bytes or fail with an incomplete local prefix.

        Args:
            request: Expected immutable request.
            destination: New staging path.
            deadline: Overall monotonic acquisition deadline.

        Raises:
            TransientFetchError: The scripted first connection disconnects.
        """
        self.attempts += 1
        if self.fail_first and self.attempts == 1:
            destination.write_bytes(b"interrupted")
            raise TransientFetchError("scripted disconnect")
        destination.write_bytes(HistoryFixture.archive(self.config))


class ArchiveHTTP:
    """Use the real HTTP response parser to exercise transport bounds without a server."""

    def __init__(self, status: int, headers: str, body: bytes) -> None:
        """Bind an independent HTTP response.

        Args:
            status: HTTP status code.
            headers: Exact synthetic response headers including line endings.
            body: Source body bytes.
        """
        self.status, self.headers, self.body = status, headers, body

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        """Require a public read without authorization headers.

        Args:
            method: HTTP method.
            path: Expected public CDN request path.
            headers: Explicit request headers.
        """
        assert method == "GET" and path.startswith("/cdn/okx/")
        assert headers == {"Accept-Encoding": "identity"}

    def respond(self) -> HTTPResponse:
        """Parse the wire response with the standard library.

        Returns:
            Open synthetic HTTP response.
        """
        wire = f"HTTP/1.1 {self.status} Synthetic\r\n{self.headers}\r\n".encode() + self.body
        with socket.socket() as sock:
            response = HTTPResponse(sock)
        assert response.fp is not None
        response.fp.close()
        response.fp = io.BufferedReader(io.BytesIO(wire))
        response.begin()
        return response


class TestOKXHistory:
    """Cover access-free success and failures that cannot reliably be induced on the venue."""

    def test_existing_acquisition_entry_point_routes_archive_work(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Use the existing pipeline command for discovery, fetch and saved archive replay."""
        config = HistoryFixture.config()
        path = tmp_path / "config.json"
        path.write_bytes(DomainCodec().encode_json(config))
        output = tmp_path / "history"
        with patch(
            "alpha_research.pipelines.acquisition.OKXHistoryTransport",
            return_value=FixtureHistoryTransport(config),
        ):
            assert main(["archive", "index", "--config", str(path)]) == 0
            assert main(["archive", "fetch", "--config", str(path), "--output", str(output)]) == 0
        archive = next(output.iterdir())
        assert main(["archive", "replay", "--archive", str(archive)]) == 0
        assert '"records":2' in capsys.readouterr().out
        assert main(["archive", "replay", "--archive", str(tmp_path / "missing")]) == 2
        assert "incomplete" in capsys.readouterr().err

    def test_acquire_saved_input_parity_and_tamper(self, tmp_path: Path) -> None:
        """Persist exact bytes and reproduce all source rows without fabricating gap assurance."""
        config = HistoryFixture.config()
        result = acquire_history(
            config,
            tmp_path,
            implementation_identity="a" * 64,
            transport=FixtureHistoryTransport(config),
        )
        root = next(tmp_path.iterdir())
        offline = OKXArchiveStore(root).replay()
        assert result["trace_identity"] == offline["trace_identity"]
        assert result["records"] == 2 and result["levels"] == 1
        assert result["gaps"] is None and result["source_sequence"] is None
        assert result["entire_archive_replayed"] is True
        (root / "index.json").write_bytes(b"tampered")
        with pytest.raises(ValueError, match="discovery"):
            OKXArchiveStore(root).replay()

    def test_retry_restarts_incomplete_download(self, tmp_path: Path) -> None:
        """Discard failed network staging and record a finite successful retry count."""
        config = replace(HistoryFixture.config(), retries=1)
        result = acquire_history(
            config,
            tmp_path,
            implementation_identity="a" * 64,
            transport=FixtureHistoryTransport(config, fail_first=True),
        )
        assert result["download_attempts"] == 2
        assert result["records"] == 2

    def test_persistence_failure_never_publishes_manifest(self, tmp_path: Path) -> None:
        """Failure during shared raw publication leaves a non-admitted download directory."""
        config = HistoryFixture.config()
        with patch(
            "alpha_research.data.venues.okx.history_store.RawStore.publish",
            side_effect=OSError("disk full"),
        ):
            with pytest.raises(OSError):
                acquire_history(
                    config,
                    tmp_path,
                    implementation_identity="a" * 64,
                    transport=FixtureHistoryTransport(config),
                )
        root = next(tmp_path.iterdir())
        assert (root / "download.part").exists() and not (root / "manifest.json").exists()
        with pytest.raises(FileNotFoundError):
            OKXArchiveStore(root).replay()

    def test_prefix_limit_is_not_whole_archive(self, tmp_path: Path) -> None:
        """Expose the precise replay selection and preserve original source clock text."""
        config = replace(HistoryFixture.config(), max_records=1)
        source = tmp_path / "archive"
        source.write_bytes(HistoryFixture.archive(config))
        result = OKXArchiveReader(config).replay(source)
        assert result["records"] == 1 and result["stop_reason"] == "record_limit"
        assert result["entire_archive_replayed"] is False
        assert result["first_source_ms"] == "1788825600004"

    @pytest.mark.parametrize(
        "rows",
        [
            _UPDATE,
            _SNAPSHOT + b"{bad}\n",
            _SNAPSHOT.rstrip(),
            _SNAPSHOT.replace(b"1788825600004", b"1"),
        ],
    )
    def test_bad_rows_fail_closed(self, tmp_path: Path, rows: bytes) -> None:
        """Reject pre-snapshot updates, malformed/truncated rows and wrong-day source clocks."""
        config = HistoryFixture.config()
        source = tmp_path / "archive"
        source.write_bytes(HistoryFixture.archive(config, rows))
        with pytest.raises(ValueError):
            OKXArchiveReader(config).replay(source)

    @pytest.mark.parametrize("missing_clock", [b"", b'"ts":null,', b'"ts":"",'])
    def test_missing_clock_preserves_archive_ordering(
        self, tmp_path: Path, missing_clock: bytes
    ) -> None:
        """Keep unknown clocks unknown while rejecting regressions across missing values."""
        config = HistoryFixture.config()
        source = tmp_path / "archive"
        missing = (
            b'{"instId":"BTC-USDT","action":"update",' + missing_clock + b'"bids":[],"asks":[]}\n'
        )
        source.write_bytes(HistoryFixture.archive(config, _SNAPSHOT + missing))
        result = OKXArchiveReader(config).replay(source)
        assert result["last_source_ms"] is None
        assert result["state_available"] is True

        source.write_bytes(HistoryFixture.archive(config, _SNAPSHOT + missing + _UPDATE))
        assert OKXArchiveReader(config).replay(source)["last_source_ms"] == "1788825600014"

        backward = _UPDATE.replace(b"1788825600014", b"1788825600003")
        source.write_bytes(HistoryFixture.archive(config, _SNAPSHOT + missing + backward))
        with pytest.raises(ValueError, match="source time moved backwards"):
            OKXArchiveReader(config).replay(source)

    def test_integrity_expansion_deadline_and_member_limits(self, tmp_path: Path) -> None:
        """Validate gzip trailers and fail bounded expansion, time and unsafe member paths."""
        config = HistoryFixture.config()
        source = tmp_path / "archive"
        raw = HistoryFixture.archive(config)
        source.write_bytes(raw[:-6])
        with pytest.raises(EOFError):
            OKXArchiveReader(config).validate(source, time.monotonic() + 5)
        source.write_bytes(raw)
        with pytest.raises(ValueError, match="expanded"):
            OKXArchiveReader(replace(config, max_expanded_bytes=100)).validate(
                source, time.monotonic() + 5
            )
        with pytest.raises(TimeoutError):
            OKXArchiveReader(config).validate(source, time.monotonic() - 1)
        source.write_bytes(HistoryFixture.archive(config, name="../../escape"))
        with pytest.raises(ValueError, match="regular"):
            OKXArchiveReader(config).validate(source, time.monotonic() + 5)

    def test_index_origin_date_and_missing_data(self) -> None:
        """Never follow arbitrary discovered hosts, wrong dates or unavailable archive lists."""
        config = HistoryFixture.config()
        index = HistoryFixture.index(config)
        for invalid in (
            index.replace(b"static.okx.com", b"elsewhere.invalid"),
            index.replace(b'"1788825600000"', b'"1"'),
            b'{"code":"0","data":[{"dateAggrType":"daily","details":[]}]}',
        ):
            with pytest.raises(ValueError):
                config.select_url(invalid)
        request = OKXArchiveRequest(
            config=config,
            implementation_identity="a" * 64,
            index_sha256=hashlib.sha256(index).hexdigest(),
            url=config.select_url(index),
            index_received=datetime.now(UTC),
        )
        assert len(request.identity) == 64
        with pytest.raises(ValueError):
            replace(config, quote_currency="USD")

    @pytest.mark.parametrize(
        "status,headers",
        [
            (403, ""),
            (429, ""),
            (302, "Location: https://elsewhere.invalid\r\n"),
            (200, "Content-Length: 101\r\n"),
            (200, "Content-Length: 5\r\n"),
            (200, "Content-Encoding: gzip\r\n"),
        ],
    )
    def test_transport_rejects_access_redirect_and_size_failures(
        self, tmp_path: Path, status: int, headers: str
    ) -> None:
        """Never admit denied, redirected, oversized, recoded or truncated responses."""
        config = replace(HistoryFixture.config(), max_bytes=100)
        request = OKXArchiveRequest(
            config=config,
            implementation_identity="a" * 64,
            index_sha256="b" * 64,
            url=f"https://static.okx.com/cdn/okx/match/orderbook/pro/L2/400lv/daily/{config.day:%Y%m%d}/{config.filename}",
            index_received=datetime.now(UTC),
        )
        http = ArchiveHTTP(status, headers, b"123")
        with (
            patch.object(HTTPSConnection, "request", side_effect=http.request),
            patch.object(HTTPSConnection, "getresponse", side_effect=http.respond),
        ):
            with pytest.raises((OSError, ValueError)):
                OKXHistoryTransport(config).download(
                    request, tmp_path / "part", time.monotonic() + 5
                )

    def test_transport_streams_exact_bytes_without_content_length(self, tmp_path: Path) -> None:
        """Count actual received bytes and reject an oversized chunk even without a header."""
        config = HistoryFixture.config()
        index = HistoryFixture.index(config)
        request = OKXArchiveRequest(
            config=config,
            implementation_identity="a" * 64,
            index_sha256=hashlib.sha256(index).hexdigest(),
            url=config.select_url(index),
            index_received=datetime.now(UTC),
        )
        http = ArchiveHTTP(200, "", b"123")
        with (
            patch.object(HTTPSConnection, "request", side_effect=http.request),
            patch.object(HTTPSConnection, "getresponse", side_effect=http.respond),
        ):
            OKXHistoryTransport(config).download(
                request, tmp_path / "success", time.monotonic() + 5
            )
            assert (tmp_path / "success").read_bytes() == b"123"
            smaller = replace(request, config=replace(config, max_bytes=2))
            with pytest.raises(ValueError, match="compressed"):
                OKXHistoryTransport(smaller.config).download(
                    smaller, tmp_path / "over", time.monotonic() + 5
                )
