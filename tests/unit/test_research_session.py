"""Unit tests for alpha_core.research.session."""

from __future__ import annotations

from pathlib import Path

import pytest

import alpha_core.research.session as session_mod
from alpha_core.research.session import ResearchSession


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestResearchSessionSchema:
    def test_required_fields_missing_raises(self) -> None:
        """Both created_at_utc and updated_at_utc are required."""
        with pytest.raises(Exception):
            ResearchSession.model_validate({"session_id": "abc"})

    def test_extra_fields_forbidden(self) -> None:
        from datetime import UTC, datetime

        with pytest.raises(Exception):
            ResearchSession.model_validate(
                {
                    "session_id": "abc",
                    "created_at_utc": datetime.now(tz=UTC),
                    "updated_at_utc": datetime.now(tz=UTC),
                    "unknown_field": "x",
                }
            )

    def test_optional_fields_default_to_none(self) -> None:
        from datetime import UTC, datetime

        now = datetime.now(tz=UTC)
        sess = ResearchSession(session_id="x", created_at_utc=now, updated_at_utc=now)
        assert sess.dataset_id is None
        assert sess.feature_set_version is None
        assert sess.strategy_id is None
        assert sess.notes is None
        assert sess.run_ids == []

    def test_round_trip_json(self, tmp_path: Path) -> None:
        sess = session_mod.create_session(
            tmp_path,
            dataset_id="ds001",
            feature_set_version="v2",
            strategy_id="zscore",
            notes="first experiment",
        )
        raw = sess.model_dump_json()
        restored = ResearchSession.model_validate_json(raw)
        assert restored == sess


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    def test_create_session_persists(self, tmp_path: Path) -> None:
        sess = session_mod.create_session(tmp_path, strategy_id="my_strategy")
        assert (tmp_path / "sessions" / f"{sess.session_id}.json").exists()

    def test_load_session_round_trip(self, tmp_path: Path) -> None:
        sess = session_mod.create_session(tmp_path, strategy_id="s1")
        loaded = session_mod.load_session(tmp_path, sess.session_id)
        assert loaded == sess

    def test_load_missing_session_raises_key_error(self, tmp_path: Path) -> None:
        with pytest.raises(KeyError, match="nonexistent"):
            session_mod.load_session(tmp_path, "nonexistent")

    def test_add_run_appends(self, tmp_path: Path) -> None:
        sess = session_mod.create_session(tmp_path)
        updated = session_mod.add_run(tmp_path, sess.session_id, run_id="run_abc")
        assert "run_abc" in updated.run_ids

    def test_add_run_idempotent(self, tmp_path: Path) -> None:
        sess = session_mod.create_session(tmp_path)
        session_mod.add_run(tmp_path, sess.session_id, run_id="run_abc")
        session_mod.add_run(tmp_path, sess.session_id, run_id="run_abc")
        loaded = session_mod.load_session(tmp_path, sess.session_id)
        assert loaded.run_ids.count("run_abc") == 1

    def test_add_run_preserves_order(self, tmp_path: Path) -> None:
        sess = session_mod.create_session(tmp_path)
        for rid in ["r1", "r2", "r3"]:
            session_mod.add_run(tmp_path, sess.session_id, run_id=rid)
        loaded = session_mod.load_session(tmp_path, sess.session_id)
        assert loaded.run_ids == ["r1", "r2", "r3"]

    def test_updated_at_changes_after_add_run(self, tmp_path: Path) -> None:
        sess = session_mod.create_session(tmp_path)
        original_ts = sess.updated_at_utc
        updated = session_mod.add_run(tmp_path, sess.session_id, run_id="r99")
        assert updated.updated_at_utc >= original_ts

    def test_update_notes(self, tmp_path: Path) -> None:
        sess = session_mod.create_session(tmp_path)
        updated = session_mod.update_notes(tmp_path, sess.session_id, notes="new notes")
        assert updated.notes == "new notes"
        loaded = session_mod.load_session(tmp_path, sess.session_id)
        assert loaded.notes == "new notes"

    def test_list_sessions_empty(self, tmp_path: Path) -> None:
        assert session_mod.list_sessions(tmp_path) == []

    def test_list_sessions_sorted_by_created(self, tmp_path: Path) -> None:
        s1 = session_mod.create_session(tmp_path, strategy_id="a")
        s2 = session_mod.create_session(tmp_path, strategy_id="b")
        results = session_mod.list_sessions(tmp_path)
        assert [s.session_id for s in results] == [s1.session_id, s2.session_id]

    def test_find_sessions_by_run(self, tmp_path: Path) -> None:
        s1 = session_mod.create_session(tmp_path)
        s2 = session_mod.create_session(tmp_path)
        session_mod.add_run(tmp_path, s1.session_id, run_id="shared_run")
        session_mod.add_run(tmp_path, s2.session_id, run_id="shared_run")
        matching = session_mod.find_sessions_by_run(tmp_path, "shared_run")
        assert {m.session_id for m in matching} == {s1.session_id, s2.session_id}

    def test_find_sessions_by_run_no_match(self, tmp_path: Path) -> None:
        session_mod.create_session(tmp_path)
        assert session_mod.find_sessions_by_run(tmp_path, "unknown_run") == []

    def test_multiple_sessions_independent(self, tmp_path: Path) -> None:
        s1 = session_mod.create_session(tmp_path, strategy_id="a")
        s2 = session_mod.create_session(tmp_path, strategy_id="b")
        session_mod.add_run(tmp_path, s1.session_id, run_id="r1")
        s1_loaded = session_mod.load_session(tmp_path, s1.session_id)
        s2_loaded = session_mod.load_session(tmp_path, s2.session_id)
        assert s1_loaded.run_ids == ["r1"]
        assert s2_loaded.run_ids == []
