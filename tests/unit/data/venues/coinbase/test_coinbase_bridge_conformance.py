"""Exercise the installed Coinbase snapshot/bridge conformance consumer on saved journals."""

from __future__ import annotations

# standard library imports
import shutil
import subprocess
import sys
from pathlib import Path

# third party library imports
import msgspec
import pytest

# project library imports
from configuration import CaptureConfig
from market_data.contracts import CaptureRecord, CaptureRequest
from market_data.storage import CaptureJournal

_ROOT = Path(__file__).parents[5]
_TIME = "2033-05-18T03:33:20.000000{:03d}Z"


class _Result(msgspec.Struct, frozen=True):
    """Decode the consumer's retained result into typed pair and summary maps."""

    searched: list[str]
    selected: list[str]
    summary: dict[str, object]
    pairs: list[dict[str, object]]


class TestCoinbaseBridgeConformance:
    """Author synthetic captures in the retained journal format; none claims venue behavior."""

    @classmethod
    def _coinbase(cls, root: Path, *, bridge_ns: int, is_sealed: bool) -> Path:
        """Save one epoch: covered and bridged updates, a timed REST snapshot, then a match."""
        config = CaptureConfig.read(_ROOT / "configs/live/coinbase-btc-usd.json")
        schema = (_ROOT / "tests/fixtures/market_data/coinbase/coinbase-schema.json").read_bytes()
        frames = (
            b'{"type":"subscriptions","channels":[{"name":"level3","product_ids":["BTC-USD"]}]}',
            msgspec.json.encode(msgspec.json.decode(schema, type=dict[str, object])),
            f'["noop","BTC-USD","9","{_TIME.format(100)}"]'.encode(),
            f'["open","BTC-USD","11","other","sell","102","2","{_TIME.format(bridge_ns)}"]'.encode(),
        )
        snapshot = (
            b'{"sequence":10,"bids":[["100","0.3","maker"]],"asks":[],"time":"'
            + _TIME.format(300).encode()
            + b'"}'
        )
        match = f'["match","BTC-USD","12","maker","taker","100","0.1","{_TIME.format(500)}"]'
        journal = CaptureJournal(
            root,
            CaptureRequest(
                config=config,
                recording_id=f"00000000-0000-0000-0000-00000000{bridge_ns:04d}",
                implementation_identity="a" * 64,
            ),
        )
        journal.start()
        journal.append(CaptureRecord(kind="session", epoch=0, received_ns=1))
        for index, raw in enumerate(frames, 2):
            journal.append(CaptureRecord(kind="frame", epoch=0, received_ns=index, raw=raw))
        journal.append(CaptureRecord(kind="snapshot", epoch=0, received_ns=6, raw=snapshot))
        journal.append(CaptureRecord(kind="frame", epoch=0, received_ns=7, raw=match.encode()))
        if is_sealed:
            journal.append(
                CaptureRecord(kind="end", epoch=0, received_ns=8, reason="message_limit")
            )
            journal.finish(9)
        return root

    @staticmethod
    def _okx(root: Path) -> Path:
        """Start an OKX capture that discovery must count but never examine."""
        CaptureJournal(
            root,
            CaptureRequest(
                config=CaptureConfig.read(_ROOT / "configs/live/okx-btc-usdt.json"),
                recording_id="00000000-0000-0000-0000-000000000001",
                implementation_identity="a" * 64,
            ),
        ).start()
        return root

    @staticmethod
    def _run(tmp_path: Path, name: str, *arguments: str) -> _Result:
        """Run a copy of the consumer outside the checkout with the installed interpreter."""
        script = tmp_path / "coinbase_bridge_conformance.py"
        if not script.exists():
            shutil.copyfile(
                _ROOT / "tests/integration/consumers/capture/coinbase_bridge_conformance.py",
                script,
            )
        output = tmp_path / f"{name}.json"
        result = subprocess.run(
            [sys.executable, "-I", str(script), *arguments, "--output", str(output)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        return msgspec.json.decode(output.read_bytes(), type=_Result)

    @pytest.mark.integration
    def test_reports_absent_pairs_and_the_snapshot_time_conflict(self, tmp_path: Path) -> None:
        """Say when no pair exists, and separate a time-refused bridge from a clean one."""
        empty = tmp_path / "empty"
        self._okx(empty / "okx")
        (empty / "other").mkdir()
        (empty / "other/request.json").write_bytes(b'{"not":"a capture request"}')
        absent = self._run(tmp_path, "absent", "--search", str(empty))
        assert absent.pairs == []
        assert absent.summary["captures_by_venue"] == {"okx:books": 1}
        assert absent.summary["pairs_available"] == 0
        assert str(absent.summary["conclusion"]).startswith("no Coinbase snapshot/bridge pairs")

        captures = tmp_path / "captures"
        self._okx(captures / "okx")
        clean = self._coinbase(captures / "clean", bridge_ns=400, is_sealed=True)
        early = self._coinbase(captures / "early", bridge_ns=200, is_sealed=False)
        found = self._run(tmp_path, "found", "--search", str(captures))
        assert len(found.pairs) == 2
        by_capture = {Path(str(pair["capture"])).name: pair for pair in found.pairs}
        common = {
            "snapshot_sequence": 10,
            "snapshot_time": _TIME.format(300),
            "buffered_updates": 2,
            "covered_updates": 1,
            "first_bridge_sequence": 11,
            "contiguous_bridge_updates": 2,
            "is_stale_snapshot": False,
            "is_sequence_only_bridgeable": True,
        }
        assert by_capture["clean"] | common == by_capture["clean"]
        assert by_capture["clean"]["is_completed_capture"] is True
        assert by_capture["clean"]["bridged_before_snapshot_time"] == 0
        assert by_capture["clean"]["adapter_refusal"] == "none"
        assert by_capture["early"] | common == by_capture["early"]
        assert by_capture["early"]["is_completed_capture"] is False
        assert by_capture["early"]["bridged_before_snapshot_time"] == 1
        assert by_capture["early"]["buffered_before_snapshot_time"] == 1
        assert by_capture["early"]["largest_lead_before_snapshot_ns"] == 100
        assert by_capture["early"]["adapter_refusal"] == "source_time"
        assert by_capture["early"]["adapter_message"] == "Coinbase source time moved backwards"
        assert found.summary["captures_by_venue"] == {"coinbase:level3": 2, "okx:books": 1}
        assert found.summary["pairs_with_bridged_update_before_snapshot_time"] == 1
        assert found.summary["pairs_refused_by_adapter_on_source_time"] == 1
        assert found.summary["refused_pairs_bridgeable_by_sequence_only"] == 1
        # An explicit capture is examined without searching, whatever its seal state.
        for capture, is_sealed in ((clean, True), (early, False)):
            selected = self._run(tmp_path, capture.name, "--capture", str(capture))
            assert selected.searched == [] and selected.selected == [str(capture)]
            assert [pair["is_completed_capture"] for pair in selected.pairs] == [is_sealed]
