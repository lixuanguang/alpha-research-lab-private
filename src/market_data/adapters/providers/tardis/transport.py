"""Fetch one bounded gzip response from the Tardis raw replay endpoint."""

from __future__ import annotations

# standard library imports
import gzip
import math
from http.client import HTTPException, HTTPSConnection
from io import BytesIO
from urllib.parse import urlencode
from zlib import error as ZlibError

# project library imports
from market_data.contracts import SourceRequest
from market_data.contracts import TransientFetchError as TransientFetchError
from serialization import DomainCodec


class TardisTransport:
    """Own one-request HTTP and gzip validation, leaving frame interpretation to readers."""

    def __init__(
        self, connection: HTTPSConnection, *, timeout_seconds: float, max_bytes: int
    ) -> None:
        """Bind a caller-supplied, unopened HTTPS connection and explicit resource limits.

        Args:
            connection: Connection to api.tardis.dev, or an injected test connection.
                This adapter closes it after each attempt; disable HTTP debug logging.
            timeout_seconds: Finite positive socket inactivity timeout in seconds.
            max_bytes: Positive cap applied separately to compressed and expanded bytes.

        Raises:
            ValueError: Host, debug setting or resource bounds are invalid.
        """
        if connection.host != "api.tardis.dev" or connection.debuglevel:
            raise ValueError("Tardis requires api.tardis.dev with HTTP debug logging disabled")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        connection.timeout = timeout_seconds
        self._connection = connection
        self._max_bytes = max_bytes

    def fetch(
        self, request: SourceRequest, *, permitted_rights_reference: str, api_key: str | None
    ) -> bytes:
        """Validate selection and explicit admission, then fetch exact compressed bytes.

        Args:
            request: Resolved historical acquisition request for one instrument/minute.
            permitted_rights_reference: Caller-confirmed dated evidence covering access,
                intended use, retention and destination; must match the job reference.
                A matching string is an attestation, not automatic legal verification.
            api_key: Explicit credential, or None for a permitted keyless sample.

        Returns:
            Original gzip bytes after HTTP length and complete gzip integrity checks.
            Empty expanded content is representable, without a coverage claim.

        Raises:
            ValueError: Selection, admission, response encoding, size or gzip is invalid.
            PermissionError: HTTP authentication or entitlement failed.
            TransientFetchError: Retryable status, timeout, connection or protocol failure.
            OSError: HTTP status, network or protocol failure; no retry is performed.
        """
        request.__post_init__()
        job = request.manifest.job
        if (job.provider, job.mode, job.pipeline) != ("tardis", "historical", "acquisition.fetch"):
            raise ValueError("Tardis fetch requires historical/acquisition.fetch selection")
        if (
            not permitted_rights_reference
            or permitted_rights_reference != job.rights_reference
            or permitted_rights_reference.casefold() in {"unresolved", "unknown", "pending"}
        ):
            raise ValueError("source access requires matching permitted rights evidence")
        parameters = {
            "from": job.start.isoformat(),
            "offset": str(request.offset_minutes),
            "sliceSize": "1",
            "compression": "gzip",
            "filters": DomainCodec()
            .encode_json([{"channel": job.stream, "symbols": [request.instrument.symbol.lower()]}])
            .decode(),
        }
        headers = {"Accept-Encoding": "gzip"}
        if api_key is not None:
            if not api_key or not api_key.isascii() or not api_key.isprintable():
                raise ValueError("Tardis credential must contain printable ASCII characters")
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            self._connection.request(
                "GET", f"/v1/data-feeds/{job.venue}?{urlencode(parameters)}", headers=headers
            )
            with self._connection.getresponse() as response:
                if response.status in (401, 403):
                    raise PermissionError(f"Tardis access denied (HTTP {response.status})")
                if response.status in (408, 429, 500, 502, 503, 504):
                    raise TransientFetchError(f"Tardis temporary failure (HTTP {response.status})")
                if response.status != 200:
                    raise OSError(f"Tardis fetch failed (HTTP {response.status})")
                if response.getheader("Content-Encoding") != "gzip":
                    raise ValueError("Tardis response must use gzip content encoding")
                if response.getheader("x-slice-size", "1") != "1":
                    raise ValueError("Tardis response must contain one minute")
                payload = response.read(self._max_bytes + 1)
                length = response.getheader("Content-Length")
                if length is not None and (
                    not length.isascii() or not length.isdecimal() or int(length) != len(payload)
                ):
                    raise ValueError("Tardis response Content-Length mismatch")
            if not payload or len(payload) > self._max_bytes:
                raise ValueError("Tardis compressed response is empty or exceeds max_bytes")
            with gzip.GzipFile(fileobj=BytesIO(payload)) as expanded:
                if len(expanded.read(self._max_bytes + 1)) > self._max_bytes:
                    raise ValueError("Tardis expanded response exceeds max_bytes")
            return payload
        except (EOFError, gzip.BadGzipFile, ZlibError) as error:
            raise ValueError("Tardis response has invalid or truncated gzip bytes") from error
        except (TimeoutError, ConnectionError, HTTPException) as error:
            raise TransientFetchError("Tardis transient network/protocol failure") from error
        finally:
            self._connection.close()
