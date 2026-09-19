"""Exercise installed acquisition, recovery, publication and EDA with synthetic HTTP."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import runpy
import socket
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from http.client import HTTPResponse, HTTPSConnection
from io import BufferedReader, BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
import alpha_research
from alpha_research.configuration import Configuration
from alpha_research.data.eda import EdaQuery
from alpha_research.data.eligibility import EligibilityAssertions
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.quality import QualityPolicy
from alpha_research.data.query import QueryReader
from alpha_research.data.raw_store import RawStore
from alpha_research.data.snapshots import SnapshotStore
from alpha_research.pipelines.eda import inspect_eda
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec

_LIMIT = 262_144
_CODEC = DomainCodec()


class _Arguments(argparse.Namespace):
    """Type copied input/output paths and the optional acquisition child mode."""

    inputs: Path
    output: Path
    acquire: str | None


class _ArchiveHTTP:
    """Supply deterministic checksummed ZIP responses without opening a connection."""

    def __init__(self, output: Path, point: str) -> None:
        """Bind an access log and optional interruption before the second instrument."""
        self.output, self.point, self.path = output, point, ""

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        """Record attempted source requests and interrupt before the second instrument."""
        assert method == "GET" and headers == {"Accept-Encoding": "identity"}
        self.path = path
        if self.point == "interrupt" and "ETHUSDT" in path:
            raise KeyboardInterrupt
        with (self.output / "fetches.txt").open("a") as log:
            log.write(path + "\n")

    def respond(self) -> HTTPResponse:
        """Parse independent HTTP responses containing three trades and one duplicate."""
        name = self.path.rsplit("/", 1)[-1].removesuffix(".CHECKSUM")
        member = ZipInfo(name.removesuffix(".zip") + ".csv")
        member.compress_type = ZIP_DEFLATED
        rows = b"12,100.00,2.0,200,1717200000000,true,true\n" * 2
        rows += b"13,101.00,2.0,202,1717200060000,true,true\n"
        rows += b"14,102.00,2.0,204,1717200120000,true,true\n"
        with BytesIO() as output:
            with ZipFile(output, "w") as archive:
                archive.writestr(member, rows)
            payload = output.getvalue()
        body = (
            f"{hashlib.sha256(payload).hexdigest()}  {name}\n".encode()
            if self.path.endswith(".CHECKSUM")
            else payload
        )
        wire = f"HTTP/1.1 200 Synthetic\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body
        with socket.socket() as sock:
            response = HTTPResponse(sock)
        assert response.fp is not None
        response.fp.close()
        response.fp = BufferedReader(BytesIO(wire))
        response.begin()
        return response


class _Workflow:
    """Retain process outcomes and attempt reports for the complete historical handoff."""

    def __init__(self, inputs: Path, output: Path) -> None:
        """Bind copied fixtures and a fresh outside-checkout destination."""
        self.inputs, self.output = inputs, output
        self.commands: list[tuple[str, int]] = []

    def command(self, arguments: list[str], *, status: int = 0) -> list[dict[str, object]]:
        """Execute an installed process and retain its complete safe diagnostic output."""
        result = subprocess.run(
            arguments, cwd=self.output, capture_output=True, text=True, check=False, timeout=30
        )
        self.commands.append((" ".join(arguments), result.returncode))
        with (self.output / "commands.jsonl").open("ab") as log:
            log.write(
                _CODEC.encode_json(
                    {
                        "argv": arguments,
                        "exit_code": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
                + b"\n"
            )
        assert result.returncode == status, (arguments, result.stdout, result.stderr)
        return [
            msgspec.json.decode(line, type=dict[str, object]) for line in result.stdout.splitlines()
        ]

    def acquire(self, point: str, *, status: int = 0) -> None:
        """Invoke a fresh installed acquisition process with only HTTP replaced."""
        self.command(
            [
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                str(self.inputs),
                str(self.output),
                "--acquire",
                point,
            ],
            status=status,
        )

    def report(self, record: dict[str, object]) -> None:
        """Retain the EDA entry's attempt records beside the immutable stores."""
        with (self.output / "eda.jsonl").open("ab") as log:
            log.write(_CODEC.encode_json(record) + b"\n")


