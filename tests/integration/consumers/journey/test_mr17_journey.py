"""Prove the MR17 journey declaration, command records, guide coverage and summary rules."""

from __future__ import annotations

# standard library imports
import subprocess  # nosec B404  # [owner=runtime; rationale=authored git fixture; expires=2027-03-01]
import sys
from pathlib import Path

# third party library imports
import msgspec
import pytest
from mr17_journey import (
    CaptureWindow,
    Commands,
    GuideCoverage,
    Journey,
    JourneyDeclaration,
    Summary,
)


class JourneyFixture:
    """Author declarations, guides and repositories for the journey driver."""

    @staticmethod
    def window(**changes: int) -> CaptureWindow:
        """Author a valid 30-minute capture window."""
        values = {
            "lead_seconds": 120,
            "ready_seconds": 60,
            "duration_seconds": 1800,
            "max_messages": 10_000_000,
            "max_bytes": 8 * 1024**3,
            "max_segments": 8,
            "max_reconnects": 4,
        }
        values.update(changes)
        return CaptureWindow(**values)

    @classmethod
    def declaration(cls, root: Path, **changes: object) -> JourneyDeclaration:
        """Author a valid rehearsal declaration rooted under ``root``."""
        values: dict[str, object] = {
            "attempt": "rehearsal-1",
            "counted": False,
            "through": "J5",
            "repository": str(root / "repository"),
            "commit": "0" * 40,
            "qr_workspace": str(root / "qr"),
            "qr_commit": "1" * 40,
            "evidence_root": str(root / "evidence"),
            "temporary_root": str(root / "t"),
            "uv": "/usr/bin/true",
            "local_services_env": str(root / "local-services.env"),
            "lakefs_credentials": str(root / "lakefs-access.json"),
            "lakefs_repository": "mr17-rehearsal-1",
            "feeds": ("okx-btc-usdt-books", "okx-btc-usdt-trades"),
            "window": cls.window(),
            "holdouts": 1,
            "guides": ("examples/qr-quickstart.md",),
        }
        values.update(changes)
        return msgspec.json.decode(msgspec.json.encode(values), type=JourneyDeclaration)

    @staticmethod
    def git(cwd: Path, *arguments: str) -> str:
        """Run one git command in an authored repository."""
        completed = subprocess.run(  # nosec B603 B607  # [owner=runtime; rationale=authored git fixture; expires=2027-03-01]
            ("git", *arguments), cwd=cwd, capture_output=True, check=True, text=True
        )
        return completed.stdout.strip()

    @classmethod
    def repository(cls, root: Path) -> str:
        """Create a one-commit repository and return its commit."""
        root.mkdir(parents=True)
        cls.git(root, "init", "-q")
        (root / "README.md").write_text("fixture\n")
        cls.git(root, "add", "README.md")
        cls.git(
            root,
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=f@example.invalid",
            "commit",
            "-q",
            "-m",
            "fixture",
        )
        return cls.git(root, "rev-parse", "HEAD")


class TestDeclaration:
    """Refuse declarations the record does not allow."""

    def test_valid_rehearsal(self, tmp_path: Path) -> None:
        """A rehearsal may stop before J8 and name no capacity records."""
        declaration = JourneyFixture.declaration(tmp_path)
        assert declaration.through == "J5" and not declaration.counted

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            ({"attempt": "trial"}, "rehearsal-<n>"),
            ({"counted": True}, "only a counted attempt"),
            ({"attempt": "counted", "counted": True}, "through J8"),
            ({"repository": "relative/path"}, "absolute"),
            ({"commit": "abc"}, "full SHA-1"),
            ({"feeds": ("a", "a")}, "distinct feeds"),
            ({"holdouts": 0}, "holdout"),
            ({"temporary_root": "/" + "t" * 90}, "socket"),
        ],
    )
    def test_refusals(self, tmp_path: Path, changes: dict[str, object], message: str) -> None:
        """Each invalid field is refused with its reason."""
        with pytest.raises((ValueError, msgspec.ValidationError), match=message):
            JourneyFixture.declaration(tmp_path, **changes)

    def test_counted_attempt_requires_both_capacity_records(self, tmp_path: Path) -> None:
        """A counted attempt runs through J8 with R1 and 2b records."""
        declaration = JourneyFixture.declaration(
            tmp_path,
            attempt="counted",
            counted=True,
            through="J8",
            capacity_records=(str(tmp_path / "r1.md"), str(tmp_path / "2b.md")),
        )
        assert declaration.counted

    @pytest.mark.parametrize(
        "changes",
        [{"lead_seconds": 5}, {"ready_seconds": 1800}, {"duration_seconds": 6 * 3600 + 1}],
    )
    def test_window_bounds(self, changes: dict[str, int]) -> None:
        """The window starts in the future, is ready inside itself and lasts six hours at most."""
        with pytest.raises(ValueError, match=r"capture window|six hours"):
            JourneyFixture.window(**changes)


