"""Download only discovered OKX public archives with finite time and byte budgets."""

from __future__ import annotations

# standard library imports
import http.client
import os
import ssl
import time
from pathlib import Path
from urllib.parse import urlsplit

# project library imports
from alpha_research.data.providers.transport import TransientFetchError
from alpha_research.data.venues.okx.history_config import OKXArchiveRequest, OKXHistoryConfig


class OKXHistoryTransport:
    """Own public HTTPS acquisition without credentials, redirects or private endpoints."""

    def __init__(self, config: OKXHistoryConfig) -> None:
        """Bind the selected UTC day and all network resource ceilings.

        Args:
            config: Validated public archive configuration.
        """
        config.__post_init__()
        self.config = config

    def index(self) -> bytes:
        """Read the bounded public download index for exactly one configured day.

        Returns:
            Original source index bytes for request provenance.

        Raises:
            ValueError: The response exceeds the metadata byte limit.
        """
        connection = self._connection("www.okx.com", self.config.timeout_seconds)
        try:
            connection.request(
                "GET", self.config.index_path, headers={"Accept-Encoding": "identity"}
            )
            response = connection.getresponse()
            self._status(response)
            raw = response.read(65_537)
            if len(raw) > 65_536:
                raise ValueError("OKX history index exceeds metadata budget")
            return raw
        finally:
            connection.close()

    def download(self, request: OKXArchiveRequest, destination: Path, deadline: float) -> None:
        """Stream one complete archive to an exclusive staging file and fsync it.

        Args:
            request: Validated discovery and exact CDN artifact binding.
            destination: New local staging file; never a completed raw object.
            deadline: Overall monotonic acquisition deadline shared across retries.

        Raises:
            ValueError: Source size, request binding or representation is invalid.
            TimeoutError: The acquisition duration is exhausted.
        """
        request.__post_init__()
        if request.config != self.config:
            raise ValueError("OKX transport configuration differs from request")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("OKX archive duration exhausted")
        connection = self._connection("static.okx.com", min(self.config.timeout_seconds, remaining))
        try:
            connection.request(
                "GET", urlsplit(request.url).path, headers={"Accept-Encoding": "identity"}
            )
            response = connection.getresponse()
            self._status(response)
            expected = response.getheader("Content-Length")
            if expected is not None and (
                not expected.isascii()
                or not expected.isdigit()
                or int(expected) > self.config.max_bytes
            ):
                raise ValueError("OKX archive Content-Length exceeds byte budget")
            total = 0
            with destination.open("xb") as output:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("OKX archive duration exhausted")
                    if connection.sock is not None:
                        connection.sock.settimeout(min(self.config.timeout_seconds, remaining))
                    chunk = response.read1(min(1_048_576, self.config.max_bytes - total + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.config.max_bytes:
                        raise ValueError("OKX archive exceeds compressed byte budget")
                    output.write(chunk)
                if not total or (expected is not None and int(expected) != total):
                    raise ValueError("OKX archive length is empty or incomplete")
                output.flush()
                os.fsync(output.fileno())
        except (http.client.HTTPException, ConnectionError) as error:
            raise TransientFetchError("OKX archive network failure") from error
        finally:
            connection.close()

    @staticmethod
    def _connection(host: str, timeout: float) -> http.client.HTTPSConnection:
        """Create a TLS-verifying connection without logging authentication or payloads."""
        return http.client.HTTPSConnection(
            host, timeout=timeout, context=ssl.create_default_context()
        )

    @staticmethod
    def _status(response: http.client.HTTPResponse) -> None:
        """Classify explicit access/temporary failures without following redirects."""
        if response.status in (401, 403):
            raise PermissionError(f"OKX public archive access denied (HTTP {response.status})")
        if response.status in (408, 429, 500, 502, 503, 504):
            raise TransientFetchError(f"OKX temporary archive failure (HTTP {response.status})")
        if response.status != 200:
            raise OSError(f"OKX archive HTTP status {response.status}")
        if response.getheader("Content-Encoding", "identity") != "identity":
            raise ValueError("OKX archive response changed content encoding")
