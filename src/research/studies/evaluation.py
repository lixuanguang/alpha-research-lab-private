"""Retain economic trial objectives; predictive errors are the models' own records."""

from __future__ import annotations

# standard library imports
import math
from fractions import Fraction

# project library imports
from financial_units import ExactRatio
from serialization import WireRecord


class TrialEvaluation(WireRecord, frozen=True):
    """Keep an authoritative exact objective separate from Optuna's float projection."""

    net_return: ExactRatio

    def __post_init__(self) -> None:
        """Validate direct construction at the evaluation boundary."""
        if type(self.net_return) is not ExactRatio:
            raise TypeError("trial objective requires exact net return")
        self.net_return.__post_init__()
        try:
            projection = float(
                Fraction(int(self.net_return.numerator), int(self.net_return.denominator))
            )
        except OverflowError as error:
            raise ValueError("trial objective has no finite Optuna projection") from error
        if not math.isfinite(projection):
            raise ValueError("trial objective has no finite Optuna projection")
