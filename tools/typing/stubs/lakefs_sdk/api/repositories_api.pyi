"""Describe explicit lakeFS repository creation."""

# third party library imports
from lakefs_sdk import ApiClient, RepositoryCreation

class RepositoriesApi:
    """Describe repository administration used by dataset publication."""
    def __init__(self, api_client: ApiClient) -> None:
        """Bind an explicit client.

        Args:
            api_client: Caller-owned connection pool.
        """
        ...
    def create_repository(
        self, repository_creation: RepositoryCreation, *, _request_timeout: int
    ) -> object:
        """Create one repository.

        Args:
            repository_creation: Name, storage namespace and default branch.
            _request_timeout: Socket timeout seconds.

        Returns:
            The created repository description.
        """
        ...
