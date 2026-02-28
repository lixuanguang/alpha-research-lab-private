"""Secrets helpers for resolving credentials from environment variables."""

from __future__ import annotations

import os
import re
from pathlib import Path

from alpha_core.config.models import Settings


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_secrets_file() -> Path:
    return _project_root() / "secrets" / ".secrets"


def _resolve_from_venue_secrets_file(env_var_name: str) -> str | None:
    """Resolve ALPHA_<VENUE>_(API_KEY|PRIVATE_KEY) from secrets/<venue>.secrets."""
    match = re.fullmatch(r"ALPHA_([A-Z0-9_]+)_(API_KEY|PRIVATE_KEY)", env_var_name)
    if match is None:
        return None

    venue_name = match.group(1).lower()
    key_kind = match.group(2)
    venue_secrets_path = _project_root() / "secrets" / f"{venue_name}.secrets"
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
        secret = value.strip()
        return secret or None

    return None


def _load_secrets_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

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
            secrets[key] = value

    return secrets


def resolve_secret(env_var_name: str | None, secrets_file: Path | None = None) -> str | None:
    """Resolve secret from env first, then optional local secrets file."""
    if not env_var_name:
        return None

    value = os.getenv(env_var_name)
    if value is not None:
        secret = value.strip()
        return secret or None

    secret_path = _default_secrets_file() if secrets_file is None else secrets_file
    file_value = _load_secrets_file(secret_path).get(env_var_name)
    if file_value is None:
        if secrets_file is not None:
            return None
        return _resolve_from_venue_secrets_file(env_var_name)

    secret = file_value.strip()
    return secret or None


def missing_required_secrets(settings: Settings, secrets_file: Path | None = None) -> list[str]:
    """Return missing env-var names required by enabled venues."""
    missing: list[str] = []

    for venue in settings.venues:
        if not venue.enabled:
            continue

        required_names = [venue.api_key_env, venue.private_key_env]
        for env_name in required_names:
            if not env_name:
                continue
            if resolve_secret(env_name, secrets_file=secrets_file) is None:
                missing.append(env_name)

    return sorted(set(missing))


def raise_for_missing_required_secrets(
    settings: Settings,
    secrets_file: Path | None = None,
) -> None:
    """Raise ValueError when an enabled venue is missing required credentials."""
    missing = missing_required_secrets(settings, secrets_file=secrets_file)
    if missing:
        message = ", ".join(missing)
        raise ValueError(f"Missing required secrets for enabled venues: {message}")
