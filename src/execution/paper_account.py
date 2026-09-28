"""Describe the account operations consumed by public-paper orchestration."""

from __future__ import annotations

# standard library imports
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

    def paper_traces(self, account_id: str | None = None) -> tuple[AccountPaperTrace, ...]:
        """Read durable modeled effects for an account."""
        ...

    def paper_market_seen(self, account_id: str, market_identity: str) -> bool:
        """Read fresh committed/failed membership under the current bound account owner."""
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

    def match_public_market(
        self, account_id: str, market: PaperMarket, scenario: PaperExecutionScenario
    ) -> AccountPaperTrace:
        """Match one bounded eligible book under the durable worker fence."""
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
