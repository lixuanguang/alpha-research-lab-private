"""Compose packaged candidates through admitted replay and online feature interfaces."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from itertools import pairwise
from typing import Literal

# project library imports
from configuration import CandidateDeployment, CapabilityRegistry
from research.experiments import CandidateBundle
from research.observations import DecisionSource
from runtime import (
    CandidateCheckpoint,
    CandidateComponents,
    CandidateLoader,
    CandidateSession,
    CandidateStep,
)
from serialization import WireRecord


class CandidateRunResult(WireRecord, frozen=True):
    """Retain linked candidate/deployment identities and the exact committed decision prefix."""

    candidate_identity: str
    deployment_identity: str
    binding_identity: str
    steps: tuple[CandidateStep, ...]
    checkpoint: CandidateCheckpoint
    schema_version: Literal["candidate-run-result"] = "candidate-run-result"

    def __post_init__(self) -> None:
        """Reject disconnected result/checkpoint identities and nonmonotonic traces."""
        if self.schema_version != "candidate-run-result" or type(self.steps) is not tuple:
            raise ValueError("unsupported candidate result schema")
        for digest in (self.candidate_identity, self.deployment_identity, self.binding_identity):
            if (
                type(digest) is not str
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                raise ValueError("candidate result requires SHA-256 identities")
        self.checkpoint.__post_init__()
        if self.checkpoint.binding_identity != self.binding_identity:
            raise ValueError("candidate result checkpoint belongs to another binding")
        for step in self.steps:
            step.__post_init__()
            if step.checkpoint.binding_identity != self.binding_identity:
                raise ValueError("candidate result contains a foreign step")
        if any(a.at >= b.at for a, b in zip(self.steps, self.steps[1:])):
            raise ValueError("candidate result must advance its decision clock")
        if self.steps and self.steps[-1].checkpoint != self.checkpoint:
            raise ValueError("candidate result does not end at its checkpoint")


def run_candidate(
    bundle: CandidateBundle,
    deployment: CandidateDeployment,
    *,
    components: CandidateComponents,
    registry: CapabilityRegistry,
    source: DecisionSource,
    decisions: tuple[datetime, ...],
    checkpoint: CandidateCheckpoint | None = None,
    stop_after: int | None = None,
) -> CandidateRunResult:
    """Resolve the same candidate factories into replay or intent-only runtime evaluation.

    The complete selection and schedule are admitted before source reads. A
    pause ends this bounded call at the last committed checkpoint. Source errors
    propagate without fabricating a successful result or submitting an order.
    ``stop_after`` retains a prefix for explicit process restart; a resumed call
    skips only cutoffs already committed by the identical binding.
    """
    loaded = CandidateLoader(components, registry).load(bundle, deployment)
    if (
        deployment.input_mode != "source"
        or source.identity != deployment.source_identity
        or source.requirements != loaded.definition.inputs
    ):
        raise ValueError("candidate source binding differs from admitted deployment")
    if type(decisions) is not tuple or not decisions or any(a >= b for a, b in pairwise(decisions)):
        raise ValueError("candidate run requires an ordered immutable schedule")
    if stop_after is not None and (type(stop_after) is not int or stop_after < 1):
        raise ValueError("candidate stop_after must be positive")
    session = CandidateSession(loaded, checkpoint)
    # Validate every requested cutoff before the first data read, including the
    # skipped prefix, while the session owns gaps and restored state admission.
    for at in decisions:
        session.admit_cutoff(at, include_committed=True)
    steps: list[CandidateStep] = []
    for at in decisions:
        if (
            checkpoint is not None
            and checkpoint.policy.last_at is not None
            and at <= checkpoint.policy.last_at
        ):
            continue
        inputs = source.read(deployment.entity, at)
        if inputs.entity != deployment.entity or inputs.decision_at != at:
            raise ValueError("candidate source returned another entity or cutoff")
        step = session.evaluate_inputs(inputs)
        steps.append(step)
        if step.status == "paused" or (stop_after is not None and len(steps) == stop_after):
            break
    return CandidateRunResult(
        candidate_identity=loaded.definition.identity,
        deployment_identity=deployment.identity,
        binding_identity=loaded.identity,
        steps=tuple(steps),
        checkpoint=session.checkpoint(),
    )
