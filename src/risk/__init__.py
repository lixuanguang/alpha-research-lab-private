"""Expose independent limits for the cash-funded spot simulation."""

# standard library imports
from typing import TYPE_CHECKING

# project library imports
from risk.budgets import (
    AccountLimit,
    BudgetEngine,
    BudgetPolicy,
    BudgetRequest,
    ExposureCommitment,
    InstanceLimit,
)
from risk.spot import SpotLimits

if TYPE_CHECKING:
    # project library imports
    from risk.admission import AdmissionDecision, SubmissionAdmission


def __getattr__(name: str) -> object:
    """Load admission only after configuration and spot limits are initialized."""
    if name in {"AdmissionDecision", "SubmissionAdmission"}:
        # project library imports
        from risk import admission

        exports: dict[str, object] = {
            "AdmissionDecision": admission.AdmissionDecision,
            "SubmissionAdmission": admission.SubmissionAdmission,
        }
        return exports[name]
    raise AttributeError(name)


__all__ = [
    "AccountLimit",
    "AdmissionDecision",
    "BudgetEngine",
    "BudgetPolicy",
    "BudgetRequest",
    "ExposureCommitment",
    "InstanceLimit",
    "SpotLimits",
    "SubmissionAdmission",
]
