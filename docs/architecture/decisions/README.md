# Architecture Decision Log

## A02 package record

| Field | Value |
| --- | --- |
| Package | A02 - Architecture principles and ADR framework |
| Operating track | Solo bootstrap |
| Status | Partial |
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

The eleven records remain `Proposed` because solo-bootstrap implementation cannot
manufacture Code Owner acceptance. This package is therefore partial even when
all repository-local checks pass.

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

## Closed validation evidence

| Finding | Evidence | Result |
| --- | --- | --- |
| A02-F02 | [PR #5 hosted validation record](https://github.com/lixuanguang/alpha-research-lab-private/pull/5) | The PR record binds its exact head commit to the retained successful architecture-governance job |

## Open findings

| Finding | Owner | Unavailable evidence | Closure condition |
| --- | --- | --- | --- |
| A02-F01 | Platform Code Owner | Independent commit-bound review and acceptance of the principles, process, and proposed ADRs | A named Code Owner reviews the exact change, resolves findings, records approval, and changes accepted records deliberately |

This finding is not a waiver. A02 remains partial until it closes; later
provisional packages cannot convert the records to accepted or claim a wave exit.

## Review split plan

Because the complete A02 epic exceeds the preferred 400-line review target, it
should be reviewed in three dependency-ordered slices if opened as merge requests:

1. `A02a`: principles, dependency rules, ADR lifecycle, deprecation, and exception
   process;
2. `A02b`: template, decision log, and ten proposed decisions;
3. `A02c`: deterministic checker, boundary/failure tests, root command, and hosted
   CI integration.

Each slice retains A02 as its roadmap epic. No slice alone satisfies A02 exit
evidence, and acceptance of later slices cannot compensate for a finding in an
earlier slice.

## Non-goals

A02 does not assign CODEOWNERS (A03), classify changes with policy-as-code (A04),
define SHA-bound evidence bundles (A05), create the target topology (B01), install
the target toolchains (B02-B03), or deploy/activate any runtime.
