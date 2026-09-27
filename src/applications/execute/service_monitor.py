"""Retain current service economics through existing exact reports and telemetry."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

# project library imports
from accounting import (
    AccountLedger,
    AttributedPaperFill,
    PaperAccountReporter,
    PaperCostEvidence,
    PaperCurrencyResult,
    PaperGasPolicy,
    PaperPositionMark,
    PaperScopeReport,
)
from configuration import AccountConfiguration, PaperServiceSource
from execution import (
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountPaperTrace,
    AccountView,
    ExecutionMonitoring,
    NetOrder,
    PaperActivation,
    PaperMarket,
    PaperMonitoring,
    PaperOwner,
    PaperReductionResult,
    SocketPaperAccount,
    TaggedOrder,
)
from serialization import DomainCodec
from telemetry import TelemetryStore


class _InspectedPaperAccount(SocketPaperAccount):
    """Serve monitoring reads from one immutable installed account inspection."""

    def __init__(
        self, config: AccountConfiguration, owner: PaperOwner, state: AccountExecutionResult
    ) -> None:
        """Retain only the definition and inspected result; no transport is available."""
        self.config = config
        self.paper_owner = owner
        self._state = state

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Refuse any command, including another diagnostic read."""
        raise RuntimeError("monitoring snapshot cannot execute account commands")

    def accounts(self) -> tuple[AccountView, ...]:
        """Return the account views from the same inspection."""
        return self._state.accounts

    def orders(self) -> tuple[TaggedOrder, ...]:
        """Return attributable orders from the same inspection."""
        return self._state.orders

    def net_orders(self) -> tuple[NetOrder, ...]:
        """Return physical orders from the same inspection."""
        return self._state.net_orders

    def paper_restore_quarantined(self) -> bool:
        """Return the inspected restore quarantine signal."""
        return self._state.paper_restore_quarantined

    def paper_activations(self) -> tuple[PaperActivation, ...]:
        """Return inspected deployment and authority records."""
        return self._state.paper_activations

    def paper_reductions(self) -> tuple[PaperReductionResult, ...]:
        """Return the inspected reduction outcomes."""
        return self._state.paper_reductions

    def paper_traces(self, account_id: str | None = None) -> tuple[AccountPaperTrace, ...]:
        """Keep trace reads within the inspected account scope."""
        return tuple(
            trace
            for trace in self._state.paper_traces
            if account_id is None or trace.account_id == account_id
        )


