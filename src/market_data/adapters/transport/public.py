"""Fetch bounded, unauthenticated market data from selected official HTTPS endpoints."""

# standard library imports
import http.client
import ssl
import time


class PublicHTTPS:
    """Bound response size, socket inactivity and transient retries without credential access."""

    def __init__(self, *, max_bytes: int, timeout_seconds: int) -> None:
        """Bind positive byte and timeout limits for one sequential ingestion worker."""
        if (
            type(max_bytes) is not int
            or max_bytes <= 0
            or type(timeout_seconds) is not int
            or not 1 <= timeout_seconds <= 60
        ):
            raise ValueError("invalid public HTTP limits")
        self._max_bytes, self._timeout = max_bytes, timeout_seconds

    def get(self, host: str, path: str) -> bytes:
        """Fetch exact identity-encoded bytes with at most two rate-limited retries.

        Only public market/reference paths are allowed. Redirects, credentials,
        compressed bodies, application errors and malformed bytes are not retried.
        """
        allowed = {
            "www.okx.com": ("/api/v5/market/", "/api/v5/public/instruments?"),
            "api-pub.bitfinex.com": ("/v2/trades/", "/v2/conf/"),
        }
        if (
            host not in allowed
            or not path.startswith(allowed[host])
            or any(c in path for c in ("\r", "\n", "#"))
        ):
            raise ValueError("unadmitted public endpoint")
        for attempt in range(3):
            connection = http.client.HTTPSConnection(
                host, timeout=self._timeout, context=ssl.create_default_context()
            )
            try:
                connection.request(
                    "GET",
                    path,
                    headers={"Accept-Encoding": "identity", "User-Agent": "alpha-public-data/1"},
                )
                response = connection.getresponse()
                if response.status in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
                if (
                    response.status != 200
                    or response.getheader("Content-Encoding", "identity") != "identity"
                ):
                    raise OSError(
                        f"public market data HTTP status/encoding refused: {response.status}"
                    )
                payload = response.read(self._max_bytes + 1)
                if len(payload) > self._max_bytes:
                    raise ValueError("public response exceeds byte budget")
                return payload
            finally:
                connection.close()
        raise OSError("public request retries exhausted")
