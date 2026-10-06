"""Terminate a real publisher immediately before or after its atomic link."""

from __future__ import annotations

# standard library imports
import argparse
import os
from pathlib import Path
from unittest.mock import patch

# project library imports
from market_data.contracts import RawObject, SourceRequest
from market_data.storage import RawStore
from serialization import DomainCodec


class _Arguments(argparse.Namespace):
    """Type the explicit saved inputs for one interrupted child process."""

    root: Path
    source: Path
    descriptor: Path
    request: Path
    point: str


class _InterruptedPublication:
    """Keep the real link operation and terminate without Python cleanup."""

    def __init__(self, point: str) -> None:
        """Bind the chosen interruption boundary.

        Args:
            point: Either before or after the atomic link operation.
        """
        self._point = point
        self._link = os.link

    def link(self, source: Path, destination: Path) -> None:
        """Exit before or after publication, leaving observable filesystem state."""
        if self._point == "after":
            self._link(source, destination)
        os._exit(75)


def main() -> None:
    """Load synthetic inputs and run one deliberately interrupted publication.

    Raises:
        OSError: A saved input or store cannot be accessed.
        ValueError: An input fails its typed contract.
        RuntimeError: Publication unexpectedly returns without interruption.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("descriptor", type=Path)
    parser.add_argument("request", type=Path)
    parser.add_argument("point", choices=("before", "after"))
    arguments = parser.parse_args(namespace=_Arguments())
    codec = DomainCodec()
    descriptor = codec.decode_json(arguments.descriptor.read_bytes(), RawObject)
    request = codec.decode_json(arguments.request.read_bytes(), SourceRequest)
    interruption = _InterruptedPublication(arguments.point)
    with patch("market_data.storage.raw.os.link", interruption.link):
        RawStore(arguments.root).publish(
            arguments.source, descriptor=descriptor, request=request.binding, compress=False
        )
    raise RuntimeError("publication did not reach the requested interruption")


if __name__ == "__main__":
    main()
