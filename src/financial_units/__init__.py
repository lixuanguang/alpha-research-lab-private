"""Expose the financial units public contract."""

# standard library imports
from typing import TYPE_CHECKING

# project library imports
from financial_units.models import (
    Compounding,
    Currency,
    DayCount,
    DecimalGrid,
    Dimension,
    Duration,
    EvaluationContext,
    FXRate,
    Lot,
    Money,
    Multiplier,
    Price,
    Quantity,
    QuantityKind,
    Rate,
    RateConvention,
    Rounding,
    Tick,
    UnitError,
    Volatility,
    Yield,
)
from financial_units.ratios import ExactRatio

if TYPE_CHECKING:
    # project library imports
    from financial_units.conventions import (
        QUANTLIB_VERSION,
        BusinessDayConvention,
        ConventionError,
        DayCountResult,
        QuantLibConventions,
        SettlementConventions,
    )


def __getattr__(name: str) -> object:
    """Load the optional native convention adapter only for explicit consumers."""
    if name in {
        "QUANTLIB_VERSION",
        "BusinessDayConvention",
        "ConventionError",
        "DayCountResult",
        "QuantLibConventions",
        "SettlementConventions",
    }:
        # project library imports
        from financial_units import conventions

        exports: dict[str, object] = {
            "QUANTLIB_VERSION": conventions.QUANTLIB_VERSION,
            "BusinessDayConvention": conventions.BusinessDayConvention,
            "ConventionError": conventions.ConventionError,
            "DayCountResult": conventions.DayCountResult,
            "QuantLibConventions": conventions.QuantLibConventions,
            "SettlementConventions": conventions.SettlementConventions,
        }
        return exports[name]
    raise AttributeError(name)


__all__ = [
    "QUANTLIB_VERSION",
    "BusinessDayConvention",
    "Compounding",
    "ConventionError",
    "Currency",
    "DayCount",
    "DayCountResult",
    "DecimalGrid",
    "Dimension",
    "Duration",
    "EvaluationContext",
    "ExactRatio",
    "FXRate",
    "Lot",
    "Money",
    "Multiplier",
    "Price",
    "QuantLibConventions",
    "Quantity",
    "QuantityKind",
    "Rate",
    "RateConvention",
    "Rounding",
    "SettlementConventions",
    "Tick",
    "UnitError",
    "Volatility",
    "Yield",
]
