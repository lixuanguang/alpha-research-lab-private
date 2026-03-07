"""Unit tests for alpha_core.research.experiment_catalog."""

from __future__ import annotations

from pathlib import Path

import pytest

import alpha_core.research.experiment_catalog as catalog_mod

# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestCatalogEntrySchema:
    def test_required_fields_missing_raises(self) -> None:
        with pytest.raises(Exception):
            catalog_mod.CatalogEntry.model_validate({"entry_id": "abc"})

    def test_extra_fields_forbidden(self) -> None:
        from datetime import UTC, datetime

        now = datetime.now(tz=UTC)
        with pytest.raises(Exception):
            catalog_mod.CatalogEntry.model_validate(
                {
                    "entry_id": "abc",
                    "run_id": "r1",
                    "created_at_utc": now,
                    "updated_at_utc": now,
                    "unknown_field": "x",
                }
            )

    def test_default_status_is_candidate(self) -> None:
        from datetime import UTC, datetime

        now = datetime.now(tz=UTC)
        entry = catalog_mod.CatalogEntry(
            entry_id="e1", run_id="r1", created_at_utc=now, updated_at_utc=now
        )
        assert entry.status == "candidate"

    def test_invalid_status_rejected_by_schema(self) -> None:
        from datetime import UTC, datetime

        now = datetime.now(tz=UTC)
        with pytest.raises(Exception):
            catalog_mod.CatalogEntry.model_validate(
                {
                    "entry_id": "e1",
                    "run_id": "r1",
                    "status": "invalid_status",
                    "created_at_utc": now,
                    "updated_at_utc": now,
                }
            )

    def test_round_trip_json(self, tmp_path: Path) -> None:
        entry = catalog_mod.add_entry(tmp_path, run_id="r1", strategy_id="zscore")
        raw = entry.model_dump_json()
        restored = catalog_mod.CatalogEntry.model_validate_json(raw)
        assert restored == entry


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


