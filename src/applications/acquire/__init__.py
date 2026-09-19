"""Expose the applications acquire public contract."""

# project library imports
from applications.acquire.workflow import (
    acquire,
    acquire_history,
    fetch_partition,
    main,
)

__all__ = ["acquire", "acquire_history", "fetch_partition", "main"]
