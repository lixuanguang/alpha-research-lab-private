"""Run explicit, non-submitting paper account commands against the durable OMS."""

from __future__ import annotations

# standard library imports
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Literal

# project library imports
from accounting import LedgerBalance, LedgerState
from configuration import PaperConfiguration
from execution import (
    AccountReservations,
    OrderDecision,
    OrderEvent,
    OrderState,
    PaperMarket,
    PaperMatcher,
    PaperOrderJournal,
    StepCommit,
)
from financial_units import Money, Price, Quantity
from risk import SpotLimits
from serialization import DomainCodec, WireRecord

type PaperAction = Literal["inspect", "decide", "replace", "market", "event", "cancel", "reconcile"]


class PaperExecutionRequest(WireRecord, frozen=True):
    """Select one identified paper account operation without executable authority."""

    action: PaperAction
    identity: str
    checkpoint: bytes = b""
    decision: OrderDecision | None = None
    reference: Price | None = None
    market: PaperMarket | None = None
    event: OrderEvent | None = None
    order_id: str | None = None
    at: datetime | None = None
    expected_cash: Money | None = None
    expected_holding: Quantity | None = None
    open_order_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Reject mixed command payloads before opening the durable account."""
        if self.action not in (
            "inspect",
            "decide",
            "replace",
            "market",
            "event",
            "cancel",
            "reconcile",
        ):
            raise ValueError("unknown paper execution action")
        if (
            type(self.identity) is not str
            or not self.identity
            or type(self.checkpoint) is not bytes
        ):
            raise ValueError("paper request requires identity and immutable checkpoint bytes")
        if self.action == "inspect":
            if self._has_payload():
                raise ValueError("paper inspection cannot mutate an account")
        elif self.action == "decide":
            if (
                self.decision is None
                or self.market is not None
                or self.event is not None
                or self.order_id is not None
                or self.at is not None
                or self.expected_cash is not None
                or self.expected_holding is not None
                or self.open_order_ids
            ):
                raise ValueError(
                    "paper decision requires only its intent, reference and checkpoint"
                )
            self.decision.__post_init__()
            if self.reference is not None:
                self.reference.model_copy()
        elif self.action == "replace":
            if (
                self.decision is None
                or not self.order_id
                or self.market is not None
                or self.event is not None
                or self.at is not None
                or self.expected_cash is not None
                or self.expected_holding is not None
                or self.open_order_ids
            ):
                raise ValueError(
                    "paper replacement requires old order ID, intent, reference and checkpoint"
                )
            self.decision.__post_init__()
            if self.reference is not None:
                self.reference.model_copy()
        elif self.action == "market":
            if self.market is None or self._has_other_than("market"):
                raise ValueError("paper market request has mixed payloads")
            self.market.__post_init__()
        elif self.action == "event":
            if (
                self.event is None
                or self.identity != self.event.identity
                or self._has_other_than("event")
            ):
                raise ValueError("paper order event identity or payload is inconsistent")
            self.event.__post_init__()
        elif self.action == "cancel":
            if not self.order_id or self.at is None or self._has_other_than("cancel"):
                raise ValueError("paper cancellation requires order ID and UTC time")
            self._require_utc(self.at, field_name="paper cancel time")
        elif self.action == "reconcile":
            if (
                self.expected_cash is None
                or self.expected_holding is None
                or self._has_other_than("reconcile")
            ):
                raise ValueError("paper reconciliation requires cash, holdings and open IDs")
            self.expected_cash.model_copy()
            self.expected_holding.model_copy()
            if len(set(self.open_order_ids)) != len(self.open_order_ids):
                raise ValueError("paper reconciliation repeats an open order ID")

    def _has_payload(self) -> bool:
        """Report whether any action-specific field was supplied."""
        return (
            self.checkpoint != b""
            or self.decision is not None
            or self.reference is not None
            or self.market is not None
            or self.event is not None
            or self.order_id is not None
            or self.at is not None
            or self.expected_cash is not None
            or self.expected_holding is not None
            or bool(self.open_order_ids)
        )

    def _has_other_than(self, selected: Literal["market", "event", "cancel", "reconcile"]) -> bool:
        """Keep each mutation's wire representation single-purpose."""
        return (
            self.checkpoint != b""
            or self.decision is not None
            or self.reference is not None
            or (selected != "market" and self.market is not None)
            or (selected != "event" and self.event is not None)
            or (selected != "cancel" and (self.order_id is not None or self.at is not None))
            or (
                selected != "reconcile"
                and (
                    self.expected_cash is not None
                    or self.expected_holding is not None
                    or bool(self.open_order_ids)
                )
            )
        )


class PaperExecutionResult(WireRecord, frozen=True):
    """Report a complete local account snapshot with explicit no-submission proof."""

    action: PaperAction
    account: str
    instance: str
    mode: Literal["paper", "shadow"]
    binding_identity: str
    qualification: Literal["fixture", "referenced"]
    orders: tuple[OrderState, ...]
    balance: LedgerBalance
    reservations: AccountReservations
    last_event_sequence: int
    blocked_reason: str | None
    step: StepCommit | None = None
    order: OrderState | None = None
    reconciled: bool | None = None
    submission_attempted: bool = False

    def __post_init__(self) -> None:
        """Keep CLI output attributable and incapable of implying venue activity."""
        if (
            not self.account
            or not self.instance
            or len(self.binding_identity) != 64
            or type(self.last_event_sequence) is not int
            or self.last_event_sequence < 0
            or self.submission_attempted is not False
        ):
            raise ValueError("invalid paper execution result")
        self.balance.__post_init__()
        self.reservations.__post_init__()


