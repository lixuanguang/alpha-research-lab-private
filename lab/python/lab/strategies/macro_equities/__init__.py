"""lab.strategies.macro_equities — macro-equities alpha strategy."""

from lab.strategies.macro_equities.baseline_signals import (
    cross_sectional_momentum,
    earnings_yield_stub,
    inverse_volatility,
    momentum_12_1,
    trend_sma,
)
from lab.strategies.macro_equities.portfolio_rules import (
    apply_regime_overlay,
    risk_parity_stub,
    signal_proportional,
    top_n_equal_weight,
)
from lab.strategies.macro_equities.regimes import (
    dual_ma_regime,
    hmm_regime_stub,
    trend_regime,
    vol_regime,
)

# Import triggers @register("macro_equities.baseline")
from lab.strategies.macro_equities.strategy import baseline_strategy

__all__ = [
    "apply_regime_overlay",
    "baseline_strategy",
    "cross_sectional_momentum",
    "dual_ma_regime",
    "earnings_yield_stub",
    "hmm_regime_stub",
    "inverse_volatility",
    "momentum_12_1",
    "risk_parity_stub",
    "signal_proportional",
    "top_n_equal_weight",
    "trend_regime",
    "trend_sma",
    "vol_regime",
]
