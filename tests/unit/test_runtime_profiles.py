"""Tests for LA-021: runtime environment profiles across collector, research, and live.

Covers:
- load_settings applies profile log_level, dry_run, and profile field
- Unknown profile raises ValueError fast
- Profile YAML overlays (research, paper, live) load via loader
- guard_execution raises PermissionError for non-execution profiles
- guard_real_money raises PermissionError for non-real-money profiles
- All three CLIs accept and honour --profile
- Live --execute blocked when profile forbids execution
"""

from __future__ import annotations

from pathlib import Path

import apps.data_collector.main as collector_main
import apps.live_system.main as live_main
import apps.research.main as research_main
import pytest
from click.testing import CliRunner

import alpha_core.config.loader as config_loader
import alpha_core.config.profiles as config_profiles

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_YAML = "\n".join(
    [
        "project_name: alpha-research-lab",
        "log_level: INFO",
        "storage:",
        "  base_path: data",
        "venues:",
        "  - name: polymarket",
        "    exchange_class: Polymarket",
        "    enabled: true",
        "    rate_limit_rpm: 60",
    ]
)


@pytest.fixture()
def config_root(tmp_path: Path) -> Path:
    """Minimal config tree with research/paper/live environment overlays."""
    root = tmp_path / "repo"
    cfg = root / "config"
    (cfg / "environments").mkdir(parents=True)
    (cfg / "venues").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "alpha-research-lab"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (cfg / "default.yaml").write_text(_MINIMAL_YAML, encoding="utf-8")

    for profile_name in ("research", "paper", "live"):
        ep = config_profiles.get_profile(profile_name)
        (cfg / "environments" / f"{profile_name}.yaml").write_text(
            "\n".join(
                [
                    f"profile: {profile_name}",
                    f"log_level: {ep.log_level}",
                    "feature_flags:",
                    f"  dry_run: {'true' if ep.dry_run else 'false'}",
                    "storage:",
                    f"  base_path: data/{profile_name}",
                ]
            ),
            encoding="utf-8",
        )
    (cfg / "user_settings.yaml").write_text(
        "venue_enabled:\n  polymarket: true\n",
        encoding="utf-8",
    )
    return cfg


# ---------------------------------------------------------------------------
# 1. load_settings with --profile
# ---------------------------------------------------------------------------


