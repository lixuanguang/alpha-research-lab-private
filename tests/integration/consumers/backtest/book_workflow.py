"""Exercise installed L2 CLI recovery and another configured spot archive outside the checkout."""

from __future__ import annotations

# standard library imports
import hashlib
import io
import subprocess
import sys
import tarfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# third party library imports
from msgspec.structs import replace

# project library imports
from configuration import BookRun, OKXHistoryConfig
from financial_units import Quantity
from market_data.adapters.venues.okx import OKXArchiveDiscovery, OKXArchiveStore
from market_data.contracts import OKXArchiveRequest
from research.experiments import AttemptStore, BookReport
from serialization import DomainCodec


class _SavedBooks:
    """Create bounded synthetic native source bytes using the actual archive persistence API."""

    @staticmethod
    def create(root: Path, config: OKXHistoryConfig) -> Path:
        """Publish a tiny complete native archive with explicit synthetic provenance."""
        codec = DomainCodec()
        url = (
            "https://static.okx.com/cdn/okx/match/orderbook/pro/L2/400lv/daily/"
            f"{config.day:%Y%m%d}/{config.filename}"
        )
        index = codec.encode_json(
            {
                "code": "0",
                "data": [
                    {
                        "dateAggrType": "daily",
                        "details": [
                            {
                                "instId": config.symbol,
                                "instType": "SPOT",
                                "groupDetails": [
                                    {
                                        "filename": config.filename,
                                        "dateTs": str(config.start_ms),
                                        "sizeMB": "0.001",
                                        "url": url,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        request = OKXArchiveRequest(
            config=config,
            index_sha256=hashlib.sha256(index).hexdigest(),
            index_received=datetime.now(UTC),
            implementation_identity="a" * 64,
            url=OKXArchiveDiscovery.select_url(config, index),
        )
        rows = [
            codec.encode_json(
                {
                    "instId": config.symbol,
                    "action": "snapshot",
                    "ts": str(config.start_ms + ms),
                    "bids": [["100", "10", "1"]],
                    "asks": [["101", "1", "1"], ["102", "1", "1"]],
                }
            )
            + b"\n"
            for ms in (0, 1250, 2500, 4500, 7900)
        ]
        payload = b"".join(rows)
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w:gz") as archive:
            member = tarfile.TarInfo(config.filename.removesuffix(".tar.gz") + ".data")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        saved = root / "archive"
        store = OKXArchiveStore(saved)
        store.start(request, index)
        (saved / "download.part").write_bytes(raw.getvalue())
        store.finish(request, datetime.now(UTC))
        return saved

    @staticmethod
    def command(config: Path, archive: Path, output: Path, *extra: str) -> Path:
        """Run the installed application executable from an external working directory."""
        completed = subprocess.run(
            [
                str(Path(sys.executable).parent / "alpha-backtest"),
                "books",
                "--config",
                str(config),
                "--archive",
                str(archive),
                "--output",
                str(output),
                *extra,
            ],
            cwd=config.parent,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert completed.returncode == 0, (completed.stdout, completed.stderr)
        return Path(completed.stdout.strip())


def main() -> None:
    """Compose saved inputs and prove installed CLI recovery, isolation and failure retention.

    Raises:
        AssertionError: An installed behavior differs from the independent expected result.
    """
    root = Path(sys.argv[1])
    codec = DomainCodec()
    authored = BookRun.read(root / "book-config.json")
    instance = authored.instances[0]
    quantity = Quantity(value=Decimal("3"), dimension=instance.quantity.dimension)
    instance = replace(
        instance,
        quantity=quantity,
        limits=replace(
            instance.limits,
            maximum=quantity,
            lot=Quantity(value=Decimal("0.1"), dimension=quantity.dimension),
        ),
        take_fraction=Decimal("1"),
    )
    control = replace(instance, instance="control", rule="book-no-trade-v1")
    smaller = replace(
        instance,
        instance="smaller",
        quantity=Quantity(value=Decimal("0.5"), dimension=quantity.dimension),
    )
    selected = replace(
        authored,
        history=replace(authored.history, max_records=5),
        end=authored.start + timedelta(seconds=8),
        timing=replace(
            authored.timing,
            processing_us=100000,
            entry_us=200000,
            response_us=500000,
            stale_us=10000000,
        ),
        instances=(instance, control, smaller),
    )
    config = root / "resolved.json"
    config.write_bytes(codec.encode_json(selected))
    archive = _SavedBooks.create(root, selected.history)
    complete = _SavedBooks.command(config, archive, root / "runs")
    checkpoint = _SavedBooks.command(
        config,
        archive,
        root / "runs",
        "--stop-at",
        (selected.start + timedelta(milliseconds=1300)).isoformat(),
    )
    resumed = _SavedBooks.command(config, archive, root / "runs", "--resume", str(checkpoint))
    assert (complete / "report.json").read_bytes() == (resumed / "report.json").read_bytes()
    for index in range(3):
        assert (complete / f"checkpoint-{index}.json").read_bytes() == (
            resumed / f"checkpoint-{index}.json"
        ).read_bytes()
    report = codec.decode_json((complete / "report.json").read_bytes(), BookReport)
    assert len(report.features) == 5 and all(
        row.received_ns is None and row.sequence is None for row in report.features
    )
    balances = [account.state.valuations[-1].balance for account in report.accounts]
    assert [balance.holding.value for balance in balances] == [
        Decimal("2"),
        Decimal("0"),
        Decimal("0.5"),
    ]
    assert balances[0].cash.value == Decimal("796.797")
    assert balances[1].cash.value == Decimal("1000")
    btc = OKXHistoryConfig.read(root / "btc-history.json")
    btc_history = replace(
        selected.history,
        instrument_id=btc.instrument_id,
        base_currency=btc.base_currency,
        symbol=btc.symbol,
    )
    dimension = quantity.dimension.model_copy(update={"instrument_id": btc.instrument_id})
    other = replace(
        instance,
        instance="second-spot",
        quantity=Quantity(value=Decimal("3"), dimension=dimension),
        limits=replace(
            instance.limits,
            maximum=Quantity(value=Decimal("3"), dimension=dimension),
            lot=Quantity(value=Decimal("0.1"), dimension=dimension),
            tick=instance.limits.tick.model_copy(update={"per": dimension}),
        ),
    )
    other_run = replace(selected, history=btc_history, instances=(other,))
    other_root = root / "second"
    other_root.mkdir()
    other_config = other_root / "resolved.json"
    other_config.write_bytes(codec.encode_json(other_run))
    second = _SavedBooks.command(
        other_config, _SavedBooks.create(other_root, btc_history), other_root / "runs"
    )
    second_report = codec.decode_json((second / "report.json").read_bytes(), BookReport)
    assert second_report.accounts[0].state.valuations[-1].balance.cash.value == Decimal("796.797")
    # Preserve the failed source-validation attempt instead of substituting a valid fixture.
    descriptor = report.raw_sha256
    (archive / descriptor).chmod(0o600)
    (archive / descriptor).write_bytes(b"corrupted")
    failed = subprocess.run(
        [
            str(Path(sys.executable).parent / "alpha-backtest"),
            "books",
            "--config",
            str(config),
            "--archive",
            str(archive),
            "--output",
            str(root / "runs"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert failed.returncode != 0
    histories = AttemptStore(root / "runs/attempts").histories()
    assert sorted(item.status for item in histories) == [
        "abandoned",
        "completed",
        "completed",
        "failed",
    ]
    (root / "result.json").write_bytes(
        codec.encode_json(
            {
                "restart_equal": True,
                "instances": 3,
                "spot_configurations": (selected.history.symbol, btc_history.symbol),
                "failed_source_retained": True,
            }
        )
    )


if __name__ == "__main__":
    main()
