"""Describe the consumed nbclient notebook execution interface."""

# standard library imports
from collections.abc import Mapping

# third party library imports
from jupyter_client.manager import KernelManager
from nbformat import NotebookNode

class NotebookClient:
    """Execute a notebook's cells in a kernel started by its kernel manager."""

    def __init__(
        self,
        nb: NotebookNode,
        *,
        km: KernelManager,
        timeout: int,
        resources: Mapping[str, object],
    ) -> None:
        """Bind the notebook, its kernel manager, the cell timeout and resources."""

    def execute(self, *, env: Mapping[str, str]) -> NotebookNode:
        """Start the kernel with the environment and execute every cell in place."""