def main() -> None:
    """Run the installed end-to-end consumer or its bounded synthetic acquisition child.

    Raises:
        AssertionError: Resume, admission, publication or query violates its contract.
        SystemExit: The installed acquisition child returns its actual command status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--acquire", choices=("interrupt", "complete"))
    args = parser.parse_args(namespace=_Arguments())
    inputs, output = args.inputs.resolve(), args.output.resolve()
    assert "site-packages" in Path(alpha_research.__file__).parts
    executable = Path(sys.executable).parent
    if args.acquire is not None:
        http = _ArchiveHTTP(output, args.acquire)
        selected = Configuration.read(output / "jobs.json")
        sys.argv = [
            "alpha-acquire",
            "--config",
            str(output / "jobs.json"),
            "--catalog",
            str(inputs / "binance-archive-spot.json"),
            "--job",
            "btc-archive",
            "--store",
            str(output / "raw"),
            "--manifest",
            str(output / "acquisition.json"),
            "--rights-reference",
            selected.jobs[0].rights_reference,
            "--timeout-seconds",
            "1",
            "--max-bytes",
            str(_LIMIT),
        ]
        with (
            patch.object(HTTPSConnection, "request", http.request),
            patch.object(HTTPSConnection, "getresponse", http.respond),
        ):
            runpy.run_path(str(executable / "alpha-acquire"), run_name="__main__")
        return
    output.mkdir(exist_ok=False)
    (output / "raw").mkdir()
    (output / "snapshots").mkdir()
    fixture = _Workflow(inputs, output)
    config = Configuration.read(inputs / "binance-archive.json")
    config = replace(config, jobs=(replace(config.jobs[0], universe="both"),))
    (output / "jobs.json").write_bytes(_CODEC.encode_json(config))
    catalog = _CODEC.decode_json(
        (inputs / "binance-archive-spot.json").read_bytes(), CatalogSnapshot
    )
    history = EligibilityAssertions.read(inputs / "membership-corrections.json", catalog=catalog)
    (output / "eligibility.json").write_bytes(_CODEC.encode_json(history))
    policy = QualityPolicy(
        use="exploratory", known_at=config.jobs[0].start, max_gap=timedelta(hours=1)
    )
    (output / "policy.json").write_bytes(_CODEC.encode_json(policy))
    common = [
        "--store",
        str(output / "raw"),
        "--snapshots",
        str(output / "snapshots"),
        "--max-bytes",
        str(_LIMIT),
    ]
    publish = [
        str(executable / "alpha-dataset"),
        "publish",
        *common,
        "--policy",
        str(output / "policy.json"),
        "--eligibility",
        str(output / "eligibility.json"),
        "--manifests",
        str(output / "acquisition.json"),
    ]
    fixture.acquire("interrupt", status=130)
    partial = _CODEC.decode_json((output / "acquisition.json").read_bytes(), AcquisitionManifest)
    assert len(partial.completed) == 1
    fixture.command(publish, status=3)
    assert not list((output / "snapshots").iterdir())
    fixture.acquire("complete")
    acquired = (output / "acquisition.json").read_bytes()
    completed = _CODEC.decode_json(acquired, AcquisitionManifest)
    assert completed.completed[:1] == partial.completed
    fetched = (output / "fetches.txt").read_bytes()
    assert len(fetched.splitlines()) == 4
    fixture.acquire("complete")
    assert (output / "fetches.txt").read_bytes() == fetched
    interrupted = fixture.command(
        [sys.executable, "-I", str(inputs / "interrupt_command.py"), *publish[1:]], status=75
    )
    candidate = str(interrupted[-1]["snapshot_id"])
    fixture.command(
        [str(executable / "alpha-dataset"), "inspect", *common, "--snapshot-id", candidate],
        status=4,
    )
    assert not (output / "snapshots" / candidate).exists()
    records = fixture.command(publish)
    identity = str(records[-1]["snapshot_id"])
    assert identity == candidate
    quality = [record for record in records if record["status"] == "validated"]
    assert [record["duplicate_count"] for record in quality] == [1, 1]
    assert fixture.command([*publish, publish[-1]])[-1]["snapshot_id"] == identity
    fixture.command(
        [str(executable / "alpha-dataset"), "inspect", *common, "--snapshot-id", identity]
    )
    assert (output / "acquisition.json").read_bytes() == acquired
    raw = RawStore(output / "raw")
    saved = SnapshotStore(output / "snapshots", raw).read(identity, max_bytes=_LIMIT)
    assert tuple(part.acquisition.completed[0] for part in saved.partitions) == completed.completed
    query = EdaQuery(
        snapshot_id=identity,
        precedence=tuple(
            (item.source, "trade", item.instrument_id) for item in completed.run.instruments
        ),
        instruments=tuple(item.instrument_id for item in completed.run.instruments),
        start=config.jobs[0].start,
        end=config.jobs[0].end,
        known_at=datetime(2026, 9, 18, tzinfo=UTC),
        columns=("price", "revision"),
        mode="history",
        batch_size=2,
        max_bytes=_LIMIT,
    )
    (output / "query.json").write_bytes(_CODEC.encode_json(query))
    summary = inspect_eda(output / "query.json", output / "snapshots", raw, report=fixture.report)
    assert summary["rows"] == 6
    reader = QueryReader.read(
        output / "snapshots", raw, identity=identity, max_bytes=_LIMIT, precedence=query.precedence
    )
    cutoff = tuple(
        reader.batches(
            query.instruments,
            start=query.start,
            end=query.end,
            known_at=query.known_at,
            columns=("price",),
            batch_size=2,
        )
    )
    assert sum(len(batch.rows) for batch in cutoff) == 0
    assert all("original trade availability unknown" in item.reasons for item in cutoff[0].evidence)
    result = {
        "snapshot_id": identity,
        "partitions": len(saved.partitions),
        "scope": saved.scope,
        "history_rows": summary["rows"],
        "cutoff_rows": 0,
        "duplicate_counts": [1, 1],
        "fetches": 4,
        "resume_preserved_first_descriptor": True,
        "repeat_fetches": 0,
        "incomplete_publish_exit": 3,
        "interrupted_publish_exit": 75,
        "commands": fixture.commands,
    }
    (output / "result.json").write_bytes(_CODEC.encode_json(result))
    print(_CODEC.encode_json(result).decode())


if __name__ == "__main__":
    main()
