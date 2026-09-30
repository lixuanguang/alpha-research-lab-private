"""Bounded TLS REST and private WebSocket transport for fixed venue hosts."""

from __future__ import annotations

# standard library imports
import time
from datetime import UTC, datetime
from http.client import HTTPSConnection
from ssl import create_default_context
from typing import Literal

# third party library imports
from websockets.exceptions import WebSocketException
from websockets.sync.client import ClientConnection, connect

# project library imports
from execution.venues.contracts import (
    VenueHttpRequest,
    VenueHttpResponse,
    VenueOutcomeUnknownError,
    VenueProtocolError,
)


class TlsVenueHttpTransport:
    """Make one bounded HTTPS request without redirects, retries, or chosen hosts."""

    def __init__(
        self,
        venue: Literal["okx", "bitfinex"],
        *,
        timeout_seconds: float = 5.0,
        total_seconds: float = 20.0,
        max_response_bytes: int = 1_048_576,
    ) -> None:
        """Pin the documented venue host and resource bounds.

        ``timeout_seconds`` bounds each socket operation; ``total_seconds`` bounds
        the whole request, which a dispatch lease relies on.
        """
        if (
            venue not in ("okx", "bitfinex")
            or not 0 < timeout_seconds <= total_seconds
            or max_response_bytes <= 0
        ):
            raise ValueError("invalid venue transport configuration")
        self.host = "openapi.okx.com" if venue == "okx" else "api.bitfinex.com"
        self.timeout_seconds = timeout_seconds
        self.total_seconds = total_seconds
        self.max_response_bytes = max_response_bytes

    def request(self, request: VenueHttpRequest) -> VenueHttpResponse:
        """Retain status and raw body while leaving outcome classification to adapter."""
        if (
            not request.path.startswith("/")
            or request.path.startswith("//")
            or "://" in request.path
        ):
            raise VenueProtocolError("venue request path must be relative to fixed host")
        deadline = time.monotonic() + self.total_seconds
        connection = HTTPSConnection(
            self.host, timeout=self.timeout_seconds, context=create_default_context()
        )
        try:
            connection.request(
                request.method,
                request.path,
                body=request.body if request.method == "POST" else None,
                headers=dict(request.headers),
            )
            self._limit(connection, deadline)
            response = connection.getresponse()
            chunks: list[bytes] = []
            size = 0
            while size <= self.max_response_bytes:
                self._limit(connection, deadline)
                chunk = response.read(min(65_536, self.max_response_bytes + 1 - size))
                if type(chunk) is not bytes:
                    raise VenueProtocolError("venue REST response is not bytes")
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            body = b"".join(chunks)
            if len(body) > self.max_response_bytes:
                raise VenueProtocolError("venue REST response exceeds bound or is not bytes")
            status = response.status
            if type(status) is not int:
                raise VenueProtocolError("venue REST response status is invalid")
        except (TimeoutError, OSError) as error:
            raise VenueOutcomeUnknownError("venue REST response outcome unknown") from error
        finally:
            connection.close()
        return VenueHttpResponse(status=status, body=body, received_at=datetime.now(UTC))

    def _limit(self, connection: HTTPSConnection, deadline: float) -> None:
        """Shorten the next socket wait to the request's remaining total time."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("venue REST request exceeded its total bound")
        if connection.sock is not None:
            connection.sock.settimeout(min(self.timeout_seconds, remaining))


class PrivateVenueSession:
    """Read bounded authenticated frames; reconnect only after REST reconciliation."""

    def __init__(
        self,
        venue: Literal["okx", "bitfinex"],
        *,
        timeout_seconds: float = 5.0,
        max_frame_bytes: int = 1_048_576,
    ) -> None:
        """Pin the non-live private endpoint and receive bounds."""
        if venue not in ("okx", "bitfinex") or timeout_seconds <= 0 or max_frame_bytes <= 0:
            raise ValueError("invalid private stream bounds")
        self.url = (
            "wss://wspap.okx.com:8443/ws/v5/private"
            if venue == "okx"
            else "wss://api.bitfinex.com/ws/2"
        )
        self.timeout_seconds = timeout_seconds
        self.max_frame_bytes = max_frame_bytes
        self.connection: ClientConnection | None = None
        self._waited = 0.0

    def open(self, login: bytes, *, configuration: tuple[bytes, ...] = ()) -> None:
        """Open a TLS socket and send the caller-signed login once."""
        if self.connection is not None:
            raise VenueProtocolError("private venue session already open")
        try:
            self.connection = connect(
                self.url,
                open_timeout=self.timeout_seconds,
                close_timeout=self.timeout_seconds,
                max_size=self.max_frame_bytes,
            )
            for frame in configuration:
                self.connection.send(frame.decode("utf-8"))
            self.connection.send(login.decode("utf-8"))
            self._waited = 0.0
        except (OSError, TimeoutError, WebSocketException) as error:
            self.close()
            raise VenueOutcomeUnknownError("private venue login transport failed") from error

    def send(self, frame: bytes) -> None:
        """Send one subscription after the adapter has verified login."""
        if self.connection is None:
            raise VenueProtocolError("private venue session is closed")
        try:
            self.connection.send(frame.decode("utf-8"))
        except (OSError, TimeoutError, WebSocketException) as error:
            self.close()
            raise VenueOutcomeUnknownError("private venue stream lost") from error

    def receive(self, wait_seconds: float | None = None) -> tuple[bytes, datetime] | None:
        """Return one bounded frame and UTC local receipt, or None after a quiet wait.

        The stream is lost after ``timeout_seconds`` spent waiting without a frame,
        counted across quiet returns but not across the caller's work in between.
        A shorter ``wait_seconds`` returns None when it passes without a frame.
        """
        if self.connection is None:
            raise VenueProtocolError("private venue session is closed")
        remaining = self.timeout_seconds - self._waited
        quiet = wait_seconds is not None and wait_seconds < remaining
        started = time.monotonic()
        try:
            frame = self.connection.recv(
                timeout=max(0.0, wait_seconds) if quiet and wait_seconds is not None else remaining
            )
        except TimeoutError as error:
            if quiet:
                self._waited += time.monotonic() - started
                return None
            self.close()
            raise VenueOutcomeUnknownError("private venue stream lost") from error
        except (OSError, WebSocketException) as error:
            self.close()
            raise VenueOutcomeUnknownError("private venue stream lost") from error
        self._waited = 0.0
        raw = frame.encode("utf-8") if isinstance(frame, str) else frame
        if len(raw) > self.max_frame_bytes:
            self.close()
            raise VenueProtocolError("private venue frame exceeds bound")
        return raw, datetime.now(UTC)

    def close(self) -> None:
        """End the session; caller must reconcile before starting a new one."""
        connection = self.connection
        self.connection = None
        if connection is not None:
            connection.close()
