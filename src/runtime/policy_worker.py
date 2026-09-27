"""Run one pure decision transition in a bounded spawned policy process."""

from __future__ import annotations

# standard library imports
import multiprocessing
import threading
import time
from multiprocessing.connection import Connection
from typing import Literal, cast

# project library imports
from research.observations import NumericField
from serialization import DomainCodec, WireRecord
from strategies import DecisionContext, DecisionPolicy, DecisionTransition
from telemetry import HealthMetric, HealthMetrics


class PolicyProcessFailure(RuntimeError):
    """Identify a failed pure policy call before its cohort can reach account admission."""

    def __init__(self, pid: int | None, reason: str) -> None:
        """Name the isolated process without classifying any account-command outcome."""
        self.pid = pid
        super().__init__(reason)


class _DecisionRequest(WireRecord, frozen=True):
    """Carry only a causal context and portable instance state to the child."""

    context: DecisionContext
    state: bytes

    def __post_init__(self) -> None:
        """Validate both typed inputs after crossing the process boundary."""
        if type(self.context) is not DecisionContext or type(self.state) is not bytes:
            raise TypeError("decision worker requires context and state bytes")
        self.context.__post_init__()


class _DecisionReply(WireRecord, frozen=True):
    """Return either one valid transition or one bounded policy failure."""

    transition: DecisionTransition | None
    error: str | None

    def __post_init__(self) -> None:
        """Reject ambiguous or malformed child outcomes."""
        if (self.transition is None) == (self.error is None):
            raise ValueError("decision worker reply requires one outcome")
        if self.transition is not None:
            self.transition.__post_init__()
        if self.error is not None and (type(self.error) is not str or not self.error):
            raise ValueError("decision worker error must be named")


class ProcessDecisionPolicy:
    """Delegate pure policy metadata locally and isolate each decision in a child.

    The parent retains policy checkpoints and economic admission. The child sees
    only the serialized context and prior state, and has no account capability.
    One synchronous decision occupies the single bounded pipe at a time.
    """

    def __init__(self, policy: DecisionPolicy, *, timeout_seconds: int = 2) -> None:
        """Start a spawn-picklable policy with a two-second maximum reply budget."""
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 2:
            raise ValueError("decision worker timeout must be one or two seconds")
        self._policy = policy
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
            args=(policy, child, self.health),
            name="decision-policy",
        )
        try:
            self._process.start()
        except Exception:
            parent.close()
            child.close()
            raise
        child.close()

    @property
    def identity(self) -> str:
        """Expose the selected policy's complete identity without child execution."""
        return self._policy.identity

    @property
    def output(self) -> Literal["target", "exposure", "order", "quote"]:
        """Expose the policy's declared intent family for parent admission."""
        return self._policy.output

    def admit(self, fields: tuple[NumericField, ...], prediction: NumericField | None) -> None:
        """Validate the selected feature signature in the parent."""
        self._policy.admit(fields, prediction)

    def initial_state(self) -> bytes:
        """Create a policy checkpoint in the parent-owned state store."""
        return self._policy.initial_state()

    def validate_state(self, state: bytes) -> None:
        """Reject a foreign checkpoint before sending any work to the child."""
        self._policy.validate_state(state)

    @property
    def pid(self) -> int | None:
        """Identify the spawned policy process for supervision."""
        return self._process.pid

    @property
    def is_alive(self) -> bool:
        """Expose whether the isolated policy can still accept a decision."""
        return self._process.is_alive()

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Return one typed transition or fail within the bounded response time."""
        context.__post_init__()
        self._policy.validate_state(state)
        request = _DecisionRequest(context=context, state=state)
        with self._lock:
            if not self.is_alive:
                raise PolicyProcessFailure(self.pid, "decision policy process unavailable")
            try:
                self._connection.send_bytes(self._codec.encode_json(request))
                if not self._connection.poll(self._timeout_seconds):
                    self.close()
                    raise PolicyProcessFailure(self.pid, "decision policy response timed out")
                reply = self._codec.decode_json(
                    self._connection.recv_bytes(16_777_216), _DecisionReply
                )
            except PolicyProcessFailure:
                raise
            except (BrokenPipeError, EOFError, OSError) as error:
                self.close()
                raise PolicyProcessFailure(
                    self.pid, "decision policy process unavailable"
                ) from error
            reply.__post_init__()
            if reply.error is not None:
                raise ValueError(f"decision policy rejected input: {reply.error}")
            if reply.transition is None:
                raise ValueError("decision worker omitted transition")
            return reply.transition

    def close(self) -> None:
        """Terminate and join the child, including a policy stuck in a decision."""
        self._connection.close()
        if self._process.is_alive():
            self._process.terminate()
        self._process.join(1)
        if self._process.is_alive():
            self._process.kill()
            self._process.join(1)

    @staticmethod
    def _heartbeat(health: HealthMetrics, stopped: threading.Event) -> None:
        """Publish liveness independently while the policy blocks or computes."""
        while not stopped.is_set():
            health.set(HealthMetric.HEARTBEAT, time.monotonic_ns())
            stopped.wait(0.1)

    @classmethod
    def _serve(
        cls,
        policy: DecisionPolicy,
        connection: Connection[bytes, bytes],
        health: HealthMetrics,
    ) -> None:
        """Own the child pipe and execute only the policy's pure decide method."""
        stopped = threading.Event()
        heartbeat = threading.Thread(target=cls._heartbeat, args=(health, stopped), daemon=True)
        heartbeat.start()
        codec = DomainCodec()
        try:
            while True:
                try:
                    payload = connection.recv_bytes(16_777_216)
                except EOFError:
                    return
                try:
                    request = codec.decode_json(payload, _DecisionRequest)
                    request.__post_init__()
                    transition = policy.decide(request.context, request.state)
                    transition.__post_init__()
                    reply = _DecisionReply(transition=transition, error=None)
                except Exception as error:
                    reply = _DecisionReply(
                        transition=None, error=str(error)[:256] or type(error).__name__
                    )
                connection.send_bytes(codec.encode_json(reply))
        finally:
            stopped.set()
            heartbeat.join(0.2)
            connection.close()
