"""Verify installed acquisition commands, truthful progress and resumable failures."""

from __future__ import annotations

# standard library imports
import hashlib
import shutil
import subprocess
import sys
from datetime import timedelta
from http.client import HTTPSConnection
from pathlib import Path
from unittest.mock import patch

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from alpha_research.configuration import Configuration
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.pipelines.acquisition import main
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()
_REPORTS = msgspec.json.Decoder(dict[str, object])


class TestAcquisitionCommand:
    """Exercise copied configuration and real persistence through the installed entry point."""

    @pytest.fixture()
    def inputs(self, tmp_path: Path) -> list[str]:
        """Copy non-secret source selections and resolve the shared synthetic process fixture.

        Args:
            tmp_path: Isolated local destination for copied inputs and generated state.

        Returns:
            Command arguments for three partitions in an outside-checkout destination.
        """
        configuration = Configuration.read(_ROOT / "configs/data-jobs/fixture-inspection.json")
        job = replace(configuration.jobs[0], mode="historical", pipeline="acquisition.fetch")
        configuration = replace(
            configuration, jobs=(replace(job, end=job.start + timedelta(minutes=3)),)
        )
        (tmp_path / "jobs.json").write_bytes(_CODEC.encode_json(configuration))
        shutil.copyfile(_ROOT / "configs/reference/binance-spot.json", tmp_path / "catalog.json")
        shutil.copyfile(_ROOT / "tests/fixtures/mr06/acquire.py", tmp_path / "acquire.py")
        catalog = _CODEC.decode_json((tmp_path / "catalog.json").read_bytes(), CatalogSnapshot)
        run = configuration.resolve(job.name, catalog)
        (tmp_path / "run.json").write_bytes(_CODEC.encode_json(run))
        (tmp_path / "raw").mkdir()
        return [
            "--config",
            str(tmp_path / "jobs.json"),
            "--catalog",
            str(tmp_path / "catalog.json"),
            "--job",
            job.name,
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--store",
            str(tmp_path / "raw"),
            "--rights-reference",
            job.rights_reference,
            "--timeout-seconds",
            "1",
            "--max-bytes",
            "4096",
            "--retry-delays",
            "0",
            "0",
        ]

    @staticmethod
    def _process(root: Path, arguments: list[str], point: str) -> subprocess.CompletedProcess[str]:
        """Execute the installed console script with injected HTTP and real checkpoint files."""
        return subprocess.run(
            [
                sys.executable,
                "-I",
                str(root / "acquire.py"),
                str(root),
                str(root / "run.json"),
                point,
                "--command",
                *arguments,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

    @pytest.mark.parametrize("point", ["after-raw", "interrupt", "exhausted", "retry"])
    def test_installed_interrupt_resume_repeat_and_telemetry(
        self,
        tmp_path: Path,
        inputs: list[str],
        point: str,
    ) -> None:
        """Retain flushed progress before process death and reuse acknowledged completions."""
        first = self._process(tmp_path, inputs, point)
        assert (
            first.returncode
            == {"after-raw": 75, "interrupt": 130, "exhausted": 4, "retry": 0}[point]
        ), first.stderr
        records = [_REPORTS.decode(line) for line in first.stdout.splitlines()]
        start = records[0]
        assert (
            start["command_identity"]
            == hashlib.sha256(_CODEC.encode_json(start["command"])).hexdigest()
        )
        checkpoint = next(row for row in records if row["status"] == "checkpointed")
        assert checkpoint["completed"] == 1 and checkpoint["total"] == 3
        assert isinstance(checkpoint["last_persistence"], str)
        assert isinstance(checkpoint["persisted_bytes"], int) and checkpoint["persisted_bytes"] > 0
        assert checkpoint["request_identity"] is not None
        assert "synthetic private" not in first.stdout + first.stderr
        if first.stderr:
            terminal = _REPORTS.decode(first.stderr)
            assert terminal["completed"] == 1
            assert terminal["last_persistence"] == checkpoint["last_persistence"]
            assert terminal["scope"] == "job" and terminal["stage"] == "fetch"
            assert terminal["retries"] == (2 if point == "exhausted" else 0)
        if point == "retry":
            assert records[-1]["status"] == "complete" and records[-1]["retries"] == 1
        before = _CODEC.decode_json((tmp_path / "manifest.json").read_bytes(), AcquisitionManifest)
        result = self._process(tmp_path, inputs, "none")
        assert result.returncode == 0 and result.stderr == ""
        terminal = _REPORTS.decode(result.stdout.splitlines()[-1])
        assert terminal["status"] == "complete" and terminal["completed"] == terminal["total"] == 3
        assert terminal["command_identity"] == start["command_identity"]
        manifest_bytes = (tmp_path / "manifest.json").read_bytes()
        state = _CODEC.decode_json(manifest_bytes, AcquisitionManifest)
        assert state.completed[: len(before.completed)] == before.completed
        if before.pending is not None and point == "after-raw":
            assert state.completed[1].ts_received == before.pending.ts_received
        assert terminal["persisted_bytes"] == sum(item.size_bytes for item in state.completed)
        assert len({item.request_identity for item in state.completed}) == 3
        fetches = (tmp_path / "fetches.txt").read_bytes()
        repeat = self._process(tmp_path, inputs, "none")
        assert repeat.returncode == 0 and repeat.stderr == ""
        assert (tmp_path / "manifest.json").read_bytes() == manifest_bytes
        assert (tmp_path / "fetches.txt").read_bytes() == fetches
        assert all(_REPORTS.decode(row)["stage"] != "fetch" for row in repeat.stdout.splitlines())

    @pytest.mark.parametrize("damage", ["missing", "mutation", "truncation", "foreign-run"])
    def test_completed_state_rejected_by_unpatched_installed_command(
        self,
        tmp_path: Path,
        inputs: list[str],
        damage: str,
    ) -> None:
        """Reject damaged bytes or a changed configuration before any fresh source access."""
        assert self._process(tmp_path, inputs, "none").returncode == 0
        saved = (tmp_path / "manifest.json").read_bytes()
        state = _CODEC.decode_json(saved, AcquisitionManifest)
        target = tmp_path / "raw" / state.completed[0].sha256
        if damage == "foreign-run":
            configuration = Configuration.read(tmp_path / "jobs.json")
            job = replace(configuration.jobs[0], source_revision="changed-revision")
            (tmp_path / "jobs.json").write_bytes(
                _CODEC.encode_json(replace(configuration, jobs=(job,)))
            )
        elif damage == "missing":
            target.unlink()
        else:
            payload = target.read_bytes()
            target.chmod(0o644)
            target.write_bytes(payload[:-1] if damage == "truncation" else b"X" + payload[1:])
        result = subprocess.run(
            [str(Path(sys.executable).parent / "alpha-acquire"), *inputs],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == (4 if damage == "missing" else 3)
        terminal = _REPORTS.decode(result.stderr)
        assert terminal["stage"] == "resume" and terminal["completed"] is None
        assert terminal["last_persistence"] is None and terminal["status"] == "failed"
        assert (tmp_path / "manifest.json").read_bytes() == saved

    @pytest.mark.parametrize(
        ("option", "value"),
        [
            ("--job", "unknown"),
            ("--timeout-seconds", "nan"),
            ("--max-bytes", "0"),
            ("--retry-delays", "-1"),
            ("--rights-reference", "unresolved"),
            ("--api-key-env", "MR07_MISSING_CREDENTIAL"),
        ],
    )
    def test_preflight_and_admission_errors_are_terminal(
        self,
        tmp_path: Path,
        inputs: list[str],
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        option: str,
        value: str,
    ) -> None:
        """Validate explicit command inputs and never fetch after a rejected selection."""
        monkeypatch.delenv("MR07_MISSING_CREDENTIAL", raising=False)
        if option in inputs:
            inputs[inputs.index(option) + 1] = value
        else:
            inputs.extend((option, value))
        with patch.object(HTTPSConnection, "request") as request:
            assert main(inputs) == (3 if option in {"--retry-delays", "--rights-reference"} else 2)
            request.assert_not_called()
        terminal = _REPORTS.decode(capsys.readouterr().err)
        assert terminal["status"] == "failed" and terminal["diagnostic"]
        assert not list((tmp_path / "raw").iterdir())

    def test_checkpoint_failure_reports_last_acknowledged_persistence(
        self,
        tmp_path: Path,
        inputs: list[str],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A failed checkpoint cannot advertise its unacknowledged bytes or completion."""
        assert self._process(tmp_path, inputs, "after-raw").returncode == 75
        original = _CODEC.decode_json(
            (tmp_path / "manifest.json").read_bytes(), AcquisitionManifest
        )
        outcomes: list[OSError | None] = [None, OSError("private path")]
        with patch.object(AcquisitionManifest, "save", side_effect=outcomes):
            assert main(inputs) == 4
        output = capsys.readouterr()
        terminal = _REPORTS.decode(output.err)
        assert terminal["stage"] == "checkpoint" and terminal["completed"] == 1
        assert terminal["persisted_bytes"] == original.completed[0].size_bytes
        assert terminal["last_persistence"] == original.completed[
            0
        ].ts_ingested.isoformat().replace("+00:00", "Z")
        assert "private path" not in output.out + output.err

    def test_credential_is_only_in_http_header(
        self,
        inputs: list[str],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Never put an environment credential into command identity, errors or saved state."""
        monkeypatch.setenv("MR07_SYNTHETIC_KEY", "private-test-key")
        inputs.extend(("--api-key-env", "MR07_SYNTHETIC_KEY"))
        with patch.object(
            HTTPSConnection, "request", side_effect=PermissionError("private-test-key")
        ) as request:
            assert main(inputs) == 4
            request.assert_called_once()
            assert "private-test-key" in str(request.call_args)
        output = capsys.readouterr()
        assert "private-test-key" not in output.out + output.err
        saved = Path(inputs[inputs.index("--manifest") + 1]).read_text()
        assert "private-test-key" not in saved

    def test_manifest_cannot_overwrite_configuration(
        self,
        inputs: list[str],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Reject an accidental output/input alias before checkpoint publication."""
        config = inputs[inputs.index("--config") + 1]
        original = Path(config).read_bytes()
        inputs[inputs.index("--manifest") + 1] = config
        assert main(inputs) == 2
        assert _REPORTS.decode(capsys.readouterr().err)["stage"] == "configuration"
        assert Path(config).read_bytes() == original
