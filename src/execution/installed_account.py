"""Route public-paper account requests through the verified installed execution runner."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import socket
import struct
import subprocess  # nosec B404 [owner=execution; rationale=Bounded signed launcher uses explicit argv without a shell; expires=2027-03-01]
from pathlib import Path
from uuid import uuid4

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
    AccountView,
    NetOrder,
    PortfolioBatch,
    PortfolioCommit,
    PortfolioResidual,
    TaggedOrder,
)
from execution.account_reduction import PaperReductionResult
from execution.paper import PaperMarket
from execution.paper_authority import PaperActivation, PaperOwner
from serialization import DomainCodec


class InstalledPaperAccount:
    """Translate typed public input operations into fenced signed account commands.

    The target runs only its admitted execution/contracts wheels. The caller may
    collect public inputs and evaluate reference policies, but cannot override
    signed configuration, journal, release identity or account risk. Requests are
    retained before dispatch. A failed/uncertain command is never retried here;
    inspect the same journal and reuse its original identity during recovery.
    """

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
            RuntimeError: The signed runner rejected the command; no retry is made.
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
        result = subprocess.run(  # nosec B603 [owner=execution; rationale=Caller selects a trusted absolute launcher with fixed operation arguments; expires=2027-03-01]
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
            timeout=30,
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

    def _inspect(
        self,
        *,
        account_id: str | None = None,
        instance: str | None = None,
        batch: str | None = None,
        market: str | None = None,
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
                projection=projection,
                paper_owner=self.paper_owner if projection == "market_membership" else None,
            )
        )

    def accounts(self) -> tuple[AccountView, ...]:
        """Read current ledgers and controls from installed account state."""
        return self._inspect(projection="accounts").accounts

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

    def paper_traces(self, account_id: str | None = None) -> tuple[AccountPaperTrace, ...]:
        """Read original public quotes and committed modeled effects."""
        return self._inspect(account_id=account_id, projection="traces").paper_traces

    def paper_market_seen(self, account_id: str, market_identity: str) -> bool:
        """Inspect fresh account-scoped membership under the bound installed owner."""
        result = self._inspect(
            account_id=account_id, market=market_identity, projection="market_membership"
        )
        if type(result.market_seen) is not bool:
            raise ValueError("installed paper response lacks Boolean market membership")
        return result.market_seen

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

    def match_public_market(
        self, account_id: str, market: PaperMarket, scenario: PaperExecutionScenario
    ) -> AccountPaperTrace:
        """Match one finite eligible quote under the current durable owner."""
        result = self.execute(
            AccountExecutionRequest(
                action="paper_market",
                account_id=account_id,
                market=market,
                scenario=scenario,
                paper_owner=self.paper_owner,
                projection="operation",
            )
        )
        if result.matched_market is None:
            raise ValueError("installed paper response lacks matching result")
        return result.matched_market

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


class SocketPaperAccount(InstalledPaperAccount):
    """Use the same typed PaperAccount operations through one claimed local owner.

    Requests are retained before sending. A timeout or lost response is an
    uncertain outcome and this adapter never resubmits the operation.
    """

    _maximum_bytes = 1_048_576

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

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Send one retained command and decode one response without retrying."""
        request.__post_init__()
        if request.paper_owner not in (None, self._owner):
            raise ValueError("paper_owner_stale_or_absent")
        payload = self._codec.encode_json(request)
        if not 0 < len(payload) <= self._maximum_bytes:
            raise ValueError("socket paper request exceeds one MiB")
        self.requests.mkdir(parents=True, exist_ok=True)
        path = self.requests / f"{hashlib.sha256(payload).hexdigest()}.{uuid4().hex}.json"
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
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
            path.with_suffix(".error.txt").write_bytes(response)
            raise RuntimeError(
                f"paper account service rejected request: {response.decode('utf-8')}"
            )
        if status != b"\x00":
            raise ValueError("invalid paper account service response")
        decoded = self._codec.decode_json(response, AccountExecutionResult)
        path.with_suffix(".result.json").write_bytes(response)
        return decoded

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
