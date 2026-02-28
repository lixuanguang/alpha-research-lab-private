"""Secrets helpers for resolving credentials from environment variables."""

from __future__ import annotations

import os
import re
from pathlib import Path

import alpha_core.config.models as config_models
import alpha_core.config.paths as config_paths


def _resolve_from_venue_secrets_file(env_var_name: str) -> str | None:
    """Resolve ALPHA_<VENUE>_(API_KEY|PRIVATE_KEY) from secrets/<venue>.secrets."""
    match = re.fullmatch(r"ALPHA_([A-Z0-9_]+)_(API_KEY|PRIVATE_KEY)", env_var_name)
    if match is None:
        return None

    venue_name = match.group(1).lower()
    key_kind = match.group(2)
    venue_secrets_path = (
        config_paths.find_project_root(__file__) / "secrets" / f"{venue_name}.secrets"
    )
    if not venue_secrets_path.exists():
        return None

    venue_secrets = _load_secrets_file(venue_secrets_path)
    aliases = (
        ["API_KEY_ENV", "API_KEY"] if key_kind == "API_KEY" else ["PRIVATE_KEY_ENV", "PRIVATE_KEY"]
    )
    for alias in aliases:
        value = venue_secrets.get(alias)
        if value is None:
            continue
        return value.strip() or None

    return None


def _has_secure_permissions(path: Path) -> bool:
    """Require owner-only read/write permissions for secrets files on POSIX."""
    if os.name == "nt":
        return True
    return (path.stat().st_mode & 0o077) == 0


def _load_secrets_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    if not _has_secure_permissions(path):
        raise PermissionError(
            f"Insecure permissions on secrets file `{path}`. "
            "Restrict access to owner only (chmod 600)."
        )

    secrets: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()

        if "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            secrets[key] = _normalize_secret_value(value)

    return secrets


def resolve_secret(env_var_name: str | None, secrets_file: Path | None = None) -> str | None:
    """Resolve secret from env first, then optional local secrets file."""
    if not env_var_name:
        return None

    value = os.getenv(env_var_name)
    if value is not None:
        return _normalize_secret_value(value.strip()) or None

    if secrets_file is None:
        file_value = _load_secrets_file(
            config_paths.find_project_root(__file__) / "secrets" / ".secrets"
        ).get(env_var_name)
        if file_value is None:
            return _resolve_from_venue_secrets_file(env_var_name)
    else:
        file_value = _load_secrets_file(secrets_file).get(env_var_name)
        if file_value is None:
            return None

    return file_value.strip() or None


def _normalize_secret_value(value: str) -> str:
    """Normalize a parsed secret value from file content."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def missing_required_secrets(
    settings: config_models.Settings,
    secrets_file: Path | None = None,
) -> list[str]:
    """Return missing env-var names required by enabled venues."""
    required_names = {
        env_name
        for venue in settings.venues
        for env_name in (venue.api_key_env, venue.private_key_env)
        if venue.enabled and env_name
    }
    return sorted(
        env_name
        for env_name in required_names
        if resolve_secret(env_name, secrets_file=secrets_file) is None
    )


def raise_for_missing_required_secrets(
    settings: config_models.Settings,
    secrets_file: Path | None = None,
) -> None:
    """Raise ValueError when an enabled venue is missing required credentials."""
    missing = missing_required_secrets(settings, secrets_file=secrets_file)
    if missing:
        message = ", ".join(missing)
        raise ValueError(f"Missing required secrets for enabled venues: {message}")
