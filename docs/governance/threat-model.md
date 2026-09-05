# Threat Model and Regulatory Control Map

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A07 |
| Operating track | Solo bootstrap |
| Package status | Partial |
| Accountable owner role | Security |
| Risk class | R2 shared sensitive governance contract |
| Dependencies | A02 and A06, provisionally ready with open findings |
| Applicable gates | QG01-QG06, QG09-QG14 |
| Machine-readable map | [Security control map](security-control-map.toml) |

## Purpose, scope, and authority

This package defines the repository's first versioned threat model and regulatory
control map. The TOML map is authoritative for identifiers and cross-references;
this document explains its review model, assumptions, limitations, and evidence.
It is subordinate to the institutional blueprint, architecture principles,
platform contracts, and quality and operations rules.

The map covers the intended platform path from governed source and external data
through artifacts, research, model promotion, deployment control, independent
risk, order management, external markets, telemetry, audit, and recovery. It
models target capabilities that later packages must implement. A07-C02 now also
links B08's repository-local artifact evidence, but that does not establish its
protected signing, registry, independent-review, or target-environment controls.
Other listed controls remain requirements or design constraints rather than
evidence that a target-environment control exists.

This is engineering governance, not legal advice. It makes no determination that
an entity, activity, product, instrument, venue, account, licence, permission,
territory, regulator, recordkeeping rule, or legal obligation applies. Only
qualified Legal and Compliance reviewers may tailor jurisdictional scope and make
applicability determinations from established operating facts.

## Assumptions and non-assumptions

The system is assumed to be a future institutional multi-asset quantitative
platform with separate research, data, model, control, risk, trading, monitoring,
and management zones. Contributors, dependencies, external data, operators,
workloads, vendors, venues, brokers, and control planes are not trusted merely
because they are internal, authenticated, or automated. Integrity, authorization,
causality, independent control, and evidence must survive compromise or failure
of one component.

The repository does not establish the actual organization, identities, accounts,
infrastructure, entitlements, network topology, market-access arrangements, or
regulated activities. Those omissions are recorded in A07-F01 and A07-F03, not
filled with invented assumptions.

## Assets and trust boundaries

The map protects eight asset groups: governed source and review evidence; build
inputs and provenance; market, reference, research, and entitlement metadata;
models and trials; configuration, limits, credentials, and activation authority;
risk decisions, orders, fills, positions, and kill state; external market-access
sessions; and audit, telemetry, surveillance, and incident evidence.

| Boundary | Trust change | Accountable owner |
| --- | --- | --- |
| TB01 contributor to governed source | Proposed content becomes reviewable only with exact-commit checks and required review | Platform |
| TB02 reviewed source to artifact registry | Explicit inputs become immutable, attributable artifacts | Security |
| TB03 external data to governed data plane | External payloads become entitled, checksummed, revision-aware causal records | Data Platform |
| TB04 research to promotion registry | Exploratory output becomes a candidate only through immutable trials, lineage, and validation | Model Validation |
| TB05 deployment control to runtime authority | Deployability remains separate from privileged activation and market authority | Security |
| TB06 strategy to independent risk and order control | Strategy intent cannot change or bypass its own external limits | Independent Risk |
| TB07 order management to external market | Authorized messages enter external state requiring conduct safeguards and reconciliation | Trading Engineering |
| TB08 runtime to audit and monitoring | Activity becomes attributable evidence whose loss or alteration is detected | SRE |

## Abuse cases and privileged actions

The twelve scenarios cover all required threat classes:

- **Privileged access:** source-governance bypass and risk or kill-control bypass.
- **Software supply chain:** dependency or artifact substitution and vulnerable or
  malicious build inputs.
- **Data entitlement:** unauthorized use or exfiltration and causal data poisoning
  or silent correction.
- **Model risk:** hidden selection or self-validation and unauthorized model or
  feature substitution.
- **Market integrity:** manipulative or misleading order behavior and venue,
  broker, or account-control misuse.
- **Operational resilience:** state divergence, duplicate execution, lost orders,
  suppressed telemetry, or failed recovery.

Privileged actions include changing protected-source or evidence policy; signing,
promoting, or admitting artifacts; granting data or infrastructure access;
rotating secrets and keys; approving model candidates; changing limits,
throttles, venue or account authorization, and kill state; deploying, activating,
rolling back, or restarting runtime lanes; overriding surveillance or
reconciliation findings; and deleting or changing retained evidence. A07-C03
requires time-bound least privilege, separation of duties, dual control for
critical actions, immutable session evidence, and tested revocation or break-glass
closure. This package does not grant any of those privileges.

## Control and evidence model

Each A07-C01 through A07-C12 control records one accountable owner, independent
review roles, preventive/detective/response/recovery functions, implementing
roadmap packages, a test procedure, a fail-safe response, and one or more evidence
sources. Control owners cannot independently review their own controls. Evidence
is either `available` at a contained repository path or `deferred` with future
packages and a closure condition; ambiguous or unsupported status fails closed.

