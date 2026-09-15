"""Share retry classification across supported acquisition transports."""


class TransientFetchError(OSError):
    """Identify retryable HTTP/network failures without exposing response bodies."""
