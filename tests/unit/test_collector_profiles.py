"""Unit tests for §13.4 — Operational Profiles for Data Collection.

Covers:
- All three built-in profiles exist with correct field values
- get_collector_profile() lookup by name and StrEnum
- Unknown profile raises ValueError with actionable message
- Profiles are frozen (immutable)
- apply_collector_profile() overwrites timing fields and preserves others
- Profile contracts: dev slower than research/live, live strictest health gates
- Metadata emission flags: research emits, dev and live do not
"""

from __future__ import annotations

import pytest

import alpha_core.config.collector_profiles as cp
import alpha_core.config.models as models

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_NAMES = [
    cp.CollectorProfileName.DEV,
    cp.CollectorProfileName.RESEARCH,
    cp.CollectorProfileName.LIVE,
]


def _base_collection_config() -> models.CollectionConfig:
    return models.CollectionConfig(
        mode="poll",
        trade_poll_interval=30.0,
        ohlcv_poll_interval=300.0,
        book_poll_interval=60.0,
        market_refresh_interval=300.0,
        stream_outcomes_max=50,
        heartbeat_timeout=120.0,
        reconnect_backoff_base=1.0,
        reconnect_backoff_max=60.0,
    )


# ---------------------------------------------------------------------------
# Registry completeness
# ---------------------------------------------------------------------------


class TestBuiltinProfiles:
    def test_all_three_profiles_registered(self) -> None:
        assert set(cp.BUILTIN_COLLECTOR_PROFILES.keys()) == {
            cp.CollectorProfileName.DEV,
            cp.CollectorProfileName.RESEARCH,
            cp.CollectorProfileName.LIVE,
        }

    @pytest.mark.parametrize("name", _ALL_NAMES)
    def test_profile_name_field_matches_key(self, name: cp.CollectorProfileName) -> None:
        profile = cp.BUILTIN_COLLECTOR_PROFILES[name]
        assert profile.name == name

    @pytest.mark.parametrize("name", _ALL_NAMES)
    def test_all_timing_fields_positive(self, name: cp.CollectorProfileName) -> None:
        p = cp.BUILTIN_COLLECTOR_PROFILES[name]
        assert p.trade_poll_interval > 0
        assert p.ohlcv_poll_interval > 0
        assert p.book_poll_interval > 0
        assert p.market_refresh_interval > 0
        assert p.heartbeat_timeout > 0
        assert p.reconnect_backoff_base > 0
        assert p.reconnect_backoff_max > 0


# ---------------------------------------------------------------------------
# get_collector_profile lookup
# ---------------------------------------------------------------------------


class TestGetCollectorProfile:
    @pytest.mark.parametrize("name", ["dev", "research", "live"])
    def test_lookup_by_string(self, name: str) -> None:
        profile = cp.get_collector_profile(name)
        assert profile.name.value == name

    @pytest.mark.parametrize("name", _ALL_NAMES)
    def test_lookup_by_enum(self, name: cp.CollectorProfileName) -> None:
        profile = cp.get_collector_profile(name)
        assert profile.name == name

    def test_unknown_profile_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown collector profile"):
            cp.get_collector_profile("staging")

    def test_error_message_lists_valid_options(self) -> None:
        with pytest.raises(ValueError, match="dev"):
            cp.get_collector_profile("invalid")


# ---------------------------------------------------------------------------
# Profile immutability
# ---------------------------------------------------------------------------


class TestProfileImmutability:
    @pytest.mark.parametrize("name", _ALL_NAMES)
    def test_profile_is_frozen(self, name: cp.CollectorProfileName) -> None:
        profile = cp.get_collector_profile(name)
        assert profile.model_config.get("frozen") is True


# ---------------------------------------------------------------------------
# dev profile contract
# ---------------------------------------------------------------------------


class TestDevProfile:
    def setup_method(self) -> None:
        self.profile = cp.get_collector_profile("dev")

    def test_log_level_is_debug(self) -> None:
        assert self.profile.log_level == "DEBUG"

    def test_retention_is_7_days(self) -> None:
        assert self.profile.data_retention_days == 7

    def test_does_not_emit_replay_package(self) -> None:
        assert self.profile.emit_replay_package is False

    def test_does_not_emit_handoff_manifest(self) -> None:
        assert self.profile.emit_handoff_manifest is False

    def test_health_gate_is_lenient(self) -> None:
        assert self.profile.health_gate_strict is False

    def test_restart_policy_is_lenient(self) -> None:
        assert self.profile.restart_policy == "lenient"

    def test_max_reconnect_attempts_is_bounded(self) -> None:
        assert self.profile.max_reconnect_attempts is not None
        assert self.profile.max_reconnect_attempts >= 1

    def test_poll_intervals_slower_than_research(self) -> None:
        research = cp.get_collector_profile("research")
        assert self.profile.trade_poll_interval > research.trade_poll_interval
        assert self.profile.ohlcv_poll_interval > research.ohlcv_poll_interval
        assert self.profile.book_poll_interval > research.book_poll_interval