class TestLoadSettingsWithProfile:
    @pytest.mark.parametrize("profile_name", ["dev", "research", "ci", "paper", "live"])
    def test_profile_field_set(self, config_root: Path, profile_name: str) -> None:
        settings = config_loader.load_settings(config_dir=config_root, profile=profile_name)
        assert settings.profile is not None
        assert settings.profile.value == profile_name

    @pytest.mark.parametrize(
        "profile_name,expected_log",
        [
            ("dev", "DEBUG"),
            ("research", "INFO"),
            ("ci", "WARNING"),
            ("paper", "INFO"),
            ("live", "INFO"),
        ],
    )
    def test_log_level_matches_profile(
        self, config_root: Path, profile_name: str, expected_log: str
    ) -> None:
        settings = config_loader.load_settings(config_dir=config_root, profile=profile_name)
        assert settings.log_level == expected_log

    @pytest.mark.parametrize(
        "profile_name,expected_dry_run",
        [
            ("dev", True),
            ("research", True),
            ("ci", True),
            ("paper", False),
            ("live", False),
        ],
    )
    def test_dry_run_matches_profile(
        self, config_root: Path, profile_name: str, expected_dry_run: bool
    ) -> None:
        settings = config_loader.load_settings(config_dir=config_root, profile=profile_name)
        assert settings.feature_flags.get("dry_run") == expected_dry_run

    @pytest.mark.parametrize(
        "profile_name,expected_suffix",
        [
            ("dev", "data/dev"),
            ("research", "data/research"),
            ("ci", "data/ci"),
            ("paper", "data/paper"),
            ("live", "data/live"),
        ],
    )
    def test_storage_root_matches_profile(
        self, config_root: Path, profile_name: str, expected_suffix: str
    ) -> None:
        settings = config_loader.load_settings(config_dir=config_root, profile=profile_name)
        assert settings.storage.base_path.as_posix().endswith(expected_suffix)

    @pytest.mark.parametrize(
        "profile_name,expected_retention",
        [
            ("dev", None),
            ("research", None),
            ("ci", 7),
            ("paper", 90),
            ("live", None),
        ],
    )
    def test_retention_matches_profile(
        self, config_root: Path, profile_name: str, expected_retention: int | None
    ) -> None:
        settings = config_loader.load_settings(config_dir=config_root, profile=profile_name)
        assert settings.storage.retention_days == expected_retention

    def test_safety_flags_are_authoritative(self, config_root: Path) -> None:
        """Profile log_level cannot be overridden by a lower-priority YAML layer."""
        # ci.yaml would normally set WARNING; profile always wins
        (config_root / "environments" / "local.yaml").write_text(
            "log_level: DEBUG\n", encoding="utf-8"
        )
        settings = config_loader.load_settings(
            config_dir=config_root, environment="local", profile="ci"
        )
        # ci profile should enforce WARNING despite local.yaml DEBUG
        assert settings.log_level == "WARNING"

    def test_unknown_profile_raises_fast(self, config_root: Path) -> None:
        with pytest.raises(ValueError, match="Unknown profile"):
            config_loader.load_settings(config_dir=config_root, profile="staging")

    def test_no_profile_leaves_settings_unchanged(self, config_root: Path) -> None:
        settings = config_loader.load_settings(config_dir=config_root)
        assert settings.profile is None
        assert settings.log_level == "INFO"


# ---------------------------------------------------------------------------
# 2. Settings.profile field validation
# ---------------------------------------------------------------------------


class TestSettingsProfileField:
    def test_profile_field_accepts_valid_name(self, config_root: Path) -> None:
        settings = config_loader.load_settings(config_dir=config_root, profile="paper")
        assert settings.profile == config_profiles.ProfileName.PAPER

    def test_profile_none_by_default(self, config_root: Path) -> None:
        settings = config_loader.load_settings(config_dir=config_root)
        assert settings.profile is None


# ---------------------------------------------------------------------------
# 3. Safety guard functions
# ---------------------------------------------------------------------------


class TestGuardExecution:
    @pytest.mark.parametrize(
        "profile_name",
        ["dev", "research", "ci"],
    )
    def test_raises_for_non_execution_profiles(self, profile_name: str) -> None:
        profile = config_profiles.get_profile(profile_name)
        with pytest.raises(PermissionError, match="does not allow"):
            config_profiles.guard_execution(profile)

    @pytest.mark.parametrize("profile_name", ["paper", "live"])
    def test_passes_for_execution_profiles(self, profile_name: str) -> None:
        profile = config_profiles.get_profile(profile_name)
        config_profiles.guard_execution(profile)  # must not raise

    def test_none_profile_skips_guard(self) -> None:
        config_profiles.guard_execution(None)  # no profile → no guard


class TestGuardRealMoney:
    @pytest.mark.parametrize("profile_name", ["dev", "research", "ci", "paper"])
    def test_raises_for_non_real_money_profiles(self, profile_name: str) -> None:
        profile = config_profiles.get_profile(profile_name)
        with pytest.raises(PermissionError, match="does not allow"):
            config_profiles.guard_real_money(profile)

    def test_passes_for_live_profile(self) -> None:
        profile = config_profiles.get_profile("live")
        config_profiles.guard_real_money(profile)  # must not raise

    def test_none_profile_skips_guard(self) -> None:
        config_profiles.guard_real_money(None)  # no profile → no guard

    def test_error_message_mentions_live(self) -> None:
        profile = config_profiles.get_profile("paper")
        with pytest.raises(PermissionError, match="live"):
            config_profiles.guard_real_money(profile)


