"""Evict named files from the Darwin page cache and prove which of their pages stay resident.

A process may discard the clean cached pages of a file it can open: ``msync`` with
``MS_SYNC | MS_INVALIDATE`` on a shared read-only mapping first writes back any dirty
page and then invalidates the file's cached pages, without privilege and without
touching other files. ``mincore`` reports each page's residency, so a cold read is
proved by observation rather than assumed from the eviction call.
"""

from __future__ import annotations

# standard library imports
import ctypes
import mmap
import os
import sys
from collections.abc import Iterable
from pathlib import Path

_MS_INVALIDATE = 0x2
_MS_SYNC = 0x10


class PageCache:
    """Own per-file eviction and residency observation on the declared Darwin host."""

    def __init__(self) -> None:
        """Bind libc; other platforms have different eviction semantics and are refused."""
        if sys.platform != "darwin":
            raise RuntimeError("per-file page-cache eviction is declared for Darwin only")
        libc = ctypes.CDLL(None, use_errno=True)
        libc.mmap.restype = ctypes.c_void_p
        libc.mmap.argtypes = (
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_long,
        )
        libc.munmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
        libc.msync.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
        libc.mincore.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p)
        self.libc = libc
        self.page = os.sysconf("SC_PAGE_SIZE")

    def _call(self, name: str, *arguments: object) -> int:
        """Call one prototyped libc function and narrow its integer or pointer result."""
        result: object = getattr(self.libc, name)(*arguments)
        if result is None:
            return 0
        if type(result) is not int:
            raise TypeError(f"libc {name} returned {type(result).__name__}")
        return result

    def _mapped(self, path: Path, operation: str) -> int:
        """Map one non-empty file read-only and shared, apply one operation and unmap it."""
        size = path.stat().st_size
        if not size:
            return 0
        descriptor = os.open(path, os.O_RDONLY)
        try:
            address = self._call("mmap", None, size, mmap.PROT_READ, mmap.MAP_SHARED, descriptor, 0)
            if address in (0, ctypes.c_void_p(-1).value):
                raise OSError(ctypes.get_errno(), f"cannot map {path}")
            try:
                if operation == "evict":
                    if self._call("msync", address, size, _MS_SYNC | _MS_INVALIDATE):
                        raise OSError(ctypes.get_errno(), f"cannot invalidate {path}")
                    return 0
                pages = (size + self.page - 1) // self.page
                vector = ctypes.create_string_buffer(pages)
                if self._call("mincore", address, size, vector):
                    raise OSError(ctypes.get_errno(), f"cannot observe residency of {path}")
                return sum(byte & 1 for byte in vector.raw)
            finally:
                self._call("munmap", address, size)
        finally:
            os.close(descriptor)

    def pages(self, path: Path) -> int:
        """Return the file's page count at the host page size."""
        return (path.stat().st_size + self.page - 1) // self.page

    def resident(self, path: Path) -> int:
        """Return how many of the file's pages are resident now."""
        return self._mapped(path, "resident")

    def evict(self, paths: Iterable[Path]) -> dict[str, int]:
        """Evict every file, then return each one's remaining resident page count."""
        selected = tuple(paths)
        for path in selected:
            self._mapped(path, "evict")
        return {str(path): self.resident(path) for path in selected}
