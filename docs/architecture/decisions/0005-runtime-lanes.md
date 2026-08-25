# ADR 0005: Runtime lanes

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

Batch research, standard event-driven services, and ultra-low-latency execution
need different scheduling, dependency, telemetry, and failure profiles while
sharing contracts, evidence, risk, and audit controls.

## Decision drivers

- Isolated blast radii and security/performance profiles without duplicating the
  strategy kernel or weakening release, risk, rollback, and observability.
- A deliberately narrow first target that does not make one lane universal.

## Considered alternatives

- **One universal orchestrated runtime:** simple control plane but unsuitable for
  every latency and isolation profile.
- **Independent stacks with copied contracts:** flexible but creates research/live
  drift and fragmented governance.
- **Three governed lanes:** batch/HPC, standard live services, and a separately
  justified low-latency host lane sharing the thin waist.

## Decision

Maintain batch/HPC, standard live, and low-latency runtime lanes. The low-latency
hot path excludes general control-plane dependencies but must report the same
release identity, consume compatible schemas, obey independent risk, and emit
bounded audit/telemetry. Mode differences use injected adapters and configuration.

## Consequences

Workloads receive appropriate isolation and budgets, while certification and
operations must cover more than one runtime profile. A low-latency lane is not
created until a measured strategy requirement justifies its cost.

## Migration and rollout

H02 defines runtime composition; I05 and I06 implement standard and low-latency
deployment lanes separately. The initial production certification path defaults
to the standard lane unless measurements approve otherwise.

## Reversal plan

Disable a lane that cannot meet safety, recovery, or operational budgets and move
only compatible workloads to a previously certified lane. Re-certify performance,
state, telemetry, and failure behavior before any activation.

## Review and evidence

Platform/SRE review requires workload budgets, failure domains, dependency and
telemetry profiles, recovery tests, and measured justification. Review before any
low-latency I06 implementation or change in first-target latency posture.
