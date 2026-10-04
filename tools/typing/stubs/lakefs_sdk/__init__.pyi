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

class RepositoryCreation:
    """Describe an explicit repository creation request."""
    def __init__(self, *, name: str, storage_namespace: str, default_branch: str) -> None:
        """Name the repository, its storage namespace and default branch.

        Args:
            name: Repository name.
            storage_namespace: Storage location, such as ``local://name``.
            default_branch: Initial branch name.
        """
        ...

class CommitCreation:
    """Describe an explicit commit request."""
    def __init__(self, *, message: str) -> None:
        """Bind the commit message.

        Args:
            message: Human-readable commit message.
        """
        ...
