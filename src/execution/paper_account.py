"""Describe the account operations consumed by public-paper orchestration."""

from __future__ import annotations

# standard library imports
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Protocol

# project library imports
from configuration import AccountConfiguration, PaperExecutionScenario
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


class PaperAccount(Protocol):
    """Keep signed remote commands and local journal calls under one owned contract."""

    @property
    def config(self) -> AccountConfiguration:
        """Expose the exact account configuration bound by the operating target."""
        ...

    @property
    def paper_owner(self) -> PaperOwner | None:
        """Expose the claimed worker generation without granting new authority."""
        ...

    def accounts(self) -> tuple[AccountView, ...]:
        """Read current account ledgers and controls."""
        ...

    def account_statuses(self) -> tuple[AccountStatus, ...]:
        """Read each account's operating phase and blocks without its ledger."""
        ...

    def orders(self) -> tuple[TaggedOrder, ...]:
        """Read current attributable child orders."""
        ...

    def net_orders(self) -> tuple[NetOrder, ...]:
        """Read current physical paper orders."""
        ...

    def paper_restore_quarantined(self) -> bool:
        """Expose historical-copy quarantine without authorizing resumption."""
        ...

    def paper_activations(self) -> tuple[PaperActivation, ...]:
        """Read retained disabled manifests and separate authority."""
        ...

    def paper_reductions(self) -> tuple[PaperReductionResult, ...]:
        """Read requests without interpreting admission as liquidation."""
        ...

    def paper_trace_page(self, account_id: str | None = None, *, after: int = -1) -> PaperTracePage:
        """Read one count- and byte-bounded page of committed traces after a history position."""
        ...

    def iter_paper_traces(
        self, account_id: str | None = None, *, after: int = -1
    ) -> Iterator[AccountPaperTrace]:
        """Yield committed traces after a position in commit order, one page at a time."""
        ...

    def latest_paper_traces(self, account_id: str) -> tuple[AccountPaperTrace, ...]:
        """Read the newest committed trace of each instrument bound to the account."""
        ...

    def paper_trace_history(self) -> HistoryDigest:
        """Read the committed trace history's count and hash chain."""
        ...

    def export_paper_traces(self, destination: Path, account_id: str | None = None) -> int:
        """Publish committed traces as one JSON array checked against the trace history."""
        ...

    def paper_trace(self, account_id: str, market_identity: str) -> AccountPaperTrace | None:
        """Read the account's committed or failed trace of one market identity, if any."""
        ...

    def valuation(self, instrument: Dimension) -> AccountQuote | None:
        """Read the latest observed valuation quote of one instrument, if any."""
        ...

    def paper_report_facts(
        self, account_id: str
    ) -> tuple[tuple[AccountPaperFill, ...], tuple[AccountPaperCost, ...]]:
        """Project effective fills and correction-aware costs from the account owner."""
        ...

    def checkpoint(self, instance_id: str) -> bytes | None:
        """Read the atomically committed strategy continuation."""
        ...

    def portfolio_batch(self, identity: str) -> PortfolioBatch | None:
        """Read original portfolio input for exact retry validation."""
        ...

    def portfolio_residuals(self, account_id: str) -> tuple[PortfolioResidual, ...]:
        """Read pending quantities still covered by reservations."""
        ...

    def bind_paper_scenario(self, account_id: str, scenario: PaperExecutionScenario) -> None:
        """Verify the immutable matching assumptions."""
        ...

    def advance_paper(self, at: datetime) -> None:
        """Settle modelled cancellations, releases and arrivals due strictly before ``at``."""
        ...

    def apply_public_market(
        self, account_id: str, market: PaperMarket, scenario: PaperExecutionScenario
    ) -> PaperMarketOutcome:
        """Observe and, in paper mode, match one eligible book under the worker fence.

        One transaction resolves the market's identity against all history first: an
        exact retry returns the saved outcome without effects, and a reused identity
        with other input is refused.
        """
        ...

    def coordinate(self, batch: PortfolioBatch) -> PortfolioCommit:
        """Commit independent risk admission and policy checkpoints together."""
        ...

    def observe(self, quote: AccountQuote) -> None:
        """Retain an independently observed valuation price."""
        ...

    def reconcile(self, observation: AccountObservation) -> bool:
        """Compare supplied independent facts without clearing protective controls."""
        ...

    def block(self, account_id: str, reason: str) -> None:
        """Apply an independent durable block without claiming cancellation."""
        ...

    def control(self, request: AccountControl) -> AccountControlResult:
        """Apply stop/fault/cancel separately from a generation claim."""
        ...
