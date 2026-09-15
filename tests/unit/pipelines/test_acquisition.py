"""Exercise the complete raw acquisition consumer through an injected HTTP boundary."""

from __future__ import annotations

# standard library imports
import gzip
import hashlib
import socket
from datetime import UTC, datetime, timedelta
from http.client import HTTPResponse, HTTPSConnection, IncompleteRead
from io import BufferedReader, BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from alpha_research.configuration import Configuration, DataJob
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.pipelines.acquisition import fetch_partition
from alpha_research.pipelines.dataset import inspect_fixture
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()
_RECEIVED = datetime(2026, 9, 15, tzinfo=UTC)


class _HTTPFixture:
    """Supply parsed HTTP responses without connecting to a network or printing headers."""

    def __init__(self, body: bytes, *, status: int = 200, headers: str = "") -> None:
        """Retain one synthetic wire response.

        Args:
            body: Raw compressed response body.
            status: HTTP status to inject.
            headers: Explicit response headers; empty selects gzip and exact length.
        """
        headers = headers or f"Content-Encoding: gzip\r\nContent-Length: {len(body)}\r\n"
        self._wire = f"HTTP/1.1 {status} Synthetic\r\n{headers}\r\n".encode() + body
        self.url = ""
        self.headers: dict[str, str] = {}
        self.response: HTTPResponse | None = None

    def record(self, method: str, url: str, *, headers: dict[str, str]) -> None:
        """Record request construction without source access."""
        assert method == "GET"
        self.url, self.headers = url, headers

    def respond(self) -> HTTPResponse:
        """Parse the wire fixture with the same HTTPResponse used by HTTPSConnection."""
        with socket.socket() as sock:
            response = HTTPResponse(sock)
        assert response.fp is not None
        response.fp.close()
        response.fp = BufferedReader(BytesIO(self._wire))
        response.begin()
        self.response = response
        return response


