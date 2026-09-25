"""Commit independently selected decision policies through shared portfolio admission."""

from __future__ import annotations

# standard library imports
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

# project library imports
from execution import (
    AccountDecision,
    AccountJournal,
    AccountQuote,
    OrderDecision,
    PortfolioBatch,
    PortfolioCommit,
    PortfolioContext,
    PortfolioDecision,
)
from financial_units import Money
from serialization import DomainCodec, WireRecord
from strategies import (
    DecisionContext,
    DecisionPolicy,
    DecisionRecord,
    DecisionSession,
    DecisionState,
)


@dataclass(frozen=True)
class SharedStrategyBinding:
    """Bind an installed policy to one instance, entity, account and portfolio scope.

    Applications select these explicit collaborators. The policy is the same
    public decision SDK used by research and candidate loading; no factory is
    imported from configuration and no trading authority is implied.
    """

    instance_id: str
    account_id: str
    entity: str
    policy: DecisionPolicy
    context: PortfolioContext
    maximum_fee: Money

    def __post_init__(self) -> None:
        """Reject missing ownership and invalid fee or context values."""
        if any(
            type(value) is not str or not value
            for value in (
                self.instance_id,
                self.account_id,
                self.entity,
                self.policy.identity,
            )
        ):
            raise ValueError("shared policy binding requires explicit identities")
        if type(self.context) is not PortfolioContext or type(self.maximum_fee) is not Money:
            raise TypeError("shared binding requires typed portfolio context and fee")
        self.context.__post_init__()
        self.maximum_fee.model_copy()
        if self.maximum_fee.value < 0:
            raise ValueError("shared policy fee reserve cannot be negative")


class SharedStrategyInput(WireRecord, frozen=True):
    """Supply a named instance's causal feature/prediction input and observed quote."""

    instance_id: str
    context: DecisionContext
    quote: AccountQuote

    def __post_init__(self) -> None:
        """Require typed observations; the journal independently verifies the market mark."""
        if type(self.instance_id) is not str or not self.instance_id:
            raise ValueError("shared input requires an instance")
        if type(self.context) is not DecisionContext or type(self.quote) is not AccountQuote:
            raise TypeError("shared input requires decision context and account quote")
        self.context.__post_init__()
        self.quote.__post_init__()
        if self.quote.at > self.context.decision_at:
            raise ValueError("shared input contains a future quote")


class SharedDecisionCheckpoint(WireRecord, frozen=True):
    """Retain policy continuation and the last exact retry at the account transaction."""

    batch_identity: str
    input_identity: str
    expected_checkpoint_sha256: str
    decision: DecisionRecord
    policy: DecisionState
    schema_version: Literal["shared-decision-v1"] = "shared-decision-v1"

    def __post_init__(self) -> None:
        """Require attributable immutable state and agreement on the committed cutoff."""
        if (
            self.schema_version != "shared-decision-v1"
            or type(self.batch_identity) is not str
            or not self.batch_identity
            or type(self.input_identity) is not str
            or len(self.input_identity) != 64
            or type(self.expected_checkpoint_sha256) is not str
            or len(self.expected_checkpoint_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.input_identity)
            or any(
                character not in "0123456789abcdef" for character in self.expected_checkpoint_sha256
            )
        ):
            raise ValueError("invalid shared decision continuation")
        if type(self.decision) is not DecisionRecord or type(self.policy) is not DecisionState:
            raise TypeError("shared continuation requires typed decision and policy state")
        self.decision.__post_init__()
        self.policy.__post_init__()
        if self.decision.at != self.policy.last_at:
            raise ValueError("decision and continuation clocks differ")


