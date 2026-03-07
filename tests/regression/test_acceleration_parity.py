"""Regression tests for the optional acceleration boundary (LA-022).

These tests pin the parity contract between the documented pure-Python
baseline implementations and any future accelerated counterpart.

Design rules (from alpha_core.perf.interfaces)
----------------------------------------------
1. An accelerated implementation must have identical method signatures.
2. Inputs are treated as read-only by both paths.
3. An accelerated path cannot be promoted to the default code path unless
   the relevant parity check in this file passes.

Tolerance policy
----------------
All tolerances are documented as module-level constants and are the single
source of truth for what deviation is permissible.  Any change to a constant
must be justified in the commit message and co-reviewed.

    FEATURE_TOLERANCE_ABSOLUTE = 1e-9   # rolling/ewm numeric transforms
    SIMULATION_TOLERANCE_ABSOLUTE = 1e-9  # mark-to-market / PnL kernels

Representative workloads
------------------------
- RollingMeanTransform  — sliding-window mean (mirrors feature_runner rolling paths)
- EwmTransform          — exponential weighted mean (approximate; alpha = 0.1)
- MarkToMarketKernel    — one-step position mark-to-market (mirrors backtest_runner)

Module importability
--------------------
- Both ``alpha_core.perf`` and ``alpha_core.performance`` namespaces are tested.
- Regression tests must remain importable and greenfield-passing forever.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, cast

import pytest

import alpha_core.perf as perf_alias
import alpha_core.perf.interfaces as perf_ifaces
import alpha_core.perf.parity as perf_parity
import alpha_core.performance as perf_pkg
import alpha_core.performance.interfaces as raw_ifaces
import alpha_core.performance.parity as raw_parity

# ---------------------------------------------------------------------------
# Tolerance policy constants (single source of truth)
# ---------------------------------------------------------------------------

#: Maximum absolute deviation permitted for rolling and EWM feature transforms.
FEATURE_TOLERANCE_ABSOLUTE: float = 1e-9

#: Maximum absolute deviation permitted for simulation (mark-to-market) kernels.
SIMULATION_TOLERANCE_ABSOLUTE: float = 1e-9

_PARITY_CFG_FEATURE = raw_parity.ParityConfig(tolerance=FEATURE_TOLERANCE_ABSOLUTE)
_PARITY_CFG_SIM = raw_parity.ParityConfig(tolerance=SIMULATION_TOLERANCE_ABSOLUTE)

# ---------------------------------------------------------------------------
# Baseline implementations: pure-Python reference paths
# ---------------------------------------------------------------------------


class RollingMeanTransform:
    """Pure-Python rolling mean over a fixed window.

    Mirrors the rolling-statistics path in ``alpha_core.research.feature_runner``.
    Any accelerated replacement must pass parity at ``FEATURE_TOLERANCE_ABSOLUTE``.

    Tolerance: FEATURE_TOLERANCE_ABSOLUTE (absolute mode)
    """

    def __init__(self, window: int) -> None:
        if window < 1:
            raise ValueError(f"window must be >= 1, got {window}")
        self._window = window

    @property
    def name(self) -> str:
        return f"rolling_mean_w{self._window}"

    def compute(self, values: Sequence[float]) -> Sequence[float]:
        """Return rolling windowed mean; first (window-1) values are nan-filled."""
        result: list[float] = []
        lst = list(values)
        for i, _ in enumerate(lst):
            if i < self._window - 1:
                result.append(float("nan"))
            else:
                window_slice = lst[i - self._window + 1 : i + 1]
                result.append(sum(window_slice) / self._window)
        return result


class EwmTransform:
    """Pure-Python exponential weighted mean (alpha-decay).

    Mirrors the EWM feature path in ``alpha_core.research.feature_runner``.
    Any accelerated replacement must pass parity at ``FEATURE_TOLERANCE_ABSOLUTE``.

    Formula: ewm[i] = alpha * x[i] + (1 - alpha) * ewm[i-1]
    Initialisation: ewm[0] = x[0]

    Tolerance: FEATURE_TOLERANCE_ABSOLUTE (absolute mode)
    """

    def __init__(self, alpha: float) -> None:
        if not (0.0 < alpha <= 1.0):
            raise ValueError(f"alpha must be in (0, 1], got {alpha}")
        self._alpha = alpha

    @property
    def name(self) -> str:
        return f"ewm_alpha{self._alpha}"

    def compute(self, values: Sequence[float]) -> Sequence[float]:
        lst = list(values)
        if not lst:
            return []
        result: list[float] = [lst[0]]
        for v in lst[1:]:
            result.append(self._alpha * v + (1.0 - self._alpha) * result[-1])
        return result


class MarkToMarketKernel:
    """Pure-Python mark-to-market simulation step.

    Mirrors the position accounting path in ``alpha_core.research.backtest_runner``.
    State keys: ``position`` (float), ``price`` (float), ``equity`` (float).
    Event keys: ``price`` (float, optional).

    Any accelerated replacement must pass parity at ``SIMULATION_TOLERANCE_ABSOLUTE``.
    Tolerance: SIMULATION_TOLERANCE_ABSOLUTE (absolute mode)
    """

    @property
    def name(self) -> str:
        return "mark_to_market"

    def step(
        self,
        state: Mapping[str, Any],
        event: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Update equity based on latest price from event, position unchanged."""
        new_state = dict(state)
        new_price = float(event.get("price", state.get("price", 0.0)))
        position = float(state.get("position", 0.0))
        cash = float(state.get("cash", 0.0))
        new_state["price"] = new_price
        new_state["equity"] = cash + position * new_price
        return new_state


