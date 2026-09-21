"""Exercise an actual serial ClearML agent, failed-step recovery and server overrides."""

from __future__ import annotations

# standard library imports
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# third party library imports
import msgspec
from clearml import Task
from msgspec.structs import replace

# project library imports
from research.experiments import AttemptStore, BacktestRun, PublicationReceipt, ResultManifest
from serialization import DomainCodec


class _PipelineAcceptance:
    """Compare installed agent steps with retained CLI results and preserve original failures."""

    def __init__(self, source: Path, output: Path, wheel: Path) -> None:
        """Bind saved synthetic inputs and an already running dedicated local worker."""
        self.source, self.output, self.wheel = source, output, wheel
        self.command = Path(sys.executable).parent / "alpha-backtest"
        self.attempts = output / "attempts"
        self.inputs = output / "inputs"
        self.codec = DomainCodec()
        output.mkdir(parents=True)
        self.attempts.mkdir()
        self.inputs.mkdir()
        for name in ("raw", "snapshots"):
            shutil.copytree(source / name, self.inputs / name)

    def pipeline(self, name: str, *, successful: bool, comparison: bool = False) -> None:
        """Execute the public installed CLI and retain controller output for each launch."""
        result = subprocess.run(
            [
                str(self.command),
                "pipeline",
                "--config",
                str(self.source / "configured.json"),
                "--tracking",
                str(self.source / "tracking.json"),
                "--inputs",
                str(self.inputs),
                "--attempts",
                str(self.attempts),
                "--output",
                str(self.output / name),
                "--wheel",
                str(self.wheel),
                "--max-bytes",
                "2000000",
                "--queue",
                "alpha-research-local",
            ]
            + (["--comparison-config", str(self.source / "comparison.json")] if comparison else []),
            cwd=self.output,
            capture_output=True,
            check=False,
        )
        (self.output / f"{name}.log").write_bytes(result.stdout + result.stderr)
        assert result.returncode == (0 if successful else 4), result.stderr

    def verify(self) -> None:
        """Prove parity, failed dependency suppression, fresh recovery and actual overrides."""
        self.pipeline("initial", successful=True)
        store = AttemptStore(self.attempts)
        histories = store.histories()
        assert len(histories) == 2 and all(h.status == "completed" for h in histories)
        complete = next(
            h for h in histories if "report-html" in store.artifacts(h.start.attempt_id)
        )
        reference = AttemptStore(self.source / "configured-attempts")
        local = next(h for h in reference.histories() if h.status == "completed")
        assert ResultManifest.read(store, complete.start.attempt_id) == ResultManifest.read(
            reference, local.start.attempt_id
        )
        initial_ids = {h.start.attempt_id for h in histories}
        saved = next(p for p in (self.inputs / "raw").rglob("*") if p.is_file())
        payload = saved.read_bytes()
        saved.unlink()
        self.pipeline("failed", successful=False)
        failed = next(h for h in store.histories() if h.start.attempt_id not in initial_ids)
        assert failed.status == "failed" and len(store.histories()) == 3
        assert not tuple((self.output / "failed").glob("*/complete-*-attempt.json"))
        failed_bytes = self.codec.encode_json(failed)
        association = msgspec.json.decode(
            store.artifact(failed.start.attempt_id, "pipeline-step"), type=list[str]
        )
        assert Task.get_task(task_id=association[1]).status == "failed"
        saved.write_bytes(payload)
        self.pipeline("recovered", successful=True)
        assert len(store.histories()) == 5
        assert self.codec.encode_json(store.read(failed.start.attempt_id)) == failed_bytes
        assert Task.get_task(task_id=association[1]).status == "failed"
        association = msgspec.json.decode(
            store.artifact(complete.start.attempt_id, "pipeline-step"), type=list[str]
        )
        task = Task.clone(source_task=association[1], name="configured-server-override")
        parameters = {
            key: value
            for key, value in task.get_parameters().items()
            if not key.startswith("retained/")
        }
        selected = BacktestRun.read(self.source / "configured.json")
        changed = replace(selected, economics=replace(selected.economics, rule="no-trade-v1"))
        parameters.update(
            {
                "Run/configuration": self.codec.encode_json(changed).decode(),
                "Run/upstream": "",
                "Run/controller": task.id,
            }
        )
        task.set_parameters(parameters)
        Task.enqueue(task=task, queue_name="alpha-research-local")
        until = time.monotonic() + 180
        while task.status not in ("completed", "failed", "stopped") and time.monotonic() < until:
            time.sleep(2)
            task.reload()
        assert task.status == "completed", task.status
        resolved = task.get_parameters()
        override = store.read(resolved["retained/attempt_id"])
        assert override.start.run_identity != complete.start.run_identity
        assert store.artifact(
            override.start.attempt_id, "resolved-configuration"
        ) == self.codec.encode_json(changed)
        assert store.artifact(
            override.start.attempt_id, "economic-reference"
        ) != reference.artifact(local.start.attempt_id, "economic-reference")
        (self.output / "acceptance.json").write_bytes(
            self.codec.encode_json(
                {
                    "initial": complete.start.attempt_id,
                    "failed": failed.start.attempt_id,
                    "override": override.start.attempt_id,
                    "override_task": task.id,
                    "attempt_count": len(store.histories()),
                }
            )
        )
        print("Verified pipeline parity, failed-step recovery and server override")
        self.comparison()

    def comparison(self) -> None:
        """Prove the real worker executes one frozen grid and resumes its journal unchanged."""
        self.pipeline("comparison", successful=True, comparison=True)
        store = AttemptStore(self.attempts)
        trials = tuple(
            h
            for h in store.histories()
            if "comparison-definition" in store.artifacts(h.start.attempt_id)
        )
        assert len(trials) == 2 and all(h.status == "completed" for h in trials)
        original = tuple(self.codec.encode_json(h) for h in trials)
        for history in trials:
            ResultManifest.read(store, history.start.attempt_id)
            association = msgspec.json.decode(
                store.artifact(history.start.attempt_id, "pipeline-step"), type=list[str]
            )
            task = Task.get_task(task_id=association[1])
            assert task.status == "completed" and task.get_parameters()["Run/stage"] == "comparison"
            mapped = msgspec.json.decode(
                task.get_parameters()["retained/attempt_ids"].encode(), type=tuple[str, ...]
            )
            assert history.start.attempt_id in mapped
            receipt = self.codec.decode_json(
                store.artifact(history.start.attempt_id, "clearml-receipt"), PublicationReceipt
            )
            publication = Task.get_task(task_id=receipt.task_id)
            variant = self.codec.decode_json(history.start.request, BacktestRun)
            assert publication.get_parameters()["comparison/variant"] == variant.identity
            assert publication.get_parameters()["comparison/rule"] == variant.economics.rule
            assert "comparison/exact_net_return" in publication.get_parameters()
            assert not any(event.status == "holdout_consumed" for event in history.events)
        self.pipeline("comparison", successful=True, comparison=True)
        reopened = tuple(
            h
            for h in store.histories()
            if "comparison-definition" in store.artifacts(h.start.attempt_id)
        )
        assert tuple(self.codec.encode_json(h) for h in reopened) == original
        (self.output / "comparison-acceptance.json").write_bytes(
            self.codec.encode_json(tuple(h.start.attempt_id for h in reopened))
        )
        print("Verified actual ClearML comparison execution and unchanged resumed trial history")


def main() -> None:
    """Run explicit local-service acceptance from an installed runtime outside the checkout."""
    source, output, wheel = (Path(value).resolve() for value in sys.argv[1:4])
    values = dict(
        line.split("=", 1)
        for line in Path(os.environ["ALPHA_CLEARML_LOCAL_ENV"]).read_text().splitlines()
        if line and not line.startswith("#")
    )
    os.environ.update(
        CLEARML_API_HOST="http://127.0.0.1:18008",
        CLEARML_WEB_HOST="http://127.0.0.1:18080",
        CLEARML_FILES_HOST="http://127.0.0.1:18081",
        CLEARML_API_ACCESS_KEY=values["CLEARML_LOCAL_ACCESS_KEY"],
        CLEARML_API_SECRET_KEY=values["CLEARML_LOCAL_SECRET_KEY"],
        CLEARML_CACHE_DIR=str(output / "sdk-cache"),
    )
    _PipelineAcceptance(source, output, wheel).verify()


if __name__ == "__main__":
    main()
