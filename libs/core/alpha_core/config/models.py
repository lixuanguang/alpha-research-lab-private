"""Typed configuration models for the alpha research platform."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alpha_core.config.profiles import ProfileName

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class CollectionConfig(BaseModel):
    """Per-venue data collection behaviour settings."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["poll", "stream", "both"] = "poll"
    trade_poll_interval: float = Field(default=30.0, gt=0)
    ohlcv_poll_interval: float = Field(default=300.0, gt=0)
    book_poll_interval: float = Field(default=60.0, gt=0)
    market_refresh_interval: float = Field(default=300.0, gt=0)
    stream_outcomes_max: int = Field(default=50, ge=1)
    heartbeat_timeout: float = Field(default=120.0, gt=0)
    reconnect_backoff_base: float = Field(default=1.0, gt=0)
    reconnect_backoff_max: float = Field(default=60.0, gt=0)


class VenueConfig(BaseModel):
    """Venue connectivity and rate-limiting configuration."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    exchange_class: str = Field(min_length=1)
    enabled: bool = True
    api_key_env: str | None = None
    private_key_env: str | None = None
    rate_limit_rpm: int = Field(default=60, ge=1)
    collection: CollectionConfig = Field(default_factory=CollectionConfig)


class StorageConfig(BaseModel):
    """Storage tier path and partition settings."""

    model_config = ConfigDict(extra="forbid")

    base_path: Path
    retention_days: int | None = Field(default=None, ge=1)
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
    profile: ProfileName | None = Field(
        default=None,
        description=(
            "Active runtime profile. None means no profile-level safety guards are "
            "applied."
        ),
    )
