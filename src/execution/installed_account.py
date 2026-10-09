"""Route public-paper account requests through the verified installed execution runner."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import socket
import struct
import subprocess  # nosec B404  # [owner=execution; rationale=Bounded signed launcher uses explicit argv without a shell; expires=2027-03-01]
import threading
from collections import OrderedDict
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

# third party library imports
import msgspec

# project library imports
from configuration import AccountConfiguration, PaperExecutionScenario
from execution.account_commands import (
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountResponseProjection,
)
from execution.account_records import (
    AccountControl,
    AccountControlResult,
    AccountObservation,
    AccountPaperCost,
    AccountPaperFill,
    AccountPaperTrace,
    AccountQuote,
    AccountStatus,
    AccountView,
    HistoryDigest,
    NetOrder,
    PaperMarketOutcome,
    PaperTracePage,
    PortfolioBatch,
    PortfolioCommit,
    PortfolioResidual,
    TaggedOrder,
)
from execution.account_reduction import PaperReductionResult
from execution.paper import PaperMarket
from execution.paper_authority import PaperActivation, PaperOwner
from financial_units import Dimension
from serialization import DomainCodec, DurableLines, WireRecord


class InstalledPaperAccount:
    """Translate typed public input operations into fenced signed account commands.

    The target runs only its admitted execution/contracts wheels. The caller may
    collect public inputs and evaluate reference policies, but cannot override
    signed configuration, journal, release identity or account risk. Requests are
    retained before dispatch. A failed/uncertain command is never retried here;
    inspect the same journal and reuse its original identity during recovery.

    Each command waits at most ``command_seconds(action)``: 300 seconds for
    ``backup`` and ``restore``, which copy, hash and verify the whole journal, and
    30 seconds for every other action. The signed launcher keeps its own bound (the
    signed service life plus 60 seconds, 180 seconds if undeclared), so the shorter
    of the two applies. A timeout ends only the wait: the launched command may still
    complete, so its outcome is uncertain. When the launcher's bound expires first, it
    ends the account command, possibly part-way or after publication, and exits
    non-zero: that ``RuntimeError`` is uncertain too, not a clean refusal.
    """

    _whole_journal_actions = frozenset({"backup", "restore"})

    def __init__(
        self,
        *,
        config: AccountConfiguration,
        launcher: Path,
        target: Path,
        policy: Path,
        requests: Path,
        paper_owner: PaperOwner | None = None,
    ) -> None:
        """Bind an absolute governance executable, trusted target and retained requests."""
        config.__post_init__()
        if any(not path.is_absolute() for path in (launcher, target, policy, requests)):
            raise ValueError("installed paper paths must be absolute")
        if paper_owner is not None:
            paper_owner.__post_init__()
        self.config, self.paper_owner = config, paper_owner
        self.launcher, self.target, self.policy, self.requests = launcher, target, policy, requests
        self._codec = DomainCodec()

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Retain one exact command and return only a successful validated response.

        Raises:
            RuntimeError: The signed runner rejected the command or ended it at its own
                bound (an uncertain outcome); no retry is made.
            subprocess.TimeoutExpired: Outcome is uncertain; inspect before recovery.
        """
        request.__post_init__()
        payload = self._codec.encode_json(request)
        self.requests.mkdir(parents=True, exist_ok=True)
        request_path = self.requests / f"{hashlib.sha256(payload).hexdigest()}.json"
        try:
            with request_path.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if request_path.read_bytes() != payload:
                raise ValueError("retained paper request changed") from None
        result = subprocess.run(  # nosec B603  # [owner=execution; rationale=Caller selects a trusted absolute launcher with fixed operation arguments; expires=2027-03-01]
            [
                str(self.launcher),
                "run",
                "--target",
                str(self.target),
                "--policy",
                str(self.policy),
                "--",
                "account",
                "--request",
                str(request_path),
            ],
            capture_output=True,
            check=False,
            timeout=self.command_seconds(request.action),
        )
        attempt = uuid4().hex
        receipt = self.requests / f"{request_path.stem}.{attempt}.result.json"
        if result.returncode != 0:
            (self.requests / f"{request_path.stem}.{attempt}.stderr").write_bytes(result.stderr)
            raise RuntimeError(
                f"installed paper command failed ({result.returncode}); inspect retained request"
            )
        # The governance command emits the application's JSON response verbatim.
        decoded = self._codec.decode_json(result.stdout, AccountExecutionResult)
        receipt.write_bytes(result.stdout)
        return decoded

    @classmethod
    def command_seconds(cls, action: str) -> int:
        """Return how long one command of ``action`` is awaited before it is uncertain."""
        return 300 if action in cls._whole_journal_actions else 30

    def _inspect(
        self,
        *,
        account_id: str | None = None,
        instance: str | None = None,
        batch: str | None = None,
        market: str | None = None,
        instrument: Dimension | None = None,
        projection: AccountResponseProjection = "full",
    ) -> AccountExecutionResult:
        """Query fresh state without replaying any execution operation."""
        return self.execute(
            AccountExecutionRequest(
                action="inspect",
                account_id=account_id,
                query_instance=instance,
                query_batch=batch,
                query_market=market,
                query_instrument=instrument,
                projection=projection,
            )
        )

    def accounts(self) -> tuple[AccountView, ...]:
        """Read current ledgers and controls from installed account state."""
        return self._inspect(projection="accounts").accounts

    def account_statuses(self) -> tuple[AccountStatus, ...]:
        """Read each installed account's operating phase and blocks without its ledger."""
        return self._inspect(projection="statuses").account_statuses

    def orders(self) -> tuple[TaggedOrder, ...]:
        """Read attributable child commitments from installed state."""
        return self._inspect(projection="orders").orders

    def net_orders(self) -> tuple[NetOrder, ...]:
        """Read physical simulated orders from installed state."""
        return self._inspect(projection="net_orders").net_orders

    def paper_restore_quarantined(self) -> bool:
        """Expose historical snapshot status from the signed target."""
        return self._inspect(projection="quarantine").paper_restore_quarantined

    def paper_activations(self) -> tuple[PaperActivation, ...]:
        """Inspect disabled deployments and separate operator grants."""
        return self._inspect(projection="paper_activations").paper_activations

    def paper_reductions(self) -> tuple[PaperReductionResult, ...]:
        """Read admitted/rejected reduction requests without claiming fills."""
        return self._inspect(projection="reductions").paper_reductions

    def paper_trace_page(self, account_id: str | None = None, *, after: int = -1) -> PaperTracePage:
        """Read one bounded page of committed traces after a position from installed state."""
        page = self.execute(
            AccountExecutionRequest(
                action="inspect", account_id=account_id, query_after=after, projection="traces"
            )
        ).paper_trace_page
        if page is None or page.after != after:
            raise ValueError("installed paper response lacks the requested trace page")
        return page

    def iter_paper_traces(
        self, account_id: str | None = None, *, after: int = -1
    ) -> Iterator[AccountPaperTrace]:
        """Yield installed committed traces after a position, one bounded page at a time."""
        while True:
            page = self.paper_trace_page(account_id, after=after)
            yield from page.traces
            if page.next_after is None:
                return
            after = page.next_after

    def latest_paper_traces(self, account_id: str) -> tuple[AccountPaperTrace, ...]:
        """Read each bound instrument's newest committed trace from installed state."""
        return self._inspect(account_id=account_id, projection="monitoring").paper_traces

    def paper_trace_history(self) -> HistoryDigest:
        """Read the installed trace history's count and hash chain."""
        history = self._inspect(projection="trace_history").paper_trace_history
        if history is None:
            raise ValueError("installed paper response lacks the trace history")
        return history

    def export_paper_traces(self, destination: Path, account_id: str | None = None) -> int:
        """Have the signed runner publish committed traces, checked against its history."""
        exported = self.execute(
            AccountExecutionRequest(
                action="export_traces",
                account_id=account_id,
                export_path=str(destination),
                projection="operation",
            )
        ).exported_traces
        if exported is None:
            raise ValueError("installed paper response lacks the trace export count")
        return exported

    def paper_trace(self, account_id: str, market_identity: str) -> AccountPaperTrace | None:
        """Read the account's trace of one market identity from installed state."""
        traces = self._inspect(
            account_id=account_id, market=market_identity, projection="market_trace"
        ).paper_traces
        if len(traces) > 1 or any(
            trace.account_id != account_id or trace.market.identity != market_identity
            for trace in traces
        ):
            raise ValueError("installed paper response differs from its market trace query")
        return traces[0] if traces else None

    def valuation(self, instrument: Dimension) -> AccountQuote | None:
        """Read the latest observed valuation quote of one instrument from installed state."""
        return self._inspect(instrument=instrument, projection="valuation").valuation

    def paper_report_facts(
        self, account_id: str
    ) -> tuple[tuple[AccountPaperFill, ...], tuple[AccountPaperCost, ...]]:
        """Read correction-aware facts scoped by the installed account owner."""
        result = self._inspect(account_id=account_id, projection="facts")
        return result.paper_fills, result.paper_costs

    def checkpoint(self, instance_id: str) -> bytes | None:
        """Read the last atomically committed policy continuation."""
        return self._inspect(instance=instance_id, projection="checkpoint").checkpoint

    def portfolio_batch(self, identity: str) -> PortfolioBatch | None:
        """Read exact prior input to resolve a retry without creating another decision."""
        return self._inspect(batch=identity, projection="saved_batch").saved_batch

    def portfolio_residuals(self, account_id: str) -> tuple[PortfolioResidual, ...]:
        """Keep every unroutable child attributable and reserved."""
        return tuple(
            item
            for item in self._inspect(projection="residuals").residuals
            if item.account_id == account_id
        )

    def bind_paper_scenario(self, account_id: str, scenario: PaperExecutionScenario) -> None:
        """Verify existing assumptions through the installed command boundary."""
        self.execute(
            AccountExecutionRequest(
                action="bind_paper_scenario",
                account_id=account_id,
                scenario=scenario,
                paper_owner=self.paper_owner,
                projection="operation",
            )
        )

    def apply_public_market(
        self, account_id: str, market: PaperMarket, scenario: PaperExecutionScenario
    ) -> PaperMarketOutcome:
        """Observe and match one finite eligible book under the current durable owner."""
        result = self.execute(
            AccountExecutionRequest(
                action="public_market",
                account_id=account_id,
                market=market,
                scenario=scenario,
                paper_owner=self.paper_owner,
                projection="operation",
            )
        )
        outcome = result.public_market
        if (
            outcome is None
            or outcome.account_id != account_id
            or outcome.market_identity != market.identity
        ):
            raise ValueError("installed paper response lacks this market's outcome")
        return outcome

    def coordinate(self, batch: PortfolioBatch) -> PortfolioCommit:
        """Commit the selected policy cohort through installed risk and reservations."""
        result = self.execute(
            AccountExecutionRequest(
                action="coordinate",
                batch=batch,
                paper_owner=self.paper_owner,
                projection="operation",
            )
        )
        if result.portfolio is None:
            raise ValueError("installed paper response lacks portfolio result")
        return result.portfolio

    def observe(self, quote: AccountQuote) -> None:
        """Record eligible observed valuation without creating an order."""
        self.execute(
            AccountExecutionRequest(
                action="quote", quote=quote, paper_owner=self.paper_owner, projection="operation"
            )
        )

    def reconcile(self, observation: AccountObservation) -> bool:
        """Compare supplied independent facts through installed accounting."""
        result = self.execute(
            AccountExecutionRequest(
                action="reconcile",
                observation=observation,
                paper_owner=self.paper_owner,
                projection="operation",
            )
        )
        if result.reconciled is None:
            raise ValueError("installed paper response lacks reconciliation result")
        return result.reconciled

    def block(self, account_id: str, reason: str) -> None:
        """Persist an independent protection without retrying committed work."""
        self.execute(
            AccountExecutionRequest(
                action="block",
                account_id=account_id,
                reason=reason,
                paper_owner=self.paper_owner,
                projection="operation",
            )
        )

    def control(self, request: AccountControl) -> AccountControlResult:
        """Preserve explicit stop/fault/cancel semantics in the installed account."""
        result = self.execute(
            AccountExecutionRequest(action="control", control=request, paper_owner=self.paper_owner)
        )
        if result.control is None:
            raise ValueError("installed paper response lacks control result")
        return result.control


