"""Unit tests for alpha_core.performance (13.2 — Optional Performance Boundary Contract).

Covers:
- Protocol isinstance conformance for FeatureTransform and SimulationKernel
- ParityConfig construction and field validation
- ParityResult construction
- check_feature_parity: identical outputs pass
- check_feature_parity: deviation within tolerance passes
- check_feature_parity: deviation exceeding tolerance fails
- check_feature_parity: length mismatch with require_same_length=True fails
- check_feature_parity: length mismatch with require_same_length=False is measured
- check_simulation_parity: identical state transitions pass
- check_simulation_parity: numeric deviation within tolerance passes
- check_simulation_parity: numeric deviation beyond tolerance fails
- check_simulation_parity: non-numeric key mismatch fails
- ToleranceMode.RELATIVE vs ABSOLUTE comparisons
- Module importability and alpha_core.__all__ coverage
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from pydantic import ValidationError

import alpha_core
import alpha_core.performance as perf
import alpha_core.performance.interfaces as perf_interfaces
import alpha_core.performance.parity as perf_parity

# ---------------------------------------------------------------------------
# Stub implementations
# ---------------------------------------------------------------------------


class _IdentityTransform:
    """Baseline: returns input unchanged."""

    @property
    def name(self) -> str:
        return "identity"

    def compute(self, values: Sequence[float]) -> Sequence[float]:
        return list(values)


class _ScaledTransform:
    """Accelerated stub: multiplies every value by a fixed scale factor."""

    def __init__(self, scale: float) -> None:
        self._scale = scale

    @property
    def name(self) -> str:
        return f"scaled_{self._scale}"

    def compute(self, values: Sequence[float]) -> Sequence[float]:
        return [v * self._scale for v in values]


class _ShortenTransform:
    """Returns one fewer element than the input (deliberately mismatched)."""

    @property
    def name(self) -> str:
        return "shorten"

    def compute(self, values: Sequence[float]) -> Sequence[float]:
        return list(values)[:-1] if values else []


class _PassthroughKernel:
    """Baseline: returns state unchanged."""

    @property
    def name(self) -> str:
        return "passthrough"

    def step(
        self, state: Mapping[str, Any], event: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        return dict(state)


class _OffsetPriceKernel:
    """Accelerated stub: adds a small constant to the 'price' key."""

    def __init__(self, offset: float) -> None:
        self._offset = offset

    @property
    def name(self) -> str:
        return f"offset_price_{self._offset}"

    def step(
        self, state: Mapping[str, Any], event: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        result = dict(state)
        if "price" in result and isinstance(result["price"], (int, float)):
            result["price"] = result["price"] + self._offset
        return result


class _WrongKeyKernel:
    """Returns a state with an extra unexpected key."""

    @property
    def name(self) -> str:
        return "wrong_key"

    def step(
        self, state: Mapping[str, Any], event: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        result = dict(state)
        result["__spurious__"] = 999
        return result


# ---------------------------------------------------------------------------
# 1. Protocol isinstance checks
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_feature_transform_isinstance(self) -> None:
        assert isinstance(_IdentityTransform(), perf_interfaces.FeatureTransform)

    def test_simulation_kernel_isinstance(self) -> None:
        assert isinstance(_PassthroughKernel(), perf_interfaces.SimulationKernel)

    def test_scaled_transform_isinstance(self) -> None:
        assert isinstance(_ScaledTransform(1.0), perf_interfaces.FeatureTransform)

    def test_passthrough_kernel_isinstance(self) -> None:
        assert isinstance(_PassthroughKernel(), perf_interfaces.SimulationKernel)

    def test_plain_object_fails_feature_transform(self) -> None:
        assert not isinstance(object(), perf_interfaces.FeatureTransform)

    def test_plain_object_fails_simulation_kernel(self) -> None:
        assert not isinstance(object(), perf_interfaces.SimulationKernel)


# ---------------------------------------------------------------------------
# 2. ParityConfig validation
# ---------------------------------------------------------------------------


class TestParityConfig:
    def test_default_mode_is_absolute(self) -> None:
        cfg = perf_parity.ParityConfig(tolerance=1e-9)
        assert cfg.mode is perf_parity.ToleranceMode.ABSOLUTE
        assert cfg.require_same_length is True

    def test_relative_mode(self) -> None:
        cfg = perf_parity.ParityConfig(
            tolerance=1e-6, mode=perf_parity.ToleranceMode.RELATIVE
        )
        assert cfg.mode is perf_parity.ToleranceMode.RELATIVE

    def test_zero_tolerance_allowed(self) -> None:
        cfg = perf_parity.ParityConfig(tolerance=0.0)
        assert cfg.tolerance == 0.0

    def test_negative_tolerance_rejected(self) -> None:
        with pytest.raises(ValidationError):
            perf_parity.ParityConfig(tolerance=-0.001)

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            perf_parity.ParityConfig(tolerance=1e-9, unknown="x")  # type: ignore[call-arg]

    def test_require_same_length_false(self) -> None:
        cfg = perf_parity.ParityConfig(tolerance=1.0, require_same_length=False)
        assert cfg.require_same_length is False


# ---------------------------------------------------------------------------
# 3. check_feature_parity
# ---------------------------------------------------------------------------


_INPUTS: list[list[float]] = [
    [0.1, 0.2, 0.3, 0.5, 0.8],
    [0.9, 0.85, 0.7, 0.55, 0.4],
    [0.5, 0.5, 0.5],
]

_CFG_TIGHT = perf_parity.ParityConfig(tolerance=0.0)
_CFG_LOOSE = perf_parity.ParityConfig(tolerance=0.01)
_CFG_RELATIVE = perf_parity.ParityConfig(
    tolerance=1e-6, mode=perf_parity.ToleranceMode.RELATIVE
)


class TestCheckFeatureParity:
    def test_identical_baseline_passes(self) -> None:
        baseline = _IdentityTransform()
        # accelerated is another identity (same outputs)
        accelerated = _IdentityTransform()
        result = perf_parity.check_feature_parity(
            baseline, accelerated, _INPUTS, _CFG_TIGHT
        )
        assert result.passed
        assert result.max_deviation == 0.0
        assert result.n_cases == len(_INPUTS)

    def test_within_tolerance_passes(self) -> None:
        baseline = _IdentityTransform()
        accelerated = _ScaledTransform(1.005)  # 0.5 % off
        cfg = perf_parity.ParityConfig(tolerance=0.01)
        result = perf_parity.check_feature_parity(baseline, accelerated, _INPUTS, cfg)
        assert result.passed
        assert result.max_deviation <= 0.01

    def test_beyond_tolerance_fails(self) -> None:
        baseline = _IdentityTransform()
        accelerated = _ScaledTransform(2.0)  # doubles all values
        result = perf_parity.check_feature_parity(
            baseline, accelerated, _INPUTS, _CFG_TIGHT
        )
        assert not result.passed
        assert result.max_deviation > 0.0
        assert "FAILED" in result.summary

    def test_passed_summary_label(self) -> None:
        baseline = _IdentityTransform()
        accelerated = _IdentityTransform()
        result = perf_parity.check_feature_parity(
            baseline, accelerated, _INPUTS, _CFG_TIGHT
        )
        assert "PASSED" in result.summary

    def test_length_mismatch_fails_with_require_same_length(self) -> None:
        baseline = _IdentityTransform()
        accelerated = _ShortenTransform()
        result = perf_parity.check_feature_parity(
            baseline, accelerated, _INPUTS, _CFG_TIGHT
        )
        assert not result.passed
        assert result.max_deviation == math.inf

    def test_length_mismatch_ignored_without_require_same_length(self) -> None:
        """With require_same_length=False, length differences are included in deviation."""
        baseline = _IdentityTransform()
        accelerated = _ShortenTransform()
        # _deviation returns inf for length mismatches regardless of the flag;
        # the flag only controls whether we early-exit vs let _deviation handle it.
        cfg = perf_parity.ParityConfig(tolerance=1.0, require_same_length=False)
        result = perf_parity.check_feature_parity(
            baseline, accelerated, _INPUTS, cfg
        )
        # _deviation returns inf for unequal lengths → still fails
        assert not result.passed

    def test_empty_inputs_passes(self) -> None:
        baseline = _IdentityTransform()
        accelerated = _IdentityTransform()
        result = perf_parity.check_feature_parity(
            baseline, accelerated, [], _CFG_TIGHT
        )
        assert result.passed
        assert result.n_cases == 0

    def test_relative_mode_tight(self) -> None:
        baseline = _IdentityTransform()
        accelerated = _ScaledTransform(1.0 + 1e-10)  # tiny relative error
        result = perf_parity.check_feature_parity(
            baseline, accelerated, _INPUTS, _CFG_RELATIVE
        )
        assert result.passed

    def test_relative_mode_fail(self) -> None:
        baseline = _IdentityTransform()
        accelerated = _ScaledTransform(1.1)  # 10% relative error
        cfg = perf_parity.ParityConfig(
            tolerance=1e-6, mode=perf_parity.ToleranceMode.RELATIVE
        )
        result = perf_parity.check_feature_parity(
            baseline, accelerated, _INPUTS, cfg
        )
        assert not result.passed

    def test_result_fields_present(self) -> None:
        baseline = _IdentityTransform()
        accelerated = _IdentityTransform()
        result = perf_parity.check_feature_parity(
            baseline, accelerated, _INPUTS, _CFG_TIGHT
        )
        assert isinstance(result.passed, bool)
        assert isinstance(result.max_deviation, float)
        assert isinstance(result.summary, str)
        assert result.tolerance == 0.0
        assert result.mode is perf_parity.ToleranceMode.ABSOLUTE


# ---------------------------------------------------------------------------
# 4. check_simulation_parity
# ---------------------------------------------------------------------------


_STATE: dict[str, Any] = {"price": 0.55, "position": 10, "label": "active"}
_EVENT: dict[str, Any] = {"type": "fill", "size": 5}
_SIM_CASES: list[tuple[dict[str, Any], dict[str, Any]]] = [
    ({"price": 0.55, "position": 10, "label": "open"}, {"type": "fill", "size": 5}),
    ({"price": 0.40, "position": 0, "label": "open"}, {"type": "trade", "size": 20}),
    ({"price": 0.80, "position": -3, "label": "open"}, {"type": "cancel", "size": 0}),
]


class TestCheckSimulationParity:
    def test_identical_kernels_pass(self) -> None:
        baseline = _PassthroughKernel()
        accelerated = _PassthroughKernel()
        result = perf_parity.check_simulation_parity(
            baseline, accelerated, _SIM_CASES, _CFG_TIGHT
        )
        assert result.passed
        assert result.max_deviation == 0.0

    def test_tiny_offset_within_tolerance(self) -> None:
        baseline = _PassthroughKernel()
        accelerated = _OffsetPriceKernel(offset=1e-12)
        cfg = perf_parity.ParityConfig(tolerance=1e-9)
        result = perf_parity.check_simulation_parity(
            baseline, accelerated, _SIM_CASES, cfg
        )
        assert result.passed

    def test_large_offset_fails(self) -> None:
        baseline = _PassthroughKernel()
        accelerated = _OffsetPriceKernel(offset=0.05)
        result = perf_parity.check_simulation_parity(
            baseline, accelerated, _SIM_CASES, _CFG_TIGHT
        )
        assert not result.passed

    def test_extra_key_in_output_fails(self) -> None:
        baseline = _PassthroughKernel()
        accelerated = _WrongKeyKernel()
        result = perf_parity.check_simulation_parity(
            baseline, accelerated, _SIM_CASES, _CFG_LOOSE
        )
        assert not result.passed

    def test_empty_cases_passes(self) -> None:
        baseline = _PassthroughKernel()
        accelerated = _PassthroughKernel()
        result = perf_parity.check_simulation_parity(
            baseline, accelerated, [], _CFG_TIGHT
        )
        assert result.passed
        assert result.n_cases == 0

    def test_n_cases_matches_input(self) -> None:
        baseline = _PassthroughKernel()
        accelerated = _PassthroughKernel()
        result = perf_parity.check_simulation_parity(
            baseline, accelerated, _SIM_CASES, _CFG_TIGHT
        )
        assert result.n_cases == len(_SIM_CASES)

    def test_summary_contains_passed(self) -> None:
        baseline = _PassthroughKernel()
        accelerated = _PassthroughKernel()
        result = perf_parity.check_simulation_parity(
            baseline, accelerated, _SIM_CASES, _CFG_TIGHT
        )
        assert "PASSED" in result.summary

    def test_summary_contains_failed(self) -> None:
        baseline = _PassthroughKernel()
        accelerated = _OffsetPriceKernel(offset=0.5)
        result = perf_parity.check_simulation_parity(
            baseline, accelerated, _SIM_CASES, _CFG_TIGHT
        )
        assert "FAILED" in result.summary


# ---------------------------------------------------------------------------
# 5. ToleranceMode parametrized
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", list(perf_parity.ToleranceMode))
def test_parity_config_all_modes(mode: perf_parity.ToleranceMode) -> None:
    cfg = perf_parity.ParityConfig(tolerance=1e-6, mode=mode)
    assert cfg.mode == mode


# ---------------------------------------------------------------------------
# 6. Module importability
# ---------------------------------------------------------------------------


def test_performance_package_importable() -> None:
    assert hasattr(perf, "interfaces")
    assert hasattr(perf, "parity")


def test_alpha_core_all_includes_performance() -> None:
    assert "performance" in alpha_core.__all__  # type: ignore[attr-defined]
