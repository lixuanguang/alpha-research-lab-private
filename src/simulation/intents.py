"""Compose bounded offline decision intents from exact contracts and execution models."""

from __future__ import annotations

# standard library imports
from collections.abc import Iterable, Iterator
from datetime import datetime

# project library imports
from accounting import Ledger
from simulation.intent_contracts import IntentCostModel as IntentCostModel
from simulation.intent_contracts import IntentDecisionOutcome as IntentDecisionOutcome
from simulation.intent_contracts import IntentExecutionModel as IntentExecutionModel
from simulation.intent_contracts import IntentMarket as IntentMarket
from simulation.intent_contracts import IntentOrderOutcome as IntentOrderOutcome
from simulation.intent_contracts import IntentSimulationResult as IntentSimulationResult
from simulation.intent_contracts import IntentSimulationSpec as IntentSimulationSpec
from simulation.intent_contracts import IntentTrade as IntentTrade
from simulation.intent_contracts import LimitExecutionConfig as LimitExecutionConfig
from simulation.intent_execution import LimitOrderExecution as LimitOrderExecution
from simulation.intent_execution import SpotFeeModel as SpotFeeModel
from strategies import DecisionRecord


class IntentSimulation:
    """Validate explicit compatible collaborators and invoke one offline model."""

    def __init__(
        self,
        spec: IntentSimulationSpec,
        execution: IntentExecutionModel,
        costs: IntentCostModel,
        ledger: Ledger,
    ) -> None:
        """Bind independently selected account, execution and cost implementations."""
        spec.__post_init__()
        if (
            execution.identity != spec.execution_identity
            or costs.identity != spec.cost_identity
            or ledger.state.initial_cash != spec.initial_cash
            or ledger.state.dimension != spec.limits.maximum.dimension
            or ledger.state.fills
        ):
            raise ValueError("intent simulation collaborator identity or account mismatch")
        self.spec, self.execution, self.costs, self.ledger = spec, execution, costs, ledger

    def run(
        self,
        decisions: tuple[DecisionRecord, ...],
        market: Iterable[IntentMarket],
    ) -> IntentSimulationResult:
        """Require immutable decisions and an ordered market, then delegate to the model.

        The market is streamed: each row is validated as the model consumes it, and
        rows the model leaves unread are validated after it returns.
        """
        if type(decisions) is not tuple:
            raise TypeError("offline intent decisions require an immutable tuple")
        previous: datetime | None = None
        for decision in decisions:
            if type(decision) is not DecisionRecord:
                raise TypeError("offline input requires DecisionRecord")
            decision.__post_init__()
            if (
                decision.instance != self.spec.instance
                or decision.entity != self.spec.entity
                or not self.spec.start <= decision.at < self.spec.end
                or (previous is not None and decision.at <= previous)
            ):
                raise ValueError("decision identity, sample or chronological order mismatch")
            previous = decision.at
        admitted = self._admitted(market)
        result = self.execution.run(self.spec, self.costs, self.ledger, decisions, admitted)
        for _ in admitted:
            pass
        if type(result) is not IntentSimulationResult:
            raise TypeError("execution model requires IntentSimulationResult")
        result.__post_init__()
        if (
            result.spec != self.spec
            or tuple(outcome.decision for outcome in result.decisions) != decisions
            or result.ledger != self.ledger.state
        ):
            raise ValueError("execution result differs from injected sample, decisions or ledger")
        return result

    def _admitted(self, market: Iterable[IntentMarket]) -> Iterator[IntentMarket]:
        """Yield each market row after checking identity, sample and availability order."""
        seen: set[str] = set()
        previous_market: tuple[datetime, datetime] | None = None
        for row in market:
            if type(row) is not IntentMarket:
                raise TypeError("offline market input requires IntentMarket")
            row.__post_init__()
            if (
                row.source_identity != self.spec.source_identity
                or row.instrument != self.spec.entity
                or row.channel != "l2"
                or row.identity in seen
                or not self.spec.start <= row.source_at <= self.spec.end
                or row.available_at > self.spec.end
                or (row.source_at == self.spec.end and row.trades)
                or (
                    previous_market is not None
                    and (row.available_at, row.source_at) < previous_market
                )
            ):
                raise ValueError("market identity, availability or sample order mismatch")
            seen.add(row.identity)
            previous_market = (row.available_at, row.source_at)
            for trade in row.trades:
                if (
                    trade.quantity.dimension != self.spec.limits.maximum.dimension
                    or trade.price.currency != self.spec.initial_cash.currency
                    or trade.price.per != self.spec.limits.maximum.dimension
                ):
                    raise ValueError("market trade instrument or quote currency mismatch")
            yield row
