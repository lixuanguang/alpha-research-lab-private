"""Immutable values for repository engineering standards."""

from __future__ import annotations

# standard library imports
from datetime import date

# project library imports
from alpha_research_governance._models import ImmutableModel


class EngineeringStandardsError(ValueError):
    """Report one or more fail-closed engineering-standard findings."""

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class ToolStandard(ImmutableModel):
    """One exact static-quality or test tool role."""

    tool_id: str
    version: str
    roles: tuple[str, ...]


class LanguageStandard(ImmutableModel):
    """One admitted or dormant implementation-language contract."""

    language_id: str
    admission_status: str
    version: str
    source_extensions: tuple[str, ...]
    warnings_policy: str
    sanitizers: tuple[str, ...]


class EngineeringStandards(ImmutableModel):
    """Repository-local engineering standards and their measured baselines."""

    package_status: str
    successor_package: str
    validation_workload_iterations: int
    validation_workload_budget_ms: int
    applicable_gate_ids: tuple[str, ...]
    source_roots: tuple[str, ...]
    suppression_maximum_lifetime_days: int
    suppression_minimum_rationale_characters: int
    generated_source_roots: tuple[str, ...]
    hypothesis_version: str
    hypothesis_maximum_examples: int
    coverage_statement_percent: int
    mutation_cases: int
    mutation_cases_rejected: int
    measurement_date: date
    tools: tuple[ToolStandard, ...]
    languages: tuple[LanguageStandard, ...]
    local_evidence_manifest_path: str
    local_evidence_commit_sha: str
    open_finding_ids: tuple[str, ...]
