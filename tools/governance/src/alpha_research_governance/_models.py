"""Shared configuration for validated immutable governance boundary models."""

from __future__ import annotations

# third party library imports
from pydantic import BaseModel, ConfigDict


class ImmutableModel(BaseModel):
    """Reject coercion and unknown data while preserving value-object semantics.

    Normal construction and validation check defaults, reject nonfinite numbers,
    and revalidate existing model instances. Python inputs follow strict field
    types; JSON validation uses the framework's JSON representations for types
    such as dates. Validation failures use Pydantic's ``ValidationError`` unless
    an owning loader translates them to a domain error.

    Frozen fields prevent attribute assignment, not mutation of contained mutable
    values. The inherited ``model_construct`` and ``model_copy(update=...)`` APIs
    are trusted-data operations that bypass validation; callers handling external
    data must use a validating entry point.
    """

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        strict=True,
        validate_default=True,
    )
