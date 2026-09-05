# Architecture Decision Log

## A02 package record

| Field | Value |
| --- | --- |
| Package | A02 - Architecture principles and ADR framework |
| Operating track | Solo bootstrap |
| Institutional acceptance | Partial; implementation is tracked in the program register |
| Accountable owner role | Platform |
| Risk class | R0 |
| Applicable gates | QG01, QG13 |
| Rollout | Repository documentation and CI enforcement only |
| Rollback | Reviewed revert or superseding ADR; preserve history |

Repository-local A02 evidence comprises the
[architecture principles](../principles.md), the
[governance/deprecation/exception process](../governance.md), this log, the
[ADR template](template.md), the initial proposed decisions below, and the
deterministic checker and tests executed by the root and CI interfaces.
The checker fails closed when a log row's ID, title, link target, status, owner,
or review date differs from its ADR metadata.

The original thirteen records retain their recorded `Proposed` status. New
decisions may use `Founder accepted` under the
[current operating policy](../../governance/domain-ownership.md#current-operating-policy).
No historical approval is invented. A02 implementation completion is recorded
separately from institutional acceptance in the program register.

## Decision records

| ID | Decision | Status | Owner | Review date |
| --- | --- | --- | --- | --- |
| 0001 | [Build and developer tooling](0001-build-and-developer-tooling.md) | Proposed | Platform | 2026-11-25 |
| 0002 | [Language and runtime boundaries](0002-language-runtime-boundaries.md) | Proposed | Platform | 2026-11-25 |
| 0003 | [Schema and analytical interchange](0003-schema-and-analytical-interchange.md) | Proposed | Platform | 2026-11-25 |
| 0004 | [Data storage and event transport](0004-data-storage-and-event-transport.md) | Proposed | Platform | 2026-11-25 |
| 0005 | [Runtime lanes](0005-runtime-lanes.md) | Proposed | Platform | 2026-11-25 |
| 0006 | [Deployment and activation](0006-deployment-and-activation.md) | Proposed | Platform | 2026-11-25 |
| 0007 | [Observability substrate](0007-observability-substrate.md) | Proposed | Platform | 2026-11-25 |
| 0008 | [Pydantic boundary models](0008-pydantic-boundary-models.md) | Proposed | Platform | 2026-11-30 |
| 0009 | [Remote execution service](0009-remote-execution-service.md) | Proposed | Platform | 2026-12-01 |
| 0010 | [Pydantic instrument-identity models](0010-pydantic-instrument-identity-models.md) | Proposed | Domain Architecture | 2026-12-02 |
| 0011 | [Versioned venue-calendar adapter](0011-versioned-venue-calendar-adapter.md) | Proposed | Domain Architecture | 2026-12-03 |
| 0012 | [Wheel-only source admission](0012-wheel-only-source-admission.md) | Proposed | Platform | 2026-12-03 |
| 0013 | [Explicit financial units and conventions](0013-explicit-financial-units-and-conventions.md) | Proposed | Domain Architecture | 2026-10-04 |
| 0014 | [Founder implementation acceptance](0014-founder-implementation-acceptance.md) | Founder accepted | platform | 2026-12-04 |

## Closed validation evidence

| Finding | Evidence | Result |
| --- | --- | --- |
| A02-F02 | [PR #5 hosted validation record](https://github.com/lixuanguang/alpha-research-lab-private/pull/5) | The PR record binds its exact head commit to the retained successful architecture-governance job |

## Governance references

The A02 acceptance finding is rendered in the
[program status](../../governance/program-status.md); the ADR validator retains its
closure contract. The [development workflow](../../governance/workflow.md) owns
daily evidence. ADR status records decisions only and grants no deployment or
activation authority.
