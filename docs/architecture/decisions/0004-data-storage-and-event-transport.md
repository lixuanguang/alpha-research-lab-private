# ADR 0004: Data storage and event transport

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

Immutable raw evidence, revision-aware point-in-time analytics, online serving,
event delivery, audit, and trading state have different consistency, latency,
retention, and recovery requirements. One database cannot serve them all safely.

## Decision drivers

- Immutable source integrity, as-of queries, atomic publication, corrections,
  lineage, replay, entitlements, bounded serving freshness, and recoverable events.
- Replaceable providers behind canonical contracts rather than vendor semantics.

## Considered alternatives

- **One relational database:** operationally familiar but conflates workloads and
  failure domains.
- **Provider-specific stores exposed directly:** quick to start but leaks vendor
  identity and blocks portable replay.
- **Purpose-specific tiers:** immutable object landing and an Iceberg-style PIT
  lakehouse, Kafka/Redpanda-class transport, plus owned serving/state stores.

## Decision

Adopt purpose-specific storage and transport classes behind canonical interfaces.
Raw data is append-only and checksummed; curated data uses revision-aware snapshot
manifests; corrections append; event delivery is replayable and idempotent. Exact
products and service topology require later ADRs based on D/H/J requirements.

## Consequences

Isolation and causal evidence improve, at the cost of multiple systems,
reconciliation, and lifecycle ownership. No store becomes canonical merely because
it is convenient for the bootstrap or a first digital-asset workload.

## Migration and rollout

D01-D08 implement tiers in dependency order, retain source pointers, validate
entitlements and corrections, and prove snapshot/replay identity before consumers
cut over. Online state is introduced only with freshness and fallback contracts.

## Reversal plan

Keep immutable source and portable manifests during any provider change. Dual-read
and reconcile snapshots/events, stop publication on divergence, and restore the
last verified reader/writer set within its compatibility window.

## Review and evidence

Data, platform, security, and SRE owners review product selections with PIT,
throughput, restore, entitlement, cost, and failure evidence. Revisit before D01
selects an external control plane or persistence product.
