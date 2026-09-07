"""Resolve development and institutional obligations from actual role assignments.

Validation callbacks raise ValueError when called directly. Normal Pydantic
construction and validation report callback failures as ValidationError; owning
loaders translate those failures to their domain error where specified.
"""

from __future__ import annotations

# standard library imports
import json
import re
import tomllib
from datetime import date
from pathlib import Path
from typing import Literal, Self, cast

# third party library imports
from pydantic import ValidationError, field_validator, model_validator

# project library imports
from alpha_research_governance._models import ImmutableModel

Operation = Literal["implementation", "institutional_acceptance", "release", "activation"]
GovernanceStatus = Literal["not_required", "pending", "complete"]
ImplementationStatus = Literal["planned", "in_progress", "complete", "blocked"]


class OperatingModelError(ValueError):
    """Report invalid staffing or an unsupported operating scope."""


class RoleAssignment(ImmutableModel):
    """Record one person's role and effective domains, without inventing independence.

    The principal is casefolded during validation. Domains must be nonempty and
    unique; the effective interval is half-open. Status records the staffing claim
    in the register; this model does not check employment or forge access.

    Attributes:
        principal: Individual @user identity, excluding organization/team handles.
        role: Assigned role; OperatingModel checks that it exists for each domain.
        domains: Explicit domain IDs covered by this role assignment.
        status: planned, active or inactive; only active can satisfy is_active.
        effective_from: Inclusive first effective date.
        effective_until: Exclusive last bound, later than effective_from, or None for no
            end.
    """

    principal: str
    role: str
    domains: tuple[str, ...]
    status: Literal["planned", "active", "inactive"]
    effective_from: date
    effective_until: date | None = None

    @field_validator("principal")
    @classmethod
    def individual_principal(cls, value: str) -> str:
        """Require an individual forge identity and canonicalize its case.

        Args:
            value: Handle beginning with @, then an ASCII letter or digit, followed by letters,
                digits or hyphens.

        Returns:
            The handle casefolded for identity comparison.

        Raises:
            ValueError: The string does not match the individual @user syntax.
        """
        if re.fullmatch(r"@[A-Za-z0-9][A-Za-z0-9-]*", value) is None:
            raise ValueError("principal must be an individual @user")
        return value.casefold()

    @model_validator(mode="after")
    def coherent_scope(self) -> Self:
        """Reject empty or duplicated scopes and reversed effective intervals.

        Returns:
            This assignment after checking domain uniqueness and date ordering.

        Raises:
            ValueError: Domains are empty or repeated, or effective_until is not after
                effective_from.
        """
        if not self.domains or len(set(self.domains)) != len(self.domains):
            raise ValueError("assignment domains must be non-empty and unique")
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("effective_until must follow effective_from")
        return self

    def is_active(self, on_date: date) -> bool:
        """Report whether the declared active assignment covers an evaluation date.

        Args:
            on_date: Explicit date to compare with the inclusive start and exclusive optional
                end.

        Returns:
            True only when status is active and the date lies in the effective interval.
        """
        return (
            self.status == "active"
            and self.effective_from <= on_date
            and (self.effective_until is None or on_date < self.effective_until)
        )


class DomainRoles(ImmutableModel):
    """Retain the institutional role catalog for one domain.

    These role names describe required responsibilities, not assigned people or
    evidence of independent review. OperatingModel validates assignments against
    the union of these roles.

    Attributes:
        domain_id: Exact domain key used by staffing assignments and resolution.
        accountable_role: Role accountable for the domain.
        required_review_roles: Catalog of required reviewer roles.
        independent_review_roles: Catalog of roles requiring independent review.
        escalation_roles: Catalog of roles to which issues can be escalated.
    """

    domain_id: str
    accountable_role: str
    required_review_roles: tuple[str, ...]
    independent_review_roles: tuple[str, ...]
    escalation_roles: tuple[str, ...]


