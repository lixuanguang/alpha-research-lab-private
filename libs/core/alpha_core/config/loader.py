"""Configuration loading utilities with layered YAML and env-var overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

import alpha_core.config.models as config_models
import alpha_core.config.paths as config_paths
import alpha_core.config.secrets as config_secrets

_ENV_PREFIX = "ALPHA_"


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
        elif isinstance(base_value, list) and isinstance(value, list):
            merged[key] = _merge_list_values(base_value, value)
        else:
            merged[key] = value
    return merged


def _named_mapping_list(
    entries: list[Any],
    *,
    context: str,
) -> tuple[dict[str, dict[str, Any]], list[str]] | None:
    by_name: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for entry in entries:
        if not isinstance(entry, dict):
            return None
        name = entry.get("name")
        if not isinstance(name, str):
            return None
        if name in by_name:
            raise ValueError(f"Duplicate named entry `{name}` in {context}")
        by_name[name] = entry
        order.append(name)

    return by_name, order


def _merge_list_values(base: list[Any], incoming: list[Any]) -> list[Any]:
    """Merge list overlays by `name` when both sides are named mapping lists."""
    base_named = _named_mapping_list(base, context="base list")
    incoming_named = _named_mapping_list(incoming, context="incoming list")
    if base_named is None or incoming_named is None:
        return incoming

    base_by_name, merged_order = base_named
    incoming_by_name, incoming_order = incoming_named
    merged_by_name = dict(base_by_name)

    for name in incoming_order:
        incoming_item = incoming_by_name[name]
        if name in merged_by_name:
            merged_by_name[name] = _deep_merge(merged_by_name[name], incoming_item)
            continue

        merged_by_name[name] = incoming_item
        merged_order.append(name)

    return [merged_by_name[name] for name in merged_order]


def _resolve_list_index(container: list[Any], key: str) -> int:
    if key.isdigit():
        index = int(key)
        if index < 0 or index >= len(container):
            raise IndexError(f"List override index out of range: {index}")
        return index

    for index, item in enumerate(container):
        if isinstance(item, dict) and item.get("name") == key:
            return index

    raise ValueError(
        f"List overrides must use numeric indices or existing `name` values, got `{key}`"
    )


def _set_nested_value(target: dict[str, Any], keys: list[str], value: Any) -> None:
    cursor: Any = target
    for key in keys[:-1]:
        if isinstance(cursor, dict):
            if key not in cursor:
                cursor[key] = {}
            cursor = cursor[key]
            continue

        if isinstance(cursor, list):
            cursor = cursor[_resolve_list_index(cursor, key)]
            continue

        raise TypeError(
            f"Cannot set nested override under non-container type: {type(cursor).__name__}"
        )

    last_key = keys[-1]
    if isinstance(cursor, dict):
        cursor[last_key] = value
        return

    if isinstance(cursor, list):
        cursor[_resolve_list_index(cursor, last_key)] = value
        return

    raise TypeError(f"Cannot set nested override under non-container type: {type(cursor).__name__}")


def _path_exists(config: dict[str, Any], keys: list[str]) -> bool:
    cursor: Any = config
    for key in keys:
        if isinstance(cursor, dict):
            if key not in cursor:
                return False
            cursor = cursor[key]
            continue

        if isinstance(cursor, list):
            if key.isdigit():
                index = int(key)
                if index < 0 or index >= len(cursor):
                    return False
                cursor = cursor[index]
                continue

            named_item = next(
                (
                    item
                    for item in cursor
                    if isinstance(item, dict) and item.get("name") == key
                ),
                None,
            )
            if named_item is None:
                return False
            cursor = named_item
            continue

        return False

    return True


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
        is_feature_flag_override = (
            len(parts) >= 2
            and parts[0] == "feature_flags"
            and isinstance(result.get("feature_flags"), dict)
        )
        if not _path_exists(result, parts) and not is_feature_flag_override:
            continue

        parsed_value = yaml.safe_load(value)
        _set_nested_value(result, parts, value if parsed_value is None else parsed_value)

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
            venue_name = entry["name"]
            if venue_name in by_name:
                raise ValueError(f"Duplicate venue configuration for `{venue_name}`")
            by_name[venue_name] = entry
        else:
            unnamed.append(entry)

    venue_file_source: dict[str, Path] = {}
    for venue_file in sorted(venues_dir.glob("*.yaml")):
        venue_cfg = _load_yaml(venue_file)
        venue_name = venue_cfg.get("name")
        if not isinstance(venue_name, str):
            raise ValueError(f"Venue config {venue_file} must define string `name`")
        if venue_name in venue_file_source:
            source = venue_file_source[venue_name]
            raise ValueError(
                "Duplicate venue name in venue files for "
                f"`{venue_name}`: {source} and {venue_file}"
            )
        venue_file_source[venue_name] = venue_file

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

    known_venues = {
        venue["name"]
        for venue in venues
        if isinstance(venue, dict) and isinstance(venue.get("name"), str)
    }
    normalized_enabled_map: dict[str, bool] = {}
    for raw_name, raw_value in enabled_map.items():
        if not isinstance(raw_name, str):
            raise ValueError(
                "`config/user_settings.yaml` keys under `venue_enabled` must be strings"
            )
        if not isinstance(raw_value, bool):
            raise ValueError(
                f"Enabled toggle for venue `{raw_name}` must be boolean, got "
                f"{type(raw_value).__name__}"
            )
        normalized_enabled_map[raw_name] = raw_value

    unknown_venues = sorted(name for name in normalized_enabled_map if name not in known_venues)
    if unknown_venues:
        unknown = ", ".join(unknown_venues)
        raise ValueError(
            f"Unknown venue name(s) in `config/user_settings.yaml` under `venue_enabled`: {unknown}"
        )

    updated: list[Any] = []
    for venue in venues:
        if not isinstance(venue, dict):
            updated.append(venue)
            continue

        venue_name = venue.get("name")
        if not isinstance(venue_name, str):
            updated.append(venue)
            continue

        if venue_name in normalized_enabled_map:
            updated.append({**venue, "enabled": normalized_enabled_map[venue_name]})
            continue

        updated.append(venue)

    merged["venues"] = updated
    return merged


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

    settings_dict = _load_yaml(default_path)
    settings_dict = _merge_venue_files(settings_dict, venues_dir)

    if environment:
        environment_path = environments_dir / f"{environment}.yaml"
        if not environment_path.exists():
            raise FileNotFoundError(f"Environment config does not exist: {environment_path}")
        settings_dict = _deep_merge(settings_dict, _load_yaml(environment_path))

    if apply_user_settings:
        settings_dict = _apply_venue_enabled_overrides(settings_dict, user_settings_path)

    secret_env_names = _collect_secret_env_names(settings_dict)
    settings_dict = _apply_env_overrides(settings_dict, secret_env_names=secret_env_names)

    settings = config_models.Settings.model_validate(settings_dict)
    if not settings.storage.base_path.is_absolute():
        settings.storage.base_path = (project_root / settings.storage.base_path).resolve()
    if validate_secrets:
        config_secrets.raise_for_missing_required_secrets(settings)

    return settings