class TestCatalogLifecycle:
    def test_add_entry_creates_catalog_file(self, tmp_path: Path) -> None:
        catalog_mod.add_entry(tmp_path, run_id="r1")
        assert (tmp_path / "catalog" / "catalog.jsonl").exists()

    def test_add_entry_defaults_to_candidate(self, tmp_path: Path) -> None:
        entry = catalog_mod.add_entry(tmp_path, run_id="r1")
        assert entry.status == "candidate"

    def test_get_entry_returns_latest(self, tmp_path: Path) -> None:
        entry = catalog_mod.add_entry(tmp_path, run_id="r1")
        loaded = catalog_mod.get_entry(tmp_path, entry.entry_id)
        assert loaded == entry

    def test_get_missing_entry_raises_key_error(self, tmp_path: Path) -> None:
        with pytest.raises(KeyError, match="nonexistent"):
            catalog_mod.get_entry(tmp_path, "nonexistent")

    def test_update_status_persists(self, tmp_path: Path) -> None:
        entry = catalog_mod.add_entry(tmp_path, run_id="r1")
        updated = catalog_mod.update_status(
            tmp_path,
            entry.entry_id,
            status="needs_review",
        )
        assert updated.status == "needs_review"
        loaded = catalog_mod.get_entry(tmp_path, entry.entry_id)
        assert loaded.status == "needs_review"

    def test_update_status_full_review_path(self, tmp_path: Path) -> None:
        entry = catalog_mod.add_entry(tmp_path, run_id="r1")
        catalog_mod.update_status(tmp_path, entry.entry_id, status="needs_review")
        result = catalog_mod.update_status(
            tmp_path,
            entry.entry_id,
            status="approved_for_paper",
            reviewed_by="alice",
            reason="Sharpe > 1.5",
        )
        assert result.status == "approved_for_paper"
        assert result.reviewed_by == "alice"
        assert result.reason == "Sharpe > 1.5"
        assert result.reviewed_at_utc is not None

    def test_update_status_invalid_raises_value_error(self, tmp_path: Path) -> None:
        entry = catalog_mod.add_entry(tmp_path, run_id="r1")
        with pytest.raises(ValueError, match="Invalid status"):
            catalog_mod.update_status(tmp_path, entry.entry_id, status="unknown")  # type: ignore[arg-type]

    def test_list_all_empty(self, tmp_path: Path) -> None:
        assert catalog_mod.list_all(tmp_path) == []

    def test_list_all_sorted_by_created(self, tmp_path: Path) -> None:
        e1 = catalog_mod.add_entry(tmp_path, run_id="r1")
        e2 = catalog_mod.add_entry(tmp_path, run_id="r2")
        results = catalog_mod.list_all(tmp_path)
        assert [e.entry_id for e in results] == [e1.entry_id, e2.entry_id]

    def test_list_by_status_filters(self, tmp_path: Path) -> None:
        e1 = catalog_mod.add_entry(tmp_path, run_id="r1")
        e2 = catalog_mod.add_entry(tmp_path, run_id="r2")
        catalog_mod.update_status(tmp_path, e1.entry_id, status="approved_for_paper")
        approved = catalog_mod.list_by_status(tmp_path, "approved_for_paper")
        candidates = catalog_mod.list_by_status(tmp_path, "candidate")
        assert len(approved) == 1
        assert approved[0].entry_id == e1.entry_id
        assert len(candidates) == 1
        assert candidates[0].entry_id == e2.entry_id

    def test_list_by_session_filters(self, tmp_path: Path) -> None:
        e1 = catalog_mod.add_entry(tmp_path, run_id="r1", session_id="sess_A")
        catalog_mod.add_entry(tmp_path, run_id="r2", session_id="sess_B")
        results = catalog_mod.list_by_session(tmp_path, "sess_A")
        assert len(results) == 1
        assert results[0].entry_id == e1.entry_id

    def test_list_by_run(self, tmp_path: Path) -> None:
        e = catalog_mod.add_entry(tmp_path, run_id="shared_run")
        catalog_mod.add_entry(tmp_path, run_id="other_run")
        results = catalog_mod.list_by_run(tmp_path, "shared_run")
        assert len(results) == 1
        assert results[0].entry_id == e.entry_id

    def test_audit_log_preserves_history(self, tmp_path: Path) -> None:
        """The JSONL file retains all append events for auditability."""
        entry = catalog_mod.add_entry(tmp_path, run_id="r1")
        catalog_mod.update_status(tmp_path, entry.entry_id, status="needs_review")
        catalog_mod.update_status(tmp_path, entry.entry_id, status="rejected", reason="low SR")
        catalog_path = tmp_path / "catalog" / "catalog.jsonl"
        lines = [ln for ln in catalog_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        # 3 lines: original add + 2 status updates
        assert len(lines) == 3

    def test_latest_record_wins(self, tmp_path: Path) -> None:
        """list_all returns only the latest record per entry_id."""
        entry = catalog_mod.add_entry(tmp_path, run_id="r1")
        catalog_mod.update_status(tmp_path, entry.entry_id, status="needs_review")
        catalog_mod.update_status(tmp_path, entry.entry_id, status="rejected")
        results = catalog_mod.list_all(tmp_path)
        assert len(results) == 1
        assert results[0].status == "rejected"

    def test_multiple_entries_independent(self, tmp_path: Path) -> None:
        e1 = catalog_mod.add_entry(tmp_path, run_id="r1")
        e2 = catalog_mod.add_entry(tmp_path, run_id="r2")
        catalog_mod.update_status(tmp_path, e1.entry_id, status="rejected")
        e2_loaded = catalog_mod.get_entry(tmp_path, e2.entry_id)
        assert e2_loaded.status == "candidate"

    def test_all_status_values_accepted(self, tmp_path: Path) -> None:
        for status in ("candidate", "needs_review", "approved_for_paper", "rejected"):
            entry = catalog_mod.add_entry(tmp_path, run_id=f"run_{status}")
            updated = catalog_mod.update_status(tmp_path, entry.entry_id, status=status)  # type: ignore[arg-type]
            assert updated.status == status
