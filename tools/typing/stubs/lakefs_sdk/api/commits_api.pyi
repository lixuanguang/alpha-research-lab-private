"""Describe immutable lakeFS reference resolution."""

# third party library imports
from lakefs_sdk import ApiClient, Commit

class CommitsApi:
    """Describe explicit reference access."""
    def __init__(self, api_client: ApiClient) -> None:
        """Bind the selected client.

        Args:
            api_client: Caller-owned SDK client.
        """
        ...
    def get_commit(self, repository: str, commit_id: str, *, _request_timeout: int) -> Commit:
        """Resolve the requested reference.

        Args:
            repository: Repository name.
            commit_id: Explicit selected reference.
            _request_timeout: Socket timeout seconds.

        Returns:
            Server-resolved immutable identity.
        """
        ...
