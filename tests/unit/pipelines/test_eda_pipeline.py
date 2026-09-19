"""Verify EDA orchestration, attempt retention and controlled failure recovery."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from applications.explore import inspect_eda
from market_data.adapters.sources import SourceAdapters
from market_data.query import QueryBatch, QueryReader
from market_data.storage import RawStore
from reference_data.instruments import InstrumentId
from research.exploration import EdaQuery
from serialization import DomainCodec

_ROOT = Path(__file__).parents[3]


class TestEdaPipeline:
    """Keep verified-reader admission separate from orchestration failure tests."""

    @staticmethod
    def _selection() -> EdaQuery:
        """Bind the retained MR-20 canonical fixture to a bounded two-row projection."""
        instrument = InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111")
        start = datetime(2024, 6, 1, tzinfo=UTC)
        return EdaQuery(
            snapshot_id="a" * 64,
            precedence=(("tardis.binance.spot", "trade", instrument),),
            instruments=(instrument,),
            start=start,
            end=start + timedelta(minutes=1),
            known_at=start + timedelta(seconds=10),
            columns=("price",),
            mode="cutoff",
            batch_size=1,
            max_bytes=262_144,
        )

    @staticmethod
    def _fail(batch: QueryBatch) -> None:
        """Model a failing export sink without mutating the reader."""
        raise RuntimeError("export unavailable")

    def test_completed_retention_and_consumer_failure_recovery(self, tmp_path: Path) -> None:
        """Only fully consumed queries produce a completed identity and summary."""
        selected = self._selection()
        config = tmp_path / "query.json"
        config.write_bytes(DomainCodec().encode_json(selected))
        reader = QueryReader(
            ((_ROOT / "tests/fixtures/replay/canonical.json").read_bytes(),),
            readers=SourceAdapters(),
            precedence=selected.precedence,
            max_bytes=selected.max_bytes,
        )
        records: list[dict[str, object]] = []
        with patch.object(QueryReader, "read", return_value=reader) as read:
            result = inspect_eda(config, tmp_path, RawStore(tmp_path), report=records.append)
            assert read.call_count == 1
            assert [r["status"] for r in records] == ["started", "complete"]
            assert records[-1] == result and result["rows"] == 2 and result["controls"] == 1
            assert result["config"] == selected and result["process_peak_rss_bytes"]
            assert isinstance(result["query_seconds"], float)
            assert isinstance(result["process_input_blocks"], int)
            records.clear()
            with pytest.raises(RuntimeError, match="export unavailable"):
                inspect_eda(
                    config, tmp_path, RawStore(tmp_path), report=records.append, consume=self._fail
                )
            assert [r["status"] for r in records] == ["started", "failed"]
            assert "summary_identity" not in records[-1]
            assert records[-1]["stage"] == "query"
            config.write_bytes(DomainCodec().encode_json(replace(selected, batch_size=8)))
            recovered = inspect_eda(config, tmp_path, RawStore(tmp_path), report=records.append)
            assert recovered["summary_identity"] == result["summary_identity"]
            assert recovered["config_identity"] != result["config_identity"]

    @pytest.mark.parametrize(
        "payload", [b"{}", b'{"lifecycle":"cash_settlement"}', b" " * 1_048_577]
    )
    def test_invalid_config_fails_before_snapshot_access(
        self, tmp_path: Path, payload: bytes
    ) -> None:
        """Configuration failures retain diagnostics without opening a snapshot."""
        config = tmp_path / "query.json"
        config.write_bytes(payload)
        records: list[dict[str, object]] = []
        with patch.object(QueryReader, "read") as read, pytest.raises(ValueError):
            inspect_eda(config, tmp_path, RawStore(tmp_path), report=records.append)
        read.assert_not_called()
        assert records[-1]["status"] == "failed" and records[-1]["stage"] == "configuration"

    def test_missing_or_corrupt_snapshot_never_reports_complete(self, tmp_path: Path) -> None:
        """An explicit missing input is a failed read, never an empty successful query."""
        config = tmp_path / "query.json"
        config.write_bytes(DomainCodec().encode_json(self._selection()))
        records: list[dict[str, object]] = []
        with pytest.raises(OSError):
            inspect_eda(config, tmp_path, RawStore(tmp_path), report=records.append)
        assert records[-1]["stage"] == "snapshot" and records[-1]["status"] == "failed"
        with patch.object(QueryReader, "read", side_effect=ValueError("integrity mismatch")):
            with pytest.raises(ValueError, match="integrity mismatch"):
                inspect_eda(config, tmp_path, RawStore(tmp_path), report=records.append)
        assert all(r["status"] != "complete" for r in records)
