"""Compose selected decision policies and normalized events on a shared paper account."""

from __future__ import annotations

# standard library imports
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Literal

# project library imports
from configuration import AccountConfiguration
from execution import (
    AccountJournal,
    AccountObservation,
    AccountQuote,
    AccountView,
    NetOrder,
    OrderEvent,
    PortfolioCommit,
    PortfolioResidual,
    TaggedOrder,
)
from runtime import SharedDecisionRuntime, SharedStrategyBinding, SharedStrategyInput
from serialization import WireRecord


class SharedPaperDecision(WireRecord, frozen=True):
    """Select one explicit cohort and its strictly later portfolio coordination cutoff."""

    identity: str
    at: datetime
    inputs: tuple[SharedStrategyInput, ...]
    crossing: Literal["reject", "internal_at_quote"] = "reject"

    def __post_init__(self) -> None:
        """Require typed selected inputs and an explicit compatible-cross policy."""
        self._require_utc(self.at, field_name="shared paper coordination")
        if (
            type(self.identity) is not str
            or not self.identity
            or type(self.inputs) is not tuple
            or not self.inputs
            or self.crossing not in ("reject", "internal_at_quote")
        ):
            raise ValueError("invalid shared paper decision")
        for item in self.inputs:
            if type(item) is not SharedStrategyInput:
                raise TypeError("shared paper decision requires SharedStrategyInput")
            item.__post_init__()
            if item.decision_at >= self.at:
                raise ValueError("coordination must follow every decision")


class SharedPaperResult(WireRecord, frozen=True):
    """Return exact tagged and physical state after a finite non-submitting event prefix."""

    accounts: tuple[AccountView, ...]
    children: tuple[TaggedOrder, ...]
    net_orders: tuple[NetOrder, ...]
    decisions: tuple[PortfolioCommit, ...]
    residuals: tuple[PortfolioResidual, ...] = ()
    submission_attempted: bool = False

    def __post_init__(self) -> None:
        """Validate the retained outcomes without asserting external qualification."""
        if self.submission_attempted is not False:
            raise ValueError("shared paper workflow cannot submit orders")
        if any(
            type(values) is not tuple
            for values in (
                self.accounts,
                self.children,
                self.net_orders,
                self.decisions,
                self.residuals,
            )
        ):
            raise TypeError("shared paper result requires immutable collections")
        for account in self.accounts:
            account.__post_init__()
        for child in self.children:
            child.__post_init__()
        for parent in self.net_orders:
            parent.__post_init__()
        for decision in self.decisions:
            decision.__post_init__()
        for residual in self.residuals:
            residual.__post_init__()


def run_shared_paper(
    config: AccountConfiguration,
    *,
    bindings: tuple[SharedStrategyBinding, ...],
    journal_path: Path,
    events: Iterable[AccountQuote | AccountObservation | SharedPaperDecision | OrderEvent],
) -> SharedPaperResult:
    """Run configured strategy decisions and normalized physical events through one journal.

    Applications inject the selected candidates and their causal source inputs;
    a decision whose candidates all pause commits nothing. Market marks and
    complete account observations are independent events. Physical fills are
    authored paper facts here; this workflow neither invents venue observations
    nor matches unobserved liquidity. Failures propagate with the durable journal
    intact, and reopening restores candidate continuation and reservations.
    Operator stop/restart uses the account CLI.
    """
    journal = AccountJournal(journal_path, config)
    runtime = SharedDecisionRuntime(journal, bindings)
    outcomes: list[PortfolioCommit] = []
    for event in events:
        if isinstance(event, AccountQuote):
            journal.observe(event)
        elif isinstance(event, AccountObservation):
            if not journal.reconcile(event):
                raise ValueError("shared paper account reconciliation failed")
        elif isinstance(event, SharedPaperDecision):
            event.__post_init__()
            outcome = runtime.evaluate(
                identity=event.identity,
                at=event.at,
                inputs=event.inputs,
                crossing=event.crossing,
            )
            if outcome is not None:
                outcomes.append(outcome)
        else:
            journal.apply_net_event(event)
    return SharedPaperResult(
        accounts=journal.accounts(),
        children=journal.orders(),
        net_orders=journal.net_orders(),
        decisions=tuple(outcomes),
        residuals=tuple(
            residual
            for account in journal.accounts()
            for residual in journal.portfolio_residuals(account.ledger.account_id)
        ),
    )