class PaperServiceMonitor:
    """Observe committed state without retrying economic work after diagnostic failure."""

    def __init__(self, root: Path) -> None:
        """Bind separate diagnostic storage with no authority to alter accounts."""
        self.root = root
        self.codec = DomainCodec()
        self.failures = 0
        self.last_error: str | None = None

    @staticmethod
    def _unposted_scope(ledger: AccountLedger, instance_id: str) -> PaperScopeReport:
        """Expose a configured instance with no postings as a validated zero scope."""
        snapshot = ledger.snapshot(instance_id)
        if (
            snapshot.positions
            or snapshot.fill_ids
            or snapshot.posting_ids
            or any(
                amount.value != 0
                for amounts in (
                    snapshot.cash,
                    snapshot.fees,
                    snapshot.rebates,
                    snapshot.transfers,
                )
                for amount in amounts
            )
        ):
            raise ValueError("unreported instance has account postings")
        return PaperScopeReport(
            snapshot=snapshot,
            positions=(),
            currencies=tuple(
                PaperCurrencyResult(
                    currency=cash.currency,
                    position_value=cash - cash,
                    nav=cash,
                    net_pnl=cash - cash,
                    slippage=cash - cash,
                )
                for cash in snapshot.cash
            ),
        )

    def sample(
        self,
        account: SocketPaperAccount,
        sources: tuple[PaperServiceSource, ...],
        markets: tuple[PaperMarket, ...],
    ) -> dict[str, object]:
        """Retain one independently timestamped account/strategy snapshot and telemetry.

        Diagnostic errors return visible status. Neither a failed report nor a
        failed telemetry write repeats a decision, matching operation or control.
        """
        observed = datetime.now(UTC)
        try:
            owner = account.paper_owner
            if owner is None:
                raise ValueError("monitoring requires an identified account owner")
            state = account.execute(
                AccountExecutionRequest(action="inspect", account_id=owner.account_id)
            )
            view = next(
                item for item in state.accounts if item.ledger.account_id == owner.account_id
            )
            cutoff = datetime.now(UTC)
            ledger = AccountLedger(view.ledger)
            open_dimensions = {position.dimension for position in ledger.snapshot().positions}
            report = PaperAccountReporter().build(
                view.ledger,
                cutoff=cutoff,
                max_mark_age=timedelta(microseconds=min(item.freshness_us for item in sources)),
                marks=tuple(
                    PaperPositionMark(identity=item.identity, available_at=item.at, price=item.bid)
                    for item in markets
                    if item.bid.per in open_dimensions
                ),
                fills=tuple(
                    AttributedPaperFill(
                        instance_id=item.instance_id, order_id=item.order_id, fill=item.fill
                    )
                    for item in state.paper_fills
                ),
                costs=tuple(
                    PaperCostEvidence(
                        source_fill_id=item.source_fill_id,
                        posting_id=item.posting_id,
                        amount=item.amount,
                    )
                    for item in state.paper_costs
                ),
                gas_policy=PaperGasPolicy(
                    scenario_id=hashlib.sha256(
                        self.codec.encode_json(tuple(item.scenario for item in sources))
                    ).hexdigest(),
                    applicable=False,
                    reason="; ".join(
                        sorted({item.scenario.gas_inapplicable_reason for item in sources})
                    ),
                ),
            )
            reported = {scope.snapshot.instance_id: scope for scope in report.instances}
            instances: tuple[dict[str, object], ...] = tuple(
                {
                    "instance_id": limit.instance_id,
                    "scope": reported.get(limit.instance_id)
                    or self._unposted_scope(ledger, limit.instance_id),
                    "orders": owned_orders,
                    "reservations": tuple(
                        item for item in owned_orders if not item.order.is_terminal
                    ),
                    "residuals": tuple(
                        item
                        for item in state.residuals
                        if item.account_id == owner.account_id
                        and item.instance_id == limit.instance_id
                    ),
                    "stopped": limit.instance_id in state.stopped_instances,
                }
                for limit in account.config.budgets.instances
                if limit.account_id == owner.account_id
                for owned_orders in (
                    tuple(
                        item
                        for item in state.orders
                        if item.account_id == owner.account_id
                        and item.instance_id == limit.instance_id
                    ),
                )
            )
            activation = next(
                (
                    item
                    for item in state.paper_activations
                    if item.deployment.account_id == owner.account_id
                ),
                None,
            )
            receipt = datetime.now(UTC)
            inspected = _InspectedPaperAccount(account.config, owner, state)
            events = (
                PaperMonitoring(owner.release_identity).account(
                    inspected,
                    account_id=owner.account_id,
                    observed_at=receipt,
                    sample=uuid4().hex,
                    report=report,
                )
                if account.config.mode == "paper"
                else ExecutionMonitoring(owner.release_identity).account(
                    inspected,
                    observed_at=receipt,
                    sample=uuid4().hex,
                )
            )
            snapshot: dict[str, object] = {
                "observed_at": receipt,
                "account": state,
                "account_view": view,
                "activation": activation,
                "report": report,
                "instances": instances,
                "heartbeat_is_freshness": False,
            }
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = self.root / f".{owner.account_id}.json"
            temporary.write_bytes(self.codec.encode_json(snapshot))
            temporary.replace(self.root / f"{owner.account_id}.json")
            TelemetryStore(self.root / "telemetry.sqlite3").append(events)
            return {
                "observed_at": receipt,
                "report": report,
                "account": view,
                "activation": activation,
                "instances": instances,
                "phase": view.phase,
                "status": "retained",
            }
        except Exception as error:
            self.failures += 1
            self.last_error = f"{type(error).__name__}: {error}"
            return {"observed_at": observed, "status": "failed", "error": self.last_error}
