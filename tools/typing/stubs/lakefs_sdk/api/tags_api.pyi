"""Describe immutable lakeFS reference resolution."""

# third party library imports
from lakefs_sdk import ApiClient, Ref

class TagsApi:
    """Describe explicit reference access."""
    def __init__(self, api_client: ApiClient) -> None:
        """Bind the selected client.

        Args:
            api_client: Caller-owned SDK client.
        """
        ...
    def get_tag(self, repository: str, tag: str, *, _request_timeout: int) -> Ref:
        """Resolve the requested reference.

        Args:
            repository: Repository name.
            tag: Explicit selected reference.
            _request_timeout: Socket timeout seconds.

        Returns:
            Server-resolved immutable identity.
        """
        ...
