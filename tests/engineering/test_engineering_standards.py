"""Test the compact engineering-standards boundary."""

from __future__ import annotations

# standard library imports
from datetime import date
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research_governance.engineering_standards import (
    EngineeringStandards,
    EngineeringStandardsError,
    main,
)
from alpha_research_governance.engineering_standards.format_compatibility import (
    FormatCompatibilityChecker,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
VALIDATION_DATE = date(2026, 9, 7)


class StandardsFixtures:
    """Build minimal repositories with every governed source root."""

    @staticmethod
    def repository(tmp_path: Path, source: str) -> Path:
        """Create all owned source roots with one Python fixture."""
        for source_root in (
            "src",
            "tests",
            "tools/governance/src",
            "tools/typing/stubs",
            "examples",
        ):
            (tmp_path / source_root).mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        project = tmp_path / "pyproject.toml"
        text = project.read_text()
        start, end = text.index("[project.scripts]"), text.index("[dependency-groups]")
        project.write_text(text[:start] + text[end:])
        (tmp_path / "src/fixture.py").write_text(source, encoding="utf-8")
        return tmp_path


class TestEngineeringStandards:
    """Exercise direct source validation and its command boundary."""

    def test_tooling_configuration_reports_malformed_toml(self, tmp_path: Path) -> None:
        """Report malformed TOML through the controlled configuration boundary."""
        (tmp_path / "pyproject.toml").write_text("[tool", encoding="utf-8")
        findings = EngineeringStandards.tooling_configuration_findings(tmp_path)
        assert len(findings) == 1
        assert findings[0].startswith("Python tooling configuration:")

    def test_source_accepts_unparenthesized_exception_types(self, tmp_path: Path) -> None:
        """Parse Python 3.14 exception syntax emitted by the pinned formatter."""
        root = StandardsFixtures.repository(
            tmp_path,
            '"""Exercise exception syntax."""\n\n'
            "def _parse(value: str) -> int:\n"
            '    """Return an integer or the invalid-input sentinel."""\n'
            "    try:\n"
            "        return int(value)\n"
            "    except TypeError, ValueError:\n"
            "        return -1\n",
        )
        assert EngineeringStandards.source_tree_findings(root) == ()

    def test_repository_source_passes_without_policy_or_evidence_files(self) -> None:
        """Validate the retained source contract without repository policy records."""
        assert EngineeringStandards.validate_repository(REPOSITORY_ROOT) == ()

    def test_source_findings_include_untracked_fixture_diagnostics(self, tmp_path: Path) -> None:
        """Report clarity findings from a newly created Python file."""
        root = StandardsFixtures.repository(
            tmp_path,
            '"""Fixture module."""\n\nfrom typing import Any\n\nvalue: Any\n',
        )

        findings = EngineeringStandards.source_tree_findings(root)

        assert any("src/fixture.py" in finding and "PYI001" in finding for finding in findings)

    @pytest.mark.parametrize(
        ("old", "new", "expected"),
        [
            ("strict = true", "strict = false", "strict"),
            ("disallow_any_expr = true", "disallow_any_expr = false", "disallow_any_expr"),
            ("init_typed = true", "init_typed = false", "init_typed"),
            ("init_forbid_extra = true", "init_forbid_extra = false", "init_forbid_extra"),
            (
                "warn_required_dynamic_aliases = true",
                "warn_required_dynamic_aliases = false",
                "warn_required_dynamic_aliases",
            ),
            (
                'select = ["E", "F", "I", "W", "UP", "RUF", "D", "ANN401"]',
                'select = ["E", "F", "W", "UP", "RUF", "D", "ANN401"]',
                "import sorting",
            ),
            ('convention = "google"', 'convention = "pep257"', "Google convention"),
            (
                'mypy_path = ["src", "tools/governance/src", "tools/typing/stubs"]',
                'mypy_path = ["src"]',
                "source and native-stub scope",
            ),
            ('filterwarnings = ["error"]', 'filterwarnings = ["default"]', "warnings"),
            ("strict = true", 'strict = true\nexclude = "tests"', "bypass checks"),
            (
                "[tool.mypy]\n",
                '[tool.mypy]\ndisable_error_code = ["misc"]\n',
                "disable_error_code",
            ),
            (
                "[tool.mypy]\n",
                '[tool.mypy]\nper_module_options = { "tests.*" = { ignore_errors = true } }\n',
                "per_module_options",
            ),
            (
                'select = ["E", "F", "I", "W", "UP", "RUF", "D", "ANN401"]',
                'select = "I"',
                "Ruff selected rules must be a list of strings",
            ),
        ],
    )
    def test_tooling_configuration_preserves_strict_clarity_settings(
        self, tmp_path: Path, old: str, new: str, expected: str
    ) -> None:
        """Reject weakened strict mypy, Ruff, and pytest clarity configuration."""
        path = tmp_path / "pyproject.toml"
        content = (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert old in content
        path.write_text(content.replace(old, new, 1), encoding="utf-8")

        findings = EngineeringStandards.tooling_configuration_findings(tmp_path)

        assert any(expected in finding for finding in findings)

    def test_validate_repository_raises_for_source_findings(self, tmp_path: Path) -> None:
        """Turn direct findings into one controlled standards error."""
        root = StandardsFixtures.repository(
            tmp_path,
            '"""Fixture module."""\n\nfrom typing import Any\n\nvalue: Any\n',
        )

        with pytest.raises(EngineeringStandardsError) as error:
            EngineeringStandards.validate_repository(root)

        assert "PYT001" in str(error.value)

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("value = call()  # noqa: RUF100", "requires"),
            (
                "value = call()  # noqa: RUF100 [owner=platform; rationale=keep "
                "behavior; expires=2026-09-06]",
                "expired",
            ),
            (
                "value = call()  # noqa: RUF100 [owner=platform; rationale=keep "
                "behavior; expires=2027-04-01]",
                "maximum lifetime",
            ),
        ],
    )
    def test_suppression_annotations_fail_closed(self, line: str, expected: str) -> None:
        """Require local owner, rationale, and bounded expiry metadata."""
        findings = EngineeringStandards.validate_suppression_line(
            line, validation_date=VALIDATION_DATE
        )

        assert any(expected in finding for finding in findings)

    def test_suppression_annotation_accepts_local_owner_without_registry(self) -> None:
        """Accept valid metadata without loading an ownership role table."""
        line = (
            "value = call()  # noqa: RUF100 [owner=founder; "
            "rationale=keep behavior while boundary is simplified; expires=2026-12-01]"
        )

        assert (
            EngineeringStandards.validate_suppression_line(line, validation_date=VALIDATION_DATE)
            == ()
        )

    def test_cli_reports_success_usage_error_and_missing_root(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Keep command statuses and diagnostics stable at the CLI boundary."""
        valid_root = StandardsFixtures.repository(
            tmp_path / "valid", '"""Fixture module."""\n\nvalue: int = 1\n'
        )
        assert main([str(valid_root)]) == 0
        assert "Python clarity standards passed" in capsys.readouterr().out

        assert main(["one", "two"]) == 2
        assert "usage:" in capsys.readouterr().err

        assert main([str(tmp_path / "missing")]) == 1
        assert "missing Python standards source root" in capsys.readouterr().err


class TestFormatCompatibilityChecker:
    """Reject runtime text that labels code or documentation as kept for an old format."""

    @pytest.mark.parametrize(
        "line",
        [
            "# Keep legacy readers for v1 manifests.",
            "Backward compatible decoding of old journals.",
            "backward-compat alias",
            "LEGACY path",
            "Backwards compatible decoding of old journals.",
        ],
    )
    def test_rejects_compatibility_wording_in_any_runtime_text(
        self, tmp_path: Path, line: str
    ) -> None:
        """Report the exact file and line in Python and Markdown sources alike."""
        package = tmp_path / "src/package"
        package.mkdir(parents=True)
        (package / "module.py").write_text('"""Module."""\n')
        (package / "README.md").write_text(f"# Package\n\n{line}\n")
        (package / "data.bin").write_bytes(b"\xff\xfe legacy")

        findings = FormatCompatibilityChecker.findings(tmp_path)

        assert len(findings) == 1
        assert findings[0].startswith("src/package/README.md:3: format changes replace in place")

    def test_accepts_current_wording_and_missing_root(self, tmp_path: Path) -> None:
        """Current-format wording passes, and an absent runtime root yields no findings."""
        assert FormatCompatibilityChecker.findings(tmp_path) == ()
        (tmp_path / "src").mkdir()
        (tmp_path / "src/README.md").write_text("Unsupported schemas are refused.\n")
        assert FormatCompatibilityChecker.findings(tmp_path) == ()

    def test_rejects_revision_suffixed_names_but_not_listed_external_paths(
        self, tmp_path: Path
    ) -> None:
        """Owned code, tests and configs cannot name formats by revision."""
        suffix = "-" + "v2"
        (tmp_path / "configs").mkdir()
        (tmp_path / "configs/job.json").write_text(f'{{"schema": "job{suffix}"}}\n')
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests/test_x.py").write_text(f"handler_{suffix[1:]} = 1\n")
        (tmp_path / "src").mkdir()
        (tmp_path / "src/README.md").write_text("See https://www.okx.com/docs" + "-" + "v5/en/\n")
        (tmp_path / "src/.venv").mkdir()
        (tmp_path / "src/.venv/vendor.py").write_text(f"third_party{suffix} = 1\n")

        findings = FormatCompatibilityChecker.findings(tmp_path)

        assert sorted(finding.split(": ")[0] for finding in findings) == [
            "configs/job.json:1",
            "tests/test_x.py:1",
        ]
        assert all("revision suffix" in finding for finding in findings)

    @pytest.mark.parametrize(
        "name",
        ["decode_" + "v2" + "_rows", "DECODER_" + "V2", "decoder" + "V2", "api-" + "V3"],
    )
    def test_rejects_revision_suffixes_inside_names_and_in_any_case(
        self, tmp_path: Path, name: str
    ) -> None:
        """A revision marker is a suffix even when more name follows or it is uppercase."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src/module.py").write_text(
            f"{name} = 1  # IPv6 and UUIDv4 are not revisions\n"
        )

        findings = FormatCompatibilityChecker.findings(tmp_path)

        assert len(findings) == 1 and "revision suffix" in findings[0]

    def test_repository_runtime_text_has_no_compatibility_wording(self) -> None:
        """Keep the checked-in runtime tree free of old-format compatibility wording."""
        assert FormatCompatibilityChecker.findings(REPOSITORY_ROOT) == ()

    def test_validate_repository_reports_compatibility_wording(self, tmp_path: Path) -> None:
        """The engineering command fails closed on the wording finding."""
        root = StandardsFixtures.repository(tmp_path, '"""Keep the legacy reader."""\n')
        with pytest.raises(EngineeringStandardsError, match="format changes replace in place"):
            EngineeringStandards.validate_repository(root, validation_date=VALIDATION_DATE)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
