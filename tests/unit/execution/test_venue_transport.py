"""Bound the venue REST transport by its caller's absolute deadline."""

from __future__ import annotations

# standard library imports
import socket
import ssl
import threading
import time
from collections.abc import Callable
from functools import partial
from http.client import HTTPConnection
from ssl import SSLContext
from typing import cast

# third party library imports
import pytest

# project library imports
from execution.venues import TlsVenueHttpTransport
from execution.venues import transport as transport_module
from execution.venues.contracts import (
    VenueHttpRequest,
    VenueNotSentError,
    VenueOutcomeUnknownError,
)


class LocalVenue:
    """Accept one plain-TCP connection and answer it with a scripted behaviour."""

    def __init__(self, answer: Callable[[socket.socket], None]) -> None:
        """Listen on a loopback port and serve one connection in the background."""
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = cast(tuple[str, int], self.listener.getsockname())[1]
        self.received = b""
        self._answer = answer
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        """Read the request head, then run the scripted answer."""
        try:
            connection, _ = self.listener.accept()
        except OSError:
            return
        with connection:
            connection.settimeout(5)
            try:
                while b"\r\n\r\n" not in self.received:
                    chunk = connection.recv(65_536)
                    if not chunk:
                        return
                    self.received += chunk
                self._answer(connection)
            except OSError:
                return

    def close(self) -> None:
        """Stop listening."""
        self.listener.close()
        self._thread.join(5)


class Loopback:
    """Where the transport's pinned host is routed, and how slowly it connects."""

    def __init__(self) -> None:
        """Start with no venue, no connect delay and no connect failure."""
        self.port = 0
        self.delay = 0.0
        self.failure: OSError | None = None

    def serve(self, answer: Callable[[socket.socket], None]) -> LocalVenue:
        """Start a local venue and route the next connection to it."""
        venue = LocalVenue(answer)
        self.port = venue.port
        return venue


