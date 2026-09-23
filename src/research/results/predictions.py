"""Retain exact model predictions independently of estimator and strategy implementations."""

# standard library imports
from datetime import datetime

# project library imports
from financial_units import ExactRatio
from research.observations import NumericField
from serialization import WireRecord


class Prediction(WireRecord, frozen=True):
    """Bind a then-available prediction to its model, feature row, entity, units and clock."""

    entity: str
    decision_at: datetime
    feature_identity: str
    model_identity: str
    field: NumericField
    value: ExactRatio

    def __post_init__(self) -> None:
        """Require exact values and nonempty lineage."""
        self._require_utc(self.decision_at, field_name="decision_at")
        self.field.__post_init__()
        if type(self.value) is not ExactRatio:
            raise TypeError("prediction must use exact arithmetic")
        self.value.__post_init__()
        if any(
            type(v) is not str or not v
            for v in (self.entity, self.feature_identity, self.model_identity)
        ):
            raise ValueError("prediction requires entity and source versions")
