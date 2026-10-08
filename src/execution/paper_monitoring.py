"""Project committed public-paper account facts into exact monitoring observations."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import (
    AccountLedger,
    AccountSnapshot,
    PaperAccountReport,
    PaperCurrencyResult,
    PaperScopeReport,
)
from execution.account_records import AccountPaperTrace, PortfolioCommit, TaggedOrder
from execution.monitoring import ExecutionMonitoring
from execution.paper_account import PaperAccount
from execution.records import OrderEvent, OrderState
from financial_units import ExactRatio, Money
from risk import SpotLimits
from serialization import DomainCodec
from telemetry import MonitoringEvent, MonitoringIdentity


class PaperMonitoring:
    """Observe durable paper state without taking execution or accounting authority."""

    def __init__(self, release: str | None = None) -> None:
        """Bind an optional installed release identity to the projection."""
        self.release = release
        self.execution = ExecutionMonitoring(release)

    def account(
        self,
        journal: PaperAccount,
        *,
        account_id: str,
        observed_at: datetime,
        sample: str,
        report: PaperAccountReport | None = None,
        source: str | None = None,
        venue: str | None = None,
        decisions: tuple[PortfolioCommit, ...] = (),
    ) -> tuple[MonitoringEvent, ...]:
        """Project one current account and its strategies, with optional marked report.

        The journal supplies present risk, orders and reservations. A supplied report
        supplies its own historical cutoff and exact native-currency economics; this
        method never derives an earlier journal snapshot from current mutable state.
        ``observed_at`` is the actual monitoring receipt clock, including imports.
        ``decisions`` must be outcomes selected for this account by the caller.
        """
        MonitoringEvent._require_utc(observed_at, field_name="paper monitoring receipt")
        MonitoringIdentity.check_text(sample)
        if journal.config.mode != "paper":
            raise ValueError("paper monitoring requires a paper account journal")
        account = next(
            (item for item in journal.accounts() if item.ledger.account_id == account_id), None
        )
        if account is None:
            raise ValueError("unknown paper account")
        tagged = tuple(item for item in journal.orders() if item.account_id == account_id)
        physical = (
            *(item.order for item in tagged if item.context is None),
            *(item.order for item in journal.net_orders() if item.account_id == account_id),
        )
        known_clocks = [
            journal.config.opening_at,
            *(posting.known_at for posting in account.ledger.postings),
            *(item.order.decision_at for item in tagged),
            *(order.decision_at for order in physical),
            *(trace.market.at for trace in journal.paper_traces(account_id)),
        ]
        if account.reconciled_at is not None:
            known_clocks.append(account.reconciled_at)
        if max(known_clocks) > observed_at:
            raise ValueError("current paper state follows monitoring receipt")
        if report is not None:
            report.__post_init__()
            declared_currencies = {
                amount.currency for amount in AccountLedger(account.ledger).snapshot().cash
            }
            report_currencies = {amount.currency for amount in report.account.snapshot.cash}
            if (
                report.account.snapshot.account_id != account_id
                or report.cutoff > observed_at
                or report_currencies != declared_currencies
            ):
                raise ValueError("paper report differs from account or monitoring receipt")
        if type(decisions) is not tuple or any(
            type(decision) is not PortfolioCommit for decision in decisions
        ):
            raise TypeError("paper decisions must be committed portfolio outcomes")
        for decision in decisions:
            decision.__post_init__()

        report_id = (
            hashlib.sha256(DomainCodec().encode_json(report)).hexdigest()
            if report is not None
            else None
        )
        account_context = self._context(
            account_id,
            state_epoch=str(account.recovery_generation),
            source=source,
            venue=venue,
        )
        events: list[MonitoringEvent] = []
        for event in self.execution.account(journal, observed_at=observed_at, sample=sample):
            if (
                event.context.account != account_id
                or event.name == "runtime.alert_delivery_failure"
            ):
                continue
            if report is not None and event.name.startswith(("account.cash.", "account.position.")):
                continue
            events.append(
                replace(event, context=replace(event.context, source=source, venue=venue))
            )

        events.append(
            self._state_event(
                account_context,
                "account.reconciliation_failed",
                sample,
                observed_at,
                "boolean",
                (
                    1
                    if account.fault == "account_break"
                    else 0
                    if account.reconciled_at is not None
                    else None
                ),
                missing_reason=(
                    "not_measured"
                    if account.fault != "account_break" and account.reconciled_at is None
                    else None
                ),
            )
        )
        events.append(
            self._state_event(
                account_context,
                "risk.admission_rejected",
                sample,
                observed_at,
                "boolean",
                # A strategy refused inside a committed batch is a rejection too.
                int(any(item.status == "rejected" or item.refused for item in decisions))
                if decisions
                else None,
                missing_reason=None if decisions else "not_measured",
            )
        )

        account_snapshot = AccountLedger(account.ledger).snapshot()
        events.extend(
            self._state_scope(
                account_context,
                account_snapshot,
                tagged,
                physical,
                observed_at=observed_at,
                sample=sample,
                include_balances=report is not None,
                include_order_status=False,
                instruments=journal.config.instruments,
            )
        )
        instance_ids = {
            limit.instance_id
            for limit in journal.config.budgets.instances
            if limit.account_id == account_id
        }
        instance_ids.update(item.instance_id for item in tagged)
        if report is not None:
            instance_ids.update(
                item.snapshot.instance_id
                for item in report.instances
                if item.snapshot.instance_id is not None
            )
        for instance_id in sorted(instance_ids):
            context = self._context(
                account_id,
                strategy=instance_id,
                state_epoch=str(account.recovery_generation),
                source=source,
                venue=venue,
            )
            owned = tuple(item for item in tagged if item.instance_id == instance_id)
            events.extend(
                self._state_scope(
                    context,
                    AccountLedger(account.ledger).snapshot(instance_id),
                    owned,
                    tuple(item.order for item in owned),
                    observed_at=observed_at,
                    sample=sample,
                    include_balances=True,
                    include_order_status=True,
                    instruments=journal.config.instruments,
                )
            )

        if report is None:
            for context, snapshot in (
                (account_context, account_snapshot),
                *(
                    (
                        self._context(
                            account_id,
                            strategy=instance_id,
                            state_epoch=str(account.recovery_generation),
                            source=source,
                            venue=venue,
                        ),
                        AccountLedger(account.ledger).snapshot(instance_id),
                    )
                    for instance_id in sorted(instance_ids)
                ),
            ):
                events.extend(self._missing_report(context, snapshot, observed_at, sample))
        else:
            events.extend(
                self._report_scope(
                    account_context, report.account, report, report_id, observed_at, sample
                )
            )
            reported_instances: set[str] = set()
            for scope in report.instances:
                report_instance_id = scope.snapshot.instance_id
                if report_instance_id is None:
                    raise AssertionError("validated paper instance has no identity")
                reported_instances.add(report_instance_id)
                context = self._context(
                    account_id,
                    strategy=report_instance_id,
                    state_epoch=str(account.recovery_generation),
                    source=source,
                    venue=venue,
                )
                events.extend(
                    self._report_scope(context, scope, report, report_id, observed_at, sample)
                )
            for instance_id in sorted(instance_ids - reported_instances):
                context = self._context(
                    account_id,
                    strategy=instance_id,
                    state_epoch=str(account.recovery_generation),
                    source=source,
                    venue=venue,
                )
                events.extend(
                    self._report_scope(
                        context,
                        self._unposted_scope(report, instance_id),
                        report,
                        report_id,
                        observed_at,
                        sample,
                    )
                )
        return tuple(events)

    def trace(
        self,
        trace: AccountPaperTrace,
        *,
        observed_at: datetime,
        source: str | None = None,
        venue: str | None = None,
        children: tuple[TaggedOrder, ...] = (),
    ) -> tuple[MonitoringEvent, ...]:
        """Project one newly committed trace once at its actual monitoring receipt.

        Callers retain the returned envelope for byte-identical replay. Rebuilding a
        past trace at a later time would invent a new monitoring receipt and is not
        a valid replay of that envelope.
        """
        trace.__post_init__()
        MonitoringEvent._require_utc(observed_at, field_name="paper trace receipt")
        if trace.market.at > observed_at:
            raise ValueError("paper trace availability follows monitoring receipt")
        if type(children) is not tuple or any(
            type(child) is not TaggedOrder or child.account_id != trace.account_id
            for child in children
        ):
            raise ValueError("paper trace children must belong to its account")
        context = self._context(
            trace.account_id, source=source, venue=trace.scenario.venue if venue is None else venue
        )
        events: list[MonitoringEvent] = []
        for event in trace.physical_events:
            events.append(self._lifecycle(context, event, trace, observed_at))
        if trace.rejected_event is not None:
            events.append(
                self._lifecycle(
                    context, trace.rejected_event, trace, observed_at, kind="paper_match_failed"
                )
            )
        owners = {child.order.identity: child.instance_id for child in children}
        for event in trace.child_fill_events:
            owner = owners.get(event.order_id)
            if owner is None:
                if children:
                    raise ValueError("paper trace fill has no supplied strategy owner")
                continue
            strategy_context = replace(
                context,
                scope=f"account:{trace.account_id}:strategy:{owner}",
                strategy=owner,
            )
            events.append(self._lifecycle(strategy_context, event, trace, observed_at))
            if event.fill is None:
                raise AssertionError("validated paper child event has no fill")
            instrument = str(event.fill.quantity.dimension.instrument_id)
            for target in (context, strategy_context):
                events.append(
                    self._historical_event(
                        replace(
                            target,
                            instrument=instrument,
                            order=event.order_id,
                            fill=event.fill.identity,
                            dataset=trace.input_sha256,
                        ),
                        f"execution.event.fill_quantity.{instrument}",
                        event.fill.identity,
                        event.at,
                        observed_at,
                        event.fill.quantity.dimension.kind.value,
                        Fraction(event.fill.quantity.value),
                        clock_quality="modeled",
                    )
                )
        return tuple(events)

    def _state_scope(
        self,
        context: MonitoringIdentity,
        snapshot: AccountSnapshot,
        tagged: tuple[TaggedOrder, ...],
        orders: tuple[OrderState, ...],
        *,
        observed_at: datetime,
        sample: str,
        include_balances: bool,
        include_order_status: bool,
        instruments: tuple[SpotLimits, ...],
    ) -> tuple[MonitoringEvent, ...]:
        """Summarize current owned fills and reserved child exposure once per sample."""
        events = [
            self._state_event(
                context, "execution.orders", sample, observed_at, "count", len(orders)
            ),
            self._state_event(
                context, "execution.fills", sample, observed_at, "count", len(snapshot.fill_ids)
            ),
        ]
        if include_order_status:
            for name, value in (
                ("execution.open_orders", sum(not order.is_terminal for order in orders)),
                ("execution.uncertain", sum(order.status == "unknown" for order in orders)),
                ("execution.rejected", sum(order.status == "rejected" for order in orders)),
                (
                    "execution.cancel_pending",
                    sum(order.cancel_requested and not order.is_terminal for order in orders),
                ),
            ):
                events.append(self._state_event(context, name, sample, observed_at, "count", value))
        if include_balances:
            for cash in snapshot.cash:
                events.append(
                    self._state_event(
                        context,
                        f"account.cash.{cash.currency.code}",
                        f"{sample}:cash:{cash.currency.code}",
                        observed_at,
                        cash.currency.code,
                        Fraction(cash.value),
                    )
                )
            for limits in instruments:
                dimension = limits.maximum.dimension
                instrument = str(dimension.instrument_id)
                position = next(
                    (item for item in snapshot.positions if item.dimension == dimension), None
                )
                events.append(
                    self._state_event(
                        replace(context, instrument=instrument),
                        f"account.position.{instrument}",
                        f"{sample}:position:{hashlib.sha256(instrument.encode()).hexdigest()[:16]}",
                        observed_at,
                        dimension.kind.value,
                        Fraction(0) if position is None else Fraction(position.value),
                    )
                )
        for limits in instruments:
            dimension = limits.maximum.dimension
            instrument = str(dimension.instrument_id)
            pending = sum(
                (
                    Fraction(item.order.remaining.value)
                    for item in tagged
                    if not item.order.is_terminal and item.order.remaining.dimension == dimension
                ),
                Fraction(0),
            )
            events.append(
                self._state_event(
                    replace(context, instrument=instrument),
                    f"execution.pending_quantity.{instrument}",
                    f"{sample}:pending:{hashlib.sha256(instrument.encode()).hexdigest()[:16]}",
                    observed_at,
                    dimension.kind.value,
                    pending,
                )
            )
        for cash in snapshot.cash:
            currency = cash.currency
            pending_fee = sum(
                (
                    Fraction(item.order.maximum_fee.value - item.order.paid_fee.value)
                    for item in tagged
                    if not item.order.is_terminal and item.order.maximum_fee.currency == currency
                ),
                Fraction(0),
            )
            events.append(
                self._state_event(
                    context,
                    f"execution.pending_fee.{currency.code}",
                    f"{sample}:pending_fee:{currency.code}",
                    observed_at,
                    currency.code,
                    pending_fee,
                )
            )
        return tuple(events)

    def _report_scope(
        self,
        context: MonitoringIdentity,
        scope: PaperScopeReport,
        report: PaperAccountReport,
        report_id: str | None,
        observed_at: datetime,
        sample: str,
    ) -> tuple[MonitoringEvent, ...]:
        """Publish report-owned cumulative economics without a second cost debit."""
        if report_id is None:
            raise AssertionError("report scope requires a content identity")
        report_context = replace(context, dataset=report_id)
        report_sample = f"{sample}:report:{report_id[:16]}"
        events = [
            self._historical_event(
                report_context,
                "paper.gas_applicable",
                report_sample,
                report.cutoff,
                observed_at,
                "boolean",
                int(report.gas_policy.applicable),
            ),
            self._historical_event(
                report_context,
                "paper.mark_max_age_seconds",
                report_sample,
                report.cutoff,
                observed_at,
                "seconds",
                Fraction(report.max_mark_age_us, 1_000_000),
            ),
        ]
        for index, result in enumerate(scope.currencies):
            cash = scope.snapshot.cash[index]
            fees = scope.snapshot.fees[index]
            rebates = scope.snapshot.rebates[index]
            gross = (
                Fraction(result.net_pnl.value)
                + Fraction(fees.value)
                - Fraction(rebates.value)
                + Fraction(result.slippage.value)
            )
            for name, value in (
                ("paper.cash", cash.value),
                ("paper.inventory_value", result.position_value.value),
                ("paper.fees", fees.value),
                ("paper.rebates", rebates.value),
                ("paper.slippage", result.slippage.value),
                ("paper.gross_pnl", gross),
                ("paper.net_pnl", result.net_pnl.value),
                ("paper.nav", result.nav.value),
            ):
                events.append(
                    self._historical_event(
                        report_context,
                        f"{name}.{result.currency.code}",
                        f"{report_sample}:{result.currency.code}",
                        report.cutoff,
                        observed_at,
                        result.currency.code,
                        Fraction(value),
                    )
                )
        for position in scope.positions:
            instrument = str(position.position.dimension.instrument_id)
            age = report.cutoff - position.mark.available_at
            microseconds = (age.days * 86_400 + age.seconds) * 1_000_000 + age.microseconds
            events.append(
                self._historical_event(
                    replace(report_context, instrument=instrument),
                    f"paper.mark_age_seconds.{instrument}",
                    f"{report_sample}:{hashlib.sha256(instrument.encode()).hexdigest()[:16]}",
                    report.cutoff,
                    observed_at,
                    "seconds",
                    Fraction(microseconds, 1_000_000),
                )
            )
        return tuple(events)

    @staticmethod
    def _unposted_scope(report: PaperAccountReport, instance_id: str) -> PaperScopeReport:
        """Represent a reporter-omitted instance with no postings at its cutoff."""
        zeroes = tuple(
            Money(value=Decimal(0), currency=cash.currency) for cash in report.account.snapshot.cash
        )
        return PaperScopeReport(
            snapshot=AccountSnapshot(
                account_id=report.account.snapshot.account_id,
                instance_id=instance_id,
                cash=zeroes,
                positions=(),
                fees=zeroes,
                rebates=zeroes,
                transfers=zeroes,
                fill_ids=(),
                posting_ids=(),
            ),
            positions=(),
            currencies=tuple(
                PaperCurrencyResult(
                    currency=zero.currency,
                    position_value=zero,
                    nav=zero,
                    net_pnl=zero,
                    slippage=zero,
                )
                for zero in zeroes
            ),
        )

    def _missing_report(
        self,
        context: MonitoringIdentity,
        snapshot: AccountSnapshot,
        observed_at: datetime,
        sample: str,
    ) -> tuple[MonitoringEvent, ...]:
        """Represent unavailable valuation and gas policy without synthetic zeroes."""
        events = [
            self._state_event(
                context,
                "paper.gas_applicable",
                sample,
                observed_at,
                "boolean",
                None,
                missing_reason="report_unavailable",
            )
        ]
        for cash, fees, rebates in zip(snapshot.cash, snapshot.fees, snapshot.rebates, strict=True):
            for name, value in (
                ("paper.cash", cash.value),
                ("paper.fees", fees.value),
                ("paper.rebates", rebates.value),
            ):
                events.append(
                    self._state_event(
                        context,
                        f"{name}.{cash.currency.code}",
                        f"{sample}:{cash.currency.code}",
                        observed_at,
                        cash.currency.code,
                        Fraction(value),
                    )
                )
            for name in (
                "paper.inventory_value",
                "paper.slippage",
                "paper.gross_pnl",
                "paper.net_pnl",
                "paper.nav",
            ):
                events.append(
                    self._state_event(
                        context,
                        f"{name}.{cash.currency.code}",
                        f"{sample}:{cash.currency.code}",
                        observed_at,
                        cash.currency.code,
                        None,
                        missing_reason="report_unavailable",
                    )
                )
        return tuple(events)

    def _lifecycle(
        self,
        context: MonitoringIdentity,
        event: OrderEvent,
        trace: AccountPaperTrace,
        observed_at: datetime,
        *,
        kind: str | None = None,
    ) -> MonitoringEvent:
        """Keep source availability and modeled lifecycle timing distinct from receipt."""
        return self._historical_event(
            replace(
                context,
                order=event.order_id,
                fill=None if event.fill is None else event.fill.identity,
                dataset=trace.input_sha256,
            ),
            f"execution.event.{event.kind if kind is None else kind}",
            event.identity,
            event.at,
            observed_at,
            "count",
            1,
            clock_quality="modeled",
        )

    def _context(
        self,
        account_id: str,
        *,
        strategy: str | None = None,
        state_epoch: str | None = None,
        source: str | None = None,
        venue: str | None = None,
    ) -> MonitoringIdentity:
        """Keep account and strategy observations in independently queryable scopes."""
        return MonitoringIdentity(
            scope=(
                f"account:{account_id}"
                if strategy is None
                else f"account:{account_id}:strategy:{strategy}"
            ),
            mode="paper",
            release=self.release,
            account=account_id,
            strategy=strategy,
            source=source,
            venue=venue,
            state_epoch=state_epoch,
        )

    @staticmethod
    def _state_event(
        context: MonitoringIdentity,
        name: str,
        sample: str,
        at: datetime,
        units: str,
        value: int | Fraction | None,
        *,
        missing_reason: str | None = None,
    ) -> MonitoringEvent:
        """Encode one current exact scalar at the real monitoring observation."""
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
    def _historical_event(
        context: MonitoringIdentity,
        name: str,
        sample: str,
        at: datetime,
        recorded_at: datetime,
        units: str,
        value: int | Fraction,
        *,
        clock_quality: Literal["observed", "modeled", "unknown"] = "observed",
    ) -> MonitoringEvent:
        """Preserve event/availability clocks and the actual monitoring receipt."""
        return MonitoringEvent(
            context=context,
            name=name,
            version="1",
            sample=sample,
            at=at,
            available_at=at,
            recorded_at=recorded_at,
            units=units,
            value=ExactRatio.from_fraction(Fraction(value)),
            clock_quality=clock_quality,
        )
