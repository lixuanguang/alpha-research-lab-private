"""Standardized run summary block emitted after every research and live command.

Public API
----------
- :data:`RUN_SUMMARY_SCHEMA_VERSION` — increment whenever :class:`RunSummary`
  fields change (add / remove / rename / type change).
- :class:`RunSummary` — Pydantic model serialized to JSON or text by CLIs.
  Round-trips losslessly via :meth:`~pydantic.BaseModel.model_dump` /
  :meth:`~pydantic.BaseModel.model_validate`.

Schema versioning rule
----------------------
When any field in :class:`RunSummary` changes:

1. Bump :data:`RUN_SUMMARY_SCHEMA_VERSION`.
2. Update the snapshot in
   ``tests/regression/test_run_manifest_schema.py`` — change
   ``_EXPECTED_RUN_SUMMARY_KEYS`` and ``_EXPECTED_RUN_SUMMARY_VERSION``.
3. Record a brief reason in the commit message (e.g. "added latency_ms field").

``summary_version`` is included in every serialized payload so consumers can
detect incompatible producer versions at runtime.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

import alpha_core.research.run_context as run_context_mod

# ---------------------------------------------------------------------------
# Schema version — pin here; tests pin in regression suite
# ---------------------------------------------------------------------------

#: Bump whenever any field in :class:`RunSummary` changes.
#: The regression snapshot in tests/regression/test_run_manifest_schema.py
#: will fail until explicitly updated alongside this constant.
RUN_SUMMARY_SCHEMA_VERSION: int = 1


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class RunSummary(BaseModel):
    """Core traceability block emitted after every research or live command run.

    Fields cover the full provenance chain — identity, timing, config
    fingerprint, git commit, and the artifact index — so any downstream
    consumer can reconstruct what ran, when, and where the outputs live.

    Stage-specific values (e.g. ``trade_count``, ``strategy_id``) belong in
    the :attr:`extra` dict rather than as top-level fields so the contract
    stays stable across all pipeline stages.
    """

    model_config = ConfigDict(extra="forbid")

    summary_version: int = Field(
        default=RUN_SUMMARY_SCHEMA_VERSION,
        description="Schema version.  Bump with every field change.",
    )
    run_id: str
    """Unique run identifier (UUID hex) assigned at run-context creation."""
    run_type: str
    """Pipeline stage: ``dataset_build``, ``backtest``, ``live``, etc."""
    status: str
    """Lifecycle state: ``planned``, ``materialized``, ``completed``, ``failed``."""
    config_hash: str | None = None
    """SHA-256 hex digest of the run config payload (first 16 chars shown in text mode)."""
    git_commit: str | None = None
    """Git HEAD short-hash at the time the run was created, or ``None``."""
    started_at_utc: datetime | None = None
    """UTC timestamp when the run context was created."""
    completed_at_utc: datetime | None = None
    """UTC timestamp when the run context was closed, or ``None`` for planned runs."""
    artifact_keys: list[str] = Field(default_factory=list)
    """Sorted list of artifact labels persisted by this run."""
    extra: dict[str, Any] = Field(default_factory=dict)
    """Stage-specific extensions.  Kept flat for JSON-friendliness.

    Examples: ``{"strategy_id": "zscore_v1", "trade_count": 42}``.
    """

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_run_context(
        cls,
        run_context: run_context_mod.RunContext,
        *,
        status: str,
        artifact_keys: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> RunSummary:
        """Build a summary from a completed research run context.

        Args:
            run_context: The closed run context to summarise.
            status:       Human-readable lifecycle label (``"materialized"``, etc.).
            artifact_keys: Labels of persisted output artifacts.
            extra:         Stage-specific key/value pairs to include verbatim.
        """
        return cls(
            run_id=run_context.run_id,
            run_type=run_context.run_type,
            status=status,
            config_hash=run_context.config_hash,
            git_commit=run_context.git_commit,
            started_at_utc=run_context.started_at_utc,
            completed_at_utc=run_context.completed_at_utc,
            artifact_keys=sorted(artifact_keys or []),
            extra=extra or {},
        )

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def as_text(self) -> str:
        """Single-line human-readable summary for CLI text output.

        Example::

            run_summary v=1  run_id=ab12cd34  run_type=backtest  ...
        """
        parts = [
            f"run_summary v={self.summary_version}",
            f"run_id={self.run_id}",
            f"run_type={self.run_type}",
            f"status={self.status}",
        ]
        if self.config_hash:
            parts.append(f"config_hash={self.config_hash[:16]}")
        if self.git_commit:
            parts.append(f"git={self.git_commit}")
        if self.artifact_keys:
            parts.append(f"artifacts={','.join(self.artifact_keys)}")
        for k, v in sorted(self.extra.items()):
            parts.append(f"{k}={v}")
        return "  ".join(parts)

    def as_json_str(self, *, indent: int = 2) -> str:
        """JSON-serialized summary with sorted keys for stable diffs."""
        return json.dumps(self.model_dump(mode="json"), indent=indent, sort_keys=True)


__all__ = ["RUN_SUMMARY_SCHEMA_VERSION", "RunSummary"]