class PaperExecutionApplication:
    """Compose an installed paper request with its independent durable account."""

    def __init__(self) -> None:
        """Reuse the exact public wire codec across configuration, requests and output."""
        self._codec = DomainCodec()

    def run(
        self,
        *,
        config_path: Path,
        journal_path: Path,
        instance: str,
        request_path: Path | None,
    ) -> PaperExecutionResult:
        """Apply one non-executable request and return the resulting account snapshot."""
        if type(instance) is not str or not instance:
            raise ValueError("paper execution requires an instance identity")
        config_bytes = config_path.read_bytes()
        if len(config_bytes) > 1_048_576:
            raise ValueError("paper configuration exceeds one MiB")
        config = self._codec.decode_json(config_bytes, PaperConfiguration)
        config.__post_init__()
        if request_path is None:
            request = PaperExecutionRequest(action="inspect", identity="inspect")
            request_bytes = b""
        else:
            request_bytes = request_path.read_bytes()
            if len(request_bytes) > 1_048_576:
                raise ValueError("paper request exceeds one MiB")
            request = self._codec.decode_json(request_bytes, PaperExecutionRequest)
        request.__post_init__()
        binding_identity = hashlib.sha256(
            self._codec.encode_json(("installed-paper-execution-v1", config.identity, instance))
        ).hexdigest()
        limits = SpotLimits(
            maximum=config.maximum,
            lot=config.lot,
            tick=config.tick,
            product="spot",
        )
        ledger_state = LedgerState(
            initial_cash=config.initial_cash, dimension=config.maximum.dimension
        )
        with PaperOrderJournal(
            journal_path,
            account=config.account,
            instance=instance,
            binding_identity=binding_identity,
            mode=config.mode,
            limits=limits,
            ledger_state=ledger_state,
        ) as journal:
            if request.action == "inspect":
                return self._snapshot(request.action, journal)
            epoch = journal.claim(f"alpha-execute:{os.getpid()}:{instance}")
            try:
                step: StepCommit | None = None
                order: OrderState | None = None
                reconciled: bool | None = None
                if request.action == "decide":
                    if request.decision is None:
                        raise ValueError("paper decision is missing")
                    step = journal.commit_step(
                        epoch=epoch,
                        step_id=f"decision:{request.identity}",
                        checkpoint=request.checkpoint,
                        decision=request.decision,
                        reference=request.reference,
                        maximum_fee=config.maximum_fee,
                        input_bytes=request_bytes,
                        result_bytes=self._codec.encode_json(request.decision),
                    )
                elif request.action == "replace":
                    if request.decision is None or request.order_id is None:
                        raise ValueError("paper replacement details are missing")
                    step = journal.replace(
                        epoch=epoch,
                        old_order_id=request.order_id,
                        step_id=f"replace:{request.identity}",
                        checkpoint=request.checkpoint,
                        decision=request.decision,
                        reference=request.reference,
                        maximum_fee=config.maximum_fee,
                        input_bytes=request_bytes,
                        result_bytes=self._codec.encode_json(request.decision),
                    )
                elif request.action == "market":
                    if request.market is None or config.mode != "paper":
                        raise ValueError("market matching is available only in paper mode")
                    step_id = f"market:{request.identity}"
                    journal.has_step(step_id, request_bytes)
                    PaperMatcher(
                        journal,
                        fee_rate=config.fee_rate,
                        lot=config.lot,
                        scenario=config.execution,
                    ).match(request.market, epoch=epoch)
                    step = journal.commit_step(
                        epoch=epoch,
                        step_id=step_id,
                        checkpoint=journal.checkpoint() or b"",
                        decision=None,
                        reference=None,
                        maximum_fee=config.maximum_fee,
                        input_bytes=request_bytes,
                        result_bytes=self._codec.encode_json(request.market),
                    )
                elif request.action == "event":
                    if request.event is None:
                        raise ValueError("paper order event is missing")
                    order = journal.apply_event(epoch=epoch, event=request.event)
                elif request.action == "cancel":
                    if request.order_id is None or request.at is None:
                        raise ValueError("paper cancel details are missing")
                    order = journal.request_cancel(
                        epoch=epoch,
                        order_id=request.order_id,
                        event_id=request.identity,
                        at=request.at,
                    )
                elif request.action == "reconcile":
                    if request.expected_cash is None or request.expected_holding is None:
                        raise ValueError("paper reconciliation snapshot is missing")
                    reconciled = journal.reconcile_account(
                        epoch=epoch,
                        expected_cash=request.expected_cash,
                        expected_holding=request.expected_holding,
                        open_order_ids=request.open_order_ids,
                    )
                return self._snapshot(
                    request.action, journal, step=step, order=order, reconciled=reconciled
                )
            finally:
                journal.release(epoch)

    @staticmethod
    def _snapshot(
        action: PaperAction,
        journal: PaperOrderJournal,
        *,
        step: StepCommit | None = None,
        order: OrderState | None = None,
        reconciled: bool | None = None,
    ) -> PaperExecutionResult:
        """Bind an operation outcome to current exact account and journal state."""
        events = journal.events()
        return PaperExecutionResult(
            action=action,
            account=journal.account,
            instance=journal.instance,
            mode=journal.mode,
            binding_identity=journal.binding_identity,
            qualification=journal.qualification,
            orders=journal.orders(),
            balance=journal.ledger_balance(),
            reservations=journal.reservations(),
            last_event_sequence=0 if not events else events[-1].sequence,
            blocked_reason=journal.blocked_reason(),
            step=step,
            order=order,
            reconciled=reconciled,
        )
