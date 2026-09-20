"""Describe the SDK endpoint inspection used to bind publication receipts to a server."""

class Session:
    """Expose configured API host without exposing credentials."""
    @classmethod
    def get_api_server_host(cls) -> str:
        """Read the SDK's resolved API endpoint.

        Returns:
            Configured server URL, validated against the retained destination.
        """
        ...
