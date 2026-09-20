"""Describe consumed lakeFS 1.86.0 connection configuration."""

class Configuration:
    """Describe explicit endpoint and private client credentials."""
    def __init__(self, host: str = ..., username: str = ..., password: str = ...) -> None:
        """Configure a connection without retained credentials.

        Args:
            host: Explicit API base URL.
            username: Private access key.
            password: Private secret key.
        """
        ...

class ApiClient:
    """Describe a caller-owned SDK connection pool."""
    def __init__(self, configuration: Configuration) -> None:
        """Bind explicit configuration.

        Args:
            configuration: Endpoint and credentials.
        """
        ...
    def close(self) -> None:
        """Close the connection pool."""
        ...

class Ref:
    """Describe the resolved immutable reference."""

    commit_id: str

class Commit:
    """Describe the immutable commit identity."""

    id: str
