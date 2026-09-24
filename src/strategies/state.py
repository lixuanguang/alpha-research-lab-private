"""Own instance-isolated decision state and validate returned intent capabilities."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime

# project library imports
from serialization import DomainCodec, WireRecord
from strategies.decisions import (
    DecisionContext,
    DecisionPolicy,
    DecisionRecord,
    OrderIntent,
    QuoteIntent,
    TargetIntent,
)


class DecisionState(WireRecord, frozen=True):
    """Bind policy state to its complete run and completed decision clock."""

    run_identity: str
    last_at: datetime | None
    state: bytes
    sha256: str

    def __post_init__(self) -> None:
        """Reject corrupted or malformed checkpoint bytes."""
        if (
            type(self.run_identity) is not str
            or not self.run_identity
            or type(self.state) is not bytes
        ):
            raise ValueError("invalid decision state")
        if self.last_at is not None:
            self._require_utc(self.last_at, field_name="last_at")
        if self.sha256 != self.digest(self.run_identity, self.last_at, self.state):
            raise ValueError("decision state digest mismatch")

    @staticmethod
    def digest(run_identity: str, last_at: datetime | None, state: bytes) -> str:
        """Hash binding, cutoff and policy bytes together."""
        return hashlib.sha256(DomainCodec().encode_json((run_identity, last_at, state))).hexdigest()


class DecisionSession:
    """Commit only valid pure policy transitions; intent generation never submits orders."""

    def __init__(
        self,
        policy: DecisionPolicy,
        *,
        run_identity: str,
        instance: str,
        entity: str,
        checkpoint: DecisionState | None = None,
    ) -> None:
        """Bind one independent stream and validate selected policy restart bytes."""
        self._policy, self._policy_identity = policy, policy.identity
        self._run, self._instance, self._entity = run_identity, instance, entity
        self._state, self._last_at = policy.initial_state(), None
        if checkpoint is not None:
            checkpoint.__post_init__()
            if checkpoint.run_identity != run_identity:
                raise ValueError("decision checkpoint belongs to another run")
            self._state, self._last_at = checkpoint.state, checkpoint.last_at
        policy.validate_state(self._state)

    def evaluate(self, context: DecisionContext) -> DecisionRecord:
        """Validate context, output family/units and successor state before committing."""
        context.__post_init__()
        self._policy.admit(
            context.features.fields,
            None if context.prediction is None else context.prediction.field,
        )
        at = context.decision_at
        if (
            context.features.entity != self._entity
            or self._policy.identity != self._policy_identity
            or (self._last_at is not None and at <= self._last_at)
        ):
            raise ValueError("decision entity, policy or monotonic clock mismatch")
        result = self._policy.decide(context, self._state)
        result.__post_init__()
        self._policy.validate_state(result.state)
        intent = result.intent
        output = (
            "target"
            if isinstance(intent, TargetIntent)
            else "order"
            if isinstance(intent, OrderIntent)
            else "quote"
            if isinstance(intent, QuoteIntent)
            else "exposure"
        )
        if output != self._policy.output:
            raise ValueError("policy returned an undeclared output contract")
        quantity = (
            intent.quantity
            if isinstance(intent, (TargetIntent, OrderIntent))
            else intent.bid.quantity
            if isinstance(intent, QuoteIntent)
            else None
        )
        if quantity is not None and str(quantity.dimension.instrument_id) != self._entity:
            raise ValueError("intent quantity belongs to another instrument")
        record = DecisionRecord(
            instance=self._instance,
            entity=self._entity,
            at=at,
            policy=self._policy_identity,
            feature_identity=context.features.identity,
            model_identity=None
            if context.prediction is None
            else context.prediction.model_identity,
            intent=intent,
        )
        self._state, self._last_at = result.state, at
        return record

    def checkpoint(self) -> DecisionState:
        """Return immutable state for exact instance-isolated continuation."""
        return DecisionState(
            run_identity=self._run,
            last_at=self._last_at,
            state=self._state,
            sha256=DecisionState.digest(self._run, self._last_at, self._state),
        )