# ---------------------------------------------------------------------------
# 4. CLI entrypoints accept and honour --profile
# ---------------------------------------------------------------------------

_CLI_ENV_KEY = "ALPHA_RESEARCH_ROOT"


def _repo_env(root: Path) -> dict[str, str]:
    return {_CLI_ENV_KEY: str(root)}


class TestDataCollectorCLI:
    def test_validate_accepts_profile_flag(self, config_root: Path) -> None:
        runner = CliRunner()
        repo_root = config_root.parent
        result = runner.invoke(
            collector_main.main,
            ["validate", "--profile", "research", "--ignore-user-settings"],
            env={_CLI_ENV_KEY: str(repo_root)},
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "profile=research" in result.output

    def test_validate_unknown_profile_exits_nonzero(self, config_root: Path) -> None:
        runner = CliRunner()
        repo_root = config_root.parent
        result = runner.invoke(
            collector_main.main,
            ["validate", "--profile", "staging"],
            env={_CLI_ENV_KEY: str(repo_root)},
        )
        # click.Choice validation rejects unknown values before the command body
        assert result.exit_code != 0


class TestResearchCLI:
    def test_help_shows_profile_option(self) -> None:
        runner = CliRunner()
        result = runner.invoke(research_main.main, ["--help"])
        assert "--profile" in result.output

    def test_profile_stored_in_context(self, config_root: Path) -> None:
        """Verify --profile is accepted at group level without error."""
        runner = CliRunner()
        repo_root = config_root.parent
        result = runner.invoke(
            research_main.main,
            ["--profile", "research", "--help"],
            env={_CLI_ENV_KEY: str(repo_root)},
        )
        assert result.exit_code == 0


class TestLiveSystemCLI:
    def test_help_shows_profile_option(self) -> None:
        runner = CliRunner()
        result = runner.invoke(live_main.main, ["--help"])
        assert "--profile" in result.output

    def test_execute_blocked_by_research_profile(self, config_root: Path) -> None:
        """--execute with --profile research must fail with actionable error."""
        runner = CliRunner()
        repo_root = config_root.parent
        result = runner.invoke(
            live_main.main,
            [
                "--profile",
                "research",
                "run",
                "--instrument",
                "p:abc:yes",
                "--execute",
            ],
            env={_CLI_ENV_KEY: str(repo_root)},
        )
        assert result.exit_code != 0
        assert "does not allow" in result.output or "does not allow" in str(result.exception)

    def test_plan_only_passes_with_research_profile(self, config_root: Path) -> None:
        """--plan-only with any profile must succeed (no order submission)."""
        runner = CliRunner()
        repo_root = config_root.parent
        result = runner.invoke(
            live_main.main,
            [
                "--profile",
                "research",
                "run",
                "--instrument",
                "p:abc:yes",
                "--plan-only",
            ],
            env={_CLI_ENV_KEY: str(repo_root)},
        )
        # plan-only never triggers the execution guard
        assert result.exit_code == 0

    def test_real_money_requires_live_profile(self, config_root: Path) -> None:
        runner = CliRunner()
        repo_root = config_root.parent
        result = runner.invoke(
            live_main.main,
            [
                "--profile",
                "paper",
                "run",
                "--instrument",
                "p:abc:yes",
                "--storage-root",
                str(config_root.parent / "paper_storage"),
                "--execute",
                "--real-money",
            ],
            env={_CLI_ENV_KEY: str(repo_root)},
        )
        assert result.exit_code != 0
        assert "profile live" in result.output.lower()

    def test_real_money_allowed_for_live_profile(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            live_main.main,
            [
                "--profile",
                "live",
                "run",
                "--instrument",
                "p:abc:yes",
                "--storage-root",
                str(tmp_path),
                "--execute",
                "--real-money",
            ],
        )
        assert result.exit_code == 0, result.output

    def test_unknown_profile_exits_nonzero(self) -> None:
        runner = CliRunner()
        result = runner.invoke(live_main.main, ["--profile", "staging", "run", "--help"])
        assert result.exit_code != 0
