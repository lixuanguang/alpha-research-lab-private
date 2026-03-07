"""Research runtime scaffolding for stage-aligned run manifests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import alpha_core.research.run_context as run_context_mod


@dataclass(slots=True, frozen=True)
class ResearchStageOutcome:
    run_id: str
    run_type: run_context_mod.RunType
    status: str
    config_hash: str
    manifest_path: Path | None = None


def plan_stage(
    *,
    run_type: run_context_mod.RunType,
    payload: dict[str, Any],
) -> ResearchStageOutcome:
    run_context = run_context_mod.make_run_context(
        run_type,
        config_payload=payload,
    )
    return ResearchStageOutcome(
        run_id=run_context.run_id,
        run_type=run_context.run_type,
        status="planned",
        config_hash=run_context.config_hash,
    )


__all__ = ["ResearchStageOutcome", "plan_stage"]