class TestAcquisition:
    """Protect HTTP failures, identity, safe progress and durable publication together."""

    @pytest.fixture()
    def request_partition(self) -> SourceRequest:
        """Resolve a synthetic acquisition job with the real configuration codec.

        Returns:
            First selected minute with explicit synthetic-only rights evidence.
        """
        configuration = Configuration.read(_ROOT / "configs/data-jobs/fixture-inspection.json")
        job = replace(configuration.jobs[0], mode="historical", pipeline="acquisition.fetch")
        job = _CODEC.decode_json(_CODEC.encode_json(job), DataJob)
        configuration = replace(configuration, jobs=(job,))
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        return SourceRequest.partition(configuration.resolve(job.name, catalog))[0]

    @staticmethod
    def _run(
        request: SourceRequest,
        destination: Path,
        reports: list[str],
        *,
        max_bytes: int = 4096,
        rights: str = "synthetic-local-fixtures-v1",
    ) -> RawObject:
        """Call the installed pipeline with independent original local clock readings."""
        clocks = iter((_RECEIVED, _RECEIVED + timedelta(seconds=1)))
        return fetch_partition(
            request,
            store=RawStore(destination),
            connection=HTTPSConnection("api.tardis.dev"),
            clock=clocks.__next__,
            report=reports.append,
            timeout_seconds=0.5,
            max_bytes=max_bytes,
            permitted_rights_reference=rights,
            api_key="synthetic-secret",
        )

    @pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT"])
    def test_fetch_stores_exact_gzip_and_reports_original_clocks(
        self, request_partition: SourceRequest, tmp_path: Path, symbol: str
    ) -> None:
        """Onboard a second supported instrument by selection without changing shared code."""
        original = request_partition.manifest
        instrument = next(item for item in original.catalog.instruments if item.symbol == symbol)
        manifest = replace(original, instruments=(instrument,))
        request = SourceRequest(manifest=manifest, instrument=instrument, offset_minutes=3)
        frame = (_ROOT / f"tests/fixtures/m0/{symbol.lower()}.txt").read_bytes()
        frame = frame.replace(b"00:00:00.0041023Z", b"00:03:00.0041023Z")
        payload = gzip.compress(frame + b"\n", mtime=0)
        exchange = _HTTPFixture(payload)
        reports: list[str] = []
        with (
            patch.object(HTTPSConnection, "request", exchange.record),
            patch.object(HTTPSConnection, "getresponse", exchange.respond),
        ):
            descriptor = self._run(request, tmp_path, reports)
        assert exchange.response is not None and exchange.response.isclosed()
        query = parse_qs(urlsplit(exchange.url).query)
        assert urlsplit(exchange.url).path == "/v1/data-feeds/binance"
        assert query == {
            "from": [manifest.job.start.isoformat()],
            "offset": ["3"],
            "sliceSize": ["1"],
            "compression": ["gzip"],
            "filters": [
                '[{"channel":"trade","symbols":["SYMBOL"]}]'.replace("SYMBOL", symbol.lower())
            ],
        }
        assert exchange.headers["Authorization"] == "Bearer synthetic-secret"
        assert descriptor.sha256 == hashlib.sha256(payload).hexdigest()
        assert descriptor.ts_received == _RECEIVED
        assert descriptor.ts_ingested == _RECEIVED + timedelta(seconds=1)
        assert descriptor.request_identity == request.identity
        restored = _CODEC.decode_json(_CODEC.encode_json(descriptor), RawObject)
        with RawStore(tmp_path).open(descriptor=restored, request=request) as saved:
            assert saved.read() == payload
        assert list(tmp_path.iterdir()) == [tmp_path / descriptor.sha256]
        records = [msgspec.json.Decoder(dict[str, str | int]).decode(row) for row in reports]
        assert [row["status"] for row in records] == ["started", "received", "stored"]
        assert all(row["run_identity"] == manifest.identity for row in records)
        assert records[-1]["bytes"] == len(payload)
        assert "synthetic-secret" not in "".join(reports) + _CODEC.encode_json(descriptor).decode()

    @pytest.mark.parametrize(
        ("payload", "status", "headers", "error_type", "message"),
        [
            (b"secret error body", 401, "", PermissionError, "401"),
            (b"secret error body", 403, "", PermissionError, "403"),
            (b"redirect", 302, "Location: https://example.com\r\n", OSError, "302"),
            (b"unavailable", 503, "", OSError, "503"),
            (b"not gzip", 200, "", ValueError, "gzip"),
            (gzip.compress(b"hello", mtime=0)[:-4], 200, "", ValueError, "truncated"),
            (b"", 200, "", ValueError, "empty"),
            (gzip.compress(b"x"), 200, "Content-Encoding: identity\r\n", ValueError, "encoding"),
            (
                gzip.compress(b"x"),
                200,
                "Content-Encoding: gzip\r\nx-slice-size: 2\r\n",
                ValueError,
                "minute",
            ),
            (
                gzip.compress(b"x"),
                200,
                "Content-Encoding: gzip\r\nContent-Length: 99\r\n",
                ValueError,
                "Length",
            ),
            (
                gzip.compress(b"x"),
                200,
                "Content-Encoding: gzip\r\nContent-Length: bad\r\n",
                ValueError,
                "Length",
            ),
        ],
    )
    def test_invalid_response_never_publishes(
        self,
        request_partition: SourceRequest,
        tmp_path: Path,
        payload: bytes,
        status: int,
        headers: str,
        error_type: type[Exception],
        message: str,
    ) -> None:
        """Fail HTTP, encoding, size and gzip integrity without leaking response content."""
        exchange = _HTTPFixture(payload, status=status, headers=headers)
        reports: list[str] = []
        with (
            patch.object(HTTPSConnection, "request", exchange.record),
            patch.object(HTTPSConnection, "getresponse", exchange.respond),
            pytest.raises(error_type, match=message),
        ):
            self._run(request_partition, tmp_path, reports)
        assert list(tmp_path.iterdir()) == []
        assert '"status":"failed"' in reports[-1]
        assert "secret" not in "".join(reports)
        assert exchange.response is not None and exchange.response.isclosed()

    @pytest.mark.parametrize("failure", [TimeoutError("secret"), IncompleteRead(b"secret")])
    def test_transport_timeout_and_truncation_report_failure(
        self, request_partition: SourceRequest, tmp_path: Path, failure: Exception
    ) -> None:
        """Report connection/protocol failure and permit a later independent invocation."""
        reports: list[str] = []
        with patch.object(HTTPSConnection, "request", side_effect=failure), pytest.raises(OSError):
            self._run(request_partition, tmp_path, reports)
        assert list(tmp_path.iterdir()) == []
        assert '"status":"failed"' in reports[-1]
        assert "secret" not in "".join(reports)
        exchange = _HTTPFixture(gzip.compress(b"", mtime=0))
        with (
            patch.object(HTTPSConnection, "request", exchange.record),
            patch.object(HTTPSConnection, "getresponse", exchange.respond),
        ):
            self._run(request_partition, tmp_path, reports)
        assert '"status":"stored"' in reports[-1]

    @pytest.mark.parametrize("payload", [b"z" * 33, gzip.compress(b"x" * 1000, mtime=0)])
    def test_compressed_and_expanded_limits(
        self, request_partition: SourceRequest, tmp_path: Path, payload: bytes
    ) -> None:
        """Bound both representations, including compressed bombs, before publication."""
        exchange = _HTTPFixture(payload)
        with (
            patch.object(HTTPSConnection, "request", exchange.record),
            patch.object(HTTPSConnection, "getresponse", exchange.respond),
            pytest.raises(ValueError, match="max_bytes"),
        ):
            self._run(request_partition, tmp_path, [], max_bytes=32)
        assert list(tmp_path.iterdir()) == []

    def test_invalid_admission_selection_and_unsafe_request_fail_before_http(
        self, request_partition: SourceRequest, tmp_path: Path
    ) -> None:
        """Do not let saved-fixture selections, unsupported copies or absent rights fetch."""
        with patch.object(
            HTTPSConnection, "request", side_effect=AssertionError("unexpected HTTP")
        ):
            for rights in ("", "unresolved", "other-evidence"):
                with pytest.raises(ValueError, match="rights"):
                    self._run(request_partition, tmp_path, [], rights=rights)
            unresolved = replace(
                request_partition,
                manifest=replace(
                    request_partition.manifest,
                    job=replace(request_partition.manifest.job, rights_reference="unresolved"),
                ),
            )
            with pytest.raises(ValueError, match="rights"):
                self._run(unresolved, tmp_path, [], rights="unresolved")
            fixture_job = replace(
                request_partition.manifest.job, mode="fixture", pipeline="dataset.inspect"
            )
            fixture = replace(
                request_partition, manifest=replace(request_partition.manifest, job=fixture_job)
            )
            with pytest.raises(ValueError, match="historical"):
                self._run(fixture, tmp_path, [])
            with pytest.raises(ValueError, match="mode/pipeline"):
                replace(fixture_job, mode="historical")
            msgspec.structs.force_setattr(request_partition, "offset_minutes", -1)
            with pytest.raises(ValueError, match="offset"):
                self._run(request_partition, tmp_path, [])
        assert list(tmp_path.iterdir()) == []

    def test_store_failure_and_wrong_consumer_are_visible(
        self, request_partition: SourceRequest, tmp_path: Path
    ) -> None:
        """Storage failure cannot emit stored; fixture inspection cannot activate acquisition."""
        exchange = _HTTPFixture(gzip.compress(b"", mtime=0))
        reports: list[str] = []
        with (
            patch.object(HTTPSConnection, "request", exchange.record),
            patch.object(HTTPSConnection, "getresponse", exchange.respond),
            pytest.raises(FileNotFoundError),
        ):
            self._run(request_partition, tmp_path / "missing", reports)
        assert '"stage":"store"' in reports[-1] and '"status":"failed"' in reports[-1]
        with pytest.raises(ValueError, match=r"dataset\.inspect"):
            inspect_fixture(
                request_partition.manifest,
                tmp_path / "absent",
                local_received=_RECEIVED,
                local_ingested=_RECEIVED,
                source_sequence=0,
            )

    @pytest.mark.parametrize("timeout", [0.0, -1.0, float("inf"), float("nan")])
    def test_invalid_timeout_is_reported_without_network(
        self, request_partition: SourceRequest, tmp_path: Path, timeout: float
    ) -> None:
        """Reject unbounded or nonpositive socket timeouts at the consumer boundary."""
        reports: list[str] = []
        with pytest.raises(ValueError, match="timeout_seconds"):
            fetch_partition(
                request_partition,
                store=RawStore(tmp_path),
                connection=HTTPSConnection("api.tardis.dev"),
                clock=self._clock,
                report=reports.append,
                timeout_seconds=timeout,
                max_bytes=32,
                permitted_rights_reference="synthetic-local-fixtures-v1",
            )
        assert '"status":"failed"' in reports[-1]

    @staticmethod
    def _clock() -> datetime:
        """Supply a fixed UTC instant for preflight-only cases."""
        return _RECEIVED

    def test_body_timeout_and_credential_errors_do_not_leak_or_publish(
        self, request_partition: SourceRequest, tmp_path: Path
    ) -> None:
        """Handle inactivity during response reading and reject unsafe header values safely."""
        exchange = _HTTPFixture(gzip.compress(b"", mtime=0))
        reports: list[str] = []
        with (
            patch.object(HTTPSConnection, "request", exchange.record),
            patch.object(HTTPSConnection, "getresponse", exchange.respond),
            patch.object(HTTPResponse, "read", side_effect=TimeoutError("private-detail")),
            pytest.raises(TimeoutError),
        ):
            self._run(request_partition, tmp_path, reports)
        assert exchange.response is not None and exchange.response.isclosed()
        assert '"status":"failed"' in reports[-1] and "private-detail" not in reports[-1]
        for key in ("", "secret\r\ninjected", "secret\u2603"):
            with pytest.raises(ValueError, match="credential") as error:
                fetch_partition(
                    request_partition,
                    store=RawStore(tmp_path),
                    connection=HTTPSConnection("api.tardis.dev"),
                    clock=self._clock,
                    report=reports.append,
                    timeout_seconds=1.0,
                    max_bytes=32,
                    permitted_rights_reference="synthetic-local-fixtures-v1",
                    api_key=key,
                )
            assert "secret" not in str(error.value)
        assert list(tmp_path.iterdir()) == []
