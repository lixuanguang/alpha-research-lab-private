"""Operational profiles for the data-collection subsystem (§13.4).

Three named profiles govern how the data collector runs across environments.
They are **orthogonal to** the general :class:`~alpha_core.config.profiles.EnvironmentProfile`
(which controls trading execution and real-money safety).  Collector profiles
only affect ingestion cadence, metadata emission, health-gate strictness, and
restart behaviour.

Profiles
--------
dev
    Low poll cadence (10x slower), debug logging, 7-day retention.
    No replay-package or handoff-manifest emission — keep dev storage light.
    Lenient health gates and restart policy so transient failures don't
    interrupt local experimentation.
research
    Normal poll cadence, info logging, unlimited retention.
    Full metadata emission: replay packages + handoff manifests written on
    every successful run so that downstream research pipelines can discover
    and consume the data automatically.
    Lenient restart policy; moderate reconnect budget (10 attempts).
live
    Normal poll cadence, info logging, unlimited retention.
    Strict health gates: anomalous latency or missed heartbeats raise
    immediate alerts rather than degraded warnings.
    Conservative restart policy: circuit-breaks after repeated failures and
    waits for operator acknowledgement before resuming.
    Unlimited reconnect attempts with capped exponential backoff to ensure
    continuous data coverage.

Usage::

    import alpha_core.config.collector_profiles as cp

    profile = cp.get_collector_profile(cp.CollectorProfileName.LIVE)
    assert profile.health_gate_strict
    assert profile.restart_policy == "conservative"

    # Adjust a CollectionConfig to match a profile:
    cfg = CollectionConfig()
    cfg = cp.apply_collector_profile(cfg, profile)
    assert cfg.trade_poll_interval == profile.trade_poll_interval
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    import alpha_core.config.models as _models_mod


# ---------------------------------------------------------------------------
# Profile name enum
# ---------------------------------------------------------------------------


class CollectorProfileName(StrEnum):
    """Named operational profiles for the data-collection subsystem."""

    DEV = "dev"
    RESEARCH = "research"
    LIVE = "live"


# ---------------------------------------------------------------------------
# Profile model
# ---------------------------------------------------------------------------

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
RestartPolicy = Literal["lenient", "conservative"]


class CollectorProfile(BaseModel):
    """Complete specification of a collector operational profile.

    Attributes
    ----------
    name:
        Canonical profile identifier.
    log_level:
        Minimum log level for the data collection process under this profile.
    trade_poll_interval:
        Seconds between trade-polling cycles.  Derived from
        ``CollectionConfig.trade_poll_interval x poll_cadence_multiplier``.
    ohlcv_poll_interval:
        Seconds between OHLCV-polling cycles.
    book_poll_interval:
        Seconds between book-polling cycles.
    market_refresh_interval:
        Seconds between market-metadata refresh cycles.
    data_retention_days:
        How many days of raw + silver data to retain.  ``None`` = forever.
    emit_replay_package:
        When ``True``, a :class:`~alpha_core.storage.replay_package.ReplayPackageManifest`
        is written after every successful ingestion run so research runners can
        discover and replay the data deterministically.
    emit_handoff_manifest:
        When ``True``, a dataset-ready handoff manifest is written and the
        lineage run is marked ``dataset_ready=True`` after quality gates pass.
    health_gate_strict:
        When ``True``, anomalous latency, missed heartbeats, or quality
        degradations raise hard failures rather than degraded warnings.
    restart_policy:
        ``"lenient"`` — reconnect freely; ``"conservative"`` — circuit-break
        after repeated failures and wait for operator acknowledgement.
    max_reconnect_attempts:
        Maximum consecutive reconnection attempts before circuit-breaking.
        ``None`` = unlimited (live profile default).
    heartbeat_timeout:
        Seconds of silence before a stream is considered stale.  Live uses a
        shorter timeout for earlier alerting.
    reconnect_backoff_base:
        Base delay (seconds) for the exponential-backoff reconnection policy.
    reconnect_backoff_max:
        Maximum delay (seconds) to cap exponential backoff.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: CollectorProfileName
    log_level: LogLevel
    # Polling intervals (seconds)
    trade_poll_interval: float = Field(gt=0)
    ohlcv_poll_interval: float = Field(gt=0)
    book_poll_interval: float = Field(gt=0)
    market_refresh_interval: float = Field(gt=0)
    # Retention
    data_retention_days: int | None = Field(default=None, ge=1)
    # Metadata emission
    emit_replay_package: bool
    emit_handoff_manifest: bool
    # Health & reliability
    health_gate_strict: bool
    restart_policy: RestartPolicy
    max_reconnect_attempts: int | None = Field(default=None, ge=1)
    heartbeat_timeout: float = Field(gt=0)
    reconnect_backoff_base: float = Field(gt=0)
    reconnect_backoff_max: float = Field(gt=0)


