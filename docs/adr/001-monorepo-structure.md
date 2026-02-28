# ADR 001: Monorepo Structure

- Status: Accepted
- Date: 2026-02-28

## Context

The platform has three application entrypoints (data collector, live system, research) and one shared core library. We need tight coordination between domain models, adapters, and storage while keeping release and CI friction low.

## Decision

Use a monorepo layout with:

- `libs/core/alpha_core` for shared typed domain logic
- `apps/*` for entrypoint-specific CLIs and orchestration
- `tests/` for unit and integration tests across all modules
- `config/`, `infra/`, `docs/adr/`, and `data/schemas/` as top-level operational assets

## Consequences

- Cross-module refactors are simpler and atomic.
- Shared standards (`ruff`, `mypy`, `pytest`) are enforced uniformly.
- CI remains straightforward but repository size may grow over time.
