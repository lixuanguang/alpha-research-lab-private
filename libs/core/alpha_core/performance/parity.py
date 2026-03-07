"""Parity testing helpers for performance boundary enforcement.

Provides ``check_feature_parity`` and ``check_simulation_parity`` to verify
that an optional accelerated implementation produces outputs within a
documented tolerance of its pure-Python baseline counterpart.

Parity policy
-------------
- Accelerated implementations MUST pass parity checks before being promoted
  as the default code path.
- Tolerance values and modes MUST be documented on the concrete accelerated
  class (not buried in test code).
- Regression CI must re-run parity checks whenever either the baseline or
  the accelerated implementation changes.
- If identical outputs are required (integer counts, categorical labels),
  use ``ToleranceMode.ABSOLUTE`` with ``tolerance=0.0``.

Usage::

    from alpha_core.performance.parity import ParityConfig, check_feature_parity
    from alpha_core.performance.interfaces import FeatureTransform

    config = ParityConfig(tolerance=1e-9)
    result = check_feature_parity(baseline, accelerated, [inputs1, inputs2], config)
    assert result.passed, result.summary
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    import alpha_core.performance.interfaces as _ifaces


# ---------------------------------------------------------------------------
# Tolerance configuration
# ---------------------------------------------------------------------------


class ToleranceMode(StrEnum):
    """How deviation between two numeric sequences is measured.

    ABSOLUTE
        Maximum absolute difference across all corresponding elements:
        ``max(|a_i - b_i|) <= tolerance``.

    RELATIVE
        Maximum relative difference, normalised by the absolute baseline
        value plus a small epsilon to avoid division by zero:
        ``max(|a_i - b_i| / (|a_i| + 1e-12)) <= tolerance``.
    """

    ABSOLUTE = "absolute"
    RELATIVE = "relative"


class ParityConfig(BaseModel):
    """Configuration controlling how parity between two implementations is checked.

    Attributes
    ----------
    tolerance:
        Maximum permitted deviation (in the units of ``mode``).
    mode:
        Whether deviation is measured in absolute or relative units.
    require_same_length:
        When ``True`` (default), length mismatches between baseline and
        accelerated outputs immediately fail parity regardless of tolerance.
    """

    model_config = ConfigDict(extra="forbid")

    tolerance: float = Field(ge=0.0, description="Max permitted deviation (>= 0).")
    mode: ToleranceMode = ToleranceMode.ABSOLUTE
    require_same_length: bool = True


# ---------------------------------------------------------------------------
# Parity result
# ---------------------------------------------------------------------------


class ParityResult(BaseModel):
    """Outcome of a single parity check run.

    Attributes
    ----------
    passed:
        ``True`` when every test case satisfies the configured tolerance.
    max_deviation:
        Largest deviation observed across all test cases and elements.
    tolerance:
        The tolerance value from the governing :class:`ParityConfig`.
    mode:
        The tolerance mode from the governing :class:`ParityConfig`.
    n_cases:
        Number of input cases checked.
    summary:
        Human-readable description of the outcome, suitable for assertion
        messages and CI logs.
    """

    model_config = ConfigDict(extra="forbid")

    passed: bool
    max_deviation: float
    tolerance: float
    mode: ToleranceMode
    n_cases: int
    summary: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _deviation(
    baseline: Sequence[float],
    accelerated: Sequence[float],
    mode: ToleranceMode,
) -> float:
    """Return the scalar deviation between two numeric sequences.

    NaN handling:
    - Both NaN at the same position → no deviation (skip).
    - One NaN, one finite at the same position → return ``math.inf``.
    - Both finite → compare normally.
    """
    if len(baseline) != len(accelerated):
        return math.inf
    if not baseline:
        return 0.0
    worst: float = 0.0
    for a, b in zip(baseline, accelerated, strict=True):
        a_nan = math.isnan(a)
        b_nan = math.isnan(b)
        if a_nan and b_nan:
            continue  # matching NaN — no deviation
        if a_nan != b_nan:
            return math.inf  # one finite, one NaN — mismatch
        if mode is ToleranceMode.ABSOLUTE:
            worst = max(worst, abs(a - b))
        else:
            worst = max(worst, abs(a - b) / (abs(a) + 1e-12))
    return worst


def _mapping_deviation(
    baseline: Mapping[str, Any],
    accelerated: Mapping[str, Any],
    mode: ToleranceMode,
) -> float:
    """Return the scalar deviation between two state mappings.

    Only numeric values (``int`` / ``float``) are compared; non-numeric
    values must be identical (otherwise ``math.inf`` is returned to fail
    the parity check).
    """
    if set(baseline.keys()) != set(accelerated.keys()):
        return math.inf
    worst: float = 0.0
    for key in baseline:
        bv = baseline[key]
        av = accelerated[key]
        if isinstance(bv, (int, float)) and isinstance(av, (int, float)):
            if mode is ToleranceMode.ABSOLUTE:
                worst = max(worst, abs(float(bv) - float(av)))
            else:
                worst = max(worst, abs(float(bv) - float(av)) / (abs(float(bv)) + 1e-12))
        elif bv != av:
            return math.inf
    return worst


# ---------------------------------------------------------------------------
# Public parity check functions
# ---------------------------------------------------------------------------


def check_feature_parity(
    baseline: _ifaces.FeatureTransform,
    accelerated: _ifaces.FeatureTransform,
    inputs: Sequence[Sequence[float]],
    config: ParityConfig,
) -> ParityResult:
    """Check that ``accelerated`` matches ``baseline`` within ``config`` for all ``inputs``.

    Parameters
    ----------
    baseline:
        The reference pure-Python implementation.
    accelerated:
        The candidate accelerated implementation to validate.
    inputs:
        One or more input sequences to use as test cases.
    config:
        Tolerance configuration.

    Returns
    -------
    ParityResult
        Passed when every case satisfies the tolerance; failed otherwise.
    """
    worst: float = 0.0
    for case in inputs:
        b_out = baseline.compute(case)
        a_out = accelerated.compute(case)
        if config.require_same_length and len(b_out) != len(a_out):
            return ParityResult(
                passed=False,
                max_deviation=math.inf,
                tolerance=config.tolerance,
                mode=config.mode,
                n_cases=len(inputs),
                summary=(f"Length mismatch: baseline={len(b_out)}, accelerated={len(a_out)}"),
            )
        worst = max(worst, _deviation(list(b_out), list(a_out), config.mode))

    passed = worst <= config.tolerance
    return ParityResult(
        passed=passed,
        max_deviation=worst,
        tolerance=config.tolerance,
        mode=config.mode,
        n_cases=len(inputs),
        summary=(
            f"PASSED ({config.mode}, tol={config.tolerance}, max_dev={worst:.3e}, "
            f"cases={len(inputs)})"
            if passed
            else f"FAILED ({config.mode}, tol={config.tolerance}, max_dev={worst:.3e}, "
            f"cases={len(inputs)})"
        ),
    )


def check_simulation_parity(
    baseline: _ifaces.SimulationKernel,
    accelerated: _ifaces.SimulationKernel,
    cases: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
    config: ParityConfig,
) -> ParityResult:
    """Check that ``accelerated`` matches ``baseline`` for all ``(state, event)`` cases.

    Parameters
    ----------
    baseline:
        The reference pure-Python kernel.
    accelerated:
        The candidate accelerated kernel to validate.
    cases:
        Sequence of ``(state, event)`` pairs to use as test cases.
    config:
        Tolerance configuration.

    Returns
    -------
    ParityResult
        Passed when every case satisfies the tolerance; failed otherwise.
    """
    worst: float = 0.0
    for state, event in cases:
        b_out = baseline.step(state, event)
        a_out = accelerated.step(state, event)
        worst = max(worst, _mapping_deviation(dict(b_out), dict(a_out), config.mode))

    passed = worst <= config.tolerance
    return ParityResult(
        passed=passed,
        max_deviation=worst,
        tolerance=config.tolerance,
        mode=config.mode,
        n_cases=len(cases),
        summary=(
            f"PASSED ({config.mode}, tol={config.tolerance}, max_dev={worst:.3e}, "
            f"cases={len(cases)})"
            if passed
            else f"FAILED ({config.mode}, tol={config.tolerance}, max_dev={worst:.3e}, "
            f"cases={len(cases)})"
        ),
    )
