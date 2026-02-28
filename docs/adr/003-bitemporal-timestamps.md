# ADR 003: Bitemporal Timestamps

- Status: Accepted
- Date: 2026-02-28

## Context

Prediction market feeds can arrive late, out of order, or be corrected. Research reproducibility and live diagnostics need both venue-time and ingest-time tracking.

## Decision

All canonical events store two timestamps:

- `ts_event`: when the venue says the event occurred
- `ts_record`: when our system recorded the event

Validation rule: `ts_event <= ts_record`.

## Consequences

- We can detect feed latency and ordering issues explicitly.
- As-of dataset construction is less prone to look-ahead bias.
- Storage and DuckDB analytics preserve both temporal perspectives end to end.