Only A07-C12, map-contract integrity, is currently `repository_local`. The other
controls are `planned`. Their deferred evidence includes protected-forge results,
SBOM and provenance admission, identity and secret exercises, data entitlement
tests, independent model validation, risk replay and kill game days, algorithm
certification, market-conduct surveillance exercises, independent reconciliation,
recovery exercises, and qualified applicability review.

## Jurisdictional source map

The sources were verified against official publishers on 2026-08-30. They are
starting points for qualified review, not an exhaustive obligation register.

| Profile | Engineering topic | Status and limitation |
| --- | --- | --- |
| United Kingdom | FCA MAR 7A systems, testing, limits, monitoring, continuity, and records; FCA supervisory observations on governance and surveillance | `requires_legal_review`; regulated-firm, permission, activity, venue, instrument, and territorial facts are unknown |
| Singapore | Securities and Futures Act sections 197-201 market-conduct risks | `requires_legal_review`; entity, licence, product, market, account, conduct, and territorial facts are unknown |
| United States federal | SEC Rule 15c3-5 market-access controls and interagency model-risk guidance | `requires_legal_review`; broker-dealer, market-access, banking-organization, activity, product, and regulator facts are unknown |
| Global reference | NIST Secure Software Development Framework 1.1 | `reference_only`; voluntary engineering reference, not a binding rule or legal conclusion |

Official sources: [FCA MAR 7A](https://handbook.fca.org.uk/handbook/mar7a?timeline=true),
[FCA algorithmic-trading controls review](https://www.fca.org.uk/publications/multi-firm-reviews/algorithmic-trading-controls-high-level-observations),
[Singapore SFA sections 197-201](https://sso.agc.gov.sg/Act/SFA2001?ProvIds=pr197-%2Cpr198-%2Cpr199-%2Cpr200-%2Cpr201-),
[SEC Rule 15c3-5 adopting release](https://www.sec.gov/rules-regulations/2011/06/risk-management-controls-brokers-or-dealers-market-access),
[Federal Reserve SR 26-2](https://www.federalreserve.gov/frrs/guidance/supervisory-guidance-on-model-risk-management.htm),
and [NIST SP 800-218](https://csrc.nist.gov/pubs/sp/800/218/final).

Adding, removing, or changing a jurisdiction, source, status, or control mapping
requires Security and Compliance review. Legal/Compliance must re-verify sources
by each profile's due date and whenever operating facts or relevant rules change.
The machine contract requires source verification within 31 days of the map's
`as_of_date` and schedules the next jurisdiction review no more than 93 days
later; changing the map date therefore cannot silently preserve stale evidence.

## Validation and query interface

`make security-controls-check` validates strict TOML fields and types, package
dependencies, risk class and gate metadata, stable and ordered identifiers, A03
owner roles, independent reviewers, cross-references, complete threat categories,
asset/boundary/control/evidence coverage, implementation status and packages,
repository path containment, credential-free HTTPS authority URLs pinned to the
official publisher host, source/profile consistency, legal-mapping ownership and
review evidence, non-conclusive applicability status, bounded review dates, exact
findings, and a typed immutable synthetic-evidence profile binding the accountable
owner, every classification fact, exact gate statuses, partial findings, and the
prohibition on approvals, waivers, or caller-added gates.

The CLI emits byte-stable JSON and supports one filter at a time:

```sh
PYTHONPATH=src uv run --frozen python -m alpha_research.security_controls --json
PYTHONPATH=src uv run --frozen python -m alpha_research.security_controls --threat-category market_integrity
PYTHONPATH=src uv run --frozen python -m alpha_research.security_controls --control-owner-role security
PYTHONPATH=src uv run --frozen python -m alpha_research.security_controls --jurisdiction SG
```

## Evidence policy

Applicable control definitions live in the
[quality-gate catalog](../architecture/operations.md#quality-gate-catalog). Exact
A07 gate state and finding closure conditions live in
[security-control-map.toml](security-control-map.toml); current state and finding
IDs are rendered in the [program status](program-status.md).

## Migration, rollout, rollback, monitoring, and runbook

Schema version 1 is additive and has no database, runtime state, or consumer
migration. Future incompatible map changes require a new schema version and a
compatibility window. Rollout adds repository validation only; it does not deploy
or activate a target control. Rollback is a reviewed Git revert that retains prior
maps and evidence in history.

Pre-commit, CI, and CLI failures are the current monitoring and stop signal.
Owners must correct the map or explicitly retain an open finding; bypassing the
check does not close risk. No production dashboard, alert route, incident
runbook, kill path, credential, market session, or recovery authority is created
by A07.

## Governance references

The [development workflow](workflow.md) owns daily evidence and validation. The
[program status](program-status.md) owns the current finding and handover view.
Qualified legal applicability and operation-specific controls remain external to
this repository contract; A07 grants no release, activation, market, credential,
capital or risk authority.