class SharedDecisionRuntime:
    """Stage independent policies and atomically persist portfolio decisions and state.

    All state comes from the account journal at each call. A policy or persistence
    failure leaves every instance at its prior continuation. A rejected risk
    decision is retained with its successor policy state, just like dedicated
    candidate admission. Inputs and market observations remain separate trust
    boundaries: this runtime cannot replace the journal's independently observed
    quote. Stop/restart and physical events use the journal's operator interface.
    """

    def __init__(
        self, journal: AccountJournal, bindings: tuple[SharedStrategyBinding, ...]
    ) -> None:
        """Validate active selection against existing account authority and restored state."""
        if type(bindings) is not tuple or not bindings:
            raise ValueError("shared runtime requires immutable selected bindings")
        if any(type(binding) is not SharedStrategyBinding for binding in bindings):
            raise TypeError("shared runtime requires SharedStrategyBinding")
        if len({binding.instance_id for binding in bindings}) != len(bindings):
            raise ValueError("shared runtime requires distinct selected instances")
        self.journal = journal
        self._bindings = {binding.instance_id: binding for binding in bindings}
        self._codec = DomainCodec()
        for binding in bindings:
            binding.__post_init__()
            owner = next(
                (
                    item
                    for item in journal.config.budgets.instances
                    if item.instance_id == binding.instance_id
                ),
                None,
            )
            if (
                owner is None
                or owner.account_id != binding.account_id
                or binding.entity not in tuple(str(item) for item in owner.instruments)
                or binding.maximum_fee.currency != journal.config.budgets.valuation_currency
            ):
                raise ValueError("shared binding exceeds configured instance authority")
            saved = journal.checkpoint(binding.instance_id)
            if saved is not None:
                checkpoint = self._codec.decode_json(saved, SharedDecisionCheckpoint)
                self._session(binding, checkpoint.policy)

    def evaluate(
        self,
        *,
        identity: str,
        at: datetime,
        inputs: tuple[SharedStrategyInput, ...],
        crossing: Literal["reject", "internal_at_quote"] = "reject",
    ) -> PortfolioCommit:
        """Evaluate a selected cohort and commit one strictly later coordination boundary.

        Args:
            identity: Stable batch identity; retry requires identical inputs and policy.
            at: UTC coordination time, strictly later than every decision cutoff.
            inputs: Causal observations for distinct configured instances.
            crossing: Explicit policy for compatible opposite interests.

        Returns:
            The durable batch result, including child ownership and physical orders.

        Raises:
            ValueError: Inputs, restored bindings, clocks or retry bytes differ.
        """
        if type(inputs) is not tuple or not inputs:
            raise ValueError("shared runtime requires immutable inputs")
        if any(type(item) is not SharedStrategyInput for item in inputs):
            raise TypeError("shared runtime requires SharedStrategyInput")
        if len({item.instance_id for item in inputs}) != len(inputs):
            raise ValueError("shared runtime requires distinct input owners")
        original = self.journal.portfolio_batch(identity)
        if original is not None:
            self._validate_retry(original, at, inputs, crossing)
            return self.journal.coordinate(original)
        decisions: list[PortfolioDecision] = []
        for item in sorted(inputs, key=self._input_order):
            item.__post_init__()
            binding = self._bindings.get(item.instance_id)
            if binding is None or item.context.features.entity != binding.entity:
                raise ValueError("shared input is not selected or its entity differs")
            if str(item.quote.price.per.instrument_id) != binding.entity:
                raise ValueError("shared quote belongs to another instrument")
            input_identity = hashlib.sha256(
                self._codec.encode_json((at, crossing, item))
            ).hexdigest()
            saved = self.journal.checkpoint(item.instance_id)
            checkpoint = (
                None if saved is None else self._codec.decode_json(saved, SharedDecisionCheckpoint)
            )
            session = self._session(binding, None if checkpoint is None else checkpoint.policy)
            record = session.evaluate(item.context)
            checkpoint = SharedDecisionCheckpoint(
                batch_identity=identity,
                input_identity=input_identity,
                expected_checkpoint_sha256=hashlib.sha256(saved or b"").hexdigest(),
                decision=record,
                policy=session.checkpoint(),
            )
            decisions.append(
                PortfolioDecision(
                    request=AccountDecision(
                        account_id=binding.account_id,
                        instance_id=binding.instance_id,
                        decision=OrderDecision(
                            identity=hashlib.sha256(
                                self._codec.encode_json((identity, record))
                            ).hexdigest(),
                            at=record.at,
                            intent=record.intent,
                        ),
                        quote=item.quote,
                        maximum_fee=binding.maximum_fee,
                        checkpoint=self._codec.encode_json(checkpoint),
                    ),
                    context=binding.context,
                    expected_checkpoint_sha256=checkpoint.expected_checkpoint_sha256,
                )
            )
        return self.journal.coordinate(
            PortfolioBatch(
                identity=identity,
                at=at,
                decisions=tuple(decisions),
                crossing=crossing,
            )
        )

    def _validate_retry(
        self,
        original: PortfolioBatch,
        at: datetime,
        inputs: tuple[SharedStrategyInput, ...],
        crossing: Literal["reject", "internal_at_quote"],
    ) -> None:
        """Admit an old exact retry without rewinding a newer policy continuation."""
        ordered = tuple(sorted(inputs, key=self._input_order))
        if (
            original.at != at
            or original.crossing != crossing
            or tuple(item.request.instance_id for item in original.decisions)
            != tuple(item.instance_id for item in ordered)
        ):
            raise ValueError("shared batch retry changed its cohort or policy")
        for item, decision in zip(ordered, original.decisions, strict=True):
            item.__post_init__()
            binding = self._bindings.get(item.instance_id)
            if binding is None:
                raise ValueError("shared batch retry changed selected instances")
            checkpoint = self._codec.decode_json(
                decision.request.checkpoint, SharedDecisionCheckpoint
            )
            self._session(binding, checkpoint.policy)
            input_identity = hashlib.sha256(
                self._codec.encode_json((at, crossing, item))
            ).hexdigest()
            if checkpoint.input_identity != input_identity:
                raise ValueError("shared batch retry changed its observations")

    def _session(
        self, binding: SharedStrategyBinding, checkpoint: DecisionState | None
    ) -> DecisionSession:
        """Bind policy state to the complete selected configuration and independent limits."""
        identity = hashlib.sha256(
            self._codec.encode_json(
                (
                    self.journal.config,
                    binding.instance_id,
                    binding.account_id,
                    binding.entity,
                    binding.policy.identity,
                    binding.context,
                    binding.maximum_fee,
                )
            )
        ).hexdigest()
        return DecisionSession(
            binding.policy,
            run_identity=identity,
            instance=binding.instance_id,
            entity=binding.entity,
            checkpoint=checkpoint,
        )

    @staticmethod
    def _input_order(item: SharedStrategyInput) -> str:
        """Keep allocation and batch identities stable when application selection order changes."""
        return item.instance_id