class OperatingRules(ImmutableModel):
    """Separate scoped handover obligations from permission to finish engineering.

    These fields describe OperatingModel.resolve output. Direct construction
    checks field types without enforcing profile/reviewer consistency.

    Attributes:
        profile: founder, scoped_team or institutional scope chosen for the operation.
        governance_status: Handover state; pending does not itself block local engineering
            completion.
        assigned_reviewers: Distinct active non-founder principals for the domain, sorted by
            identity.
        institutional_approval_required: Whether local engineering evidence is insufficient
            for this operation.
    """

    profile: Literal["founder", "scoped_team", "institutional"]
    governance_status: GovernanceStatus
    assigned_reviewers: tuple[str, ...]
    institutional_approval_required: bool

    def require_local_completion(
        self, *, repository_local_status: str, technical_finding_ids: tuple[str, ...]
    ) -> None:
        """Accept passing engineering evidence independently of organizational handover.

        This check does not mutate governance_status or record an acceptance. Pending
        handover and assigned reviewers do not block an implementation that passes it.

        Args:
            repository_local_status: Exact passed status required from the repository-local
                checks.
            technical_finding_ids: Outstanding technical findings; must be empty.

        Raises:
            OperatingModelError: Evidence fails, technical issues remain, or the operation
                requires institutional approval.
        """
        if self.institutional_approval_required:
            raise OperatingModelError("local completion cannot authorize institutional operations")
        if repository_local_status != "passed" or technical_finding_ids:
            raise OperatingModelError(
                "completion requires passing repository-local evidence and no technical findings"
            )


class OperatingModel(ImmutableModel):
    """Resolve the founder policy and hiring trigger for explicitly assigned domains.

    One founder assignment must cover every domain. A founder cannot also be
    registered as a hired reviewer. Each principal/role/domain combination is
    unique even when proposed effective intervals do not overlap. Construction
    validates these relationships without checking whether anyone is active today.

    Attributes:
        founder_principal: Exact canonical identity matching the founder assignment.
        domains: Nonempty catalog with unique domain IDs.
        assignments: Role assignments whose domains and non-founder roles exist in that
            catalog.
    """

    founder_principal: str
    domains: tuple[DomainRoles, ...]
    assignments: tuple[RoleAssignment, ...]

    @model_validator(mode="after")
    def valid_assignments(self) -> Self:
        """Reject unknown roles/scopes and duplicate or misleading identities.

        Returns:
            This model after checking founder coverage and assignment consistency.

        Raises:
            ValueError: Domains are missing or duplicated, founder coverage is invalid, the
                founder is also a hired reviewer, a role/domain is unknown, or an assignment
                combination is repeated.
        """
        domain_map = {domain.domain_id: domain for domain in self.domains}
        if not domain_map or len(domain_map) != len(self.domains):
            raise ValueError("operating domains must be non-empty and unique")
        founders = [assignment for assignment in self.assignments if assignment.role == "founder"]
        if (
            len(founders) != 1
            or founders[0].principal != self.founder_principal
            or set(founders[0].domains) != set(domain_map)
        ):
            raise ValueError("one founder assignment must cover every domain")
        seen: set[tuple[str, str, str]] = set()
        for assignment in self.assignments:
            if assignment.principal == self.founder_principal and assignment.role != "founder":
                raise ValueError("founder cannot also be recorded as a hired reviewer")
            for domain_id in assignment.domains:
                domain = domain_map.get(domain_id)
                if domain is None:
                    raise ValueError(f"unknown assignment domain {domain_id!r}")
                roles = {
                    domain.accountable_role,
                    *domain.required_review_roles,
                    *domain.independent_review_roles,
                    *domain.escalation_roles,
                }
                if assignment.role != "founder" and assignment.role not in roles:
                    raise ValueError(f"role {assignment.role!r} is not defined for {domain_id}")
                key = (assignment.principal, assignment.role, domain_id)
                if key in seen:
                    raise ValueError("duplicate role assignment; update its effective interval")
                seen.add(key)
        return self

    def resolve(self, *, domain_id: str, operation: Operation, on_date: date) -> OperatingRules:
        """Resolve a domain at an explicit date; planned hires never activate rules.

        Resolution checks active assignments in the requested domain; it does not
        prove coverage of every review role or record completed approval evidence.

        Args:
            domain_id: Exact key in the model domain catalog.
            operation: implementation, institutional_acceptance, release or activation.
            on_date: Evaluation date used for founder and reviewer effective intervals.

        Returns:
            Fresh rules with sorted unique active non-founder principals. Implementation uses
            founder/not_required when none exist, otherwise scoped_team/pending. Other
            operations use institutional/pending and require institutional approval.

        Raises:
            OperatingModelError: The domain or operation is unknown, or the founder is not
                active on the evaluation date.
        """
        if domain_id not in {domain.domain_id for domain in self.domains}:
            raise OperatingModelError(f"unknown operating domain {domain_id!r}")
        if operation not in {"implementation", "institutional_acceptance", "release", "activation"}:
            raise OperatingModelError(f"unsupported operation {operation!r}")
        founder = next(
            assignment for assignment in self.assignments if assignment.role == "founder"
        )
        if not founder.is_active(on_date):
            raise OperatingModelError("founder assignment is not active on the evaluation date")
        reviewers = tuple(
            sorted(
                {
                    assignment.principal
                    for assignment in self.assignments
                    if assignment.role != "founder"
                    and domain_id in assignment.domains
                    and assignment.is_active(on_date)
                }
            )
        )
        institutional = operation != "implementation"
        return OperatingRules(
            profile="institutional" if institutional else "scoped_team" if reviewers else "founder",
            governance_status="pending" if institutional or reviewers else "not_required",
            assigned_reviewers=reviewers,
            institutional_approval_required=institutional,
        )


