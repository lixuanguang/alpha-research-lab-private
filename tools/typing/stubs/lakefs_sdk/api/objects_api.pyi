"""Describe bounded object reads through the lakeFS SDK."""

# third party library imports
from lakefs_sdk import ApiClient

class ObjectsApi:
    """Describe explicit object reads."""
    def __init__(self, api_client: ApiClient) -> None:
        """Bind an explicit client.

        Args:
            api_client: Caller-owned connection pool.
        """
        ...
    def get_object(
        self,
        repository: str,
        ref: str,
        path: str,
        *,
        range: str,
        presign: bool,
        _request_timeout: int,
    ) -> bytearray:
        """Read a bounded immutable object range.

        Args:
            repository: Retained repository name.
            ref: Exact commit ID.
            path: Retained object path.
            range: Inclusive byte range.
            presign: Disable redirected object storage reads.
            _request_timeout: Socket timeout seconds.

        Returns:
            Downloaded object bytes.
        """
        ...
    def upload_object(
        self,
        repository: str,
        branch: str,
        path: str,
        *,
        content: bytes,
        _request_timeout: int,
    ) -> object:
        """Upload one object's complete bytes to a branch.

        Args:
            repository: Repository name.
            branch: Writable branch.
            path: Object path relative to the branch.
            content: Complete object bytes.
            _request_timeout: Socket timeout seconds.

        Returns:
            The server's object statistics.
        """
        ...
