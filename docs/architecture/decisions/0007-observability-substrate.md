# ADR 0007: Observability substrate

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

Platform metrics alone cannot distinguish software health from stale data, model
degradation, execution cost, risk, or economic failure. Telemetry also must not
block latency-sensitive risk, order, market-data, or kill paths.

## Decision drivers

- Vendor-neutral correlation across release, strategy, model, data, config,
  account, asset, venue, order, host, and incident.
- Stable naming/units, bounded cardinality, explicit retention, SLOs, actionable
  alerts, and non-blocking hot-path behavior.

## Considered alternatives

- **Independent logs and dashboards per service:** simple locally but prevents
  end-to-end audit and control decisions.
- **Vendor-specific instrumentation:** expedient but couples domain contracts to
  one backend.
- **OpenTelemetry-based contracts with Prometheus/Grafana-class backends:** keeps
  correlation stable while allowing replaceable storage and visualization.

## Decision

Use OpenTelemetry as the telemetry/context substrate with Prometheus/Grafana-class
metric and dashboard capabilities. Define shared trace, metric, log, audit, units,
cardinality, clock-skew, sensitive-data, sampling, and retention conventions.
Latency-sensitive emission is bounded and non-blocking; loss is observable.

## Consequences

Technical and economic planes can drive explicit continue, throttle, hedge,
disable, and rollback decisions. Schema governance, cardinality budgets, storage
costs, and privacy/entitlement review become mandatory.

## Migration and rollout

J01-J08 introduce contracts, collectors, SLOs, monitors, TCA/PnL attribution,
alerts, runbooks, audit, and game days. Instrumentation begins with synthetic
probes and cannot claim active monitoring before target-environment alert tests.

## Reversal plan

Keep canonical telemetry and audit schemas independent of a backend. During a
backend change, dual-emit within a bounded budget, compare loss/cardinality and
alert behavior, then restore the last verified collector path on divergence.

## Review and evidence

Platform/SRE and security review naming, correlation, loss, sensitive-data,
cardinality, performance, retention, and synthetic-alert evidence. Revisit when
J01 selects concrete backends or a hot-path budget changes.

