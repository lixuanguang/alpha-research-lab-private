"""Retain distinct exact predictive errors and economic trial objectives."""

from __future__ import annotations

# standard library imports
import math
from datetime import datetime
from fractions import Fraction
from typing import Literal

# project library imports
from financial_units import ExactRatio
from research.experiments.identity import Fingerprint
from research.experiments.splits import TimeWindow
from serialization import WireRecord


class EvaluationRecord(WireRecord, frozen=True, kw_only=True):
    """Record exact squared prediction errors with sample, version and outcome clocks."""

    schema_version: Literal["model-evaluation-v1"] = "model-evaluation-v1"
    dataset_sha256: str
    split_identity: str
    window: TimeWindow
    partition: Literal["validation", "holdout"]
    evaluated_as_of: datetime
    predictions: tuple[tuple[str, str, ExactRatio, ExactRatio, datetime], ...]
    excluded: tuple[tuple[str, str], ...]
    mean_squared_error: ExactRatio
    selection: Literal["accepted", "rejected"]
    reason: str
    metric: Literal["mean((prediction-forward_return)**2)"] = "mean((prediction-forward_return)**2)"
    units: Literal["dimensionless-squared"] = "dimensionless-squared"

    def __post_init__(self) -> None:
        """Reject absent provenance, malformed results and non-UTC outcome availability."""
        if (
            self.schema_version != "model-evaluation-v1"
            or self.partition not in ("validation", "holdout")
            or self.selection not in ("accepted", "rejected")
            or self.metric != "mean((prediction-forward_return)**2)"
            or self.units != "dimensionless-squared"
            or type(self.reason) is not str
            or not self.reason.strip()
        ):
            raise ValueError("unsupported evaluation contract or missing selection reason")
        Fingerprint(name="dataset", sha256=self.dataset_sha256)
        Fingerprint(name="split", sha256=self.split_identity)
        self.window.__post_init__()
        self._require_utc(self.evaluated_as_of, field_name="evaluated_as_of")
        if type(self.predictions) is not tuple or not self.predictions:
            raise ValueError("evaluation requires predictions")
        if any(type(row) is not tuple or len(row) != 5 for row in self.predictions):
            raise TypeError("evaluation predictions must be immutable rows")
        if type(self.excluded) is not tuple or any(
            type(row) is not tuple
            or len(row) != 2
            or any(type(value) is not str or not value.strip() for value in row)
            for row in self.excluded
        ):
            raise TypeError("evaluation exclusions must be immutable named reasons")
        row_ids = tuple(row[0] for row in self.predictions) + tuple(row[0] for row in self.excluded)
        if len(set(row_ids)) != len(row_ids):
            raise ValueError("evaluation rows must be unique and scored or excluded")
        errors: list[Fraction] = []
        for row_id, version, prediction, outcome, available in self.predictions:
            Fingerprint(name=row_id, sha256=version)
            prediction.__post_init__()
            outcome.__post_init__()
            self._require_utc(available, field_name="outcome availability")
            if available > self.evaluated_as_of:
                raise ValueError("evaluation cannot use an unavailable outcome")
            errors.append(
                (
                    Fraction(int(prediction.numerator), int(prediction.denominator))
                    - Fraction(int(outcome.numerator), int(outcome.denominator))
                )
                ** 2
            )
        self.mean_squared_error.__post_init__()
        expected = ExactRatio.from_fraction(sum(errors, Fraction()) / len(errors))
        if self.mean_squared_error != expected:
            raise ValueError("mean squared error differs from retained prediction outcomes")


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
