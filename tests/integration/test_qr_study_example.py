"""Run the maintained QR study example over authored captures and package its learned study."""

from __future__ import annotations

# standard library imports
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from configuration import CaptureConfig, UniverseSelection
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import CaptureRecord, CaptureRequest
from market_data.datasets import DatasetPublication
from market_data.storage import CaptureJournal, RawStore
from research.experiments import AttemptStore, CandidateMetricContract, CandidateStateContract
from runtime import CandidatePackager, ComponentSelection
from serialization import DomainCodec

_ROOT = Path(__file__).resolve().parents[2]
_START = datetime(2026, 9, 23, 12, tzinfo=UTC)
_SECONDS = 200


class AuthoredMarket:
    """Author three minutes of OKX BTC-USDT books and trades with moving touch and flow."""

    def __init__(self, root: Path) -> None:
        """Bind the output root and both feeds' requests."""
        self.root = root
        books = replace(
            CaptureConfig.read(_ROOT / "configs/live/okx-btc-usdt.json"),
            duration_seconds=3600,
            max_messages=100_000,
            max_bytes=256_000_000,
        )
        trades = replace(
            books, channel="trades", depth=0, max_orders=1, max_frame_bytes=100_000, idle_seconds=60
        )
        selected = (books.instrument_id,)
        universes = UniverseSelection(
            collection=selected, research=selected, strategy=(), authorized_trading=()
        )
        self.books = CaptureRequest(
            config=books,
            recording_id="00000000-0000-0000-0000-000000000031",
            implementation_identity="a" * 64,
            universes=universes,
        )
        self.trades = CaptureRequest(
            config=trades,
            recording_id="00000000-0000-0000-0000-000000000032",
            implementation_identity="a" * 64,
            universes=universes,
        )

    @staticmethod
    def ns(at: datetime) -> int:
        """Return exact Unix nanoseconds."""
        return (at - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(microseconds=1) * 1000

    def book_frames(self) -> list[tuple[datetime, bytes]]:
        """A snapshot, then every half second the best bid improves or retreats."""
        frames: list[tuple[datetime, bytes]] = [
            (_START, b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}'),
        ]
        bids = '[["100.0","1","0","1"],["99.9","2","0","1"]]'
        asks = '[["100.2","1","0","1"],["100.3","2","0","1"]]'
        frames.append((_START, self.book("snapshot", -1, 1, bids, asks)))
        for index in range(2 * _SECONDS):
            at = _START + timedelta(milliseconds=500 * (index + 1))
            if index % 4 == 0:
                change = ('[["100.1","1","0","1"]]', "[]")
            elif index % 4 == 2:
                change = ('[["100.1","0","0","0"]]', "[]")
            else:
                change = ("[]", f'[["100.2","{1 + index % 3}","0","1"]]')
            frames.append((at, self.book("update", 1 + index, 2 + index, *change)))
        return frames

    @staticmethod
    def book(action: str, previous: int, sequence: int, bids: str, asks: str) -> bytes:
        """Encode one OKX books message."""
        return (
            f'{{"arg":{{"channel":"books","instId":"BTC-USDT"}},"action":"{action}",'
            f'"data":[{{"prevSeqId":{previous},"seqId":{sequence},'
            f'"bids":{bids},"asks":{asks}}}]}}'
        ).encode()

    def trade_frames(self) -> list[tuple[datetime, bytes]]:
        """Acknowledge, then one trade a second with a varying side and size."""
        frames = [(_START, b'{"event":"subscribe","arg":{"channel":"trades","instId":"BTC-USDT"}}')]
        for index in range(_SECONDS):
            at = _START + timedelta(seconds=index + 1)
            side = "buy" if index % 5 < 3 else "sell"
            frames.append(
                (
                    at,
                    DomainCodec().encode_json(
                        {
                            "arg": {"channel": "trades", "instId": "BTC-USDT"},
                            "data": [
                                {
                                    "instId": "BTC-USDT",
                                    "tradeId": str(1000 + index),
                                    "ts": str(self.ns(at) // 1_000_000),
                                    "px": "100.1",
                                    "sz": f"0.{1 + index % 7}",
                                    "side": side,
                                    "count": "1",
                                }
                            ],
                        }
                    ),
                )
            )
        return frames

    def write(self, request: CaptureRequest, frames: list[tuple[datetime, bytes]]) -> Path:
        """Write one complete capture directory."""
        directory = self.root / request.recording_id
        journal = CaptureJournal(directory, request)
        journal.start()
        journal.append(CaptureRecord(kind="session", epoch=0, received_ns=self.ns(_START)))
        for offset, (at, raw) in enumerate(frames):
            journal.append(
                CaptureRecord(kind="frame", epoch=0, received_ns=self.ns(at) + offset, raw=raw)
            )
        end = self.ns(_START + timedelta(seconds=_SECONDS + 1))
        journal.append(CaptureRecord(kind="end", epoch=0, received_ns=end, reason="message_limit"))
        journal.finish(self.ns(_START))
        return directory


class TestQRStudyExample:
    """Prove the quickstart's study example runs and packages from published captures."""

    @pytest.mark.integration
    def test_rule_learned_holdout_and_packaging(self, tmp_path: Path) -> None:
        """Both studies complete, the holdout runs once, and the learned study packages."""
        market = AuthoredMarket(tmp_path / "captures")
        books = market.write(market.books, market.book_frames())
        trades = market.write(market.trades, market.trade_frames())
        (tmp_path / "raw").mkdir()
        (tmp_path / "snapshots").mkdir()
        published = DatasetPublication(SourceAdapters(), "b" * 64).publish_captures(
            (books, trades),
            RawStore(tmp_path / "raw"),
            tmp_path / "snapshots",
            max_records=100_000,
            max_bytes=256_000_000,
        )
        common = [
            "--snapshots",
            str(tmp_path / "snapshots"),
            "--raw",
            str(tmp_path / "raw"),
            "--attempts",
            str(tmp_path / "attempts"),
            "--book-snapshot",
            published.book,
            "--instrument",
            str(market.books.config.instrument_id),
            "--trades-snapshot",
            published.trades[0],
            "--start",
            _START.isoformat(),
            "--end",
            (_START + timedelta(seconds=_SECONDS)).isoformat(),
            "--train",
            "40",
            "--test",
            "30",
            "--folds",
            "2",
            "--holdout",
            "30",
            "--cadence",
            "5",
            "--horizon",
            "10",
        ]
        summaries: list[dict[str, object]] = []
        for kind, partition in (
            ("rule", "validation"),
            ("learned", "validation"),
            ("learned", "holdout"),
        ):
            completed = subprocess.run(  # nosec B603  # [owner=research; rationale=runs the maintained example as a QR would; expires=2027-03-01]
                [
                    sys.executable,
                    str(_ROOT / "examples/qr_study.py"),
                    kind,
                    "--partition",
                    partition,
                    *common,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert completed.returncode == 0, completed.stderr[-4000:]
            summaries.append(msgspec.json.decode(completed.stdout, type=dict[str, object]))
        assert [item["status"] for item in summaries] == ["completed"] * 3
        learned = str(summaries[1]["attempt_id"])
        policy = DomainCodec().encode_json(
            {
                "instrument": str(market.books.config.instrument_id),
                "quantity": "0.001",
                "threshold": {"numerator": "0", "denominator": "1"},
            }
        )
        with AttemptStore(tmp_path / "attempts") as store:
            manifest = CandidatePackager().publish(
                tmp_path / "candidate",
                store=store,
                attempt_id=learned,
                extension="engineering-candidates",
                selections=(
                    ComponentSelection(role="feature", factory_key="projection", parameters=b"{}"),
                    ComponentSelection(
                        role="transform", factory_key="center-scale", parameters=b"{}"
                    ),
                    ComponentSelection(
                        role="estimator", factory_key="least-squares", parameters=b"{}"
                    ),
                    ComponentSelection(
                        role="policy", factory_key="prediction-target", parameters=policy
                    ),
                    ComponentSelection(role="metric", factory_key="fold-net", parameters=b"{}"),
                    ComponentSelection(role="chart", factory_key="fold-net-path", parameters=b"{}"),
                ),
                name="qr-learned",
                version="1",
                venue="okx",
                cadence_us=5_000_000,
                state=CandidateStateContract(
                    feature_mode="batch",
                    warmup_observations=0,
                    checkpoint_schema="candidate-checkpoint",
                    on_gap="continue",
                    on_restart="restore",
                    policy_state_schema="none",
                ),
                metrics=(
                    CandidateMetricContract(
                        name="fold-net",
                        kind="metric",
                        component_key="fold-net",
                        version="1",
                        units="USDT",
                        applies_to=("research",),
                    ),
                    CandidateMetricContract(
                        name="fold-net-path",
                        kind="chart",
                        component_key="fold-net-path",
                        version="1",
                        units="USDT",
                        applies_to=("research",),
                    ),
                ),
                limitations=("Authored example captures; no market evidence.",),
            )
        assert manifest.definition.name == "qr-learned"
        assert {item.role for item in manifest.definition.components} >= {
            "feature",
            "transform",
            "estimator",
            "policy",
        }
