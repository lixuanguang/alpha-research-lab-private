"""Shared configuration for validated immutable governance boundary models."""

from __future__ import annotations

# third party library imports
from pydantic import BaseModel, ConfigDict


class ImmutableModel(BaseModel):
    """Reject coercion and unknown data while preserving value-object semantics."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        strict=True,
        validate_default=True,
    )