# ---------------------------------------------------------------------------
# Representative workload fixtures
# ---------------------------------------------------------------------------

# Probability series (typical of prediction market implied-prob features)
_PROB_SERIES: list[list[float]] = [
    [0.50, 0.52, 0.55, 0.60, 0.65, 0.70, 0.68, 0.65, 0.60, 0.55],
    [0.80, 0.78, 0.75, 0.72, 0.70, 0.68, 0.65, 0.63, 0.62, 0.60],
    [0.30, 0.32, 0.35, 0.33, 0.30, 0.28, 0.25, 0.27, 0.30, 0.32],
    [0.10, 0.12, 0.15, 0.18, 0.20, 0.22, 0.25, 0.28, 0.30, 0.35],
]

# Simulation cases: (state, event)
_SIM_CASES: list[tuple[dict[str, Any], dict[str, Any]]] = [
    ({"position": 100.0, "price": 0.55, "cash": 5_000.0, "equity": 10_500.0}, {"price": 0.60}),
    ({"position": 0.0, "price": 0.40, "cash": 10_000.0, "equity": 10_000.0}, {"price": 0.42}),
    ({"position": -50.0, "price": 0.70, "cash": 8_000.0, "equity": 4_500.0}, {"price": 0.65}),
    ({"position": 200.0, "price": 0.25, "cash": 2_000.0, "equity": 7_000.0}, {"price": 0.25}),
]


# ---------------------------------------------------------------------------
# 1. Namespace alias equivalence
# ---------------------------------------------------------------------------


class TestNamespaceAliases:
    """Both ``alpha_core.perf`` and ``alpha_core.performance`` must expose
    the same objects."""

    def test_feature_transform_same_protocol(self) -> None:
        assert perf_ifaces.FeatureTransform is raw_ifaces.FeatureTransform

    def test_simulation_kernel_same_protocol(self) -> None:
        assert perf_ifaces.SimulationKernel is raw_ifaces.SimulationKernel

    def test_parity_config_same_class(self) -> None:
        assert perf_parity.ParityConfig is raw_parity.ParityConfig

    def test_check_feature_parity_same_function(self) -> None:
        assert perf_parity.check_feature_parity is raw_parity.check_feature_parity

    def test_check_simulation_parity_same_function(self) -> None:
        assert perf_parity.check_simulation_parity is raw_parity.check_simulation_parity

    def test_perf_alias_has_interfaces_attr(self) -> None:
        assert hasattr(perf_alias, "interfaces")

    def test_perf_alias_has_parity_attr(self) -> None:
        assert hasattr(perf_alias, "parity")

    def test_performance_pkg_has_interfaces_attr(self) -> None:
        assert hasattr(perf_pkg, "interfaces")


# ---------------------------------------------------------------------------
# 2. Baseline conformance (protocol isinstance checks)
# ---------------------------------------------------------------------------


class TestBaselineConformance:
    def test_rolling_mean_is_feature_transform(self) -> None:
        assert isinstance(RollingMeanTransform(5), perf_ifaces.FeatureTransform)

    def test_ewm_is_feature_transform(self) -> None:
        assert isinstance(EwmTransform(0.1), perf_ifaces.FeatureTransform)

    def test_mark_to_market_is_simulation_kernel(self) -> None:
        assert isinstance(MarkToMarketKernel(), perf_ifaces.SimulationKernel)

    def test_rolling_mean_name_is_nonempty(self) -> None:
        assert len(RollingMeanTransform(3).name) > 0

    def test_ewm_name_is_nonempty(self) -> None:
        assert len(EwmTransform(0.2).name) > 0

    def test_mark_to_market_name_is_nonempty(self) -> None:
        assert len(MarkToMarketKernel().name) > 0


# ---------------------------------------------------------------------------
# 3. Baseline self-parity (baseline vs. itself = zero deviation)
# ---------------------------------------------------------------------------


