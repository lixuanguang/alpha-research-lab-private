"""Describe complete strategy lineage and explicit physical netting compatibility."""

from __future__ import annotations

# standard library imports
import re
from typing import Literal

# project library imports
from serialization import WireRecord


class PortfolioContext(WireRecord, frozen=True):
    """Retain intent ownership and the authority scopes that constrain netting.

    Strategy, revision, horizon and reason fields remain attributable but may
    differ across a compatible physical order. Portfolio, venue, settlement,
    risk bucket and authority must agree before sharing economic execution.
    """

    portfolio_id: str
    strategy_id: str
    model_revision: str
    config_revision: str
    horizon: str
    reason: str
    venue: str
    settlement: str
    risk_bucket: str
    authority_scope: str
    schema_version: Literal["portfolio-context-v1"] = "portfolio-context-v1"

    def __post_init__(self) -> None:
        """Reject missing or unbounded attribution and authority metadata."""
        if self.schema_version != "portfolio-context-v1":
            raise ValueError("unsupported portfolio context schema")
        for value in (
            self.portfolio_id,
            self.strategy_id,
            self.model_revision,
            self.config_revision,
            self.horizon,
            self.reason,
            self.venue,
            self.settlement,
            self.risk_bucket,
            self.authority_scope,
        ):
            if (
                type(value) is not str
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", value) is None
            ):
                raise ValueError("portfolio context requires bounded metadata")

    def compatible_with(self, other: PortfolioContext) -> bool:
        """Check the economic and permission scope shared by physical execution."""
        self.__post_init__()
        other.__post_init__()
        return (
            self.portfolio_id,
            self.venue,
            self.settlement,
            self.risk_bucket,
            self.authority_scope,
        ) == (
            other.portfolio_id,
            other.venue,
            other.settlement,
            other.risk_bucket,
            other.authority_scope,
        )
