"""Commit independently selected candidates through shared portfolio admission."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

# project library imports
from execution import (
    AccountDecision,
    AccountQuote,
    OrderDecision,
    PaperAccount,
    PortfolioBatch,
    PortfolioCommit,
    PortfolioContext,
    PortfolioDecision,
)
from financial_units import Money
from research.observations import DecisionInputs
from runtime.candidate_worker import LocalCandidateExecutor
from runtime.candidates import CandidateCheckpoint, CandidateStep, LoadedCandidate
from serialization import DomainCodec, WireRecord


@dataclass(frozen=True)
class SharedStrategyBinding:
    """Bind one admitted candidate to an instance, entity, account and portfolio scope.

    Applications select these explicit collaborators. The candidate is the same
    executable definition used by replay and dedicated paper; no factory is
    imported from configuration and no trading authority is implied.
    """

    instance_id: str
    account_id: str
    entity: str
    candidate: LoadedCandidate
    context: PortfolioContext
    maximum_fee: Money

    def __post_init__(self) -> None:
        """Reject missing ownership, foreign placements and invalid fee or context values."""
        if any(
            type(value) is not str or not value
            for value in (self.instance_id, self.account_id, self.entity)
        ):
            raise ValueError("shared candidate binding requires explicit identities")
        if type(self.candidate) is not LoadedCandidate:
            raise TypeError("shared binding requires a loaded candidate")
        deployment = self.candidate.deployment
        if (
            deployment.instance != self.instance_id
            or deployment.entity != self.entity
            or deployment.mode != "runtime"
            or deployment.input_mode != "source"
        ):
            raise ValueError("shared binding differs from its candidate runtime placement")
        if type(self.context) is not PortfolioContext or type(self.maximum_fee) is not Money:
            raise TypeError("shared binding requires typed portfolio context and fee")
        self.context.__post_init__()
        self.maximum_fee.model_copy()
        if self.maximum_fee.value < 0:
            raise ValueError("shared policy fee reserve cannot be negative")


class CandidateExecutor(Protocol):
    """Evaluate one candidate step from committed state, in process or isolated."""

    def step(self, inputs: DecisionInputs, checkpoint: CandidateCheckpoint | None) -> CandidateStep:
        """Return the staged step; ``None`` starts fresh candidate state."""
        ...


class SharedStrategyInput(WireRecord, frozen=True):
    """Supply a named instance's causal source inputs and the observed account quote."""

    instance_id: str
    inputs: DecisionInputs
    quote: AccountQuote

    def __post_init__(self) -> None:
        """Require typed observations; the journal independently verifies the market mark."""
        if type(self.instance_id) is not str or not self.instance_id:
            raise ValueError("shared input requires an instance")
        if type(self.inputs) is not DecisionInputs or type(self.quote) is not AccountQuote:
            raise TypeError("shared input requires decision inputs and account quote")
        self.inputs.__post_init__()
        self.quote.__post_init__()
        if self.quote.at > self.inputs.decision_at:
            raise ValueError("shared input contains a future quote")


class SharedCandidateCheckpoint(WireRecord, frozen=True):
    """Retain a candidate continuation, its step lineage and the exact retry identities."""

    batch_identity: str
    input_identity: str
    expected_checkpoint_sha256: str
    binding_identity: str
    step: CandidateStep
    schema_version: Literal["shared-candidate-decision"] = "shared-candidate-decision"

    def __post_init__(self) -> None:
        """Require attributable immutable state and a committed decided or warming step."""
        if (
            self.schema_version != "shared-candidate-decision"
            or type(self.batch_identity) is not str
            or not self.batch_identity
            or any(
                type(value) is not str
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
                for value in (
                    self.input_identity,
                    self.expected_checkpoint_sha256,
                    self.binding_identity,
                )
            )
        ):
            raise ValueError("invalid shared candidate continuation")
        if type(self.step) is not CandidateStep:
            raise TypeError("shared continuation requires a candidate step")
        self.step.__post_init__()
        if self.step.status == "paused":
            raise ValueError("a paused candidate step commits no continuation")