class TestBaselineSelfParity:
    """Baseline must produce identical outputs given identical inputs.

    Self-parity is the minimum regression guarantee: any future change to
    the baseline that breaks determinism will be caught here.
    """

    @pytest.mark.parametrize("window", [3, 5, 10])
    def test_rolling_mean_self_parity(self, window: int) -> None:
        t = RollingMeanTransform(window)
        result = raw_parity.check_feature_parity(t, t, _PROB_SERIES, _PARITY_CFG_FEATURE)
        assert result.passed
        assert result.max_deviation == 0.0

    @pytest.mark.parametrize("alpha", [0.05, 0.1, 0.3, 0.5])
    def test_ewm_self_parity(self, alpha: float) -> None:
        t = EwmTransform(alpha)
        result = raw_parity.check_feature_parity(t, t, _PROB_SERIES, _PARITY_CFG_FEATURE)
        assert result.passed
        assert result.max_deviation == 0.0

    def test_mark_to_market_self_parity(self) -> None:
        k = MarkToMarketKernel()
        result = raw_parity.check_simulation_parity(k, k, _SIM_CASES, _PARITY_CFG_SIM)
        assert result.passed
        assert result.max_deviation == 0.0

    def test_tolerance_constants_are_documented(self) -> None:
        """The tolerance constants are importable scalars, not magic numbers."""
        assert isinstance(FEATURE_TOLERANCE_ABSOLUTE, float)
        assert isinstance(SIMULATION_TOLERANCE_ABSOLUTE, float)
        assert FEATURE_TOLERANCE_ABSOLUTE >= 0.0
        assert SIMULATION_TOLERANCE_ABSOLUTE >= 0.0


# ---------------------------------------------------------------------------
# 4. Baseline correctness (pinned expected outputs)
# ---------------------------------------------------------------------------


class TestBaselineCorrectness:
    """Pin exact outputs so that silent logic regressions are caught."""

    def test_rolling_mean_window3_first_values(self) -> None:
        """First two values are nan; third is mean of first three."""
        t = RollingMeanTransform(3)
        out = t.compute([0.50, 0.52, 0.55, 0.60])
        assert math.isnan(out[0])
        assert math.isnan(out[1])
        assert abs(out[2] - (0.50 + 0.52 + 0.55) / 3) < 1e-12
        assert abs(out[3] - (0.52 + 0.55 + 0.60) / 3) < 1e-12

    def test_ewm_initial_value_equals_first_input(self) -> None:
        t = EwmTransform(0.1)
        out = t.compute([0.50, 0.52])
        assert out[0] == pytest.approx(0.50)
        assert out[1] == pytest.approx(0.1 * 0.52 + 0.9 * 0.50)

    def test_mark_to_market_equity_update(self) -> None:
        k = MarkToMarketKernel()
        state = {"position": 100.0, "price": 0.55, "cash": 5_000.0, "equity": 10_500.0}
        event = {"price": 0.60}
        new_state = k.step(state, event)
        assert new_state["price"] == pytest.approx(0.60)
        assert new_state["equity"] == pytest.approx(5_000.0 + 100.0 * 0.60)

    def test_mark_to_market_does_not_mutate_input_state(self) -> None:
        k = MarkToMarketKernel()
        state = {"position": 100.0, "price": 0.55, "cash": 5_000.0, "equity": 10_500.0}
        original_equity = state["equity"]
        k.step(state, {"price": 0.99})
        assert state["equity"] == original_equity  # input must be untouched

    def test_rolling_mean_empty_input(self) -> None:
        assert list(RollingMeanTransform(5).compute([])) == []

    def test_ewm_empty_input(self) -> None:
        assert list(EwmTransform(0.1).compute([])) == []


# ---------------------------------------------------------------------------
# 5. Fallback policy: accelerated backend unavailable
# ---------------------------------------------------------------------------


class TestFallbackPolicy:
    """When no accelerated backend is installed the baseline must be used.

    This tests the pattern implementors must follow: wrap accelerated import
    in a try/except and fall back to the baseline without raising.
    """

    def test_fallback_to_baseline_when_accel_unavailable(self) -> None:
        """Simulate a missing accelerated backend and verify fallback works."""

        def _resolve_transform(window: int) -> perf_ifaces.FeatureTransform:
            try:
                # If an optional accelerator package existed it would be imported here.
                # Simulated as always-missing so the fallback is always exercised.
                raise ImportError("optional accelerator not installed")
            except ImportError:
                return RollingMeanTransform(window)

        transform = _resolve_transform(5)
        assert isinstance(transform, perf_ifaces.FeatureTransform)
        result = transform.compute([0.5, 0.6, 0.7, 0.8, 0.9])
        assert len(result) == 5

    def test_baseline_is_default_when_no_accel(self) -> None:
        """Baseline path must be importable and functional without any extras."""
        t = RollingMeanTransform(3)
        out = t.compute(_PROB_SERIES[0])
        # Spot-check: all non-nan values must be in [0, 1] for probability series
        non_nan = [v for v in out if not math.isnan(v)]
        assert all(0.0 <= v <= 1.0 for v in non_nan)


