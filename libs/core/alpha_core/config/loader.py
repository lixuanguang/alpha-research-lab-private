"""Configuration loading utilities with layered YAML and env-var overrides."""

from __future__ import annotations

from pathlib import Path

import alpha_core.config._merge as config_merge
import alpha_core.config._overrides as config_overrides
import alpha_core.config.models as config_models
import alpha_core.config.paths as config_paths
import alpha_core.config.secrets as config_secrets

_ENV_PREFIX = "ALPHA_"


def load_settings(
    environment: str | None = None,
    config_dir: Path | None = None,
    validate_secrets: bool = False,
    apply_user_settings: bool = False,
) -> config_models.Settings:
    """Load settings from default config, optional environment, and env vars."""
    if config_dir is None:
        project_root = config_paths.find_project_root(__file__)
        config_root = project_root / "config"
    else:
        config_root = config_dir.resolve()
        project_root = config_root.parent

    default_path = config_root / "default.yaml"
    environments_dir = config_root / "environments"
    venues_dir = config_root / "venues"
    user_settings_path = config_root / "user_settings.yaml"

    settings_dict = config_merge.load_yaml(default_path)
    settings_dict = config_overrides.merge_venue_files(settings_dict, venues_dir)

    if environment:
        environment_path = config_overrides.resolve_environment_path(environments_dir, environment)
        if not environment_path.exists():
            raise FileNotFoundError(f"Environment config does not exist: {environment_path}")
        settings_dict = config_merge.deep_merge(
            settings_dict,
            config_merge.load_yaml(environment_path),
        )

    if apply_user_settings:
        settings_dict = config_overrides.apply_venue_enabled_overrides(
            settings_dict,
            user_settings_path,
        )

    secret_env_names = config_overrides.collect_secret_env_names(settings_dict)
    settings_dict = config_overrides.apply_env_overrides(
        settings_dict,
        prefix=_ENV_PREFIX,
        secret_env_names=secret_env_names,
    )

    settings = config_models.Settings.model_validate(settings_dict)
    if not settings.storage.base_path.is_absolute():
        settings.storage.base_path = (project_root / settings.storage.base_path).resolve()
    if validate_secrets:
        config_secrets.raise_for_missing_required_secrets(settings)

    return settings


__all__ = ["load_settings"]
