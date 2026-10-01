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
        BusinessDayConvention,
        ConventionError,
        DayCountConventions,
        DayCountResult,
        SettlementConventions,
    )


def __getattr__(name: str) -> object:
    """Load the conventions, which import the settlement calendar, only for explicit consumers."""
    if name in {
        "BusinessDayConvention",
        "ConventionError",
        "DayCountResult",
        "DayCountConventions",
        "SettlementConventions",
    }:
        # project library imports
        from financial_units import conventions

        exports: dict[str, object] = {
            "BusinessDayConvention": conventions.BusinessDayConvention,
            "ConventionError": conventions.ConventionError,
            "DayCountResult": conventions.DayCountResult,
            "DayCountConventions": conventions.DayCountConventions,
            "SettlementConventions": conventions.SettlementConventions,
        }
        return exports[name]
    raise AttributeError(name)


__all__ = [
    "BusinessDayConvention",
    "Compounding",
    "ConventionError",
    "Currency",
    "DayCount",
    "DayCountConventions",
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
