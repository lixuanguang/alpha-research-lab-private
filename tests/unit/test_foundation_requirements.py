"""Foundation-stage artifact and entrypoint validation tests."""

from __future__ import annotations

import json
from pathlib import Path

import apps.data_collector.main as data_collector_main
import apps.live_system.main as live_system_main
import apps.research.main as research_main
import click.testing as click_testing

_EXPECTED_EVENT_VARIANTS = {
    "trade",
    "book_snapshot",
    "ohlcv",
    "metadata_update",
}
_EXPECTED_BASE_FIELDS = {
    "event_id",
    "instrument_id",
    "venue_id",
    "event_type",
    "ts_event",
    "ts_record",
    "schema_version",
}
_REQUIRED_FOUNDATION_FILES = [
    ".pre-commit-config.yaml",
    ".github/workflows/ci.yml",
    "config/default.yaml",
    "config/environments/local.yaml",
    "config/environments/ci.yaml",
    "infra/docker/docker-compose.yml",
    "scripts/bootstrap.sh",
    "scripts/validate_env.py",
    "docs/adr/001-monorepo-structure.md",
    "docs/adr/002-canonical-event-model.md",
    "docs/adr/003-bitemporal-timestamps.md",
]
_REQUIRED_VENUE_CONFIGS = {
    "kalshi.yaml",
    "kalshidemo.yaml",
    "polymarket.yaml",
    "limitless.yaml",
    "baozi.yaml",
    "myriad.yaml",
    "probable.yaml",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _schema_path() -> Path:
    return _repo_root() / "data" / "schemas" / "canonical_event_v1.json"


def test_foundation_artifact_files_exist() -> None:
    repo_root = _repo_root()

    for relative_path in _REQUIRED_FOUNDATION_FILES:
        artifact_path = repo_root / relative_path
        assert artifact_path.exists(), f"Missing required foundation artifact: {relative_path}"

    venue_configs_dir = repo_root / "config" / "venues"
    actual_venue_configs = {path.name for path in venue_configs_dir.glob("*.yaml")}
    assert _REQUIRED_VENUE_CONFIGS.issubset(actual_venue_configs)


def test_canonical_event_json_schema_exists_and_is_valid_json() -> None:
    schema_path = _schema_path()
    assert schema_path.exists(), f"Missing schema artifact: {schema_path}"

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "CanonicalMarketEvent v1"


def test_canonical_event_schema_declares_expected_variants_and_base_fields() -> None:
    schema = json.loads(_schema_path().read_text(encoding="utf-8"))

    refs = schema.get("oneOf", [])
    declared_variants = {
        ref["$ref"].split("/")[-1]
        for ref in refs
        if isinstance(ref, dict) and isinstance(ref.get("$ref"), str)
    }
    assert declared_variants == _EXPECTED_EVENT_VARIANTS

    base_required_fields = set(schema["$defs"]["base"]["required"])
    assert _EXPECTED_BASE_FIELDS.issubset(base_required_fields)
    event_type_enum = set(schema["$defs"]["base"]["properties"]["event_type"]["enum"])
    assert event_type_enum == _EXPECTED_EVENT_VARIANTS


def test_all_foundation_app_entrypoints_support_help() -> None:
    runner = click_testing.CliRunner()
    entrypoints = [
        data_collector_main.main,
        live_system_main.main,
        research_main.main,
    ]

    for command in entrypoints:
        result = runner.invoke(command, ["--help"])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output
