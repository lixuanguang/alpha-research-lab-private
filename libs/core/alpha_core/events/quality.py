"""Quality checks for canonical market event streams."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

import alpha_core.events.models as event_models


class QualityIssue(BaseModel):
    """Single quality rule violation discovered for an event."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class QualityReport(BaseModel):
    """Validation result for an event under configured quality rules."""

    model_config = ConfigDict(extra="forbid")

    is_valid: bool
    issues: list[QualityIssue] = Field(default_factory=list)


class EventQualityChecker:
    """Validate individual events against quality rules."""

    def __init__(self) -> None:
        self._last_ts_by_instrument: dict[str, datetime] = {}

    def check(self, event: event_models.CanonicalMarketEvent) -> QualityReport:
        issues: list[QualityIssue] = []
        ts_event = _safe_getattr(event, "ts_event")
        ts_record = _safe_getattr(event, "ts_record")
        instrument_id = _safe_getattr(event, "instrument_id")

        if (
            isinstance(ts_event, datetime)
            and isinstance(ts_record, datetime)
            and ts_event > ts_record
        ):
            issues.append(
                QualityIssue(
                    code="bitemporal_order",
                    message="`ts_event` must be <= `ts_record`",
                )
            )

        for field_name, model_field in event.__class__.model_fields.items():
            if not model_field.is_required():
                continue
            if _safe_getattr(event, field_name) is None:
                issues.append(
                    QualityIssue(
                        code="required_null",
                        message=f"Required field `{field_name}` is null",
                    )
                )

        if (
            isinstance(event, event_models.CanonicalTrade)
            and _safe_getattr(event, "price") is not None
            and not (0 <= event.price <= 1)
        ):
            issues.append(
                QualityIssue(
                    code="trade_price_bounds",
                    message="Trade price must be in [0, 1] for prediction markets",
                )
            )

        if isinstance(instrument_id, str) and instrument_id and isinstance(ts_event, datetime):
            previous_ts = self._last_ts_by_instrument.get(instrument_id)
            if previous_ts is not None and ts_event < previous_ts:
                issues.append(
                    QualityIssue(
                        code="non_monotonic_event_time",
                        message="`ts_event` regressed for instrument stream",
                    )
                )
            else:
                self._last_ts_by_instrument[instrument_id] = ts_event

        return QualityReport(is_valid=not issues, issues=issues)


def _safe_getattr(event: object, field_name: str) -> object | None:
    try:
        return cast(object, getattr(event, field_name))
    except AttributeError:
        return None
