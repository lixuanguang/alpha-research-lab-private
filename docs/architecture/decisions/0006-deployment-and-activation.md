# ADR 0006: Deployment and activation

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A02 |
| Status | Proposed |
| Decision owner | Platform |
| Decision date | 2026-08-25 |
| Review date | 2026-11-25 |
| Supersedes | None |
| Approval evidence | Pending; A02-F01 |

## Context

Mutable rebuilds, environment-specific artifacts, and deployment that implicitly
grants trading authority make rollback and audit unreliable. Standard services
and low-latency hosts need different mechanics but the same promotion contract.

## Decision drivers

- Build-once digest promotion, signed provenance, environment separation, policy
  verification, multidimensional rollback, and independent activation authority.
- Progressive replay, paper, shadow, and bounded-canary evidence before capital.

## Considered alternatives

- **Build independently per environment:** easy to operate initially but destroys
  artifact identity and comparison.
- **Manual package or host copy:** fast but unauditable, mutable, and unsafe.
- **Signed GitOps and immutable host lanes:** different mechanisms behind one
  release registry, promotion API, and activation envelope.

## Decision

Build once and promote only immutable signed digests. Use a GitOps-class lane for
standard services and attested immutable packages for low-latency hosts.
Deployment never activates trading; an independent, bounded, signed activation
envelope controls accounts, venues, assets, capital, limits, and schedule.

## Consequences

Every release becomes reconstructable and reversible, while signing, provenance,
registry, policy, and environment controls add operational work. This ADR grants
no deployment, credential, venue, or capital authority.

## Migration and rollout

B08 establishes artifact evidence; I01-I08 add release registry, separated
environments, configuration, identities, progressive rollout, migration, rollback,
restore, and DR. Promotion proceeds through replay, paper, shadow, and only then a
separately approved bounded canary.

## Reversal plan

Rollback selects a compatible prior binary, model, feature graph, config, limits,
schemas, and state. Halt on partial migration or identity mismatch; disable
activation, reconcile state, and restore the last verified multidimensional set.

## Review and evidence

Platform, SRE, security, and independent risk reviewers apply according to risk
class. Revisit with I01 registry evidence and before any production-capable
deployment or activation mechanism is accepted.
