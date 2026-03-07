"""Configuration loading utilities with layered YAML and env-var overrides."""

from __future__ import annotations

from pathlib import Path

import alpha_core.config._merge as config_merge
import alpha_core.config._overrides as config_overrides
import alpha_core.config.models as config_models
import alpha_core.config.paths as config_paths
import alpha_core.config.profiles as config_profiles
import alpha_core.config.secrets as config_secrets

_ENV_PREFIX = "ALPHA_"


def load_settings(
    environment: str | None = None,
    config_dir: Path | None = None,
    validate_secrets: bool = False,
    apply_user_settings: bool = False,
    profile: str | config_profiles.ProfileName | None = None,
) -> config_models.Settings:
    """Load settings from default config, optional environment/profile, and env vars.

    Layer order (last write wins):
    1. ``config/default.yaml``
    2. Venue YAML files from ``config/venues/``
    3. Environment overlay (``--environment``), if provided
    4. Profile overlay (``config/environments/{profile}.yaml``), if provided
    5. User-settings overrides (``--apply-user-settings``), if requested
    6. Environment-variable overrides (``ALPHA_*`` prefix)
    7. Profile safety flags (``log_level``, ``feature_flags.dry_run``) are
       enforced as the final authoritative write when a profile is active.

    Parameters
    ----------
    profile:
        Optional runtime profile name (``dev``, ``research``, ``ci``,
        ``paper``, ``live``).  When given, the corresponding environment
        YAML is merged and the profile's safety flags are applied last, so
        they cannot be overridden by lower-priority layers.
    """
    if config_dir is None:
        config_root = config_paths.find_project_root(__file__) / "config"
    else:
        config_root = config_dir.resolve()

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

    # Resolve and validate the profile before applying it so we fail fast on
    # unknown names before any expensive merging takes place.
    active_profile: config_profiles.EnvironmentProfile | None = None
    if profile is not None:
        active_profile = config_profiles.get_profile(profile)
        profile_env_path = environments_dir / f"{active_profile.name.value}.yaml"
        if profile_env_path.exists():
            settings_dict = config_merge.deep_merge(
                settings_dict,
                config_merge.load_yaml(profile_env_path),
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

    # Profile safety flags are always applied last — they are authoritative and
    # cannot be silently overridden by YAML layers or environment variables.
    if active_profile is not None:
        settings_dict["profile"] = active_profile.name.value
        settings_dict["log_level"] = active_profile.log_level
        settings_dict.setdefault("storage", {})["base_path"] = str(active_profile.storage_root)
        settings_dict["storage"]["retention_days"] = active_profile.data_retention_days
        settings_dict.setdefault("feature_flags", {})["dry_run"] = active_profile.dry_run

    settings = config_models.Settings.model_validate(settings_dict)
    if not settings.storage.base_path.is_absolute():
        settings.storage.base_path = (config_root.parent / settings.storage.base_path).resolve()
    if validate_secrets:
        config_secrets.raise_for_missing_required_secrets(settings)

    return settings


__all__ = ["load_settings"]
