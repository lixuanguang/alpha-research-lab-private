# ADR 005: Optional Acceleration Boundary

- **Status:** Accepted
- **Date:** 2026-03-07
- **Supersedes:** none
- **Related:** Foundation Stage §F6 integrated closeout, `README.LEAN_ADOPTION.md §12.4`, LA-022, ADR 004

---

## Context

The research pipeline includes compute-intensive paths that may benefit from
optional native acceleration (Numba, Rust C-extensions, or similar) in the
future.  Without a formal boundary, performance-specific code tends to:

- Mix optimisation concerns into domain modules, making them harder to test
  and reason about.
- Introduce silent numeric deviations (different floating-point evaluation
  paths) that are hard to detect and debug.
- Make it impossible to verify that a "faster" path is actually equivalent to
  the baseline before deploying it.

The two most compute-intensive current paths are:

1. **Feature transforms** — rolling/EWM statistics over probability series
   applied in `alpha_core.research.feature_runner`.
2. **Simulation kernels** — one-step mark-to-market and PnL accounting applied
   in `alpha_core.research.backtest_runner`.

---

## Decision

Introduce a formal, minimal interface boundary at
`alpha_core.performance.interfaces` (canonical) and `alpha_core.perf.interfaces`
(short-name alias):

```
FeatureTransform   – compute(values: Sequence[float]) -> Sequence[float]
SimulationKernel   – step(state: Mapping, event: Mapping) -> Mapping
```

Both protocols are `@runtime_checkable` in Python's `typing` sense, so
`isinstance` guards work without importing concrete classes.

### Promotion gate

An optional accelerated implementation **may not replace the baseline default
path** until:

1. It passes `check_feature_parity` or `check_simulation_parity` from
   `alpha_core.performance.parity` on representative workloads.
2. The tolerance used in the parity check is documented as a named constant
   on the accelerated class (not buried in test code).
3. The regression test suite in `tests/regression/test_acceleration_parity.py`
   remains green with the accelerated implementation as the `accelerated`
   argument.

### Fallback policy

When an optional accelerated backend is unavailable (import error), the caller
**must** fall back to the pure-Python baseline silently.  A missing accelerator
is not an error; it is an expected condition in development and CI environments.

Pattern::

    try:
        from accel_lib import FastRollingMean as _Impl
    except ImportError:
        from alpha_core.performance.interfaces import FeatureTransform as _Base
        _Impl = RollingMeanTransform  # pure-Python fallback

### Tolerance policy

| Compute path | Mode | Tolerance constant |
|---|---|---|
| Feature transforms (rolling, EWM) | ABSOLUTE | `FEATURE_TOLERANCE_ABSOLUTE = 1e-9` |
| Simulation kernels (mark-to-market) | ABSOLUTE | `SIMULATION_TOLERANCE_ABSOLUTE = 1e-9` |

Tighter tolerances are always permitted; looser tolerances require explicit
justification and a co-review of the affected compute path.

### Documentation modularity mapping (ADR 004 compliance)

| Content | Location |
|---|---|
| Interface contract and design rules | `alpha_core/performance/interfaces.py` (module docstring) |
| Parity harness and tolerance policy | `alpha_core/performance/parity.py` (module docstring) + `tests/regression/test_acceleration_parity.py` |
| Architecture decision | This ADR (`docs/adr/005-performance-boundary.md`) |
| Stage-implementation notes | `docs/implementation/foundation-stage.md §F6`, `docs/implementation/research-plane-mvp.md` |
| How to add an accelerated backend | `docs/guides/` (future runbook when a concrete backend is adopted) |

---

## Consequences

### Positive

- Compute-heavy paths can be replaced with faster implementations at any time
  without API changes downstream.
- Numeric deviations introduced by an accelerated path are caught by the parity
  harness before they reach production.
- The baseline path is guaranteed to remain the default and unchanged in
  behaviour; only an explicit opt-in enables an accelerated path.
- CI can validate the baseline independently of whether any accelerator package
  is installed.

### Negative / Trade-offs

- All future accelerated implementations must implement the two protocol
  methods, adding a small amount of boilerplate.
- The parity harness adds CI test time proportional to the number of
  representative workload cases (currently negligible: < 0.1 s).

### Non-goals

- This ADR does not mandate any specific accelerated backend (Numba, Rust,
  etc.); it only defines the boundary and promotion gate.
- This ADR does not apply to I/O paths, storage, or network-bound operations;
  acceleration boundaries are restricted to numeric compute kernels.
