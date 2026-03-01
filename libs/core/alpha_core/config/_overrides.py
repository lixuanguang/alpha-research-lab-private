"""Override and overlay helpers for application settings."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

import alpha_core.config._merge as config_merge

_ENVIRONMENT_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def collect_secret_env_names(config: dict[str, Any]) -> set[str]:
    """Collect env var names that should not be considered generic config overrides."""
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


def apply_env_overrides(
    config: dict[str, Any],
    *,
    prefix: str,
    secret_env_names: set[str] | None = None,
) -> dict[str, Any]:
    """Apply env var overrides onto a config payload."""
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
        if not config_merge.path_exists(result, parts) and not is_feature_flag_override:
            continue

        parsed_value = yaml.safe_load(value)
        override_value = value if parsed_value is None else parsed_value
        config_merge.set_nested_value(result, parts, override_value)

    return result


def merge_venue_files(config: dict[str, Any], venues_dir: Path) -> dict[str, Any]:
    """Merge per-venue YAML files into the base config payload."""
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
        venue_cfg = config_merge.load_yaml(venue_file)
        venue_name = venue_cfg.get("name")
        if not isinstance(venue_name, str):
            raise ValueError(f"Venue config {venue_file} must define string `name`")
        if venue_name in venue_file_source:
            source = venue_file_source[venue_name]
            raise ValueError(
                f"Duplicate venue name in venue files for `{venue_name}`: {source} and {venue_file}"
            )
        venue_file_source[venue_name] = venue_file

        existing = by_name.get(venue_name, {"name": venue_name})
        by_name[venue_name] = config_merge.deep_merge(existing, venue_cfg)

    merged_venues = [by_name[name] for name in sorted(by_name)]
    merged_venues.extend(unnamed)

    merged = dict(config)
    merged["venues"] = merged_venues
    return merged


def apply_venue_enabled_overrides(
    config: dict[str, Any],
    user_settings_path: Path,
) -> dict[str, Any]:
    """Apply opt-in user-level venue enabled/disabled overrides."""
    enabled_map = _load_enabled_map(user_settings_path)
    if not enabled_map:
        return config

    merged = dict(config)
    venues = merged.get("venues", [])
    if not isinstance(venues, list):
        raise ValueError("`venues` must be a list in configuration")

    unknown_venues = sorted(name for name in enabled_map if name not in _known_venue_names(venues))
    if unknown_venues:
        unknown = ", ".join(unknown_venues)
        raise ValueError(
            f"Unknown venue name(s) in `config/user_settings.yaml` under `venue_enabled`: {unknown}"
        )

    merged["venues"] = _apply_enabled_map(venues, enabled_map)
    return merged


def _load_enabled_map(user_settings_path: Path) -> dict[str, bool]:
    toggles_cfg = config_merge.load_yaml(user_settings_path)
    if not toggles_cfg:
        return {}

    enabled_map = toggles_cfg.get("venue_enabled")
    if not isinstance(enabled_map, dict):
        raise ValueError("`config/user_settings.yaml` must contain a mapping under `venue_enabled`")

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
    return normalized_enabled_map


def _known_venue_names(venues: list[Any]) -> set[str]:
    return {
        venue["name"]
        for venue in venues
        if isinstance(venue, dict) and isinstance(venue.get("name"), str)
    }


def _apply_enabled_map(venues: list[Any], enabled_map: dict[str, bool]) -> list[Any]:
    updated: list[Any] = []
    for venue in venues:
        if not isinstance(venue, dict):
            updated.append(venue)
            continue

        venue_name = venue.get("name")
        if not isinstance(venue_name, str) or venue_name not in enabled_map:
            updated.append(venue)
            continue

        updated.append({**venue, "enabled": enabled_map[venue_name]})
    return updated


def resolve_environment_path(environments_dir: Path, environment: str) -> Path:
    """Resolve and validate environment overlay path under `config/environments`."""
    cleaned_environment = environment.strip()
    if not cleaned_environment:
        raise ValueError("`environment` must be a non-empty string when provided")
    if _ENVIRONMENT_NAME_RE.fullmatch(cleaned_environment) is None:
        raise ValueError("Invalid `environment` value. Use only letters, numbers, `_`, and `-`.")

    environments_root = environments_dir.resolve()
    environment_path = (environments_root / f"{cleaned_environment}.yaml").resolve()
    if environment_path.parent != environments_root:
        raise ValueError("Invalid `environment` value.")
    return environment_path


__all__ = [
    "apply_env_overrides",
    "apply_venue_enabled_overrides",
    "collect_secret_env_names",
    "merge_venue_files",
    "resolve_environment_path",
]
