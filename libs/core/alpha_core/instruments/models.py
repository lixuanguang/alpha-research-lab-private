"""Canonical instrument metadata models for prediction markets."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

import alpha_core.utils.time as time_utils

_CANONICAL_ID_SEPARATOR = ":"


def _clean_required_text(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("value cannot be empty")
    return cleaned


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _validate_id_component(value: str, field_name: str) -> str:
    if _CANONICAL_ID_SEPARATOR in value:
        raise ValueError(
            f"`{field_name}` cannot contain `{_CANONICAL_ID_SEPARATOR}`; "
            "it is reserved as canonical ID separator"
        )
    return value


def _make_canonical_outcome_id(venue: str, market_id: str, outcome_id: str) -> str:
    return f"{venue}{_CANONICAL_ID_SEPARATOR}{market_id}{_CANONICAL_ID_SEPARATOR}{outcome_id}"


class MarketLifecycle(StrEnum):
    """Lifecycle state for a prediction market."""

    ACTIVE = "active"
    HALTED = "halted"
    RESOLVED = "resolved"
    DELISTED = "delisted"


class OutcomeSpec(BaseModel):
    """Canonicalized market outcome metadata."""

    model_config = ConfigDict(extra="forbid")

    outcome_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    canonical_id: str = Field(min_length=1)

    @field_validator("outcome_id", "label", "canonical_id")
    @classmethod
    def _strip_and_require_text(cls, value: str) -> str:
        return _clean_required_text(value)

    @field_validator("outcome_id")
    @classmethod
    def _validate_outcome_id_component(cls, value: str) -> str:
        return _validate_id_component(value, "outcome_id")


class MarketSpec(BaseModel):
    """Canonicalized venue market metadata."""

    model_config = ConfigDict(extra="forbid")

    market_id: str = Field(min_length=1)
    venue: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    outcomes: list[OutcomeSpec] = Field(min_length=1)
    resolution_date: datetime | None = None
    lifecycle: MarketLifecycle = MarketLifecycle.ACTIVE
    volume: Decimal | None = None
    liquidity: Decimal | None = None
    url: str | None = None
    first_seen: datetime
    last_updated: datetime
    # Optional group key for simplex-constrained outcome sets (sum_i p_i = 1).
    # Outcomes sharing the same outcome_group_id form a complete mutually-exclusive
    # partition that satisfies the probability simplex constraint.
    outcome_group_id: str | None = None

    @field_validator("market_id", "venue", "title")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        return _clean_required_text(value)

    @field_validator("market_id", "venue")
    @classmethod
    def _validate_market_id_components(cls, value: str, info: ValidationInfo) -> str:
        return _validate_id_component(value, info.field_name or "value")

    @field_validator("description", "category", "url", "outcome_group_id")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    @field_validator("venue")
    @classmethod
    def _normalize_venue(cls, value: str) -> str:
        return value.lower()

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str]) -> list[str]:
        cleaned = [tag.strip() for tag in value if tag.strip()]
        unique: list[str] = []
        seen: set[str] = set()
        for tag in cleaned:
            lowered = tag.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            unique.append(tag)
        return unique

    @field_validator("resolution_date", "first_seen", "last_updated")
    @classmethod
    def _normalize_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return time_utils.ensure_utc(value)

    @field_validator("volume", "liquidity")
    @classmethod
    def _validate_non_negative_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("value must be non-negative")
        return value

    @model_validator(mode="after")
    def _validate_timestamps(self) -> MarketSpec:
        if self.last_updated < self.first_seen:
            raise ValueError("`last_updated` must be >= `first_seen`")
        return self

    @model_validator(mode="after")
    def _validate_unique_outcomes(self) -> MarketSpec:
        seen_outcomes: set[str] = set()
        for outcome in self.outcomes:
            normalized_outcome_id = outcome.outcome_id.casefold()
            if normalized_outcome_id in seen_outcomes:
                raise ValueError("duplicate `outcome_id` values are not allowed in `outcomes`")
            seen_outcomes.add(normalized_outcome_id)

            expected_canonical_id = _make_canonical_outcome_id(
                self.venue,
                self.market_id,
                outcome.outcome_id,
            )
            if outcome.canonical_id != expected_canonical_id:
                raise ValueError(
                    "`outcomes[].canonical_id` must match derived canonical format: "
                    f"`{expected_canonical_id}`"
                )
        return self
