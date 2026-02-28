# ADR 002: Canonical Event Model

- Status: Accepted
- Date: 2026-02-28

## Context

Each venue exposes different event payload shapes. The research and live systems require a stable data contract to avoid venue-specific branching throughout the stack.

## Decision

Adopt Pydantic-based canonical event models in `alpha_core.events.models`:

- `CanonicalMarketEvent` base
- `CanonicalTrade`
- `CanonicalBookSnapshot`
- `CanonicalOHLCV`
- `CanonicalMetadataUpdate`

Key invariants:

- UTC timestamps only
- Deterministic SHA256 `event_id`
- Prediction-market price bounds in `[0, 1]`
- Explicit schema versioning (`schema_version`)

## Consequences

- Storage and analytics layers can rely on one schema contract.
- Model-level validation catches malformed vendor payload mappings early.
- New venues can be integrated through adapters without changing downstream APIs.