class SharedDecisionRuntime:
    """Stage independent candidates and atomically persist portfolio decisions and state.

    All state comes from the account journal at each call. A candidate or persistence
    failure leaves every instance at its prior continuation. A rejected risk
    decision is retained with its successor candidate state, just like dedicated
    candidate admission. A warming step commits its continuation without an intent;
    a paused step commits nothing. Inputs and market observations remain separate
    trust boundaries: this runtime cannot replace the journal's observed quote.
    A candidate whose restart rule is ``reset`` starts fresh at its first step in
    each runtime; ``restore`` resumes the journal's continuation.
    """

    def __init__(
        self,
        journal: PaperAccount,
        bindings: tuple[SharedStrategyBinding, ...],
        executors: Mapping[str, CandidateExecutor] | None = None,
    ) -> None:
        """Validate active selection against account authority and restored state."""
        if type(bindings) is not tuple or not bindings:
            raise ValueError("shared runtime requires immutable selected bindings")
        if any(type(binding) is not SharedStrategyBinding for binding in bindings):
            raise TypeError("shared runtime requires SharedStrategyBinding")
        if len({binding.instance_id for binding in bindings}) != len(bindings):
            raise ValueError("shared runtime requires distinct selected instances")
        self.journal = journal
        self._bindings = {binding.instance_id: binding for binding in bindings}
        supplied = {} if executors is None else dict(executors)
        if not set(supplied) <= set(self._bindings):
            raise ValueError("shared runtime executor has no selected binding")
        self._executors: dict[str, CandidateExecutor] = {
            binding.instance_id: supplied.get(
                binding.instance_id, LocalCandidateExecutor(binding.candidate)
            )
            for binding in bindings
        }
        self._codec = DomainCodec()
        self._fresh: set[str] = set()
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
            saved = self._saved(binding)
            if saved is None:
                continue
            if binding.candidate.definition.state.on_restart == "reset":
                self._fresh.add(binding.instance_id)

    @property
    def bindings(self) -> tuple[SharedStrategyBinding, ...]:
        """Expose the selected candidate bindings in instance order."""
        return tuple(self._bindings[name] for name in sorted(self._bindings))

    def last_committed(self, instance_id: str) -> datetime | None:
        """Return the instance's last committed decision instant, if any."""
        binding = self._bindings[instance_id]
        saved = self._saved(binding)
        return None if saved is None else saved.step.at

    def binding_identity(self, binding: SharedStrategyBinding) -> str:
        """Bind continuation to the complete selected configuration and independent limits."""
        return hashlib.sha256(
            self._codec.encode_json(
                (
                    self.journal.config,
                    binding.instance_id,
                    binding.account_id,
                    binding.entity,
                    binding.candidate.identity,
                    binding.context,
                    binding.maximum_fee,
                )
            )
        ).hexdigest()

    def evaluate(
        self,
        *,
        identity: str,
        at: datetime,
        inputs: tuple[SharedStrategyInput, ...],
        crossing: Literal["reject", "internal_at_quote"] = "reject",
    ) -> PortfolioCommit | None:
        """Evaluate a selected cohort and commit one strictly later coordination boundary.

        Args:
            identity: Stable batch identity; retry requires identical inputs and candidates.
            at: UTC coordination time, strictly later than every decision cutoff.
            inputs: Causal source inputs for distinct configured instances.
            crossing: Explicit policy for compatible opposite interests.

        Returns:
            The durable batch result, including child ownership and physical orders,
            or None when every selected candidate paused.

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
            if binding is None or item.inputs.entity != binding.entity:
                raise ValueError("shared input is not selected or its entity differs")
            if str(item.quote.price.per.instrument_id) != binding.entity:
                raise ValueError("shared quote belongs to another instrument")
            input_identity = hashlib.sha256(
                self._codec.encode_json((at, crossing, item))
            ).hexdigest()
            saved = self.journal.checkpoint(item.instance_id)
            prior = (
                None
                if saved is None or item.instance_id in self._fresh
                else self._decode(binding, saved)
            )
            step = self._executors[item.instance_id].step(
                item.inputs, None if prior is None else prior.step.checkpoint
            )
            self._require_step(binding, item, step)
            if step.status == "paused":
                continue
            continuation = SharedCandidateCheckpoint(
                batch_identity=identity,
                input_identity=input_identity,
                expected_checkpoint_sha256=hashlib.sha256(saved or b"").hexdigest(),
                binding_identity=self.binding_identity(binding),
                step=step,
            )
            decisions.append(
                PortfolioDecision(
                    request=AccountDecision(
                        account_id=binding.account_id,
                        instance_id=binding.instance_id,
                        decision=OrderDecision(
                            identity=hashlib.sha256(
                                self._codec.encode_json((identity, step))
                            ).hexdigest(),
                            at=step.at,
                            intent=None if step.decision is None else step.decision.intent,
                        ),
                        quote=item.quote,
                        maximum_fee=binding.maximum_fee,
                        checkpoint=self._codec.encode_json(continuation),
                    ),
                    context=binding.context,
                    expected_checkpoint_sha256=continuation.expected_checkpoint_sha256,
                )
            )
        if not decisions:
            return None
        result = self.journal.coordinate(
            PortfolioBatch(
                identity=identity,
                at=at,
                decisions=tuple(decisions),
                crossing=crossing,
            )
        )
        self._fresh.difference_update(item.request.instance_id for item in decisions)
        return result

    def _saved(self, binding: SharedStrategyBinding) -> SharedCandidateCheckpoint | None:
        """Read the journal's continuation for one binding, if any."""
        saved = self.journal.checkpoint(binding.instance_id)
        return None if saved is None else self._decode(binding, saved)

    def _decode(self, binding: SharedStrategyBinding, saved: bytes) -> SharedCandidateCheckpoint:
        """Decode a continuation and require it to belong to this binding."""
        continuation = self._codec.decode_json(saved, SharedCandidateCheckpoint)
        continuation.__post_init__()
        if (
            continuation.binding_identity != self.binding_identity(binding)
            or continuation.step.checkpoint.binding_identity != binding.candidate.identity
        ):
            raise ValueError("shared continuation belongs to another candidate binding")
        return continuation

    @staticmethod
    def _require_step(
        binding: SharedStrategyBinding, item: SharedStrategyInput, step: CandidateStep
    ) -> None:
        """Reject a step for another candidate, cutoff or feature lineage."""
        step.__post_init__()
        if (
            step.checkpoint.binding_identity != binding.candidate.identity
            or step.at != item.inputs.decision_at
            or (step.feature is not None and step.feature.entity != binding.entity)
        ):
            raise ValueError("candidate step differs from its binding or input cutoff")

    def _validate_retry(
        self,
        original: PortfolioBatch,
        at: datetime,
        inputs: tuple[SharedStrategyInput, ...],
        crossing: Literal["reject", "internal_at_quote"],
    ) -> None:
        """Admit an old exact retry without rewinding a newer continuation.

        Selected instances absent from the original batch paused and committed nothing.
        """
        by_instance = {item.instance_id: item for item in inputs}
        if (
            original.at != at
            or original.crossing != crossing
            or not {item.request.instance_id for item in original.decisions} <= set(by_instance)
        ):
            raise ValueError("shared batch retry changed its cohort or candidates")
        for decision in original.decisions:
            item = by_instance[decision.request.instance_id]
            item.__post_init__()
            binding = self._bindings.get(item.instance_id)
            if binding is None:
                raise ValueError("shared batch retry changed selected instances")
            continuation = self._codec.decode_json(
                decision.request.checkpoint, SharedCandidateCheckpoint
            )
            continuation.__post_init__()
            input_identity = hashlib.sha256(
                self._codec.encode_json((at, crossing, item))
            ).hexdigest()
            if (
                continuation.binding_identity != self.binding_identity(binding)
                or continuation.input_identity != input_identity
            ):
                raise ValueError("shared batch retry changed its observations")

    @staticmethod
    def _input_order(item: SharedStrategyInput) -> str:
        """Keep allocation and batch identities stable when application selection order changes."""
        return item.instance_id