class OperatingModelLoader:
    """Load one ownership operating model from a bound TOML path.

    The constructor stores the path only. Validation and file I/O occur when
    :meth:`load` is called, and every call builds a fresh model.
    """

    def __init__(self, path: Path) -> None:
        """Bind an operating-model path without reading it.

        Args:
            path: UTF-8 ownership register containing the version-2 model.
        """
        self._path = path

    def load(self) -> OperatingModel:
        """Read staffing from the version-2 ownership register, retaining its role catalog.

        The loader performs one file read and no writes. It projects only the fields
        needed for operating rules; it does not validate the entire ownership register.
        Assignment dates use JSON date strings in the TOML input; native TOML date
        values cannot be encoded by the intermediate JSON conversion.

        Returns:
            Validated founder settings, projected domain-role fields and role assignments.

        Raises:
            OperatingModelError: The schema, settings, domain tables or assignments are invalid,
                TOML parsing fails, or the projected payload cannot be JSON-encoded.
            OSError: The file cannot be read.
            UnicodeError: The file is not valid UTF-8.
        """
        path = self._path
        try:
            document: dict[str, object] = tomllib.loads(path.read_text(encoding="utf-8"))
            if document.get("schema_version") != 2:
                raise OperatingModelError("operating model requires ownership schema_version 2")
            settings = document.get("operating_model")
            if not isinstance(settings, dict):
                raise OperatingModelError("operating_model requires exactly founder_principal")
            settings_table = cast(dict[str, object], settings)
            if set(settings_table) != {"founder_principal"}:
                raise OperatingModelError("operating_model requires exactly founder_principal")
            domains = document.get("domains")
            if not isinstance(domains, list) or not all(
                isinstance(domain, dict) for domain in domains
            ):
                raise OperatingModelError("operating domains must be tables")
            domain_tables = cast(list[dict[str, object]], domains)
            payload = {
                "founder_principal": settings_table["founder_principal"],
                "assignments": document.get("role_assignments"),
                "domains": [
                    {key: domain.get(key) for key in DomainRoles.model_fields}
                    for domain in domain_tables
                ],
            }
            return OperatingModel.model_validate_json(json.dumps(payload))
        except (tomllib.TOMLDecodeError, ValidationError, TypeError) as error:
            raise OperatingModelError(f"{path}: invalid operating model: {error}") from error


def load_operating_model(path: Path) -> OperatingModel:
    """Load staffing from a version-2 ownership register.

    Args:
        path: UTF-8 TOML ownership register to read.

    Returns:
        Validated founder settings, domain roles, and role assignments.

    Raises:
        OperatingModelError: If the schema or projected model is invalid.
        OSError: If the file cannot be read.
        UnicodeError: If the file is not valid UTF-8.
    """
    return OperatingModelLoader(path).load()