class TestVenueTransport:
    """The whole request, not only each socket operation, fits the dispatch lease."""

    request = VenueHttpRequest(
        method="POST", path="/v2/auth/w/order/submit", body=b"{}", headers=()
    )

    def test_deadline_passing_before_the_send_writes_nothing(self, loopback: Loopback) -> None:
        """A slow connect past the deadline refuses as unsent before any request byte."""
        venue = loopback.serve(TestVenueTransport.ok)
        loopback.delay = 0.3
        transport = TlsVenueHttpTransport("bitfinex", timeout_seconds=1.0, total_seconds=5.0)
        with pytest.raises(VenueNotSentError):
            transport.request(self.request, deadline=time.monotonic() + 0.1)
        venue.close()
        assert venue.received == b""

    def test_trickled_response_after_close_is_bounded_by_the_deadline(
        self, loopback: Loopback
    ) -> None:
        """A body arriving within each socket timeout still ends at the total deadline."""
        venue = loopback.serve(TestVenueTransport.trickle)
        transport = TlsVenueHttpTransport("bitfinex", timeout_seconds=1.0, total_seconds=5.0)
        started = time.monotonic()
        with pytest.raises(VenueOutcomeUnknownError):
            transport.request(self.request, deadline=started + 0.5)
        assert time.monotonic() - started < 1.5
        venue.close()
        assert venue.received.startswith(b"POST /v2/auth/w/order/submit")

    def test_own_total_bounds_a_request_without_a_deadline(self, loopback: Loopback) -> None:
        """Lookups pass no deadline and stay within the transport's own total."""
        venue = loopback.serve(TestVenueTransport.trickle)
        transport = TlsVenueHttpTransport("bitfinex", timeout_seconds=1.0, total_seconds=1.0)
        started = time.monotonic()
        with pytest.raises(VenueOutcomeUnknownError):
            transport.request(self.request)
        assert time.monotonic() - started < 2.0
        venue.close()

    def test_answer_within_the_deadline_is_returned(self, loopback: Loopback) -> None:
        """A prompt venue answer is unaffected by the deadline."""
        venue = loopback.serve(TestVenueTransport.ok)
        transport = TlsVenueHttpTransport("bitfinex")
        response = transport.request(self.request, deadline=time.monotonic() + 5)
        venue.close()
        assert (response.status, response.body) == (200, b"{}")

    @pytest.mark.parametrize(
        "answer",
        [
            b"garbage\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nX-Long: " + b"a" * 70_000 + b"\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\n",
            b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\nConnection: close\r\n\r\n{}",
        ],
        ids=["bad-status-line", "line-too-long", "bad-chunk", "truncated-body"],
    )
    def test_malformed_response_after_the_send_is_outcome_unknown(
        self, loopback: Loopback, answer: bytes
    ) -> None:
        """A response HTTP cannot complete leaves the sent request's outcome unknown."""
        venue = loopback.serve(partial(self._answer, answer))
        transport = TlsVenueHttpTransport("bitfinex", timeout_seconds=1.0, total_seconds=5.0)
        with pytest.raises(VenueOutcomeUnknownError):
            transport.request(self.request, deadline=time.monotonic() + 5)
        venue.close()
        assert venue.received.startswith(b"POST /v2/auth/w/order/submit")

    @pytest.mark.parametrize(
        "failure",
        [
            socket.gaierror(socket.EAI_NONAME, "name does not resolve"),
            ssl.SSLCertVerificationError("certificate verify failed"),
            ConnectionResetError("reset during the handshake"),
        ],
        ids=["dns", "tls", "reset"],
    )
    def test_connect_failure_is_not_sent(self, loopback: Loopback, failure: OSError) -> None:
        """Resolution, TCP and TLS failures happen before any request byte is written."""
        venue = loopback.serve(TestVenueTransport.ok)
        loopback.failure = failure
        transport = TlsVenueHttpTransport("bitfinex", timeout_seconds=1.0, total_seconds=5.0)
        with pytest.raises(VenueNotSentError):
            transport.request(self.request, deadline=time.monotonic() + 5)
        venue.close()
        assert venue.received == b""

    def test_refused_connection_is_not_sent(self, loopback: Loopback) -> None:
        """A venue port that refuses the TCP connection received nothing."""
        closed = socket.create_server(("127.0.0.1", 0))
        loopback.port = cast(tuple[str, int], closed.getsockname())[1]
        closed.close()
        transport = TlsVenueHttpTransport("bitfinex", timeout_seconds=1.0, total_seconds=5.0)
        with pytest.raises(VenueNotSentError):
            transport.request(self.request, deadline=time.monotonic() + 5)

    @pytest.fixture()
    def loopback(self, monkeypatch: pytest.MonkeyPatch) -> Loopback:
        """Route the pinned TLS host to a loopback plain connection."""
        route = Loopback()

        class LoopbackConnection(HTTPConnection):
            """Plain HTTP to the local venue; the TLS context is irrelevant here."""

            def __init__(self, host: str, *, timeout: float, context: SSLContext) -> None:
                """Ignore the pinned host and TLS context."""
                del host, context
                super().__init__("127.0.0.1", route.port, timeout=timeout)

            def connect(self) -> None:
                """Stand in for slow or failing resolution, TCP connection or TLS handshake."""
                time.sleep(route.delay)
                if route.failure is not None:
                    raise route.failure
                super().connect()

        monkeypatch.setattr(transport_module, "HTTPSConnection", LoopbackConnection)
        return route

    @staticmethod
    def _answer(answer: bytes, connection: socket.socket) -> None:
        """Send one fixed response and nothing else."""
        connection.sendall(answer)

    @staticmethod
    def trickle(connection: socket.socket) -> None:
        """Send headers, then one body byte every 50 ms for three seconds, then close."""
        connection.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\nConnection: close\r\n\r\n"
        )
        for _ in range(60):
            connection.sendall(b"x")
            time.sleep(0.05)

    @staticmethod
    def ok(connection: socket.socket) -> None:
        """Answer at once."""
        connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
