"""Unit tests for alpha_core.config.profiles (13.3 — Environment Profile Contract).

Covers:
- ProfileName enum membership
- EnvironmentProfile construction and field validation
- BUILTIN_PROFILES completeness (all five profiles present)
- Safety invariants per profile (execution_enabled, dry_run, allow_real_money)
- get_profile() string and enum lookup
- get_profile() raises ValueError for unknown names
- Immutability (frozen model)
- Serialization round-trip
- data_retention_days semantics (None vs positive int)
- Log level values are valid
- Module importability via alpha_core.config
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

import alpha_core.config as config_pkg
import alpha_core.config.profiles as config_profiles

# ---------------------------------------------------------------------------
# 1. ProfileName enum
# ---------------------------------------------------------------------------


class TestProfileName:
    def test_all_five_names_present(self) -> None:
        names = {p.value for p in config_profiles.ProfileName}
        assert names == {"dev", "research", "ci", "paper", "live"}

    @pytest.mark.parametrize(
        "value",
        ["dev", "research", "ci", "paper", "live"],
    )
    def test_string_construction(self, value: str) -> None:
        assert config_profiles.ProfileName(value).value == value

    def test_invalid_name_raises(self) -> None:
        with pytest.raises(ValueError):
            config_profiles.ProfileName("staging")


# ---------------------------------------------------------------------------
# 2. BUILTIN_PROFILES completeness
# ---------------------------------------------------------------------------


class TestBuiltinProfiles:
    def test_all_profiles_registered(self) -> None:
        assert set(config_profiles.BUILTIN_PROFILES.keys()) == set(config_profiles.ProfileName)

    @pytest.mark.parametrize("profile_name", list(config_profiles.ProfileName))
    def test_profile_has_correct_name_field(
        self,
        profile_name: config_profiles.ProfileName,
    ) -> None:
        assert config_profiles.BUILTIN_PROFILES[profile_name].name == profile_name

    @pytest.mark.parametrize("profile_name", list(config_profiles.ProfileName))
    def test_storage_root_is_path(self, profile_name: config_profiles.ProfileName) -> None:
        assert isinstance(config_profiles.BUILTIN_PROFILES[profile_name].storage_root, Path)

    @pytest.mark.parametrize("profile_name", list(config_profiles.ProfileName))
    def test_log_level_is_valid(self, profile_name: config_profiles.ProfileName) -> None:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        assert config_profiles.BUILTIN_PROFILES[profile_name].log_level in valid

    @pytest.mark.parametrize("profile_name", list(config_profiles.ProfileName))
    def test_storage_root_contains_profile_name(
        self,
        profile_name: config_profiles.ProfileName,
    ) -> None:
        root = str(config_profiles.BUILTIN_PROFILES[profile_name].storage_root)
        assert profile_name.value in root


# ---------------------------------------------------------------------------
# 3. Safety invariants
# ---------------------------------------------------------------------------


class TestSafetyInvariants:
    """Core safety contracts that must never regress."""

    # Non-trading profiles: execution disabled
    @pytest.mark.parametrize(
        "profile_name",
        [
            config_profiles.ProfileName.DEV,
            config_profiles.ProfileName.RESEARCH,
            config_profiles.ProfileName.CI,
        ],
    )
    def test_non_trading_profiles_execution_disabled(
        self,
        profile_name: config_profiles.ProfileName,
    ) -> None:
        assert not config_profiles.BUILTIN_PROFILES[profile_name].execution_enabled

    # Non-trading profiles: dry_run on
    @pytest.mark.parametrize(
        "profile_name",
        [
            config_profiles.ProfileName.DEV,
            config_profiles.ProfileName.RESEARCH,
            config_profiles.ProfileName.CI,
        ],
    )
    def test_non_trading_profiles_dry_run(
        self,
        profile_name: config_profiles.ProfileName,
    ) -> None:
        assert config_profiles.BUILTIN_PROFILES[profile_name].dry_run

    # Trading profiles: execution enabled
    @pytest.mark.parametrize(
        "profile_name",
        [config_profiles.ProfileName.PAPER, config_profiles.ProfileName.LIVE],
    )
    def test_trading_profiles_execution_enabled(
        self,
        profile_name: config_profiles.ProfileName,
    ) -> None:
        assert config_profiles.BUILTIN_PROFILES[profile_name].execution_enabled

    # Trading profiles: dry_run off
    @pytest.mark.parametrize(
        "profile_name",
        [config_profiles.ProfileName.PAPER, config_profiles.ProfileName.LIVE],
    )
    def test_trading_profiles_dry_run_off(
        self,
        profile_name: config_profiles.ProfileName,
    ) -> None:
        assert not config_profiles.BUILTIN_PROFILES[profile_name].dry_run

    # Only LIVE allows real money
    def test_only_live_allows_real_money(self) -> None:
        for name, profile in config_profiles.BUILTIN_PROFILES.items():
            if name is config_profiles.ProfileName.LIVE:
                assert profile.allow_real_money, "live must allow real money"
            else:
                assert not profile.allow_real_money, f"{name} must NOT allow real money"

    # RESEARCH explicitly disables execution (key contract from spec)
    def test_research_execution_disabled(self) -> None:
        assert not config_profiles.BUILTIN_PROFILES[
            config_profiles.ProfileName.RESEARCH
        ].execution_enabled

    # CI retention is finite
    def test_ci_has_finite_retention(self) -> None:
        ret = config_profiles.BUILTIN_PROFILES[config_profiles.ProfileName.CI].data_retention_days
        assert ret is not None
        assert ret > 0

    # DEV/RESEARCH/LIVE have no retention limit
    @pytest.mark.parametrize(
        "profile_name",
        [
            config_profiles.ProfileName.DEV,
            config_profiles.ProfileName.RESEARCH,
            config_profiles.ProfileName.LIVE,
        ],
    )
    def test_indefinite_retention_profiles(
        self,
        profile_name: config_profiles.ProfileName,
    ) -> None:
        assert config_profiles.BUILTIN_PROFILES[profile_name].data_retention_days is None

    # PAPER has positive finite retention
    def test_paper_has_positive_retention(self) -> None:
        ret = config_profiles.BUILTIN_PROFILES[
            config_profiles.ProfileName.PAPER
        ].data_retention_days
        assert ret is not None and ret > 0

    # DEV has DEBUG logging
    def test_dev_debug_logging(self) -> None:
        profile = config_profiles.BUILTIN_PROFILES[config_profiles.ProfileName.DEV]
        assert profile.log_level == "DEBUG"

    # CI has WARNING+ logging (keep CI output clean)
    def test_ci_warning_logging(self) -> None:
        level = config_profiles.BUILTIN_PROFILES[config_profiles.ProfileName.CI].log_level
        assert level in {"WARNING", "ERROR", "CRITICAL"}


# ---------------------------------------------------------------------------
# 4. get_profile()
# ---------------------------------------------------------------------------


class TestGetProfile:
    @pytest.mark.parametrize("profile_name", list(config_profiles.ProfileName))
    def test_lookup_by_enum(self, profile_name: config_profiles.ProfileName) -> None:
        profile = config_profiles.get_profile(profile_name)
        assert profile.name == profile_name

    @pytest.mark.parametrize(
        "value",
        ["dev", "research", "ci", "paper", "live"],
    )
    def test_lookup_by_string(self, value: str) -> None:
        profile = config_profiles.get_profile(value)
        assert profile.name.value == value

    def test_unknown_name_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown profile"):
            config_profiles.get_profile("staging")

    def test_error_message_lists_valid_profiles(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            config_profiles.get_profile("unknown_xyz")
        msg = str(exc_info.value)
        for name in config_profiles.ProfileName:
            assert name.value in msg

    def test_returns_same_object_as_builtin_profiles(self) -> None:
        # get_profile must return the canonical registry entry (identity check)
        for name in config_profiles.ProfileName:
            assert config_profiles.get_profile(name) is config_profiles.BUILTIN_PROFILES[name]


# ---------------------------------------------------------------------------
# 5. EnvironmentProfile model validation
# ---------------------------------------------------------------------------


class TestEnvironmentProfileModel:
    def test_construct_minimal(self) -> None:
        p = config_profiles.EnvironmentProfile(
            name=config_profiles.ProfileName.DEV,
            storage_root=Path("data/custom_dev"),
            log_level="DEBUG",
            execution_enabled=False,
            dry_run=True,
            allow_real_money=False,
        )
        assert p.data_retention_days is None

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            config_profiles.EnvironmentProfile(  # type: ignore[call-arg]
                name=config_profiles.ProfileName.DEV,
                storage_root=Path("data/dev"),
                log_level="DEBUG",
                execution_enabled=False,
                dry_run=True,
                allow_real_money=False,
                unknown_field="x",
            )

    def test_zero_retention_rejected(self) -> None:
        with pytest.raises(ValidationError):
            config_profiles.EnvironmentProfile(
                name=config_profiles.ProfileName.CI,
                storage_root=Path("data/ci"),
                log_level="WARNING",
                execution_enabled=False,
                dry_run=True,
                allow_real_money=False,
                data_retention_days=0,  # must be >= 1
            )

    def test_negative_retention_rejected(self) -> None:
        with pytest.raises(ValidationError):
            config_profiles.EnvironmentProfile(
                name=config_profiles.ProfileName.CI,
                storage_root=Path("data/ci"),
                log_level="WARNING",
                execution_enabled=False,
                dry_run=True,
                allow_real_money=False,
                data_retention_days=-7,
            )

    def test_frozen_prevents_mutation(self) -> None:
        profile = config_profiles.BUILTIN_PROFILES[config_profiles.ProfileName.DEV]
        with pytest.raises(ValidationError):
            profile.execution_enabled = True  # type: ignore[misc]

    def test_round_trip_serialization(self) -> None:
        profile = config_profiles.BUILTIN_PROFILES[config_profiles.ProfileName.PAPER]
        restored = config_profiles.EnvironmentProfile.model_validate(profile.model_dump())
        assert restored == profile
        assert restored.name == config_profiles.ProfileName.PAPER
        assert restored.execution_enabled is True


# ---------------------------------------------------------------------------
# 6. Module importability
# ---------------------------------------------------------------------------


def test_profiles_importable_from_config_package() -> None:
    assert hasattr(config_pkg, "profiles")


def test_get_profile_importable_directly() -> None:
    assert callable(config_profiles.get_profile)
