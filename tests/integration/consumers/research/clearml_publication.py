"""Verify local ClearML publication from retained attempts without rerunning research."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

# third party library imports
from clearml import Task

# project library imports
from research.experiments import AttemptStore, ClearMLDestination, ClearMLPublication
from serialization import DomainCodec

_CODEC = DomainCodec()
_RETAIN = AttemptStore.retain


class _PublicationCheck:
    """Own service setup, lost-receipt recovery and exact remote artifact verification."""

    @staticmethod
    def configure() -> None:
        """Load explicitly selected private local credentials without retaining or printing them."""
        location = Path(os.environ["ALPHA_CLEARML_LOCAL_ENV"])
        values = dict(
            line.split("=", 1)
            for line in location.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        os.environ.update(
            CLEARML_API_HOST="http://127.0.0.1:18008",
            CLEARML_WEB_HOST="http://127.0.0.1:18080",
            CLEARML_FILES_HOST="http://127.0.0.1:18081",
            CLEARML_API_ACCESS_KEY=values["CLEARML_LOCAL_ACCESS_KEY"],
            CLEARML_API_SECRET_KEY=values["CLEARML_LOCAL_SECRET_KEY"],
            CLEARML_CACHE_DIR=str(location.parent / "alpha-clearml-cache"),
        )

    @staticmethod
    def _interrupt_receipt(store: AttemptStore, attempt: str, name: str, payload: bytes) -> str:
        """Lose local acknowledgement only after actual server publication succeeds."""
        if name == "clearml-receipt":
            raise ConnectionError("injected receipt interruption")
        return _RETAIN(store, attempt, name, payload)

    @classmethod
    def run(cls, root: Path, *, resume: bool) -> None:
        """Verify an explicitly selected store and its existing local publication destinations.

        Args:
            root: Retained synthetic attempt store outside the checkout.
            resume: Reconcile and verify, or first interrupt a pending receipt in the parent.

        Raises:
            AssertionError: No publication intent exists or recovery changes retained evidence.
        """
        assert root.is_dir(), root
        with AttemptStore(root) as store:
            before = store.histories()
            selected: dict[str, ClearMLDestination] = {}
            # These serial workflows create models before reloading them; random
            # attempt-ID order can try to publish an input model before its creator.
            for _, attempt, history in sorted(
                (item.start.started_at, item.start.attempt_id, item) for item in before
            ):
                if "clearml-destination" not in store.artifacts(attempt):
                    continue
                assert history.status != "incomplete", attempt
                destination = _CODEC.decode_json(
                    store.artifact(attempt, "clearml-destination"), ClearMLDestination
                )
                assert destination.api_uri == "http://127.0.0.1:18008"
                assert destination.files_uri == "http://127.0.0.1:18081"
                selected[attempt] = destination
            assert selected, "no retained publication intents"
            if not resume:
                pending = next(
                    (item for item in selected if "clearml-receipt" not in store.artifacts(item)),
                    None,
                )
                assert pending is not None, "use fresh workflow output to exercise lost receipts"
                with patch.object(AttemptStore, "retain", new=cls._interrupt_receipt):
                    try:
                        ClearMLPublication(store, selected[pending]).publish(pending)
                    except ConnectionError as error:
                        assert str(error) == "injected receipt interruption"
                    else:
                        raise AssertionError("receipt interruption was not reached")
                assert "clearml-receipt" not in store.artifacts(pending)
        if not resume:
            subprocess.run(
                [sys.executable, "-I", __file__, "resume", str(root)],
                cwd=root,
                check=True,
                timeout=180,
            )
        else:
            with AttemptStore(root) as writer:
                receipts = tuple(
                    ClearMLPublication(writer, destination).publish(attempt)
                    for attempt, destination in selected.items()
                )
                assert (
                    tuple(
                        ClearMLPublication(writer, destination).publish(attempt)
                        for attempt, destination in selected.items()
                    )
                    == receipts
                )
            assert {item.attempt_id for item in receipts} == set(selected)
            for receipt in receipts:
                attempt = receipt.attempt_id
                tasks = Task.get_tasks(
                    project_name=selected[attempt].project,
                    task_name=f"^attempt-{attempt}$",
                    allow_archived=True,
                )
                assert len(tasks) == 1 and tasks[0].id == receipt.task_id
                history = store.read(attempt)
                assert tasks[0].status == (
                    "completed" if history.status == "completed" else "failed"
                )
                expected = {"attempt-history": _CODEC.encode_json(history)}
                expected.update(
                    (name, store.artifact(attempt, name))
                    for name in store.artifacts(attempt)
                    if not name.startswith("clearml-")
                )
                assert (
                    hashlib.sha256(expected["attempt-history"]).hexdigest()
                    == receipt.history_sha256
                )
                for name, payload in expected.items():
                    downloaded = tasks[0].artifacts[name].get_local_copy()
                    assert downloaded is not None and Path(downloaded).read_bytes() == payload, name
        assert store.histories() == before


def main() -> None:
    """Check supplied stores using explicit local credentials and a fresh reconciliation process.

    Raises:
        SystemExit: No attempt store was supplied.
    """
    arguments = sys.argv[1:]
    resume = arguments[:1] == ["resume"]
    roots = arguments[1:] if resume else arguments
    if not roots:
        raise SystemExit("usage: clearml_publication.py ATTEMPTS [ATTEMPTS ...]")
    _PublicationCheck.configure()
    for root in roots:
        _PublicationCheck.run(Path(root).resolve(strict=True), resume=resume)
    print("Verified ClearML receipt recovery, unique tasks and exact remote artifacts.")


if __name__ == "__main__":
    main()
