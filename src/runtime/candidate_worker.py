"""Run one candidate step in process or in a bounded spawned candidate process."""

from __future__ import annotations

# standard library imports
import multiprocessing
import threading
import time
from multiprocessing.connection import Connection
from typing import cast

# project library imports
from research.observations import DecisionInputs
from runtime.candidates import CandidateCheckpoint, CandidateSession, CandidateStep, LoadedCandidate
from serialization import DomainCodec, WireRecord
from telemetry import HealthMetric, HealthMetrics


class CandidateProcessFailure(RuntimeError):
    """Identify a failed candidate step before its cohort can reach account admission."""

    def __init__(self, pid: int | None, reason: str) -> None:
        """Name the isolated process without classifying any account-command outcome."""
        self.pid = pid
        super().__init__(reason)


class _StepRequest(WireRecord, frozen=True):
    """Carry only causal inputs and the committed continuation to the child."""

    inputs: DecisionInputs
    checkpoint: CandidateCheckpoint | None

    def __post_init__(self) -> None:
        """Validate both typed inputs after crossing the process boundary."""
        if type(self.inputs) is not DecisionInputs:
            raise TypeError("candidate worker requires decision inputs")
        self.inputs.__post_init__()
        if self.checkpoint is not None:
            self.checkpoint.__post_init__()


class _StepReply(WireRecord, frozen=True):
    """Return either one valid candidate step or one bounded candidate failure."""

    step: CandidateStep | None
    error: str | None

    def __post_init__(self) -> None:
        """Reject ambiguous or malformed child outcomes."""
        if (self.step is None) == (self.error is None):
            raise ValueError("candidate worker reply requires one outcome")
        if self.step is not None:
            self.step.__post_init__()
        if self.error is not None and (type(self.error) is not str or not self.error):
            raise ValueError("candidate worker error must be named")


class LocalCandidateExecutor:
    """Evaluate a candidate step in the calling process.

    A ``None`` checkpoint starts fresh state; a committed checkpoint continues it.
    """

    def __init__(self, loaded: LoadedCandidate) -> None:
        """Bind one admitted candidate placement."""
        self.loaded = loaded

    def step(self, inputs: DecisionInputs, checkpoint: CandidateCheckpoint | None) -> CandidateStep:
        """Stage one feature/model/policy transition from committed state."""
        return CandidateSession(self.loaded, checkpoint, continuing=True).evaluate_inputs(inputs)


class ProcessCandidateExecutor:
    """Isolate every candidate step in a spawned child with a bounded reply time.

    The parent keeps the committed continuation and all economic admission. The
    child sees only the serialized inputs and prior checkpoint and has no account
    capability. One synchronous step occupies the single bounded pipe at a time.
    """

    def __init__(self, loaded: LoadedCandidate, *, timeout_seconds: int = 2) -> None:
        """Start a spawn-picklable candidate with a two-second maximum reply budget."""
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 2:
            raise ValueError("candidate worker timeout must be one or two seconds")
        self.loaded = loaded
        self._timeout_seconds = timeout_seconds
        self._codec = DomainCodec()
        self._lock = threading.Lock()
        self.health = HealthMetrics()
        context = multiprocessing.get_context("spawn")
        parent, child = cast(
            "tuple[Connection[bytes, bytes], Connection[bytes, bytes]]",
            context.Pipe(duplex=True),
        )
        self._connection: Connection[bytes, bytes] = parent
        self._process = context.Process(
            target=self._serve,
            args=(loaded, child, self.health),
            name="candidate-step",
        )
        try:
            self._process.start()
        except Exception:
            parent.close()
            child.close()
            raise
        child.close()

    @property
    def pid(self) -> int | None:
        """Identify the spawned candidate process for supervision."""
        return self._process.pid

    @property
    def is_alive(self) -> bool:
        """Expose whether the isolated candidate can still accept a step."""
        return self._process.is_alive()

    def step(self, inputs: DecisionInputs, checkpoint: CandidateCheckpoint | None) -> CandidateStep:
        """Return one typed step or fail within the bounded response time."""
        request = _StepRequest(inputs=inputs, checkpoint=checkpoint)
        request.__post_init__()
        with self._lock:
            if not self.is_alive:
                raise CandidateProcessFailure(self.pid, "candidate process unavailable")
            try:
                self._connection.send_bytes(self._codec.encode_json(request))
                if not self._connection.poll(self._timeout_seconds):
                    self.close()
                    raise CandidateProcessFailure(self.pid, "candidate step response timed out")
                reply = self._codec.decode_json(self._connection.recv_bytes(16_777_216), _StepReply)
            except CandidateProcessFailure:
                raise
            except (BrokenPipeError, EOFError, OSError) as error:
                self.close()
                raise CandidateProcessFailure(self.pid, "candidate process unavailable") from error
            reply.__post_init__()
            if reply.error is not None:
                raise ValueError(f"candidate rejected input: {reply.error}")
            if reply.step is None:
                raise ValueError("candidate worker omitted its step")
            return reply.step

    def close(self) -> None:
        """Terminate and join the child, including a candidate stuck in a step."""
        self._connection.close()
        if self._process.is_alive():
            self._process.terminate()
        self._process.join(1)
        if self._process.is_alive():
            self._process.kill()
            self._process.join(1)

    @staticmethod
    def _heartbeat(health: HealthMetrics, stopped: threading.Event) -> None:
        """Publish liveness independently while the candidate blocks or computes."""
        while not stopped.is_set():
            health.set(HealthMetric.HEARTBEAT, time.monotonic_ns())
            stopped.wait(0.1)

    @classmethod
    def _serve(
        cls,
        loaded: LoadedCandidate,
        connection: Connection[bytes, bytes],
        health: HealthMetrics,
    ) -> None:
        """Own the child pipe and execute only pure candidate steps."""
        stopped = threading.Event()
        heartbeat = threading.Thread(target=cls._heartbeat, args=(health, stopped), daemon=True)
        heartbeat.start()
        codec = DomainCodec()
        executor = LocalCandidateExecutor(loaded)
        try:
            while True:
                try:
                    payload = connection.recv_bytes(16_777_216)
                except EOFError:
                    return
                try:
                    request = codec.decode_json(payload, _StepRequest)
                    request.__post_init__()
                    step = executor.step(request.inputs, request.checkpoint)
                    step.__post_init__()
                    reply = _StepReply(step=step, error=None)
                except Exception as error:
                    reply = _StepReply(step=None, error=str(error)[:256] or type(error).__name__)
                connection.send_bytes(codec.encode_json(reply))
        finally:
            stopped.set()
            heartbeat.join(0.2)
            connection.close()