# ---------------------------------------------------------------------------
# research profile contract
# ---------------------------------------------------------------------------


class TestResearchProfile:
    def setup_method(self) -> None:
        self.profile = cp.get_collector_profile("research")

    def test_log_level_is_info(self) -> None:
        assert self.profile.log_level == "INFO"

    def test_no_retention_limit(self) -> None:
        assert self.profile.data_retention_days is None

    def test_emits_replay_package(self) -> None:
        assert self.profile.emit_replay_package is True

    def test_emits_handoff_manifest(self) -> None:
        assert self.profile.emit_handoff_manifest is True

    def test_health_gate_not_strict(self) -> None:
        assert self.profile.health_gate_strict is False

    def test_restart_policy_is_lenient(self) -> None:
        assert self.profile.restart_policy == "lenient"


# ---------------------------------------------------------------------------
# live profile contract
# ---------------------------------------------------------------------------


class TestLiveProfile:
    def setup_method(self) -> None:
        self.profile = cp.get_collector_profile("live")

    def test_log_level_is_info(self) -> None:
        assert self.profile.log_level == "INFO"

    def test_no_retention_limit(self) -> None:
        assert self.profile.data_retention_days is None

    def test_does_not_emit_replay_package(self) -> None:
        """Live ingestion does not need replay packages — use lineage for tracing."""
        assert self.profile.emit_replay_package is False

    def test_does_not_emit_handoff_manifest(self) -> None:
        assert self.profile.emit_handoff_manifest is False

    def test_health_gate_is_strict(self) -> None:
        assert self.profile.health_gate_strict is True

    def test_restart_policy_is_conservative(self) -> None:
        assert self.profile.restart_policy == "conservative"

    def test_max_reconnect_attempts_is_unlimited(self) -> None:
        """Live never circuit-breaks — always attempts to recover."""
        assert self.profile.max_reconnect_attempts is None

    def test_heartbeat_timeout_shorter_than_dev(self) -> None:
        """Tighter heartbeat window for earlier stale detection in production."""
        dev = cp.get_collector_profile("dev")
        assert self.profile.heartbeat_timeout < dev.heartbeat_timeout

    def test_heartbeat_timeout_shorter_than_research(self) -> None:
        research = cp.get_collector_profile("research")
        assert self.profile.heartbeat_timeout < research.heartbeat_timeout


# ---------------------------------------------------------------------------
# apply_collector_profile
# ---------------------------------------------------------------------------


class TestApplyCollectorProfile:
    def test_apply_dev_slows_down_intervals(self) -> None:
        cfg = _base_collection_config()
        dev = cp.get_collector_profile("dev")
        applied = cp.apply_collector_profile(cfg, dev)
        assert applied.trade_poll_interval == dev.trade_poll_interval
        assert applied.ohlcv_poll_interval == dev.ohlcv_poll_interval
        assert applied.book_poll_interval == dev.book_poll_interval
        assert applied.market_refresh_interval == dev.market_refresh_interval

    def test_apply_research_sets_normal_intervals(self) -> None:
        cfg = _base_collection_config()
        research = cp.get_collector_profile("research")
        applied = cp.apply_collector_profile(cfg, research)
        assert applied.trade_poll_interval == research.trade_poll_interval
        assert applied.heartbeat_timeout == research.heartbeat_timeout

    def test_apply_live_sets_tight_heartbeat(self) -> None:
        cfg = _base_collection_config()
        live = cp.get_collector_profile("live")
        applied = cp.apply_collector_profile(cfg, live)
        assert applied.heartbeat_timeout == live.heartbeat_timeout

    def test_apply_preserves_unrelated_fields(self) -> None:
        """mode and stream_outcomes_max must survive the profile merge."""
        cfg = _base_collection_config().model_copy(
            update={"mode": "both", "stream_outcomes_max": 25}
        )
        applied = cp.apply_collector_profile(cfg, cp.get_collector_profile("research"))
        assert applied.mode == "both"
        assert applied.stream_outcomes_max == 25

    def test_apply_returns_new_instance(self) -> None:
        cfg = _base_collection_config()
        dev = cp.get_collector_profile("dev")
        applied = cp.apply_collector_profile(cfg, dev)
        # original unchanged
        assert cfg.trade_poll_interval == 30.0
        assert applied.trade_poll_interval == dev.trade_poll_interval
        assert applied is not cfg

    def test_apply_live_backoff_values_preserved(self) -> None:
        cfg = _base_collection_config()
        live = cp.get_collector_profile("live")
        applied = cp.apply_collector_profile(cfg, live)
        assert applied.reconnect_backoff_base == live.reconnect_backoff_base
        assert applied.reconnect_backoff_max == live.reconnect_backoff_max
