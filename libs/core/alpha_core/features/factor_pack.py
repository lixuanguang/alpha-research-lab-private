"""FactorPackManifest — versioned, reusable feature-computation contracts.

A *factor pack* bundles a named set of feature computations under a stable
``pack_id`` + ``version`` pair so that ``build-features`` pipelines can
reference a manifest rather than embedding ad-hoc logic in notebooks.

Storage convention
------------------
Factor-pack manifests are plain YAML or JSON files loaded by callers.
Canonical location (by convention, not enforced)::

    config/research/factor_packs/<pack_id>_v<version>.yaml

Typical usage::

    import alpha_core.features.factor_pack as fp_mod

    pack = fp_mod.load_factor_pack(Path("config/research/factor_packs/momentum_v1.yaml"))
    fp_mod.validate_dependencies(pack, available_packs=[])
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class FactorPackManifest(BaseModel):
    """Versioned contract describing one reusable factor pack.

    Fields
    ------
    pack_id
        Stable identifier for this factor pack (e.g. ``"momentum"``).
    version
        Semantic version string (e.g. ``"1.0.0"``).
    description
        Human-readable summary of what this pack computes.
    dependencies
        List of ``pack_id`` strings this pack requires to have been resolved
        first.  Dependency order is validated at runtime by
        :func:`resolve_dependency_order`.
    output_schema
        Mapping of output column name to its data type description
        (e.g. ``{"price_zscore_20": "float64"}``).  This is the authoritative
        list of columns the pack adds to a feature matrix.
    parameters
        Optional default parameter values overridable per-run
        (e.g. ``{"lookback": 20}``).
    """

    model_config = ConfigDict(extra="forbid")

    pack_id: str = Field(min_length=1, description="Stable factor-pack identifier.")
    version: str = Field(min_length=1, description="Semantic version string.")
    description: str = Field(default="", description="Human-readable description.")
    dependencies: list[str] = Field(
        default_factory=list,
        description="pack_id strings that must be resolved before this pack.",
    )
    output_schema: dict[str, str] = Field(
        default_factory=dict,
        description="column_name -> dtype description for each output feature.",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Default parameter values overridable at run time.",
    )

    @field_validator("pack_id", "version")
    @classmethod
    def _strip_nonempty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must not be blank")
        return cleaned


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def load_factor_pack(path: Path) -> FactorPackManifest:
    """Load a :class:`FactorPackManifest` from a YAML or JSON file.

    Raises :exc:`FileNotFoundError` if *path* does not exist.
    Raises :exc:`ValueError` with a descriptive message for schema errors.
    """
    if not path.exists():
        raise FileNotFoundError(f"Factor-pack manifest not found: {path}")
    raw_text = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(raw_text)
    else:
        data = json.loads(raw_text)
    try:
        return FactorPackManifest.model_validate(data)
    except Exception as exc:
        raise ValueError(f"Invalid factor-pack manifest at {path}: {exc}") from exc


def save_factor_pack(pack: FactorPackManifest, path: Path) -> None:
    """Persist *pack* as YAML (or JSON for ``.json`` suffix)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = cast(dict[str, Any], json.loads(pack.model_dump_json()))
    if path.suffix in {".yaml", ".yml"}:
        path.write_text(yaml.dump(data, sort_keys=True, allow_unicode=True), encoding="utf-8")
    else:
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Dependency resolution
# ---------------------------------------------------------------------------


def resolve_dependency_order(packs: list[FactorPackManifest]) -> list[FactorPackManifest]:
    """Return *packs* in a valid topological order respecting *dependencies*.

    Raises :exc:`ValueError` if:
    - A declared dependency is not present in *packs*.
    - A circular dependency is detected.
    """
    by_id = {p.pack_id: p for p in packs}

    # Verify all declared dependencies are available.
    for pack in packs:
        for dep_id in pack.dependencies:
            if dep_id not in by_id:
                raise ValueError(
                    f"Factor pack {pack.pack_id!r} declares dependency "
                    f"{dep_id!r} which is not in the provided pack list."
                )

    # Kahn's algorithm for topological sort.
    in_degree: dict[str, int] = {p.pack_id: 0 for p in packs}
    dependents: dict[str, list[str]] = {p.pack_id: [] for p in packs}
    for pack in packs:
        for dep_id in pack.dependencies:
            dependents[dep_id].append(pack.pack_id)
            in_degree[pack.pack_id] += 1

    queue = [pid for pid, deg in in_degree.items() if deg == 0]
    ordered: list[FactorPackManifest] = []
    while queue:
        pid = queue.pop(0)
        ordered.append(by_id[pid])
        for dependent in dependents[pid]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(ordered) != len(packs):
        cycle_ids = sorted(pid for pid, deg in in_degree.items() if deg > 0)
        raise ValueError(
            f"Circular dependency detected among factor packs: {cycle_ids}"
        )
    return ordered


def validate_dependencies(
    pack: FactorPackManifest,
    available_packs: list[FactorPackManifest],
) -> None:
    """Assert that all dependencies of *pack* are present in *available_packs*.

    Raises :exc:`ValueError` listing missing dependency IDs.
    """
    available_ids = {p.pack_id for p in available_packs}
    missing = [dep for dep in pack.dependencies if dep not in available_ids]
    if missing:
        raise ValueError(
            f"Factor pack {pack.pack_id!r} has unresolved dependencies: {missing}"
        )
