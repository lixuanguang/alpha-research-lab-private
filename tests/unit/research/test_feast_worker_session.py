"""Keep one Feast worker process across requests and replace it after any failure."""

from __future__ import annotations

# standard library imports
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest

# project library imports
from applications.explore.command import main
from research.features import FeastWorkerSession, FeatureAccessError

_WORKER = """
import json, os, sys, time
for line in sys.stdin.buffer:
    request = json.loads(line)
    if request == "fail":
        print("request refused", file=sys.stderr)
        raise SystemExit(2)
    if request == "hang":
        time.sleep(30)
    sys.stdout.write(json.dumps({"pid": os.getpid(), "echo": request}) + "\\n")
    sys.stdout.flush()
"""


class TestFeastWorkerSession:
    """A session answers over one process until a failure replaces it."""

    @staticmethod
    def _session(tmp_path: Path, timeout: float = 10) -> FeastWorkerSession:
        """Bind a session to the authored line worker."""
        script = tmp_path / "worker.py"
        script.write_text(_WORKER, encoding="utf-8")
        return FeastWorkerSession((sys.executable, "-I", str(script)), timeout_seconds=timeout)

    @staticmethod
    def _answer(session: FeastWorkerSession, request: object) -> dict[str, object]:
        """Send one JSON request and decode its answer."""
        answer: dict[str, object] = json.loads(session(json.dumps(request).encode()))
        return answer

    def test_requests_share_one_process(self, tmp_path: Path) -> None:
        """Consecutive requests are answered in order by the same worker."""
        session = self._session(tmp_path)
        try:
            first = self._answer(session, {"n": 1})
            second = self._answer(session, {"n": 2})
        finally:
            session.close()
        assert (first["echo"], second["echo"]) == ({"n": 1}, {"n": 2})
        assert first["pid"] == second["pid"]

    def test_start_runs_the_worker_before_its_first_request(self, tmp_path: Path) -> None:
        """A started worker answers the first request; starting again keeps it."""
        session = self._session(tmp_path)
        try:
            session.start()
            session.start()
            first = self._answer(session, "first")["pid"]
            assert self._answer(session, "second")["pid"] == first
        finally:
            session.close()

    def test_failure_carries_stderr_and_restarts(self, tmp_path: Path) -> None:
        """A failed request raises its reason, and the next request starts a new worker."""
        session = self._session(tmp_path)
        try:
            before = self._answer(session, "ready")["pid"]
            with pytest.raises(FeatureAccessError, match="request refused"):
                session(b'"fail"')
            after = self._answer(session, "again")["pid"]
        finally:
            session.close()
        assert before != after

    def test_timeout_kills_the_worker(self, tmp_path: Path) -> None:
        """A request beyond its timeout fails and leaves no worker behind."""
        session = self._session(tmp_path, timeout=0.5)
        try:
            with pytest.raises(FeatureAccessError, match="timeout"):
                session(b'"hang"')
            assert self._answer(session, "next")["echo"] == "next"
        finally:
            session.close()

    def test_requests_are_single_lines(self, tmp_path: Path) -> None:
        """A request containing a line break is refused before it reaches the worker."""
        session = self._session(tmp_path)
        with pytest.raises(FeatureAccessError, match="bounded JSON budget"):
            session(b'{"a":\n1}')


class _Stdio:
    """Stand in for the worker's binary standard streams."""

    def __init__(self, payload: bytes) -> None:
        """Bind the request lines and an empty response buffer."""
        self.buffer = io.BytesIO(payload)


class _Echo:
    """Answer each request with its own bytes."""

    def run(self, payload: bytes) -> bytes:
        """Return the request unchanged."""
        return payload


class TestWorkerProgram:
    """The worker program answers every request line on one input."""

    def test_answers_each_line_until_input_ends(self) -> None:
        """Two request lines produce two response lines; a one-shot request still works."""
        for payload, expected in (
            (b'{"a":1}\n{"b":2}\n', b'{"a":1}\n{"b":2}\n'),
            (b'{"a":1}', b'{"a":1}\n'),
        ):
            stdin, stdout = _Stdio(payload), _Stdio(b"")
            with (
                patch("applications.explore.command.FeastWorkerCommand", _Echo),
                patch.object(sys, "stdin", stdin),
                patch.object(sys, "stdout", stdout),
            ):
                assert main(["feast-worker"]) == 0
            assert stdout.buffer.getvalue() == expected