# ---------------------------------------------------------------------------
# Built-in profile registry
# ---------------------------------------------------------------------------

BUILTIN_COLLECTOR_PROFILES: dict[CollectorProfileName, CollectorProfile] = {
    CollectorProfileName.DEV: CollectorProfile(
        name=CollectorProfileName.DEV,
        log_level="DEBUG",
        # 10x slower polling keeps dev storage light and noise low.
        trade_poll_interval=300.0,
        ohlcv_poll_interval=3000.0,
        book_poll_interval=600.0,
        market_refresh_interval=3000.0,
        data_retention_days=7,
        emit_replay_package=False,
        emit_handoff_manifest=False,
        health_gate_strict=False,
        restart_policy="lenient",
        max_reconnect_attempts=5,
        heartbeat_timeout=300.0,
        reconnect_backoff_base=2.0,
        reconnect_backoff_max=60.0,
    ),
    CollectorProfileName.RESEARCH: CollectorProfile(
        name=CollectorProfileName.RESEARCH,
        log_level="INFO",
        trade_poll_interval=30.0,
        ohlcv_poll_interval=300.0,
        book_poll_interval=60.0,
        market_refresh_interval=300.0,
        data_retention_days=None,
        emit_replay_package=True,
        emit_handoff_manifest=True,
        health_gate_strict=False,
        restart_policy="lenient",
        max_reconnect_attempts=10,
        heartbeat_timeout=120.0,
        reconnect_backoff_base=1.0,
        reconnect_backoff_max=60.0,
    ),
    CollectorProfileName.LIVE: CollectorProfile(
        name=CollectorProfileName.LIVE,
        log_level="INFO",
        trade_poll_interval=30.0,
        ohlcv_poll_interval=300.0,
        book_poll_interval=60.0,
        market_refresh_interval=300.0,
        data_retention_days=None,
        emit_replay_package=False,
        emit_handoff_manifest=False,
        health_gate_strict=True,
        restart_policy="conservative",
        max_reconnect_attempts=None,  # unlimited — never give up in production
        heartbeat_timeout=60.0,       # tighter window for earlier stale detection
        reconnect_backoff_base=1.0,
        reconnect_backoff_max=60.0,
    ),
}


def get_collector_profile(name: CollectorProfileName | str) -> CollectorProfile:
    """Return the built-in :class:`CollectorProfile` for *name*.

    Parameters
    ----------
    name:
        A :class:`CollectorProfileName` member or its string value
        (``"dev"``, ``"research"``, ``"live"``).

    Returns
    -------
    CollectorProfile
        The frozen profile specification.

    Raises
    ------
    ValueError
        If *name* is not a recognised collector profile.
    """
    try:
        key = CollectorProfileName(name)
    except ValueError:
        valid = ", ".join(p.value for p in CollectorProfileName)
        raise ValueError(
            f"Unknown collector profile {name!r}. Valid profiles: {valid}"
        ) from None
    return BUILTIN_COLLECTOR_PROFILES[key]


def apply_collector_profile(
    collection_config: _models_mod.CollectionConfig,
    profile: CollectorProfile,
) -> _models_mod.CollectionConfig:
    """Return a new :class:`~alpha_core.config.models.CollectionConfig` with
    polling intervals and heartbeat timeout overridden by *profile*.

    All other fields (``mode``, ``stream_outcomes_max``, etc.) are preserved
    from *collection_config* so venue-specific overrides are not lost.

    Parameters
    ----------
    collection_config:
        Base collection config to derive from (usually from ``VenueConfig``).
    profile:
        Collector profile whose timing values take precedence.

    Returns
    -------
    CollectionConfig
        A new config instance with profile values applied.
    """
    return collection_config.model_copy(
        update={
            "trade_poll_interval": profile.trade_poll_interval,
            "ohlcv_poll_interval": profile.ohlcv_poll_interval,
            "book_poll_interval": profile.book_poll_interval,
            "market_refresh_interval": profile.market_refresh_interval,
            "heartbeat_timeout": profile.heartbeat_timeout,
            "reconnect_backoff_base": profile.reconnect_backoff_base,
            "reconnect_backoff_max": profile.reconnect_backoff_max,
        }
    )


__all__ = [
    "BUILTIN_COLLECTOR_PROFILES",
    "CollectorProfile",
    "CollectorProfileName",
    "apply_collector_profile",
    "get_collector_profile",
]
