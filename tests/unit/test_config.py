"""Tests for hierarchical config loading and secret resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

import alpha_core.config.loader as config_loader
import alpha_core.config.secrets as secrets_module
from alpha_core.config.loader import load_settings
from alpha_core.config.secrets import (
    missing_required_secrets,
    raise_for_missing_required_secrets,
    resolve_secret,
)


@pytest.fixture
def temp_config_tree(tmp_path: Path) -> Path:
    config_root = tmp_path / "config"
    (config_root / "environments").mkdir(parents=True)
    (config_root / "venues").mkdir(parents=True)

    (config_root / "default.yaml").write_text(
        "\n".join(
            [
                "project_name: alpha-research-lab",
                "log_level: INFO",
                "storage:",
                "  base_path: data",
                "venues:",
                "  - name: kalshi",
                "    exchange_class: Kalshi",
                "    rate_limit_rpm: 60",
            ]
        ),
        encoding="utf-8",
    )
    return config_root


def test_load_default_repo_config_validates() -> None:
    settings = load_settings()

    assert settings.project_name == "alpha-research-lab"
    assert settings.storage.base_path.name == "data"
    assert any(venue.name == "kalshi" for venue in settings.venues)


def test_environment_overlay_merges_correctly(temp_config_tree: Path) -> None:
    (temp_config_tree / "environments" / "local.yaml").write_text(
        "\n".join(["log_level: DEBUG", "storage:", "  base_path: data/local"]),
        encoding="utf-8",
    )

    settings = load_settings(environment="local", config_dir=temp_config_tree)

    assert settings.log_level == "DEBUG"
    assert str(settings.storage.base_path).endswith("data/local")


def test_missing_required_fields_raise_validation_error(tmp_path: Path) -> None:
    config_root = tmp_path / "bad_config"
    (config_root / "environments").mkdir(parents=True)
    (config_root / "venues").mkdir(parents=True)
    (config_root / "default.yaml").write_text(
        "project_name: alpha-research-lab\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_settings(config_dir=config_root)


def test_env_var_override_log_level(
    monkeypatch: pytest.MonkeyPatch,
    temp_config_tree: Path,
) -> None:
    monkeypatch.setenv("ALPHA_LOG_LEVEL", "DEBUG")

    settings = load_settings(config_dir=temp_config_tree)

    assert settings.log_level == "DEBUG"


def test_env_var_nested_override(monkeypatch: pytest.MonkeyPatch, temp_config_tree: Path) -> None:
    monkeypatch.setenv("ALPHA_STORAGE__BASE_PATH", "data/override")

    settings = load_settings(config_dir=temp_config_tree)

    assert str(settings.storage.base_path).endswith("data/override")


def test_env_var_list_index_override(
    monkeypatch: pytest.MonkeyPatch, temp_config_tree: Path
) -> None:
    monkeypatch.setenv("ALPHA_VENUES__0__RATE_LIMIT_RPM", "180")

    settings = load_settings(config_dir=temp_config_tree)

    assert settings.venues[0].rate_limit_rpm == 180


def test_venue_enabled_toggle_file_applies(temp_config_tree: Path) -> None:
    (temp_config_tree / "user_settings.yaml").write_text(
        "venue_enabled:\n  kalshi: false\n",
        encoding="utf-8",
    )

    settings = load_settings(config_dir=temp_config_tree, apply_user_settings=True)
    kalshi = next(venue for venue in settings.venues if venue.name == "kalshi")

    assert kalshi.enabled is False


def test_user_settings_are_opt_in(temp_config_tree: Path) -> None:
    (temp_config_tree / "user_settings.yaml").write_text(
        "venue_enabled:\n  kalshi: false\n",
        encoding="utf-8",
    )

    settings = load_settings(config_dir=temp_config_tree)
    kalshi = next(venue for venue in settings.venues if venue.name == "kalshi")

    assert kalshi.enabled is True


def test_venue_file_overrides_defaults(temp_config_tree: Path) -> None:
    (temp_config_tree / "venues" / "kalshi.yaml").write_text(
        "name: kalshi\nrate_limit_rpm: 180\n",
        encoding="utf-8",
    )

    settings = load_settings(config_dir=temp_config_tree)
    kalshi = next(venue for venue in settings.venues if venue.name == "kalshi")

    assert kalshi.rate_limit_rpm == 180


def test_invalid_rate_limit_raises_validation_error(temp_config_tree: Path) -> None:
    (temp_config_tree / "venues" / "kalshi.yaml").write_text(
        "name: kalshi\nrate_limit_rpm: 0\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_settings(config_dir=temp_config_tree)


def test_invalid_log_level_raises_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    temp_config_tree: Path,
) -> None:
    monkeypatch.setenv("ALPHA_LOG_LEVEL", "TRACE")

    with pytest.raises(ValidationError):
        load_settings(config_dir=temp_config_tree)


def test_partition_by_rejects_duplicates(temp_config_tree: Path) -> None:
    (temp_config_tree / "default.yaml").write_text(
        "\n".join(
            [
                "project_name: alpha-research-lab",
                "log_level: INFO",
                "storage:",
                "  base_path: data",
                "  partition_by:",
                "    - venue",
                "    - venue",
                "venues:",
                "  - name: kalshi",
                "    exchange_class: Kalshi",
                "    rate_limit_rpm: 60",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_settings(config_dir=temp_config_tree)


def test_unknown_environment_file_raises(temp_config_tree: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_settings(environment="does_not_exist", config_dir=temp_config_tree)


def test_default_yaml_non_mapping_raises(tmp_path: Path) -> None:
    config_root = tmp_path / "bad_config"
    (config_root / "environments").mkdir(parents=True)
    (config_root / "venues").mkdir(parents=True)
    (config_root / "default.yaml").write_text("- bad\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected a YAML object"):
        load_settings(config_dir=config_root)


def test_environment_yaml_non_mapping_raises(temp_config_tree: Path) -> None:
    (temp_config_tree / "environments" / "local.yaml").write_text("- bad\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected a YAML object"):
        load_settings(environment="local", config_dir=temp_config_tree)


def test_user_settings_requires_mapping(temp_config_tree: Path) -> None:
    (temp_config_tree / "user_settings.yaml").write_text("venue_enabled: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain a mapping"):
        load_settings(config_dir=temp_config_tree, apply_user_settings=True)


def test_user_settings_requires_boolean_values(temp_config_tree: Path) -> None:
    (temp_config_tree / "user_settings.yaml").write_text(
        'venue_enabled:\n  kalshi: "false"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be boolean"):
        load_settings(config_dir=temp_config_tree, apply_user_settings=True)


def test_set_nested_value_rejects_non_numeric_list_index() -> None:
    target = {"venues": [{"name": "kalshi", "rate_limit_rpm": 60}]}

    with pytest.raises(ValueError, match="numeric indices"):
        config_loader._set_nested_value(target, ["venues", "first", "rate_limit_rpm"], 120)


def test_set_nested_value_rejects_out_of_range_list_index() -> None:
    target = {"venues": [{"name": "kalshi", "rate_limit_rpm": 60}]}

    with pytest.raises(IndexError, match="out of range"):
        config_loader._set_nested_value(target, ["venues", "1", "rate_limit_rpm"], 120)


def test_set_nested_value_rejects_non_container_path() -> None:
    target = {"log_level": "INFO"}

    with pytest.raises(TypeError, match="non-container"):
        config_loader._set_nested_value(target, ["log_level", "level"], "DEBUG")


def test_path_exists_supports_list_indices() -> None:
    target = {"venues": [{"name": "kalshi", "enabled": True}]}

    assert config_loader._path_exists(target, ["venues", "0", "enabled"])
    assert not config_loader._path_exists(target, ["venues", "x", "enabled"])
    assert not config_loader._path_exists(target, ["venues", "9", "enabled"])


def test_secret_resolution_returns_none_for_unset_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPHA_TEST_SECRET", raising=False)

    assert resolve_secret("ALPHA_TEST_SECRET") is None


def test_secret_resolution_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_TEST_SECRET", "  token-123  ")

    assert resolve_secret("ALPHA_TEST_SECRET") == "token-123"


def test_secret_resolution_falls_back_to_secrets_file(tmp_path: Path) -> None:
    secrets_file = tmp_path / ".secrets"
    secrets_file.write_text("ALPHA_TEST_SECRET=file-token\n", encoding="utf-8")

    assert resolve_secret("ALPHA_TEST_SECRET", secrets_file=secrets_file) == "file-token"


def test_env_secret_takes_precedence_over_secrets_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secrets_file = tmp_path / ".secrets"
    secrets_file.write_text("ALPHA_TEST_SECRET=file-token\n", encoding="utf-8")
    monkeypatch.setenv("ALPHA_TEST_SECRET", "env-token")

    assert resolve_secret("ALPHA_TEST_SECRET", secrets_file=secrets_file) == "env-token"


def test_secret_resolution_reads_venue_specific_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / "polymarket.secrets").write_text(
        "API_KEY_ENV=file-api\nPRIVATE_KEY_ENV=file-private\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(secrets_module, "_project_root", lambda: tmp_path)
    monkeypatch.delenv("ALPHA_POLYMARKET_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_POLYMARKET_PRIVATE_KEY", raising=False)

    assert resolve_secret("ALPHA_POLYMARKET_API_KEY") == "file-api"
    assert resolve_secret("ALPHA_POLYMARKET_PRIVATE_KEY") == "file-private"


def test_explicit_secrets_file_disables_venue_specific_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / "polymarket.secrets").write_text("API_KEY_ENV=file-api\n", encoding="utf-8")
    explicit_file = tmp_path / "custom.secrets"
    explicit_file.write_text("ALPHA_OTHER=unused\n", encoding="utf-8")

    monkeypatch.setattr(secrets_module, "_project_root", lambda: tmp_path)
    monkeypatch.delenv("ALPHA_POLYMARKET_API_KEY", raising=False)

    assert resolve_secret("ALPHA_POLYMARKET_API_KEY", secrets_file=explicit_file) is None


def test_secret_env_var_does_not_break_config_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_KALSHI_API_KEY", "dummy-token")

    settings = load_settings()

    assert settings.project_name == "alpha-research-lab"


def test_unknown_alpha_env_var_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
    temp_config_tree: Path,
) -> None:
    monkeypatch.setenv("ALPHA_NOT_A_REAL_SETTING", "dummy-token")

    settings = load_settings(config_dir=temp_config_tree)

    assert settings.project_name == "alpha-research-lab"


def test_missing_required_secrets_only_checks_enabled_venues() -> None:
    settings = load_settings()
    missing = missing_required_secrets(settings)

    assert "ALPHA_KALSHI_API_KEY" in missing
    assert "ALPHA_KALSHI_PRIVATE_KEY" in missing


def test_missing_required_secrets_ignores_disabled_venues(temp_config_tree: Path) -> None:
    (temp_config_tree / "default.yaml").write_text(
        "\n".join(
            [
                "project_name: alpha-research-lab",
                "log_level: INFO",
                "storage:",
                "  base_path: data",
                "venues:",
                "  - name: kalshi",
                "    exchange_class: Kalshi",
                "    enabled: false",
                "    api_key_env: ALPHA_KALSHI_API_KEY",
                "    private_key_env: ALPHA_KALSHI_PRIVATE_KEY",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(config_dir=temp_config_tree)
    assert missing_required_secrets(settings) == []


def test_raise_for_missing_required_secrets_raises() -> None:
    settings = load_settings()

    with pytest.raises(ValueError, match="Missing required secrets"):
        raise_for_missing_required_secrets(settings)


def test_load_settings_validate_secrets_true_raises(temp_config_tree: Path) -> None:
    (temp_config_tree / "default.yaml").write_text(
        "\n".join(
            [
                "project_name: alpha-research-lab",
                "log_level: INFO",
                "storage:",
                "  base_path: data",
                "venues:",
                "  - name: kalshi",
                "    exchange_class: Kalshi",
                "    enabled: true",
                "    api_key_env: ALPHA_KALSHI_API_KEY",
                "    private_key_env: ALPHA_KALSHI_PRIVATE_KEY",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Missing required secrets"):
        load_settings(config_dir=temp_config_tree, validate_secrets=True)
