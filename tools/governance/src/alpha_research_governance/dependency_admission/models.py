"""Immutable records for frozen dependencies and bounded wheel-only allowances."""

from __future__ import annotations

# standard library imports
from datetime import date
from typing import Annotated, Literal

# third party library imports
from pydantic import Field

# project library imports
from alpha_research_governance._models import ImmutableModel


class DependencyAdmissionError(ValueError):
    """Report ordered dependency-boundary findings as one domain exception.

    Attributes:
        findings: Immutable snapshot of supplied diagnostics, including duplicates.
    """

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        """Capture ordered diagnostics and expose their joined message.

        Args:
            findings: Ordered diagnostic messages. Empty input is allowed so a
                caller can preserve the same error boundary while assembling findings.
        """
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class PythonPackageAdmission(ImmutableModel):
    """Declare one exact locked package, license, and native-artifact requirement."""

    name: str
    version: str
    license_expression: str
    native_artifacts: bool


class WheelOnlyAllowance(ImmutableModel):
    """Bound development use of an exact native dependency without source binding."""

    name: str
    version: str
    rationale: Annotated[str, Field(min_length=40, max_length=2000)]
    usage: Literal["isolated_development_and_ci"]
    source_to_wheel_binding: Literal["unverified"]
    reviewed_on: date
    expires_on: date


class DependencyAdmission(ImmutableModel):
    """Store policy dates, package facts, lock digests, and wheel-only limits."""

    schema_version: int
    as_of_date: date
    review_due_on: date
    lock_digests: tuple[tuple[str, str], ...]
    packages: tuple[PythonPackageAdmission, ...]
    wheel_only_allowances: tuple[WheelOnlyAllowance, ...] = ()
