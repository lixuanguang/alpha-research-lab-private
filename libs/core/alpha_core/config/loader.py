"""Configuration loading utilities with layered YAML and env-var overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from alpha_core.config.models import Settings
from alpha_core.config.secrets import raise_for_missing_required_secrets

_ENV_PREFIX = "ALPHA_"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected a YAML object at {path}, got {type(loaded).__name__}")
    return loaded


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in incoming.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(base_value, value)
        else:
            merged[key] = value
    return merged


def _set_nested_value(target: dict[str, Any], keys: list[str], value: Any) -> None:
    cursor: Any = target
    for key in keys[:-1]:
        if isinstance(cursor, dict):
            if key not in cursor:
                cursor[key] = {}
            cursor = cursor[key]
            continue

        if isinstance(cursor, list):
            if not key.isdigit():
                raise ValueError(f"List overrides must use numeric indices, got `{key}`")
            index = int(key)
            if index < 0 or index >= len(cursor):
                raise IndexError(f"List override index out of range: {index}")
            cursor = cursor[index]
            continue

        raise TypeError(
            f"Cannot set nested override under non-container type: {type(cursor).__name__}"
        )

    last_key = keys[-1]
    if isinstance(cursor, dict):
        cursor[last_key] = value
        return

    if isinstance(cursor, list):
        if not last_key.isdigit():
            raise ValueError(f"List overrides must use numeric indices, got `{last_key}`")
        index = int(last_key)
        if index < 0 or index >= len(cursor):
            raise IndexError(f"List override index out of range: {index}")
        cursor[index] = value
        return

    raise TypeError(f"Cannot set nested override under non-container type: {type(cursor).__name__}")


def _parse_env_value(raw: str) -> Any:
    parsed = yaml.safe_load(raw)
    return raw if parsed is None else parsed


def _path_exists(config: dict[str, Any], keys: list[str]) -> bool:
    cursor: Any = config
    for key in keys:
        if isinstance(cursor, dict):
            if key not in cursor:
                return False
            cursor = cursor[key]
            continue

        if isinstance(cursor, list):
            if not key.isdigit():
                return False
            index = int(key)
            if index < 0 or index >= len(cursor):
                return False
            cursor = cursor[index]
            continue

        return False

    return True


def _is_feature_flag_override(config: dict[str, Any], keys: list[str]) -> bool:
    if len(keys) < 2 or keys[0] != "feature_flags":
        return False
    return isinstance(config.get("feature_flags"), dict)


def _collect_secret_env_names(config: dict[str, Any]) -> set[str]:
    venues = config.get("venues")
    if not isinstance(venues, list):
        return set()

    secret_names: set[str] = set()
    for venue in venues:
        if not isinstance(venue, dict):
            continue
        for key in ("api_key_env", "private_key_env"):
            value = venue.get(key)
            if isinstance(value, str) and value:
                secret_names.add(value)

    return secret_names


def _apply_env_overrides(
    config: dict[str, Any],
    prefix: str = _ENV_PREFIX,
    secret_env_names: set[str] | None = None,
) -> dict[str, Any]:
    result = dict(config)
    blocked_names = secret_env_names or set()

    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        if key in blocked_names:
            continue

        config_path = key[len(prefix) :].lower()
        if not config_path:
            continue

        parts = [part for part in config_path.split("__") if part]
        if not parts:
            continue
        if not _path_exists(result, parts) and not _is_feature_flag_override(result, parts):
            continue

        _set_nested_value(result, parts, _parse_env_value(value))

    return result


def _merge_venue_files(config: dict[str, Any], venues_dir: Path) -> dict[str, Any]:
    if not venues_dir.exists():
        return config

    current_venues = config.get("venues", [])
    if not isinstance(current_venues, list):
        raise ValueError("`venues` must be a list in configuration")

    by_name: dict[str, dict[str, Any]] = {}
    unnamed: list[Any] = []

    for entry in current_venues:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            by_name[entry["name"]] = entry
        else:
            unnamed.append(entry)

    for venue_file in sorted(venues_dir.glob("*.yaml")):
        venue_cfg = _load_yaml(venue_file)
        venue_name = venue_cfg.get("name")
        if not isinstance(venue_name, str):
            raise ValueError(f"Venue config {venue_file} must define string `name`")

        existing = by_name.get(venue_name, {"name": venue_name})
        by_name[venue_name] = _deep_merge(existing, venue_cfg)

    merged_venues = [by_name[name] for name in sorted(by_name)]
    merged_venues.extend(unnamed)

    merged = dict(config)
    merged["venues"] = merged_venues
    return merged


def _apply_venue_enabled_overrides(
    config: dict[str, Any],
    user_settings_path: Path,
) -> dict[str, Any]:
    toggles_cfg = _load_yaml(user_settings_path)
    if not toggles_cfg:
        return config

    enabled_map = toggles_cfg.get("venue_enabled")
    if not isinstance(enabled_map, dict):
        raise ValueError("`config/user_settings.yaml` must contain a mapping under `venue_enabled`")

    merged = dict(config)
    venues = merged.get("venues", [])
    if not isinstance(venues, list):
        raise ValueError("`venues` must be a list in configuration")

    updated: list[Any] = []
    for venue in venues:
        if not isinstance(venue, dict):
            updated.append(venue)
            continue

        venue_name = venue.get("name")
        if not isinstance(venue_name, str):
            updated.append(venue)
            continue

        if venue_name in enabled_map:
            enabled_value = enabled_map[venue_name]
            if not isinstance(enabled_value, bool):
                raise ValueError(
                    f"Enabled toggle for venue `{venue_name}` must be boolean, got "
                    f"{type(enabled_value).__name__}"
                )
            updated.append({**venue, "enabled": enabled_value})
            continue

        updated.append(venue)

    merged["venues"] = updated
    return merged


def load_settings(
    environment: str | None = None,
    config_dir: Path | None = None,
    validate_secrets: bool = False,
    apply_user_settings: bool = False,
) -> Settings:
    """Load settings from default config, optional environment, and env vars."""
    root = _project_root() if config_dir is None else config_dir

    default_path = root / "default.yaml"
    environments_dir = root / "environments"
    venues_dir = root / "venues"

    if config_dir is None:
        default_path = root / "config" / "default.yaml"
        environments_dir = root / "config" / "environments"
        venues_dir = root / "config" / "venues"
        user_settings_path = root / "config" / "user_settings.yaml"
    else:
        user_settings_path = root / "user_settings.yaml"

    settings_dict = _load_yaml(default_path)

    if environment:
        environment_path = environments_dir / f"{environment}.yaml"
        if not environment_path.exists():
            raise FileNotFoundError(f"Environment config does not exist: {environment_path}")
        settings_dict = _deep_merge(settings_dict, _load_yaml(environment_path))

    settings_dict = _merge_venue_files(settings_dict, venues_dir)
    if apply_user_settings:
        settings_dict = _apply_venue_enabled_overrides(settings_dict, user_settings_path)

    secret_env_names = _collect_secret_env_names(settings_dict)
    settings_dict = _apply_env_overrides(settings_dict, secret_env_names=secret_env_names)

    settings = Settings.model_validate(settings_dict)
    if validate_secrets:
        raise_for_missing_required_secrets(settings)

    return settings
