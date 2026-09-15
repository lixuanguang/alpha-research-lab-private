"""Fetch and verify one Binance public daily individual-trade ZIP archive."""

from __future__ import annotations

# standard library imports
import hashlib
import math
import re
from http.client import HTTPException, HTTPSConnection
from io import BytesIO
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile
from zlib import error as ZlibError

# project library imports
from alpha_research.data.providers.transport import TransientFetchError
from alpha_research.data.requests import SourceRequest


class BinanceArchiveTransport:
    """Validate public HTTP, publisher SHA-256 and bounded ZIP integrity before storage."""

    def __init__(
        self, connection: HTTPSConnection, *, timeout_seconds: float, max_bytes: int
    ) -> None:
        """Bind an unopened connection and explicit compressed/expanded resource bounds.

        Args:
            connection: Connection to data.binance.vision with HTTP debug logging off.
            timeout_seconds: Finite positive socket inactivity timeout in seconds.
            max_bytes: Positive cap applied separately to ZIP and expanded CSV bytes.

        Raises:
            ValueError: Host, debug setting or resource bounds are invalid.
        """
        if connection.host != "data.binance.vision" or connection.debuglevel:
            raise ValueError(
                "Binance archives require data.binance.vision without HTTP debug logging"
            )
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        connection.timeout = timeout_seconds
        self._connection = connection
        self._max_bytes = max_bytes

    def _get(self, path: str, limit: int) -> bytes:
        """Read one bounded identity-encoded response, closing the connection on all paths."""
        try:
            self._connection.request("GET", path, headers={"Accept-Encoding": "identity"})
            with self._connection.getresponse() as response:
                if response.status in (401, 403):
                    raise PermissionError(f"Binance archive access denied (HTTP {response.status})")
                if response.status in (408, 429, 500, 502, 503, 504):
                    raise TransientFetchError(f"Binance temporary failure (HTTP {response.status})")
                if response.status != 200:
                    raise OSError(f"Binance archive fetch failed (HTTP {response.status})")
                if response.getheader("Content-Encoding", "identity") != "identity":
                    raise ValueError("Binance archive response has unsupported content encoding")
                payload = response.read(limit + 1)
                length = response.getheader("Content-Length")
                if length is not None and (
                    not length.isascii() or not length.isdecimal() or int(length) != len(payload)
                ):
                    raise ValueError("Binance archive Content-Length mismatch")
            if not payload or len(payload) > limit:
                raise ValueError("Binance archive response is empty or exceeds max_bytes")
            return payload
        except (TimeoutError, ConnectionError, HTTPException) as error:
            raise TransientFetchError("Binance transient network/protocol failure") from error
        finally:
            self._connection.close()

    def fetch(
        self, request: SourceRequest, *, permitted_rights_reference: str, api_key: str | None
    ) -> bytes:
        """Fetch an admitted daily archive and verify its published checksum and ZIP CRC.

        Args:
            request: Historical individual-trade request covering one complete UTC day.
            permitted_rights_reference: Caller-confirmed access/use record matching the job;
                string equality is an attestation, not automatic legal verification.
            api_key: Must be None; public archives neither require nor receive credentials.

        Returns:
            Exact ZIP bytes. CSV interpretation belongs to the later saved-input reader.

        Raises:
            ValueError: Selection, admission, credential, checksum or ZIP validation fails.
            OSError: HTTP/network access fails, with transient failures explicitly classified.
        """
        request.__post_init__()
        job = request.manifest.job
        if job.provider != "binance-archive" or api_key is not None:
            raise ValueError(
                "Binance archive fetch requires its selected provider and no credential"
            )
        if (
            not permitted_rights_reference
            or permitted_rights_reference != job.rights_reference
            or permitted_rights_reference.casefold() in {"unresolved", "unknown", "pending"}
        ):
            raise ValueError("source access requires matching permitted rights evidence")
        symbol = request.instrument.symbol
        name = f"{symbol}-trades-{request.start.date().isoformat()}"
        path = f"/data/spot/daily/trades/{symbol}/{name}.zip"
        checksum = self._get(path + ".CHECKSUM", 1024)
        match = re.fullmatch(
            rb"([0-9a-f]{64}) [ *]" + re.escape((name + ".zip").encode()) + rb"\n?", checksum
        )
        if match is None:
            raise ValueError("Binance checksum must identify the exact requested archive")
        payload = self._get(path, self._max_bytes)
        if hashlib.sha256(payload).hexdigest().encode() != match[1]:
            raise ValueError("Binance archive SHA-256 differs from publisher checksum")
        try:
            with ZipFile(BytesIO(payload)) as archive:
                entries = archive.infolist()
                if len(entries) != 1 or entries[0].filename != name + ".csv":
                    raise ValueError("Binance ZIP must contain exactly the requested CSV")
                entry = entries[0]
                if entry.compress_type != ZIP_DEFLATED or entry.flag_bits & 1:
                    raise ValueError("Binance ZIP must use unencrypted deflate")
                if not 0 < entry.file_size <= self._max_bytes:
                    raise ValueError("Binance expanded archive is empty or exceeds max_bytes")
                with archive.open(entry) as expanded:
                    size = 0
                    while chunk := expanded.read(min(1_048_576, self._max_bytes - size + 1)):
                        size += len(chunk)
                        if size > self._max_bytes:
                            raise ValueError("Binance expanded archive exceeds max_bytes")
                if size != entry.file_size:
                    raise ValueError("Binance expanded archive size mismatch")
        except (BadZipFile, EOFError, ZlibError) as error:
            raise ValueError("Binance archive has invalid or truncated ZIP bytes") from error
        return payload
