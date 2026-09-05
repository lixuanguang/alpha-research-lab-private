"""Immutable values for repository engineering standards.

Construction checks field types through ``ImmutableModel``. The standards loader
enforces admitted tool versions, language settings and baseline relationships;
constructing these records neither inspects source nor executes quality tools.
"""

from __future__ import annotations

# standard library imports
from datetime import date

# project library imports
from alpha_research_governance._models import ImmutableModel


class EngineeringStandardsError(ValueError):
    """Report engineering-standard findings in their supplied order.

    Attributes:
        findings: Immutable snapshot of the supplied messages, including duplicates.
    """

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        """Capture findings and join them with newlines for the exception message.

        Args:
            findings: Ordered diagnostic messages; an empty sequence is permitted.
        """
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class ToolStandard(ImmutableModel):
    """Declare an exact static-quality or test tool and its responsibilities.

    Attributes:
        tool_id: Governed tool identifier.
        version: Exact admitted version string.
        roles: Ordered quality responsibilities, such as linting or type checking.
    """

    tool_id: str
    version: str
    roles: tuple[str, ...]


class LanguageStandard(ImmutableModel):
    """Declare the source and quality contract for an admitted or dormant language.

    Attributes:
        language_id: Governed implementation-language identifier.
        admission_status: Current admission state, including dormant languages.
        version: Admitted language version or standard identifier.
        source_extensions: Filename extensions used to classify this language's source.
        warnings_policy: Required treatment of compiler or tool warnings.
        sanitizers: Required sanitizer modes where applicable; may be empty.
    """

    language_id: str
    admission_status: str
    version: str
    source_extensions: tuple[str, ...]
    warnings_policy: str
    sanitizers: tuple[str, ...]


class EngineeringStandards(ImmutableModel):
    """Store repository engineering policy and its recorded measurement baseline.

    Baseline fields describe retained measurements; constructing a record does
    not measure coverage, reject mutations or run the validation benchmark.

    Attributes:
        package_status: Declared roadmap completion status.
        successor_package: Roadmap package receiving deferred work.
        validation_workload_iterations: Operation count in the validation benchmark.
        validation_workload_budget_ms: Total benchmark time budget in milliseconds.
        applicable_gate_ids: Ordered quality gates required for this package.
        source_roots: Repository-relative roots covered by standards checks.
        suppression_maximum_lifetime_days: Maximum suppression lifetime from validation.
        suppression_minimum_rationale_characters: Minimum length of suppression explanations.
        generated_source_roots: Declared locations of generated source artifacts.
        hypothesis_version: Exact admitted property-testing library version.
        hypothesis_maximum_examples: Configured example limit for property-based tests.
        coverage_statement_percent: Recorded statement coverage percentage.
        mutation_cases: Number of representative mutation cases in the baseline.
        mutation_cases_rejected: Number of those mutations rejected by the baseline checks.
        measurement_date: Calendar date assigned to the retained baseline measurements.
        tools: Ordered admitted quality/test tool records.
        languages: Ordered active and dormant language contracts.
        local_evidence_manifest_path: Repository-relative package evidence manifest.
        local_evidence_commit_sha: Commit to which the local evidence is bound.
        open_finding_ids: Declared unresolved package findings.
    """

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
