"""Apply independent spot risk and capability checks to suppressed order intents."""

from __future__ import annotations

# standard library imports
import re
from datetime import timedelta
from typing import Literal

# project library imports
from configuration import (
    CapabilityBinding,
    CapabilityRequirement,
    ExecutionConfiguration,
    ExecutionRequest,
)
from financial_units import Quantity
from risk.spot import SpotLimits
from serialization import WireRecord


class AdmissionDecision(WireRecord, frozen=True, kw_only=True):
    """Record a risk result with explicit proof that no submission occurred."""

    status: Literal["suppressed", "rejected"]
    reason: str
    mode: Literal["research", "paper", "shadow"]
    specification_identity: str
    profile_identity: str
    submission_attempted: Literal[False] = False

    def __post_init__(self) -> None:
        """Keep the output a closed, attributable no-submission decision."""
        if self.status not in ("suppressed", "rejected"):
            raise ValueError("invalid admission status")
        if type(self.reason) is not str or re.fullmatch(r"[a-z][a-z_]{0,79}", self.reason) is None:
            raise ValueError("invalid admission reason")
        if self.mode not in ("research", "paper", "shadow"):
            raise ValueError("invalid admission mode")
        if (
            type(self.specification_identity) is not str
            or re.fullmatch(r"[a-f0-9]{64}", self.specification_identity) is None
            or type(self.profile_identity) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", self.profile_identity) is None
            or self.submission_attempted is not False
        ):
            raise ValueError("invalid admission identity or submission state")


class SubmissionAdmission:
    """Evaluate a selected limit intent without binding a venue submission adapter."""

    def evaluate(
        self, config: ExecutionConfiguration, request: ExecutionRequest
    ) -> AdmissionDecision:
        """Check scope, source facts, capability and account economics before suppression."""
        config.__post_init__()
        request.__post_init__()
        if config.mode not in ("research", "paper", "shadow"):
            raise ValueError("production submission is unavailable in this package")
        if request.requested_mode != config.mode:
            raise ValueError("request mode differs from the installed credential mode")
        specification = config.reference.require_order(
            config.maximum.dimension.instrument_id,
            valid_at=request.valid_at,
            known_at=request.known_at,
            max_age=timedelta(microseconds=request.max_reference_age_us),
        )
        instrument = specification.instrument
        requirement = CapabilityRequirement(
            name="order_admission",
            kind="execution",
            product=instrument.product,
            venue=instrument.venue,
            calendar=instrument.calendar,
            operations=("admit_intent",),
            order_types=("limit",),
            lifecycle=("intent_only",),
        )
        CapabilityBinding(requirement=requirement, profile=config.profile, mode=config.mode)
        limits = SpotLimits.from_reference(
            config.reference,
            maximum=config.maximum,
            quote_currency=config.quote_currency,
            valid_at=request.valid_at,
            known_at=request.known_at,
            max_age=timedelta(microseconds=request.max_reference_age_us),
        )
        intent = request.intent
        reason = limits.order_reason(intent.quantity, intent.limit)
        if reason is None and request.pending:
            reason = "pending_intent"
        if reason is None:
            delta = (
                intent.quantity
                if intent.side == "buy"
                else Quantity(value=-intent.quantity.value, dimension=intent.quantity.dimension)
            )
            reason = limits.fill_reason(
                delta, intent.limit, request.maximum_fee, request.cash, request.holding
            )
        return AdmissionDecision(
            status="suppressed" if reason is None else "rejected",
            reason="submission_disabled" if reason is None else reason,
            mode=config.mode,
            specification_identity=specification.identity,
            profile_identity=config.profile.implementation_identity,
        )
