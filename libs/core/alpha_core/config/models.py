"""Typed configuration models for the alpha research platform."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class VenueConfig(BaseModel):
    """Venue connectivity and rate-limiting configuration."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    exchange_class: str = Field(min_length=1)
    enabled: bool = True
    api_key_env: str | None = None
    private_key_env: str | None = None
    rate_limit_rpm: int = Field(default=60, ge=1)


class StorageConfig(BaseModel):
    """Storage tier path and partition settings."""

    model_config = ConfigDict(extra="forbid")

    base_path: Path
    bronze_path: str = "bronze"
    silver_path: str = "silver"
    gold_path: str = "gold"
    partition_by: list[str] = Field(default_factory=lambda: ["venue", "date"], min_length=1)

    @field_validator("partition_by")
    @classmethod
    def _validate_partition_by(cls, value: list[str]) -> list[str]:
        cleaned = [partition.strip() for partition in value if partition.strip()]
        if not cleaned:
            raise ValueError("`partition_by` must contain at least one non-empty entry")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("`partition_by` entries must be unique")
        return cleaned


class Settings(BaseModel):
    """Top-level application settings model."""

    model_config = ConfigDict(extra="forbid")

    project_name: str = "alpha-research-lab"
    venues: list[VenueConfig] = Field(min_length=1)
    storage: StorageConfig
    log_level: LogLevel = "INFO"
    feature_flags: dict[str, bool] = Field(default_factory=dict)