# ---------------------------------------------------------------------------
# 6. Promotion gate: failed parity blocks promotion
# ---------------------------------------------------------------------------


class TestPromotionGate:
    """Accelerated path must fail parity when output deviates beyond tolerance.

    These tests document what a non-compliant accelerated implementation looks
    like, ensuring the parity harness would correctly block its promotion.
    """

    def _biased_transform(self, bias: float) -> perf_ifaces.FeatureTransform:
        """Returns a transform that adds a fixed bias to rolling mean output."""

        class _BiasedMean:
            @property
            def name(self) -> str:
                return f"biased_mean_{bias}"

            def compute(self, values: Sequence[float]) -> Sequence[float]:
                base = RollingMeanTransform(3).compute(values)
                return [v + bias if not math.isnan(v) else v for v in base]

        return cast(perf_ifaces.FeatureTransform, _BiasedMean())

    def test_large_bias_fails_parity(self) -> None:
        baseline = RollingMeanTransform(3)
        biased = self._biased_transform(0.05)
        result = raw_parity.check_feature_parity(
            baseline,
            biased,
            _PROB_SERIES,
            _PARITY_CFG_FEATURE,
        )
        assert not result.passed, "Biased transform should fail strict parity"

    def test_tiny_bias_within_tolerance_passes(self) -> None:
        baseline = RollingMeanTransform(3)
        biased = self._biased_transform(1e-12)  # well within 1e-9
        cfg = raw_parity.ParityConfig(tolerance=FEATURE_TOLERANCE_ABSOLUTE)
        result = raw_parity.check_feature_parity(baseline, biased, _PROB_SERIES, cfg)
        assert result.passed

    def test_parity_summary_shows_tolerance(self) -> None:
        baseline = RollingMeanTransform(3)
        result = raw_parity.check_feature_parity(
            baseline,
            baseline,
            _PROB_SERIES,
            _PARITY_CFG_FEATURE,
        )
        assert str(FEATURE_TOLERANCE_ABSOLUTE) in result.summary or "PASSED" in result.summary


# ---------------------------------------------------------------------------
# 7. Tolerance mode — relative vs absolute
# ---------------------------------------------------------------------------


class TestToleranceModes:
    def test_relative_mode_tight_ewm_passes(self) -> None:
        t = EwmTransform(0.1)
        cfg = raw_parity.ParityConfig(tolerance=1e-9, mode=raw_parity.ToleranceMode.RELATIVE)
        result = raw_parity.check_feature_parity(t, t, _PROB_SERIES, cfg)
        assert result.passed

    def test_absolute_mode_documented_in_parity_config(self) -> None:
        cfg = _PARITY_CFG_FEATURE
        assert cfg.mode is raw_parity.ToleranceMode.ABSOLUTE

    def test_all_tolerance_modes_are_valid(self) -> None:
        for mode in raw_parity.ToleranceMode:
            cfg = raw_parity.ParityConfig(tolerance=1e-6, mode=mode)
            assert cfg.mode == mode


# ---------------------------------------------------------------------------
# 8. Representative workload coverage
# ---------------------------------------------------------------------------


class TestRepresentativeWorkloads:
    """Run the full parity harness on all representative workloads."""

    @pytest.mark.parametrize("window", [3, 5])
    def test_rolling_mean_representative_series(self, window: int) -> None:
        t = RollingMeanTransform(window)
        result = raw_parity.check_feature_parity(t, t, _PROB_SERIES, _PARITY_CFG_FEATURE)
        assert result.passed
        assert result.n_cases == len(_PROB_SERIES)

    def test_ewm_representative_series(self) -> None:
        t = EwmTransform(0.1)
        result = raw_parity.check_feature_parity(t, t, _PROB_SERIES, _PARITY_CFG_FEATURE)
        assert result.passed
        assert result.n_cases == len(_PROB_SERIES)

    def test_mark_to_market_representative_sim(self) -> None:
        k = MarkToMarketKernel()
        result = raw_parity.check_simulation_parity(k, k, _SIM_CASES, _PARITY_CFG_SIM)
        assert result.passed
        assert result.n_cases == len(_SIM_CASES)

    def test_empty_workload_always_passes(self) -> None:
        t = RollingMeanTransform(5)
        result = raw_parity.check_feature_parity(t, t, [], _PARITY_CFG_FEATURE)
        assert result.passed
        assert result.n_cases == 0
