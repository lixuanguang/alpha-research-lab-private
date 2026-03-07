"""Schema regression tests for run manifest and run context contracts (LA-014 / §12.4).

PURPOSE
-------
These tests act as **contract stability gates**.  They will fail loudly whenever
``RunManifest`` or ``RunContext`` fields change without a corresponding:

1. ``RUN_MANIFEST_SCHEMA_VERSION`` bump in ``manifest.py``
2. Updated regression snapshot in ``tests/data/fixtures/schema_snapshots/``
3. Updated JSON Schema in ``data/schemas/run_manifest_v{N}.json``

HOW TO UPDATE SNAPSHOTS AFTER A LEGITIMATE SCHEMA CHANGE
---------------------------------------------------------
1. Bump ``RUN_MANIFEST_SCHEMA_VERSION`` in
   ``libs/core/alpha_core/research/manifest.py``.
2. Re-generate the fixture::

       python - <<'EOF'
       import json, pathlib
       from datetime import datetime, timezone
       from alpha_core.research.manifest import RunManifest, RUN_MANIFEST_SCHEMA_VERSION
       from alpha_core.research.run_context import RunContext

       ctx = RunContext(
           run_id="regression_fixture_run_001",
           run_type="backtest",
           config_hash="a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3",
           git_commit="abc1234",
           started_at_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
           completed_at_utc=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
       )
       m = RunManifest(
           run=ctx,
           artifacts={
               "features": "data/runs/regression_fixture_run_001/stage_outputs/features.parquet",
               "metrics": "data/runs/regression_fixture_run_001/stage_outputs/metrics.json",
           },
       )
       snapshot_dir = pathlib.Path("tests/data/fixtures/schema_snapshots")
       (snapshot_dir / f"run_manifest_v{RUN_MANIFEST_SCHEMA_VERSION}.json").write_text(
           m.model_dump_json(indent=2), encoding="utf-8"
       )
       print("Snapshot written.")
       EOF

3. Update ``data/schemas/run_manifest_v{N}.json`` to reflect the new field set.
4. Add a migration note in ``docs/`` and an ADR entry for breaking changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent
_SNAPSHOT_DIR = _REPO_ROOT / "tests" / "data" / "fixtures" / "schema_snapshots"
_SCHEMA_DIR = _REPO_ROOT / "data" / "schemas"

_RUN_CONTEXT_SNAPSHOT = _SNAPSHOT_DIR / "run_context_v1.json"
_RUN_MANIFEST_FILE = f"run_manifest_v{manifest_mod.RUN_MANIFEST_SCHEMA_VERSION}.json"
_RUN_MANIFEST_SNAPSHOT = _SNAPSHOT_DIR / _RUN_MANIFEST_FILE
_RUN_MANIFEST_JSON_SCHEMA = _SCHEMA_DIR / _RUN_MANIFEST_FILE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_snapshot(path: Path) -> dict:  # type: ignore[type-arg]
    """Load a JSON snapshot file, failing with a clear update instruction."""
    if not path.exists():
        pytest.fail(
            f"Regression snapshot missing: {path}\n"
            "Regenerate it following the instructions at the top of this file."
        )
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# RunManifest snapshot tests
# ---------------------------------------------------------------------------


class TestRunManifestRegression:
    """Contract-stability gate for :class:`RunManifest`.

    If any of these tests fail after a code change, follow the update steps
    documented at the top of this module.
    """

    def test_snapshot_file_exists(self) -> None:
        """The versioned snapshot file exists on disk."""
        assert _RUN_MANIFEST_SNAPSHOT.exists(), (
            f"Missing snapshot: {_RUN_MANIFEST_SNAPSHOT}\n"
            "Bump RUN_MANIFEST_SCHEMA_VERSION and regenerate the snapshot."
        )

    def test_snapshot_parses_with_current_model(self) -> None:
        """Frozen fixture JSON is accepted by the current RunManifest model."""
        data = _load_snapshot(_RUN_MANIFEST_SNAPSHOT)
        manifest = manifest_mod.RunManifest.model_validate(data)
        assert manifest.schema_version == manifest_mod.RUN_MANIFEST_SCHEMA_VERSION

    def test_snapshot_field_set_matches_model(self) -> None:
        """Top-level keys in the fixture exactly match RunManifest.model_fields.

        Fails when a field is added or removed without updating the snapshot —
        even if the change is backward-compatible via a default value.
        """
        fixture_keys = set(_load_snapshot(_RUN_MANIFEST_SNAPSHOT).keys())
        model_keys = set(manifest_mod.RunManifest.model_fields.keys())
        extra_in_fixture = fixture_keys - model_keys
        extra_in_model = model_keys - fixture_keys

        assert not extra_in_fixture, (
            f"Fixture has fields not in model: {extra_in_fixture}\n"
            "Remove them from the snapshot or add them to RunManifest."
        )
        assert not extra_in_model, (
            f"RunManifest has fields not in fixture: {extra_in_model}\n"
            "Bump RUN_MANIFEST_SCHEMA_VERSION and regenerate the snapshot."
        )

    def test_snapshot_schema_version_matches_constant(self) -> None:
        """Fixture schema_version matches the RUN_MANIFEST_SCHEMA_VERSION constant."""
        data = _load_snapshot(_RUN_MANIFEST_SNAPSHOT)
        assert data["schema_version"] == manifest_mod.RUN_MANIFEST_SCHEMA_VERSION, (
            f"Fixture schema_version={data['schema_version']} but "
            f"RUN_MANIFEST_SCHEMA_VERSION={manifest_mod.RUN_MANIFEST_SCHEMA_VERSION}.\n"
            "Regenerate the snapshot after bumping the constant."
        )

    def test_snapshot_round_trip_is_stable(self) -> None:
        """Parse → serialize → re-parse produces byte-identical JSON."""
        data = _load_snapshot(_RUN_MANIFEST_SNAPSHOT)
        manifest = manifest_mod.RunManifest.model_validate(data)
        re_serialized = json.loads(manifest.model_dump_json())
        re_parsed = manifest_mod.RunManifest.model_validate(re_serialized)
        assert re_parsed == manifest

    def test_snapshot_run_type_is_valid_run_type_literal(self) -> None:
        """The run_type in the fixture is one of the canonical RunType values."""
        data = _load_snapshot(_RUN_MANIFEST_SNAPSHOT)
        run_type_val: str = data["run"]["run_type"]
        valid: tuple[run_context_mod.RunType, ...] = (
            "ingestion",
            "dataset_build",
            "feature_build",
            "backtest",
            "evaluate",
            "report",
            "optimize",
            "live",
        )
        assert run_type_val in valid, (
            f"Fixture run_type '{run_type_val}' is not in the RunType union.\n"
            "Update the snapshot to use a valid run_type."
        )

    def test_snapshot_artifacts_are_non_empty(self) -> None:
        """Fixture artifacts dict is non-empty (documents expected structure)."""
        data = _load_snapshot(_RUN_MANIFEST_SNAPSHOT)
        assert data["artifacts"], "Fixture artifacts must be non-empty for documentation value."


# ---------------------------------------------------------------------------
# RunContext snapshot tests
# ---------------------------------------------------------------------------


class TestRunContextRegression:
    """Field-set regression guard for :class:`RunContext`.

    RunContext does not carry a schema_version field because it is embedded
    inside RunManifest (which owns the version).  Changes to RunContext fields
    must still be reflected in both the snapshot and the parent RunManifest
    schema — which is enforced indirectly via the nested fixture data.
    """

    def test_snapshot_parses_with_current_model(self) -> None:
        """Frozen RunContext fixture is accepted by the current model."""
        data = _load_snapshot(_RUN_CONTEXT_SNAPSHOT)
        ctx = run_context_mod.RunContext.model_validate(data)
        assert ctx.run_id == "regression_fixture_run_001"

    def test_snapshot_field_set_matches_model(self) -> None:
        """RunContext fixture keys exactly match RunContext.model_fields."""
        fixture_keys = set(_load_snapshot(_RUN_CONTEXT_SNAPSHOT).keys())
        model_keys = set(run_context_mod.RunContext.model_fields.keys())
        extra_in_fixture = fixture_keys - model_keys
        extra_in_model = model_keys - fixture_keys

        assert not extra_in_fixture, f"RunContext fixture has unexpected keys: {extra_in_fixture}"
        assert not extra_in_model, (
            f"RunContext model has fields absent from fixture: {extra_in_model}\n"
            "Update run_context_v1.json and bump RUN_MANIFEST_SCHEMA_VERSION."
        )

    def test_snapshot_round_trip_is_stable(self) -> None:
        """RunContext parse → serialize → re-parse is lossless."""
        data = _load_snapshot(_RUN_CONTEXT_SNAPSHOT)
        ctx = run_context_mod.RunContext.model_validate(data)
        re_parsed = run_context_mod.RunContext.model_validate(json.loads(ctx.model_dump_json()))
        assert re_parsed == ctx


# ---------------------------------------------------------------------------
# JSON Schema file integrity
# ---------------------------------------------------------------------------


class TestRunManifestJsonSchema:
    """Verify that the JSON Schema file is consistent with the versioning artifacts."""

    def test_json_schema_file_exists(self) -> None:
        """Versioned JSON Schema document exists in data/schemas/."""
        assert _RUN_MANIFEST_JSON_SCHEMA.exists(), (
            f"Missing JSON Schema: {_RUN_MANIFEST_JSON_SCHEMA}\n"
            "Create it alongside the snapshot when bumping the schema version."
        )

    def test_json_schema_is_valid_json(self) -> None:
        """JSON Schema file is parseable JSON."""
        raw = _RUN_MANIFEST_JSON_SCHEMA.read_text(encoding="utf-8")
        schema = json.loads(raw)
        assert isinstance(schema, dict)

    def test_json_schema_const_matches_constant(self) -> None:
        """The 'const' on schema_version in the JSON Schema matches the Python constant."""
        schema = json.loads(_RUN_MANIFEST_JSON_SCHEMA.read_text(encoding="utf-8"))
        schema_version_const = schema["properties"]["schema_version"]["const"]
        assert schema_version_const == manifest_mod.RUN_MANIFEST_SCHEMA_VERSION, (
            f"JSON Schema schema_version const={schema_version_const} but "
            f"RUN_MANIFEST_SCHEMA_VERSION={manifest_mod.RUN_MANIFEST_SCHEMA_VERSION}.\n"
            "Update run_manifest_v{N}.json when bumping the constant."
        )

    def test_json_schema_required_fields_match_model(self) -> None:
        """JSON Schema 'required' agrees with model optionality.

        Fields that have Python defaults should NOT appear in 'required';
        fields without defaults should be required in both places.
        """
        schema = json.loads(_RUN_MANIFEST_JSON_SCHEMA.read_text(encoding="utf-8"))
        json_required: set[str] = set(schema.get("required", []))

        # parent_run_id has default=None → must NOT be marked required
        assert "parent_run_id" not in json_required, (
            "Optional field 'parent_run_id' must not appear in JSON Schema 'required'."
        )
        # run and artifacts have no default → must be required in JSON Schema
        for required_field in ("run", "artifacts"):
            assert required_field in json_required, (
                f"Non-optional field '{required_field}' must be in JSON Schema 'required'."
            )


# ---------------------------------------------------------------------------
# Guard behaviour tests (demonstrate the gates work)
# ---------------------------------------------------------------------------


class TestSchemaRegressionGuards:
    """Self-tests that prove the regression gates actually catch violations."""

    def test_extra_field_in_json_is_rejected(self) -> None:
        """RunManifest rejects JSON with an unknown field (extra='forbid')."""
        data = _load_snapshot(_RUN_MANIFEST_SNAPSHOT)
        data["undeclared_field"] = "should_be_rejected"
        with pytest.raises(ValidationError, match="undeclared_field"):
            manifest_mod.RunManifest.model_validate(data)

    def test_missing_required_field_is_rejected(self) -> None:
        """RunManifest rejects JSON missing the required 'run' field."""
        data = _load_snapshot(_RUN_MANIFEST_SNAPSHOT)
        del data["run"]
        with pytest.raises(ValidationError):
            manifest_mod.RunManifest.model_validate(data)

    def test_invalid_run_type_is_rejected(self) -> None:
        """RunContext rejects an unrecognised run_type string."""
        data = _load_snapshot(_RUN_MANIFEST_SNAPSHOT)
        data["run"]["run_type"] = "not_a_real_stage"
        with pytest.raises(ValidationError):
            manifest_mod.RunManifest.model_validate(data)

    def test_field_set_mismatch_is_detected(self) -> None:
        """field_set check catches a fixture with an extra key (simulated schema drift)."""
        fixture_keys = {"schema_version", "run", "artifacts", "parent_run_id", "ghost_field"}
        model_keys = set(manifest_mod.RunManifest.model_fields.keys())
        extra_in_fixture = fixture_keys - model_keys
        assert "ghost_field" in extra_in_fixture

    def test_model_adding_field_without_snapshot_update_is_detected(self) -> None:
        """Simulate a new model field absent from the fixture — mismatch caught."""
        fixture_keys = set(_load_snapshot(_RUN_MANIFEST_SNAPSHOT).keys())
        # Simulate model_fields having an extra key that the fixture doesn't
        simulated_model_keys = set(manifest_mod.RunManifest.model_fields.keys()) | {
            "new_unreleased_field"
        }
        extra_in_model = simulated_model_keys - fixture_keys
        assert "new_unreleased_field" in extra_in_model