class SentRequest(WireRecord, frozen=True):
    """Name one socket command's exact payload by its action, SHA-256 and length.

    The owner service retains the payload's exact bytes as one line of its
    ``service-requests`` log before any effect, so a client record of the payload's
    identity joins it to those bytes without keeping a second copy. A command the
    service never retained had no effect.
    """

    action: str
    sha256: str
    bytes: int

    def __post_init__(self) -> None:
        """Require an action, a lowercase SHA-256 digest and a positive length."""
        if (
            type(self.action) is not str
            or not self.action
            or type(self.sha256) is not str
            or len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
            or type(self.bytes) is not int
            or self.bytes <= 0
        ):
            raise ValueError("invalid sent account request identity")


class SocketPaperAccount(InstalledPaperAccount):
    """Use the same typed PaperAccount operations through one claimed local owner.

    Each adapter retains its commands in one append-only log, ``<requests>/<log>.jsonl``.
    A command's ``request`` record, under a fresh ``attempt`` identity, is fsynced
    before it is sent; it names the exact payload by ``SentRequest``, whose bytes the
    owner service retains before applying them. The ``result`` or ``error`` record
    follows the response. A result whose exact bytes this log already holds, among
    its latest distinct results, is recorded as ``repeated_result``: their SHA-256,
    naming that earlier ``result`` record, so a repeated read is kept once. An
    attempt without any of these records has an uncertain outcome: a timeout or
    lost response, which this adapter never resubmits.
    """

    _maximum_bytes = 1_048_576
    _remembered_results = 64

    def __init__(
        self,
        *,
        config: AccountConfiguration,
        socket_path: Path,
        requests: Path,
        paper_owner: PaperOwner,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Bind one private socket and exact owner for all inherited operations."""
        config.__post_init__()
        paper_owner.__post_init__()
        if (
            not socket_path.is_absolute()
            or not requests.is_absolute()
            or not 0 < timeout_seconds <= 30
            or paper_owner.account_id not in {item.account_id for item in config.accounts}
        ):
            raise ValueError("socket paper account requires absolute paths and a bounded owner")
        self.config, self.paper_owner = config, paper_owner
        self._owner = paper_owner
        self.socket_path, self.requests = socket_path, requests
        self.timeout_seconds = timeout_seconds
        self._codec = DomainCodec()
        self._log = DurableLines(requests / f"{uuid4().hex}.jsonl")
        self._log_lock = threading.Lock()
        # Digests of the latest distinct results this log holds, oldest first.
        self._results: OrderedDict[str, None] = OrderedDict()

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Send one retained command and decode one response without retrying."""
        request.__post_init__()
        if request.paper_owner not in (None, self._owner):
            raise ValueError("paper_owner_stale_or_absent")
        payload = self._codec.encode_json(request)
        if not 0 < len(payload) <= self._maximum_bytes:
            raise ValueError("socket paper request exceeds one MiB")
        attempt = uuid4().hex
        sent = SentRequest(
            action=request.action,
            sha256=hashlib.sha256(payload).hexdigest(),
            bytes=len(payload),
        )
        self._record(attempt, "request", sent, sync=True)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout_seconds)
            connection.connect(str(self.socket_path))
            connection.sendall(struct.pack("!I", len(payload)) + payload)
            header = self._read_exact(connection, 5)
            status, length = header[:1], int.from_bytes(header[1:], "big")
            if not 0 < length <= self._maximum_bytes:
                raise ValueError("socket paper response exceeds one MiB")
            response = self._read_exact(connection, length)
        if status == b"\x01":
            # The service truncates a reason by bytes, so it may end mid-character.
            reason = response.decode("utf-8", errors="replace")
            self._record(attempt, "error", reason, sync=False)
            raise RuntimeError(f"paper account service rejected request: {reason}")
        if status != b"\x00":
            raise ValueError("invalid paper account service response")
        decoded = self._codec.decode_json(response, AccountExecutionResult)
        self._record_result(attempt, response)
        return decoded

    def _record_result(self, attempt: str, response: bytes) -> None:
        """Keep a result's bytes once in this log, recording an exact repeat by digest."""
        digest = hashlib.sha256(response).hexdigest()
        with self._log_lock:
            if digest in self._results:
                line = self._codec.encode_json({"attempt": attempt, "repeated_result": digest})
                self._log.append(line, sync=False)
                self._results.move_to_end(digest)
                return
            line = self._codec.encode_json({"attempt": attempt, "result": msgspec.Raw(response)})
            self._log.append(line, sync=False)
            self._results[digest] = None
            if len(self._results) > self._remembered_results:
                self._results.popitem(last=False)

    def _record(self, attempt: str, kind: str, value: SentRequest | str, *, sync: bool) -> None:
        """Append one attributable record of an attempt to this adapter's log."""
        line = self._codec.encode_json({"attempt": attempt, kind: value})
        with self._log_lock:
            self._log.append(line, sync=sync)

    def shutdown(self, control: AccountControl) -> AccountExecutionResult:
        """Stop the account through the owner service, then end its socket loop."""
        if control.kind != "stop" or control.account_id != self._owner.account_id:
            raise ValueError("paper service shutdown requires matching stop control")
        return self.execute(
            AccountExecutionRequest(
                action="shutdown_paper", control=control, paper_owner=self._owner
            )
        )

    @staticmethod
    def _read_exact(connection: socket.socket, count: int) -> bytes:
        """Reject a truncated response without resubmitting its request."""
        pieces: list[bytes] = []
        remaining = count
        while remaining:
            part = connection.recv(remaining)
            if not part:
                raise ConnectionError("paper account service response ended early")
            pieces.append(part)
            remaining -= len(part)
        return b"".join(pieces)
