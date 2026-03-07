"""Environment profile contract.

Defines the five named runtime profiles used across all stages of the
alpha research platform.  Each profile specifies storage, logging, safety
flags, and retention defaults so that stage code can remain
environment-agnostic.

Profiles
--------
dev        Development / local experimentation.  Debug logging, execution
           disabled, no real-money flag.
research   Backtesting and feature development.  Execution explicitly
           disabled so strategy code cannot accidentally submit orders.
ci         Continuous integration.  Warning-level logging, short retention
           to keep CI storage light.
paper      Paper-trading dry runs.  Execution enabled but real-money flag
           is off; mimics live behaviour without financial risk.
live       Production trading.  Execution and real-money both enabled;
           full data retention.

Usage::

    import alpha_core.config.profiles as config_profiles

    profile = config_profiles.get_profile(config_profiles.ProfileName.RESEARCH)
    assert not profile.execution_enabled   # safely True by contract
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


# ---------------------------------------------------------------------------
# Profile name enum
# ---------------------------------------------------------------------------


class ProfileName(StrEnum):
    """Canonical runtime profile identifiers."""

    DEV = "dev"
    RESEARCH = "research"
    CI = "ci"
    PAPER = "paper"
    LIVE = "live"


# ---------------------------------------------------------------------------
# Profile model
# ---------------------------------------------------------------------------


class EnvironmentProfile(BaseModel):
    """Complete specification of a runtime environment profile.

    Attributes
    ----------
    name:
        Canonical profile identifier.
    storage_root:
        Base directory for all data written under this profile.
    log_level:
        Minimum log level for this profile.
    execution_enabled:
        When ``False``, order-submission code must refuse to route orders.
        Provides a hard safety boundary for non-trading environments.
    dry_run:
        Convenience flag that mirrors ``not execution_enabled`` for code
        that checks ``dry_run`` independently.
    allow_real_money:
        When ``False``, live order routing to real venues must be blocked
        even if ``execution_enabled`` is ``True``.  Only ``live`` sets
        this to ``True``.
    data_retention_days:
        How many days of data to retain under ``storage_root``.  ``None``
        means retain indefinitely.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: ProfileName
    storage_root: Path
    log_level: LogLevel
    execution_enabled: bool
    dry_run: bool
    allow_real_money: bool
    data_retention_days: int | None = Field(
        default=None,
        ge=1,
        description="Days to retain data; None = keep forever.",
    )


# ---------------------------------------------------------------------------
# Built-in profile registry
# ---------------------------------------------------------------------------


BUILTIN_PROFILES: dict[ProfileName, EnvironmentProfile] = {
    ProfileName.DEV: EnvironmentProfile(
        name=ProfileName.DEV,
        storage_root=Path("data/dev"),
        log_level="DEBUG",
        execution_enabled=False,
        dry_run=True,
        allow_real_money=False,
        data_retention_days=None,
    ),
    ProfileName.RESEARCH: EnvironmentProfile(
        name=ProfileName.RESEARCH,
        storage_root=Path("data/research"),
        log_level="INFO",
        execution_enabled=False,
        dry_run=True,
        allow_real_money=False,
        data_retention_days=None,
    ),
    ProfileName.CI: EnvironmentProfile(
        name=ProfileName.CI,
        storage_root=Path("data/ci"),
        log_level="WARNING",
        execution_enabled=False,
        dry_run=True,
        allow_real_money=False,
        data_retention_days=7,
    ),
    ProfileName.PAPER: EnvironmentProfile(
        name=ProfileName.PAPER,
        storage_root=Path("data/paper"),
        log_level="INFO",
        execution_enabled=True,
        dry_run=False,
        allow_real_money=False,
        data_retention_days=90,
    ),
    ProfileName.LIVE: EnvironmentProfile(
        name=ProfileName.LIVE,
        storage_root=Path("data/live"),
        log_level="INFO",
        execution_enabled=True,
        dry_run=False,
        allow_real_money=True,
        data_retention_days=None,
    ),
}


def get_profile(name: ProfileName | str) -> EnvironmentProfile:
    """Return the built-in :class:`EnvironmentProfile` for ``name``.

    Parameters
    ----------
    name:
        A :class:`ProfileName` member or its string value
        (``"dev"``, ``"research"``, ``"ci"``, ``"paper"``, ``"live"``).

    Returns
    -------
    EnvironmentProfile
        The frozen profile specification.

    Raises
    ------
    ValueError
        If ``name`` is not a recognised profile.
    """
    try:
        key = ProfileName(name)
    except ValueError:
        valid = ", ".join(p.value for p in ProfileName)
        raise ValueError(f"Unknown profile {name!r}. Valid profiles: {valid}") from None
    return BUILTIN_PROFILES[key]


def guard_execution(
    profile: EnvironmentProfile | None,
    *,
    context: str = "order submission",
) -> None:
    """Raise :exc:`PermissionError` if ``profile`` forbids execution.

    Parameters
    ----------
    profile:
        Active :class:`EnvironmentProfile`, or ``None`` to skip the guard.
    context:
        Human-readable description of the guarded action for the error message.

    Raises
    ------
    PermissionError
        When ``profile.execution_enabled`` is ``False``.
    """
    if profile is not None and not profile.execution_enabled:
        raise PermissionError(
            f"Profile '{profile.name}' does not allow {context}. "
            f"Use '--profile paper' or '--profile live' to enable execution."
        )


def guard_real_money(
    profile: EnvironmentProfile | None,
    *,
    context: str = "real-money routing",
) -> None:
    """Raise :exc:`PermissionError` if ``profile`` forbids real-money routing.

    Parameters
    ----------
    profile:
        Active :class:`EnvironmentProfile`, or ``None`` to skip the guard.
    context:
        Human-readable description of the guarded action for the error message.

    Raises
    ------
    PermissionError
        When ``profile.allow_real_money`` is ``False``.
    """
    if profile is not None and not profile.allow_real_money:
        raise PermissionError(
            f"Profile '{profile.name}' does not allow {context}. "
            f"Use '--profile live' to enable real-money routing."
        )