class TestCommands:
    """Retain every command with a unique ordinal, its exit and output digests."""

    def test_sequential_and_concurrent_records(self, tmp_path: Path) -> None:
        """Ordinals are unique and records keep each command's own exit status."""
        commands = Commands(tmp_path)
        record, stdout = commands.run(
            "J1", "echo", (sys.executable, "-c", "print('x')"), cwd=tmp_path
        )
        assert record.ordinal == 1 and record.returncode == 0 and stdout == b"x\n"
        records = commands.run_concurrently(
            "J2",
            (
                ("ok", (sys.executable, "-c", "pass")),
                ("fail", (sys.executable, "-c", "raise SystemExit(3)")),
            ),
            cwd=tmp_path,
            timeout=60,
        )
        assert [(r.ordinal, r.label, r.returncode) for r in records] == [
            (2, "ok", 0),
            (3, "fail", 3),
        ]
        lines = (tmp_path / "commands.jsonl").read_bytes().splitlines()
        assert len(lines) == 3
        assert sorted(path.name for path in (tmp_path / "logs").iterdir())[:2] == [
            "0001-echo.stderr",
            "0001-echo.stdout",
        ]


class TestGuideCoverage:
    """Find platform names a QR workspace imports that no linked guide mentions."""

    def test_links_and_uncovered_names(self, tmp_path: Path) -> None:
        """Linked Markdown is read; external links and fragments are ignored."""
        checkout = tmp_path / "checkout"
        (checkout / "examples").mkdir(parents=True)
        (checkout / "docs").mkdir()
        (checkout / "examples/qr-quickstart.md").write_text(
            "Use `CandidatePackager`. See [guide](../docs/guide.md#part) and "
            "[site](https://example.invalid).\n"
        )
        (checkout / "docs/guide.md").write_text("`InstalledExtensions` loads providers.\n")
        workspace = tmp_path / "qr"
        (workspace / "studies").mkdir(parents=True)
        (workspace / "studies/run.py").write_text(
            "from runtime import CandidatePackager, InstalledExtensions, LoadedCandidate\n"
            "from decimal import Decimal\n"
        )
        coverage = GuideCoverage(checkout, ("examples/qr-quickstart.md",))
        assert GuideCoverage.links("[a](b.md#c) [d](https://e)") == ("b.md",)
        gate, uncovered = coverage.assess(workspace)
        assert not gate.passed and uncovered == ("LoadedCandidate",)


class TestSequence:
    """Stop at the first failure and summarize it, and refuse unimplemented steps."""

    def test_unimplemented_steps_refused(self, tmp_path: Path) -> None:
        """J6 and J7 land with M3e; a declaration through them is refused before any work."""
        declaration = JourneyFixture.declaration(tmp_path, through="J7")
        with pytest.raises(ValueError, match="implements"):
            Journey(declaration, msgspec.json.encode(declaration)).run()
        assert not (tmp_path / "evidence").exists()

    def test_dirty_repository_fails_first(self, tmp_path: Path) -> None:
        """A checkout that differs from the declared commit fails J1 before any build."""
        commit = JourneyFixture.repository(tmp_path / "repository")
        (tmp_path / "repository/README.md").write_text("changed\n")
        declaration = JourneyFixture.declaration(tmp_path, commit=commit)
        summary = Journey(declaration, msgspec.json.encode(declaration)).run()
        assert summary.result == "failed"
        assert summary.first_failure is not None
        assert summary.first_failure.criterion == "repository_clean_at_declared_commit"
        retained = msgspec.json.decode(
            (tmp_path / "evidence/rehearsal-1/summary.json").read_bytes(), type=Summary
        )
        assert [step.status for step in retained.steps][:2] == ["failed", "not_run"]
        assert not (tmp_path / "evidence/rehearsal-1/checkout").exists()
