"""Contract tests for the B02 build-graph validator boundary and state."""

from __future__ import annotations

# standard library imports
import shutil
from pathlib import Path
from typing import Final

# third party library imports
import pytest
from build_graph_test import (
    BuildGraphValidator,
    _load_json_document,
    _require_json_table,
    _ValidationReport,
)
from pydantic import ValidationError

_REPOSITORY_ROOT: Final[Path] = Path(__file__).parents[2]
_EVIDENCE_ROOT: Final[Path] = _REPOSITORY_ROOT / "docs/governance/evidence/examples/b02-r2-partial"
_EXPECTED_GATE_IDS: Final[tuple[str, ...]] = (
    "QG01",
    "QG02",
    "QG03",
    "QG04",
    "QG05",
    "QG06",
    "QG09",
    "QG10",
    "QG11",
    "QG12",
    "QG13",
    "QG14",
)


class TestBuildGraphContracts:
    """Exercise the validator's explicit context and parser boundaries."""

    def test_repeated_validations_have_no_stale_findings(self) -> None:
        """Reuse one root-bound validator without accumulating invocation state."""
        validator = BuildGraphValidator(_REPOSITORY_ROOT)

        first = validator.validate()
        second = validator.validate()

        assert first.fatal_error is None
        assert first.governance_errors == ()
        assert second == first

    def test_full_gate_set_is_accepted(self) -> None:
        """Accept the complete ordered gate set from the checked-in evidence fixture."""
        assert BuildGraphValidator(_REPOSITORY_ROOT)._evidence_errors() == []

    def test_validation_report_is_strict_and_immutable(self) -> None:
        """Keep report fields typed, closed, and immutable at the result boundary."""
        report = _ValidationReport(governance_errors=("synthetic finding",))

        assert report.fatal_error is None
        assert report.governance_errors == ("synthetic finding",)
        assert isinstance(report.governance_errors, tuple)
        invalid_type: object = {"fatal_error": 1}
        with pytest.raises(ValidationError, match="valid string"):
            _ValidationReport.model_validate(invalid_type)
        unknown_field: object = {"unexpected": "synthetic"}
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            _ValidationReport.model_validate(unknown_field)
        invalid_collection: object = {"governance_errors": ["synthetic finding"]}
        with pytest.raises(ValidationError, match="valid tuple"):
            _ValidationReport.model_validate(invalid_collection)
        with pytest.raises(ValidationError, match="Instance is frozen"):
            setattr(report, "fatal_error", "changed")

    @pytest.mark.parametrize(
        "extra_gate",
        (
            'gate_id = "QG99"\nstatus = "passed"\n',
            'status = "passed"\n',
            'gate_id = 1\nstatus = "passed"\n',
            'gate_id = ["QG99"]\nstatus = "passed"\n',
        ),
    )
    def test_malformed_extra_gate_tables_are_rejected(
        self, tmp_path: Path, extra_gate: str
    ) -> None:
        """Reject extra gate tables with missing, wrong, or unhashable IDs."""
        evidence_root = tmp_path / "docs/governance/evidence/examples/b02-r2-partial"
        evidence_root.parent.mkdir(parents=True)
        shutil.copytree(_EVIDENCE_ROOT, evidence_root)
        manifest_path = evidence_root / "manifest.toml"
        original_manifest = manifest_path.read_text(encoding="utf-8")
        malformed_manifest = original_manifest.replace(
            "\n[[artifacts]]", f"\n[[gates]]\n{extra_gate}\n[[artifacts]]", 1
        )
        manifest_path.write_text(malformed_manifest, encoding="utf-8")
        validator = BuildGraphValidator(tmp_path)

        assert validator._evidence_errors() == ["evidence must bind the exact applicable R2 gates"]
        manifest_path.write_text(original_manifest, encoding="utf-8")
        assert validator._evidence_errors() == []

    def test_non_table_extra_gate_is_rejected(self, tmp_path: Path) -> None:
        """Reject an extra non-table gate entry instead of silently ignoring it."""
        evidence_root = tmp_path / "docs/governance/evidence/examples/b02-r2-partial"
        evidence_root.parent.mkdir(parents=True)
        shutil.copytree(_EVIDENCE_ROOT, evidence_root)
        manifest_path = evidence_root / "manifest.toml"
        original_manifest = manifest_path.read_text(encoding="utf-8")
        change_start = original_manifest.index("[change]")
        gates_start = original_manifest.index("[[gates]]")
        artifacts_start = original_manifest.index("[[artifacts]]")
        gate_entries = [
            "gates = [",
            *[f'  {{gate_id = "{gate_id}", status = "passed"}},' for gate_id in _EXPECTED_GATE_IDS],
            '  "malformed",',
            "]",
            "",
        ]
        malformed_manifest = (
            original_manifest[:change_start]
            + "\n".join(gate_entries)
            + original_manifest[change_start:gates_start]
            + original_manifest[artifacts_start:]
        )
        manifest_path.write_text(malformed_manifest, encoding="utf-8")

        assert BuildGraphValidator(tmp_path)._evidence_errors() == [
            "evidence must bind the exact applicable R2 gates"
        ]

    def test_json_root_is_narrowed_at_lock_access_boundary(self) -> None:
        """Retain the raw JSON root until the historical mapping access point."""
        parsed: object = _load_json_document("[]")

        assert parsed == []
        with pytest.raises(AttributeError, match=r"list.*get"):
            _require_json_table(parsed)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-W", "error"]))
