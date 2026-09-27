"""Project durable execution state into bounded monitoring facts."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Mapping
from datetime import datetime, timedelta
from fractions import Fraction

# project library imports
from accounting import AccountLedger
from execution.account_records import TaggedOrder
from execution.account_reduction import PaperReductionResult
from execution.paper_account import PaperAccount
from execution.paper_authority import PaperActivation
from execution.records import StepCommit
from execution.venue_gateway import GatewayView
from financial_units import ExactRatio
from telemetry import MonitoringEvent, MonitoringIdentity


class ExecutionMonitoring:
    """Read account and venue state without changing admission or transport authority."""

    def __init__(self, release: str | None = None) -> None:
        """Bind an optional installed release fingerprint to projected facts."""
        self.release = release

    def account(
        self,
        journal: PaperAccount,
        *,
        observed_at: datetime,
        sample: str,
        admission: StepCommit | None = None,
        reconciled: bool | None = None,
        control_rejected: bool | None = None,
        alert_failures: Mapping[str, int] | None = None,
        alert_store_invalid: bool = False,
        operation_account_id: str | None = None,
    ) -> tuple[MonitoringEvent, ...]:
        """Project exact balances, independent blocks and physical order uncertainty."""
        MonitoringEvent._require_utc(observed_at, field_name="execution observation")
        accounts = journal.accounts()
        tagged = journal.orders()
        parents = journal.net_orders()
        activations = journal.paper_activations() if journal.config.mode == "paper" else ()
        reductions = journal.paper_reductions() if journal.config.mode == "paper" else ()
        paper_restore_quarantined = (
            journal.paper_restore_quarantined() if journal.config.mode == "paper" else False
        )
        events: list[MonitoringEvent] = []
        for account in accounts:
            account_id = account.ledger.account_id
            context = MonitoringIdentity(
                scope=f"account:{account_id}",
                mode=journal.config.mode,
                release=self.release,
                account=account_id,
                state_epoch=str(account.recovery_generation),
            )
            blocked = (
                account.phase != "running"
                or account.fault is not None
                or account.operator_block is not None
                or account.reconciled_at is None
            )
            events.append(
                self._event(context, "risk.blocked", sample, observed_at, "boolean", int(blocked))
            )
            if account.reconciled_at is None:
                events.append(
                    self._event(
                        context,
                        "account.reconciliation_age_seconds",
                        sample,
                        observed_at,
                        "seconds",
                        None,
                        missing_reason="not_reconciled",
                    )
                )
            elif account.reconciled_at > observed_at:
                events.append(
                    self._event(
                        context,
                        "account.reconciliation_age_seconds",
                        sample,
                        observed_at,
                        "seconds",
                        None,
                        missing_reason="future_reconciliation_time",
                    )
                )
            else:
                events.append(
                    self._event(
                        context,
                        "account.reconciliation_age_seconds",
                        sample,
                        observed_at,
                        "seconds",
                        self._seconds(observed_at - account.reconciled_at),
                    )
                )
            snapshot = AccountLedger(account.ledger).snapshot()
            for cash in snapshot.cash:
                events.append(
                    self._event(
                        context,
                        f"account.cash.{cash.currency.code}",
                        f"{sample}:{cash.currency.code}",
                        observed_at,
                        cash.currency.code,
                        Fraction(cash.value),
                    )
                )
            for limits in journal.config.instruments:
                dimension = limits.maximum.dimension
                instrument = str(dimension.instrument_id)
                position = next(
                    (item for item in snapshot.positions if item.dimension == dimension), None
                )
                events.append(
                    self._event(
                        MonitoringIdentity(
                            scope=context.scope,
                            mode=context.mode,
                            release=context.release,
                            account=account_id,
                            instrument=instrument,
                            state_epoch=context.state_epoch,
                        ),
                        f"account.position.{instrument}",
                        f"{sample}:{hashlib.sha256(instrument.encode()).hexdigest()[:16]}",
                        observed_at,
                        dimension.kind.value,
                        Fraction(0) if position is None else Fraction(position.value),
                    )
                )
            physical = (
                *(
                    item.order
                    for item in tagged
                    if item.account_id == account_id and item.context is None
                ),
                *(item.order for item in parents if item.account_id == account_id),
            )
            for name, value in (
                ("execution.open_orders", sum(not order.is_terminal for order in physical)),
                ("execution.uncertain", sum(order.status == "unknown" for order in physical)),
                ("execution.rejected", sum(order.status == "rejected" for order in physical)),
                (
                    "execution.cancel_pending",
                    sum(order.cancel_requested and not order.is_terminal for order in physical),
                ),
            ):
                events.append(self._event(context, name, sample, observed_at, "count", value))
            if reconciled is not None and account_id == operation_account_id:
                events.append(
                    self._event(
                        context,
                        "account.reconciliation_failed",
                        sample,
                        observed_at,
                        "boolean",
                        int(not reconciled),
                    )
                )
            if control_rejected is not None and account_id == operation_account_id:
                events.append(
                    self._event(
                        context,
                        "account.control_rejected",
                        sample,
                        observed_at,
                        "boolean",
                        int(control_rejected),
                    )
                )
            if admission is not None and account_id == operation_account_id:
                events.append(
                    self._event(
                        context,
                        "risk.admission_rejected",
                        sample,
                        observed_at,
                        "boolean",
                        int(admission.status == "rejected"),
                    )
                )
            events.append(
                self._event(
                    context,
                    "runtime.alert_delivery_failure",
                    sample,
                    observed_at,
                    "count",
                    None
                    if alert_store_invalid
                    else (0 if alert_failures is None else alert_failures.get(account_id, 0)),
                    missing_reason="alert_store_invalid" if alert_store_invalid else None,
                )
            )
            if journal.config.mode == "paper":
                activation = next(
                    (item for item in activations if item.deployment.account_id == account_id),
                    None,
                )
                events.extend(
                    self._paper_control_events(
                        context,
                        sample,
                        observed_at,
                        activation=activation,
                        reductions=tuple(
                            item for item in reductions if item.request.account_id == account_id
                        ),
                        account_orders=tuple(
                            item for item in tagged if item.account_id == account_id
                        ),
                        restore_quarantined=paper_restore_quarantined,
                    )
                )
        return tuple(events)

    @classmethod
    def _paper_control_events(
        cls,
        context: MonitoringIdentity,
        sample: str,
        observed_at: datetime,
        *,
        activation: PaperActivation | None,
        reductions: tuple[PaperReductionResult, ...],
        account_orders: tuple[TaggedOrder, ...],
        restore_quarantined: bool,
    ) -> tuple[MonitoringEvent, ...]:
        """Project retained paper deployment, authority, ownership and reduction state."""
        deployment_installed = activation is not None
        deployment_disabled = False if activation is None else not activation.deployment.enabled
        revoked_authorizations = () if activation is None else activation.revoked
        authorization = None if activation is None else activation.authorization
        authority_revoked = (
            authorization is not None and authorization.identity in revoked_authorizations
        )
        authority_expired = authorization is not None and observed_at >= authorization.expires_at
        authority_valid = (
            authorization is not None
            and authorization.identity not in revoked_authorizations
            and authorization.valid_from <= observed_at < authorization.expires_at
        )
        order_states = {item.order.identity: item.order for item in account_orders}
        accepted_order_ids = {
            order.identity
            for result in reductions
            if result.status == "accepted"
            for order in result.orders
        }
        return tuple(
            cls._event(context, name, sample, observed_at, units, value)
            for name, units, value in (
                ("paper.deployment_installed", "boolean", int(deployment_installed)),
                (
                    "paper.deployment_disabled",
                    "boolean",
                    int(deployment_disabled),
                ),
                ("paper.authority_present", "boolean", int(authorization is not None)),
                ("paper.authority_valid", "boolean", int(authority_valid)),
                ("paper.authority_expired", "boolean", int(authority_expired)),
                ("paper.authority_revoked", "boolean", int(authority_revoked)),
                (
                    "paper.owner_generation",
                    "generation",
                    0 if activation is None else activation.generation,
                ),
                ("paper.recovery_quarantined", "boolean", int(restore_quarantined)),
                (
                    "paper.reduction_accepted",
                    "count",
                    sum(result.status == "accepted" for result in reductions),
                ),
                (
                    "paper.reduction_rejected",
                    "count",
                    sum(result.status == "rejected" for result in reductions),
                ),
                (
                    "paper.reduction_unresolved",
                    "count",
                    sum(
                        order_id not in order_states or not order_states[order_id].is_terminal
                        for order_id in accepted_order_ids
                    ),
                ),
            )
        )

    def venue(
        self, gateway: GatewayView, *, observed_at: datetime, sample: str
    ) -> tuple[MonitoringEvent, ...]:
        """Project retained transport recovery and receipt state without request bytes."""
        MonitoringEvent._require_utc(observed_at, field_name="venue observation")
        context = MonitoringIdentity(
            scope=f"account:{gateway.account_id}",
            mode="venue_test",
            release=self.release,
            account=gateway.account_id,
            venue=gateway.venue,
        )
        events = [
            self._event(
                context,
                "execution.venue_recovery_required",
                sample,
                observed_at,
                "boolean",
                int(gateway.recovery_required),
            ),
            self._event(
                context,
                "execution.receipts",
                sample,
                observed_at,
                "count",
                gateway.receipt_count,
            ),
            self._event(
                context,
                "execution.dispatches",
                sample,
                observed_at,
                "count",
                len(gateway.dispatches),
            ),
        ]
        return tuple(events)

    @staticmethod
    def _event(
        context: MonitoringIdentity,
        name: str,
        sample: str,
        at: datetime,
        units: str,
        value: int | Fraction | None,
        *,
        missing_reason: str | None = None,
    ) -> MonitoringEvent:
        """Encode one exact scalar with a boundary observation clock."""
        return MonitoringEvent(
            context=context,
            name=name,
            version="1",
            sample=sample,
            at=at,
            available_at=at,
            recorded_at=at,
            units=units,
            value=None if value is None else ExactRatio.from_fraction(Fraction(value)),
            missing_reason=missing_reason,
        )

    @staticmethod
    def _seconds(duration: timedelta) -> Fraction:
        """Convert a nonnegative timedelta into exact seconds."""
        microseconds = (duration.days * 86_400 + duration.seconds) * 1_000_000
        return Fraction(microseconds + duration.microseconds, 1_000_000)
