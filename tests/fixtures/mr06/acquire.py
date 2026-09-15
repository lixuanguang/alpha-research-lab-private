"""Run three synthetic HTTP partitions with optional abrupt persistence interruption."""

from __future__ import annotations

# standard library imports
import argparse
import gzip
import os
import runpy
import socket
import sys
from datetime import UTC, datetime
from http.client import HTTPResponse, HTTPSConnection
from importlib.metadata import distribution
from io import BufferedReader, BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

# project library imports
from alpha_research.configuration import ResolvedManifest
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.raw_store import RawStore
from alpha_research.pipelines.acquisition import acquire
from alpha_research.serialization import DomainCodec


class _Arguments(argparse.Namespace):
    """Type the standalone synthetic consumer's explicit paths and fault boundary."""

    root: Path
    run: Path
    point: str
    command: list[str] | None


class _SyntheticAcquisition:
    """Inject HTTP responses and process death while retaining real filesystem operations."""

    def __init__(self, root: Path, point: str) -> None:
        """Bind the outside-checkout destination and optional second-partition failure.

        Args:
            root: Existing directory containing the raw store and checkpoint.
            point: Named fault boundary or none for uninterrupted execution.
        """
        self._root = root
        self._point = point
        self._offset = 0
        self._attempts = 0
        self._link = os.link
        self._replace = os.replace
        self._codec = DomainCodec()

    def request(self, method: str, url: str, *, headers: dict[str, str]) -> None:
        """Record each source access durably enough to inspect process-failure examples."""
        assert method == "GET" and headers == {"Accept-Encoding": "gzip"}
        self._offset = int(parse_qs(urlsplit(url).query)["offset"][0])
        with (self._root / "fetches.txt").open("a") as output:
            output.write(f"{self._offset}\n")
        if self._offset == 1:
            self._attempts += 1
            if self._point == "interrupt":
                raise KeyboardInterrupt
            if self._point == "exhausted" or (self._point == "retry" and self._attempts == 1):
                raise TimeoutError("synthetic private transport detail")

    def respond(self) -> HTTPResponse:
        """Parse a distinct fixed gzip representation for each selected minute."""
        payload = gzip.compress(f"synthetic observation {self._offset}\n".encode(), mtime=0)
        wire = (
            f"HTTP/1.1 200 Synthetic\r\nContent-Encoding: gzip\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode() + payload
        with socket.socket() as sock:
            response = HTTPResponse(sock)
        assert response.fp is not None
        response.fp.close()
        response.fp = BufferedReader(BytesIO(wire))
        response.begin()
        return response

    def link(self, source: Path, destination: Path) -> None:
        """Interrupt the second raw publication before or after its atomic link."""
        if self._offset == 1 and self._point == "before-raw":
            os._exit(75)
        self._link(source, destination)
        if self._offset == 1 and self._point == "after-raw":
            os._exit(75)

    def replace(self, source: Path, destination: Path) -> None:
        """Interrupt the second completion before or after its atomic replacement."""
        state = self._codec.decode_json(source.read_bytes(), AcquisitionManifest)
        if len(state.completed) == 2 and self._point == "before-checkpoint":
            os._exit(75)
        self._replace(source, destination)
        if len(state.completed) == 2 and self._point == "after-checkpoint":
            os._exit(75)

    @staticmethod
    def clock() -> datetime:
        """Use a fixed original/recovery clock to compare complete manifests exactly."""
        return datetime(2026, 9, 15, tzinfo=UTC)

    @staticmethod
    def sleep(seconds: float) -> None:
        """Reject unexpected backoff in this success-or-process-death fixture."""
        raise AssertionError(f"unexpected retry: {seconds}")


def main() -> None:
    """Execute the installed acquisition pipeline with real persistence and fake HTTP.

    Raises:
        OSError: A fixture or persisted object cannot be accessed.
        ValueError: An explicit input or completed object is invalid.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument(
        "point",
        choices=(
            "none",
            "before-raw",
            "after-raw",
            "before-checkpoint",
            "after-checkpoint",
            "interrupt",
            "retry",
            "exhausted",
        ),
    )
    parser.add_argument("--command", nargs=argparse.REMAINDER)
    args = parser.parse_args(namespace=_Arguments())
    scenario = _SyntheticAcquisition(args.root, args.point)
    run = DomainCodec().decode_json(args.run.read_bytes(), ResolvedManifest)
    with (
        patch.object(HTTPSConnection, "request", scenario.request),
        patch.object(HTTPSConnection, "getresponse", scenario.respond),
        patch("alpha_research.data.raw_store.os.link", scenario.link),
        patch("alpha_research.data.manifests.os.replace", scenario.replace),
    ):
        if args.command is not None:
            sys.argv = ["alpha-acquire", *args.command]
            installed = distribution("alpha-research-lab")
            script = next(item for item in installed.files or () if item.name == "alpha-acquire")
            runpy.run_path(str(installed.locate_file(script)), run_name="__main__")
            return
        state = acquire(
            run,
            manifest_path=args.root / "manifest.json",
            store=RawStore(args.root / "raw"),
            connection=HTTPSConnection("api.tardis.dev"),
            clock=scenario.clock,
            sleep=scenario.sleep,
            report=print,
            timeout_seconds=1.0,
            max_bytes=4096,
            permitted_rights_reference="synthetic-local-fixtures-v1",
        )
    print(f"completed={len(state.completed)} pending={state.pending is not None}")


if __name__ == "__main__":
    main()
