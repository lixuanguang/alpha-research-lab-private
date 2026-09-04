"""Resolve development and institutional obligations from actual role assignments."""

from __future__ import annotations

import json
import re
import tomllib
from datetime import date
from pathlib import Path
from typing import Literal, Self

from pydantic import ValidationError, field_validator, model_validator

from alpha_research_governance._models import ImmutableModel

Operation = Literal["implementation", "institutional_acceptance", "release", "activation"]
GovernanceStatus = Literal["not_required", "pending", "complete"]
ImplementationStatus = Literal["planned", "in_progress", "complete", "blocked"]


class OperatingModelError(ValueError):
    """Report invalid staffing or an unsupported operating scope."""


class RoleAssignment(ImmutableModel):
    """Record one person's role and effective domains, without inventing independence."""

    principal: str
    role: str
    domains: tuple[str, ...]
    status: Literal["planned", "active", "inactive"]
    effective_from: date
    effective_until: date | None = None

    @field_validator("principal")
    @classmethod
    def individual_principal(cls, value: str) -> str:
        """Require an individual forge identity and canonicalize its case."""
        if re.fullmatch(r"@[A-Za-z0-9][A-Za-z0-9-]*", value) is None:
            raise ValueError("principal must be an individual @user")
        return value.casefold()

    @model_validator(mode="after")
    def coherent_scope(self) -> Self:
        """Reject empty or duplicated scopes and reversed effective intervals."""
        if not self.domains or len(set(self.domains)) != len(self.domains):
            raise ValueError("assignment domains must be non-empty and unique")
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("effective_until must follow effective_from")
        return self

    def is_active(self, on_date: date) -> bool:
        """Use active only for joined people with working access in this interval."""
        return (
            self.status == "active"
            and self.effective_from <= on_date
            and (self.effective_until is None or on_date < self.effective_until)
        )


class DomainRoles(ImmutableModel):
    """Retain the institutional role catalog for one domain."""

    domain_id: str
    accountable_role: str
    required_review_roles: tuple[str, ...]
    independent_review_roles: tuple[str, ...]
    escalation_roles: tuple[str, ...]


class OperatingRules(ImmutableModel):
    """Separate scoped handover obligations from permission to finish engineering."""

    profile: Literal["founder", "scoped_team", "institutional"]
    governance_status: GovernanceStatus
    assigned_reviewers: tuple[str, ...]
    institutional_approval_required: bool

    def require_local_completion(
        self, *, repository_local_status: str, technical_finding_ids: tuple[str, ...]
    ) -> None:
        """Accept passing engineering evidence independently of organizational handover.

        Raises:
            OperatingModelError: Evidence fails, technical issues remain, or the
                requested operation needs institutional rather than local acceptance.
        """
        if self.institutional_approval_required:
            raise OperatingModelError("local completion cannot authorize institutional operations")
        if repository_local_status != "passed" or technical_finding_ids:
            raise OperatingModelError(
                "completion requires passing repository-local evidence and no technical findings"
            )


class OperatingModel(ImmutableModel):
    """Resolve the founder policy and hiring trigger for explicitly assigned domains."""

    founder_principal: str
    domains: tuple[DomainRoles, ...]
    assignments: tuple[RoleAssignment, ...]

    @model_validator(mode="after")
    def valid_assignments(self) -> Self:
        """Reject unknown roles/scopes and duplicate or misleading identities."""
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
        """Resolve a domain at an explicit date; planned hires never activate rules."""
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


def load_operating_model(path: Path) -> OperatingModel:
    """Read staffing from the version-2 ownership register, retaining its role catalog."""
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        if document.get("schema_version") != 2:
            raise OperatingModelError("operating model requires ownership schema_version 2")
        settings = document.get("operating_model")
        if not isinstance(settings, dict) or set(settings) != {"founder_principal"}:
            raise OperatingModelError("operating_model requires exactly founder_principal")
        domains = document.get("domains")
        if not isinstance(domains, list) or not all(isinstance(domain, dict) for domain in domains):
            raise OperatingModelError("operating domains must be tables")
        payload = {
            "founder_principal": settings["founder_principal"],
            "assignments": document.get("role_assignments"),
            "domains": [
                {key: domain.get(key) for key in DomainRoles.model_fields} for domain in domains
            ],
        }
        return OperatingModel.model_validate_json(json.dumps(payload))
    except (tomllib.TOMLDecodeError, ValidationError, TypeError) as error:
        raise OperatingModelError(f"{path}: invalid operating model: {error}") from error
