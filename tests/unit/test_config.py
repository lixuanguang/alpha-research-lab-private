"""Tests for hierarchical config loading and secret resolution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

import alpha_core.config.loader as config_loader
import alpha_core.config.secrets as config_secrets


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
                "  - name: polymarket",
                "    exchange_class: Polymarket",
                "    rate_limit_rpm: 60",
            ]
        ),
        encoding="utf-8",
    )
    return config_root


@pytest.fixture
def temp_repo_root(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    config_root = repo_root / "config"
    (config_root / "environments").mkdir(parents=True)
    (config_root / "venues").mkdir(parents=True)
    (repo_root / "pyproject.toml").write_text(
        '[project]\nname = "alpha-research-lab"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (config_root / "default.yaml").write_text(
        "\n".join(
            [
                "project_name: alpha-research-lab",
                "log_level: INFO",
                "storage:",
                "  base_path: data",
                "venues:",
                "  - name: polymarket",
                "    exchange_class: Polymarket",
                "    rate_limit_rpm: 60",
            ]
        ),
        encoding="utf-8",
    )
    return repo_root


def test_load_default_repo_config_validates() -> None:
    settings = config_loader.load_settings()

    assert settings.project_name == "alpha-research-lab"
    assert settings.storage.base_path.name == "data"
    assert any(venue.name == "polymarket" for venue in settings.venues)


def test_environment_overlay_merges_correctly(temp_config_tree: Path) -> None:
    (temp_config_tree / "environments" / "local.yaml").write_text(
        "\n".join(["log_level: DEBUG", "storage:", "  base_path: data/local"]),
        encoding="utf-8",
    )

    settings = config_loader.load_settings(environment="local", config_dir=temp_config_tree)

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
        config_loader.load_settings(config_dir=config_root)


def test_env_var_override_log_level(
    monkeypatch: pytest.MonkeyPatch,
    temp_config_tree: Path,
) -> None:
    monkeypatch.setenv("ALPHA_LOG_LEVEL", "DEBUG")

    settings = config_loader.load_settings(config_dir=temp_config_tree)

    assert settings.log_level == "DEBUG"


def test_env_var_nested_override(monkeypatch: pytest.MonkeyPatch, temp_config_tree: Path) -> None:
    monkeypatch.setenv("ALPHA_STORAGE__BASE_PATH", "data/override")

    settings = config_loader.load_settings(config_dir=temp_config_tree)

    assert str(settings.storage.base_path).endswith("data/override")


def test_env_var_list_index_override(
    monkeypatch: pytest.MonkeyPatch, temp_config_tree: Path
) -> None:
    monkeypatch.setenv("ALPHA_VENUES__0__RATE_LIMIT_RPM", "180")

    settings = config_loader.load_settings(config_dir=temp_config_tree)

    assert settings.venues[0].rate_limit_rpm == 180


def test_env_var_named_venue_override(
    monkeypatch: pytest.MonkeyPatch,
    temp_config_tree: Path,
) -> None:
    monkeypatch.setenv("ALPHA_VENUES__POLYMARKET__RATE_LIMIT_RPM", "240")

    settings = config_loader.load_settings(config_dir=temp_config_tree)
    polymarket = next(venue for venue in settings.venues if venue.name == "polymarket")

    assert polymarket.rate_limit_rpm == 240


def test_venue_enabled_toggle_file_applies(temp_config_tree: Path) -> None:
    (temp_config_tree / "user_settings.yaml").write_text(
        "venue_enabled:\n  polymarket: false\n",
        encoding="utf-8",
    )

    settings = config_loader.load_settings(config_dir=temp_config_tree, apply_user_settings=True)
    polymarket = next(venue for venue in settings.venues if venue.name == "polymarket")

    assert polymarket.enabled is False


def test_user_settings_are_opt_in(temp_config_tree: Path) -> None:
    (temp_config_tree / "user_settings.yaml").write_text(
        "venue_enabled:\n  polymarket: false\n",
        encoding="utf-8",
    )

    settings = config_loader.load_settings(config_dir=temp_config_tree)
    polymarket = next(venue for venue in settings.venues if venue.name == "polymarket")

    assert polymarket.enabled is True


def test_venue_file_overrides_defaults(temp_config_tree: Path) -> None:
    (temp_config_tree / "venues" / "polymarket.yaml").write_text(
        "name: polymarket\nrate_limit_rpm: 180\n",
        encoding="utf-8",
    )

    settings = config_loader.load_settings(config_dir=temp_config_tree)
    polymarket = next(venue for venue in settings.venues if venue.name == "polymarket")

    assert polymarket.rate_limit_rpm == 180


def test_environment_overlay_overrides_venue_file_with_partial_named_entry(
    temp_config_tree: Path,
) -> None:
    (temp_config_tree / "venues" / "polymarket.yaml").write_text(
        "name: polymarket\nrate_limit_rpm: 180\n",
        encoding="utf-8",
    )
    (temp_config_tree / "environments" / "local.yaml").write_text(
        "\n".join(["venues:", "  - name: polymarket", "    rate_limit_rpm: 240"]),
        encoding="utf-8",
    )

    settings = config_loader.load_settings(environment="local", config_dir=temp_config_tree)
    polymarket = next(venue for venue in settings.venues if venue.name == "polymarket")

    assert polymarket.rate_limit_rpm == 240
    assert polymarket.exchange_class == "Polymarket"


def test_invalid_rate_limit_raises_validation_error(temp_config_tree: Path) -> None:
    (temp_config_tree / "venues" / "polymarket.yaml").write_text(
        "name: polymarket\nrate_limit_rpm: 0\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        config_loader.load_settings(config_dir=temp_config_tree)


def test_invalid_log_level_raises_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    temp_config_tree: Path,
) -> None:
    monkeypatch.setenv("ALPHA_LOG_LEVEL", "TRACE")

    with pytest.raises(ValidationError):
        config_loader.load_settings(config_dir=temp_config_tree)


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
                "  - name: polymarket",
                "    exchange_class: Polymarket",
                "    rate_limit_rpm: 60",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        config_loader.load_settings(config_dir=temp_config_tree)


def test_unknown_environment_file_raises(temp_config_tree: Path) -> None:
    with pytest.raises(FileNotFoundError):
        config_loader.load_settings(environment="does_not_exist", config_dir=temp_config_tree)


def test_invalid_environment_name_rejected(temp_config_tree: Path) -> None:
    with pytest.raises(ValueError, match="Invalid `environment` value"):
        config_loader.load_settings(environment="../secrets", config_dir=temp_config_tree)


def test_default_yaml_non_mapping_raises(tmp_path: Path) -> None:
    config_root = tmp_path / "bad_config"
    (config_root / "environments").mkdir(parents=True)
    (config_root / "venues").mkdir(parents=True)
    (config_root / "default.yaml").write_text("- bad\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected a YAML object"):
        config_loader.load_settings(config_dir=config_root)


def test_environment_yaml_non_mapping_raises(temp_config_tree: Path) -> None:
    (temp_config_tree / "environments" / "local.yaml").write_text("- bad\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected a YAML object"):
        config_loader.load_settings(environment="local", config_dir=temp_config_tree)


def test_user_settings_requires_mapping(temp_config_tree: Path) -> None:
    (temp_config_tree / "user_settings.yaml").write_text("venue_enabled: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain a mapping"):
        config_loader.load_settings(config_dir=temp_config_tree, apply_user_settings=True)


def test_user_settings_requires_boolean_values(temp_config_tree: Path) -> None:
    (temp_config_tree / "user_settings.yaml").write_text(
        'venue_enabled:\n  polymarket: "false"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be boolean"):
        config_loader.load_settings(config_dir=temp_config_tree, apply_user_settings=True)


def test_user_settings_rejects_unknown_venue_names(temp_config_tree: Path) -> None:
    (temp_config_tree / "user_settings.yaml").write_text(
        "venue_enabled:\n  polymarket_unknown: false\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unknown venue name"):
        config_loader.load_settings(config_dir=temp_config_tree, apply_user_settings=True)


def test_set_nested_value_rejects_non_numeric_list_index() -> None:
    target = {"venues": [{"name": "polymarket", "rate_limit_rpm": 60}]}

    with pytest.raises(ValueError, match="numeric indices or existing `name` values"):
        config_loader._set_nested_value(target, ["venues", "first", "rate_limit_rpm"], 120)


def test_set_nested_value_rejects_out_of_range_list_index() -> None:
    target = {"venues": [{"name": "polymarket", "rate_limit_rpm": 60}]}

    with pytest.raises(IndexError, match="out of range"):
        config_loader._set_nested_value(target, ["venues", "1", "rate_limit_rpm"], 120)


def test_set_nested_value_rejects_non_container_path() -> None:
    target = {"log_level": "INFO"}

    with pytest.raises(TypeError, match="non-container"):
        config_loader._set_nested_value(target, ["log_level", "level"], "DEBUG")


def test_path_exists_supports_list_indices() -> None:
    target = {"venues": [{"name": "polymarket", "enabled": True}]}

    assert config_loader._path_exists(target, ["venues", "0", "enabled"])
    assert config_loader._path_exists(target, ["venues", "polymarket", "enabled"])
    assert not config_loader._path_exists(target, ["venues", "x", "enabled"])
    assert not config_loader._path_exists(target, ["venues", "9", "enabled"])


def test_load_settings_discovers_project_root_from_cwd(
    monkeypatch: pytest.MonkeyPatch,
    temp_repo_root: Path,
) -> None:
    monkeypatch.delenv("ALPHA_RESEARCH_ROOT", raising=False)
    monkeypatch.chdir(temp_repo_root / "config" / "venues")

    settings = config_loader.load_settings()

    assert settings.project_name == "alpha-research-lab"
    assert settings.storage.base_path == (temp_repo_root / "data").resolve()


def test_load_settings_respects_alpha_research_root_env_var(
    monkeypatch: pytest.MonkeyPatch,
    temp_repo_root: Path,
) -> None:
    monkeypatch.setenv("ALPHA_RESEARCH_ROOT", str(temp_repo_root))
    monkeypatch.chdir(temp_repo_root.parent)

    settings = config_loader.load_settings()

    assert settings.project_name == "alpha-research-lab"
    assert settings.storage.base_path == (temp_repo_root / "data").resolve()


def test_invalid_alpha_research_root_env_var_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    invalid_root = tmp_path / "missing-root"
    invalid_root.mkdir()
    monkeypatch.setenv("ALPHA_RESEARCH_ROOT", str(invalid_root))

    with pytest.raises(FileNotFoundError, match="ALPHA_RESEARCH_ROOT"):
        config_loader.load_settings()


def test_duplicate_venue_names_in_default_config_raise(temp_config_tree: Path) -> None:
    (temp_config_tree / "default.yaml").write_text(
        "\n".join(
            [
                "project_name: alpha-research-lab",
                "log_level: INFO",
                "storage:",
                "  base_path: data",
                "venues:",
                "  - name: polymarket",
                "    exchange_class: Polymarket",
                "    rate_limit_rpm: 60",
                "  - name: polymarket",
                "    exchange_class: Polymarket",
                "    rate_limit_rpm: 120",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate venue configuration"):
        config_loader.load_settings(config_dir=temp_config_tree)


def test_duplicate_venue_names_across_venue_files_raise(temp_config_tree: Path) -> None:
    (temp_config_tree / "venues" / "polymarket_a.yaml").write_text(
        "name: polymarket\nrate_limit_rpm: 120\n",
        encoding="utf-8",
    )
    (temp_config_tree / "venues" / "polymarket_b.yaml").write_text(
        "name: polymarket\nrate_limit_rpm: 180\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate venue name in venue files"):
        config_loader.load_settings(config_dir=temp_config_tree)


def test_secret_resolution_returns_none_for_unset_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPHA_TEST_SECRET", raising=False)

    assert config_secrets.resolve_secret("ALPHA_TEST_SECRET") is None


def test_secret_resolution_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_TEST_SECRET", "  token-123  ")

    assert config_secrets.resolve_secret("ALPHA_TEST_SECRET") == "token-123"


def test_secret_resolution_falls_back_to_secrets_file(tmp_path: Path) -> None:
    secrets_file = tmp_path / ".secrets"
    secrets_file.write_text("ALPHA_TEST_SECRET=file-token\n", encoding="utf-8")
    secrets_file.chmod(0o600)

    assert (
        config_secrets.resolve_secret("ALPHA_TEST_SECRET", secrets_file=secrets_file)
        == "file-token"
    )


def test_env_secret_takes_precedence_over_secrets_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secrets_file = tmp_path / ".secrets"
    secrets_file.write_text("ALPHA_TEST_SECRET=file-token\n", encoding="utf-8")
    secrets_file.chmod(0o600)
    monkeypatch.setenv("ALPHA_TEST_SECRET", "env-token")

    assert (
        config_secrets.resolve_secret("ALPHA_TEST_SECRET", secrets_file=secrets_file) == "env-token"
    )


def test_secret_resolution_reads_venue_specific_file(
    monkeypatch: pytest.MonkeyPatch,
    temp_repo_root: Path,
) -> None:
    secrets_dir = temp_repo_root / "secrets"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / "polymarket.secrets").write_text(
        "API_KEY_ENV=file-api\nPRIVATE_KEY_ENV=file-private\n",
        encoding="utf-8",
    )
    (secrets_dir / "polymarket.secrets").chmod(0o600)

    monkeypatch.setenv("ALPHA_RESEARCH_ROOT", str(temp_repo_root))
    monkeypatch.delenv("ALPHA_POLYMARKET_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_POLYMARKET_PRIVATE_KEY", raising=False)

    assert config_secrets.resolve_secret("ALPHA_POLYMARKET_API_KEY") == "file-api"
    assert config_secrets.resolve_secret("ALPHA_POLYMARKET_PRIVATE_KEY") == "file-private"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions check only")
def test_secret_resolution_raises_on_insecure_venue_specific_file(
    monkeypatch: pytest.MonkeyPatch,
    temp_repo_root: Path,
) -> None:
    secrets_dir = temp_repo_root / "secrets"
    secrets_dir.mkdir(parents=True)
    venue_file = secrets_dir / "polymarket.secrets"
    venue_file.write_text("API_KEY_ENV=file-api\n", encoding="utf-8")
    venue_file.chmod(0o644)

    monkeypatch.setenv("ALPHA_RESEARCH_ROOT", str(temp_repo_root))
    monkeypatch.delenv("ALPHA_POLYMARKET_API_KEY", raising=False)

    with pytest.raises(PermissionError, match="Insecure permissions"):
        config_secrets.resolve_secret("ALPHA_POLYMARKET_API_KEY")


def test_explicit_secrets_file_disables_venue_specific_fallback(
    monkeypatch: pytest.MonkeyPatch,
    temp_repo_root: Path,
) -> None:
    secrets_dir = temp_repo_root / "secrets"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / "polymarket.secrets").write_text("API_KEY_ENV=file-api\n", encoding="utf-8")
    explicit_file = temp_repo_root / "custom.secrets"
    explicit_file.write_text("ALPHA_OTHER=unused\n", encoding="utf-8")
    explicit_file.chmod(0o600)

    monkeypatch.setenv("ALPHA_RESEARCH_ROOT", str(temp_repo_root))
    monkeypatch.delenv("ALPHA_POLYMARKET_API_KEY", raising=False)

    assert (
        config_secrets.resolve_secret("ALPHA_POLYMARKET_API_KEY", secrets_file=explicit_file)
        is None
    )


def test_secret_resolution_unquotes_file_values(tmp_path: Path) -> None:
    secrets_file = tmp_path / ".secrets"
    secrets_file.write_text(
        "ALPHA_QUOTED_DOUBLE=\"double-token\"\nALPHA_QUOTED_SINGLE='single-token'\n",
        encoding="utf-8",
    )
    secrets_file.chmod(0o600)

    assert (
        config_secrets.resolve_secret("ALPHA_QUOTED_DOUBLE", secrets_file=secrets_file)
        == "double-token"
    )
    assert (
        config_secrets.resolve_secret("ALPHA_QUOTED_SINGLE", secrets_file=secrets_file)
        == "single-token"
    )


def test_secret_resolution_discovers_project_root_from_cwd(
    monkeypatch: pytest.MonkeyPatch,
    temp_repo_root: Path,
) -> None:
    secrets_dir = temp_repo_root / "secrets"
    secrets_dir.mkdir(parents=True)
    venue_file = secrets_dir / "polymarket.secrets"
    venue_file.write_text("API_KEY_ENV=file-api\n", encoding="utf-8")
    venue_file.chmod(0o600)

    monkeypatch.delenv("ALPHA_RESEARCH_ROOT", raising=False)
    monkeypatch.delenv("ALPHA_POLYMARKET_API_KEY", raising=False)
    monkeypatch.chdir(temp_repo_root / "config")

    assert config_secrets.resolve_secret("ALPHA_POLYMARKET_API_KEY") == "file-api"


def test_secret_env_var_does_not_break_config_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_POLYMARKET_API_KEY", "dummy-token")

    settings = config_loader.load_settings()

    assert settings.project_name == "alpha-research-lab"


def test_unknown_alpha_env_var_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
    temp_config_tree: Path,
) -> None:
    monkeypatch.setenv("ALPHA_NOT_A_REAL_SETTING", "dummy-token")

    settings = config_loader.load_settings(config_dir=temp_config_tree)

    assert settings.project_name == "alpha-research-lab"


def test_missing_required_secrets_only_checks_enabled_venues(
    monkeypatch: pytest.MonkeyPatch,
    temp_config_tree: Path,
) -> None:
    (temp_config_tree / "default.yaml").write_text(
        "\n".join(
            [
                "project_name: alpha-research-lab",
                "log_level: INFO",
                "storage:",
                "  base_path: data",
                "venues:",
                "  - name: polymarket",
                "    exchange_class: Polymarket",
                "    enabled: true",
                "    api_key_env: ALPHA_POLYMARKET_API_KEY",
                "    private_key_env: ALPHA_POLYMARKET_PRIVATE_KEY",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("ALPHA_POLYMARKET_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_POLYMARKET_PRIVATE_KEY", raising=False)

    settings = config_loader.load_settings(config_dir=temp_config_tree)
    missing = config_secrets.missing_required_secrets(
        settings,
        secrets_file=temp_config_tree / "missing.secrets",
    )

    assert missing == ["ALPHA_POLYMARKET_API_KEY", "ALPHA_POLYMARKET_PRIVATE_KEY"]


def test_missing_required_secrets_ignores_disabled_venues(temp_config_tree: Path) -> None:
    (temp_config_tree / "default.yaml").write_text(
        "\n".join(
            [
                "project_name: alpha-research-lab",
                "log_level: INFO",
                "storage:",
                "  base_path: data",
                "venues:",
                "  - name: polymarket",
                "    exchange_class: Polymarket",
                "    enabled: false",
                "    api_key_env: ALPHA_POLYMARKET_API_KEY",
                "    private_key_env: ALPHA_POLYMARKET_PRIVATE_KEY",
            ]
        ),
        encoding="utf-8",
    )

    settings = config_loader.load_settings(config_dir=temp_config_tree)
    assert config_secrets.missing_required_secrets(settings) == []


def test_raise_for_missing_required_secrets_raises(
    monkeypatch: pytest.MonkeyPatch,
    temp_config_tree: Path,
) -> None:
    (temp_config_tree / "default.yaml").write_text(
        "\n".join(
            [
                "project_name: alpha-research-lab",
                "log_level: INFO",
                "storage:",
                "  base_path: data",
                "venues:",
                "  - name: polymarket",
                "    exchange_class: Polymarket",
                "    enabled: true",
                "    api_key_env: ALPHA_POLYMARKET_API_KEY",
                "    private_key_env: ALPHA_POLYMARKET_PRIVATE_KEY",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("ALPHA_POLYMARKET_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_POLYMARKET_PRIVATE_KEY", raising=False)

    settings = config_loader.load_settings(config_dir=temp_config_tree)
    with pytest.raises(ValueError, match="Missing required secrets"):
        config_secrets.raise_for_missing_required_secrets(
            settings,
            secrets_file=temp_config_tree / "missing.secrets",
        )


def test_load_settings_validate_secrets_true_raises(
    monkeypatch: pytest.MonkeyPatch,
    temp_config_tree: Path,
) -> None:
    repo_root = temp_config_tree.parent
    (repo_root / "pyproject.toml").write_text(
        '[project]\nname = "alpha-research-lab"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHA_RESEARCH_ROOT", str(repo_root))

    (temp_config_tree / "default.yaml").write_text(
        "\n".join(
            [
                "project_name: alpha-research-lab",
                "log_level: INFO",
                "storage:",
                "  base_path: data",
                "venues:",
                "  - name: polymarket",
                "    exchange_class: Polymarket",
                "    enabled: true",
                "    api_key_env: ALPHA_POLYMARKET_TEST_API_KEY",
                "    private_key_env: ALPHA_POLYMARKET_TEST_PRIVATE_KEY",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("ALPHA_POLYMARKET_TEST_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_POLYMARKET_TEST_PRIVATE_KEY", raising=False)

    with pytest.raises(ValueError, match="Missing required secrets"):
        config_loader.load_settings(config_dir=temp_config_tree, validate_secrets=True)
