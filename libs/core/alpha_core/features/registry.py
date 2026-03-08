"""FeatureRegistry — manages feature definitions and resolves computation order.

Usage::

    registry = FeatureRegistry()
    registry.register(RollingMean(window=20))
    registry.register(ZScore(window=50))   # no dependency on RollingMean here

    enriched_table = registry.compute_all(gold_table)

Dependency handling
-------------------
A feature can list other feature names in its ``dependencies`` property.
:meth:`dependency_order` returns a topologically sorted list so dependent
features are always computed *after* their inputs already exist as columns
in the working table.

Error policy
------------
- Registering a feature whose dependency isn't registered yet raises
  :exc:`ValueError` immediately (fail-fast).
- Computing an unregistered feature name raises :exc:`KeyError`.
- Cyclic dependencies raise :exc:`ValueError` from the topological sort.
"""

from __future__ import annotations

from collections import deque

import pyarrow as pa
import pyarrow.compute as pc

import alpha_core.features.base as feature_base


class FeatureRegistry:
    """Manages feature definitions, dependency resolution, and computation."""

    def __init__(self) -> None:
        self._features: dict[str, feature_base.Feature] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, feature: feature_base.Feature) -> None:
        """Register a feature.

        Raises:
            ValueError: If any declared dependency has not yet been registered.
            ValueError: If a feature with the same name is already registered.
        """
        if feature.name in self._features:
            raise ValueError(
                f"Feature '{feature.name}' is already registered. "
                "Use a unique name or deregister the existing one first."
            )
        missing_deps = [d for d in feature.dependencies if d not in self._features]
        if missing_deps:
            raise ValueError(
                f"Feature '{feature.name}' depends on unregistered features: {missing_deps}. "
                "Register dependencies first."
            )
        self._features[feature.name] = feature

    def deregister(self, name: str) -> None:
        """Remove a feature from the registry (raises KeyError when absent)."""
        if name not in self._features:
            raise KeyError(f"Feature '{name}' is not registered.")
        # Guard: refuse if another registered feature depends on this one.
        dependants = [f.name for f in self._features.values() if name in f.dependencies]
        if dependants:
            raise ValueError(f"Cannot deregister '{name}': depended on by {dependants}.")
        del self._features[name]

    # ------------------------------------------------------------------
    # Computation
    # ------------------------------------------------------------------

    def compute_feature(
        self,
        name: str,
        data: pa.Table,
        instrument_id: str | None = None,
    ) -> feature_base.FeatureResult:
        """Compute a single registered feature.

        Raises:
            KeyError: When *name* is not registered.
        """
        if name not in self._features:
            raise KeyError(f"Feature '{name}' is not registered.")
        return self._features[name].compute(data, instrument_id=instrument_id)

    def compute_all(
        self,
        data: pa.Table,
        *,
        features: list[str] | None = None,
        instrument_ids: list[str] | None = None,
    ) -> pa.Table:
        """Compute requested features in dependency order.

        Args:
            data: Input table (typically gold dataset partition).
            features: Subset of registered feature names to compute.
                      When ``None``, all registered features are computed.
            instrument_ids: Optional instrument filter applied *before*
                            computation (filters table rows).

        Returns:
            Input table with one additional column per computed feature.
            Columns are appended in topological dependency order.

        Raises:
            KeyError: When a requested feature name is not registered.
            ValueError: When dependencies form a cycle.
        """
        requested = set(features) if features is not None else set(self._features)
        unknown = requested - set(self._features)
        if unknown:
            raise KeyError(f"Unregistered features requested: {sorted(unknown)}")

        # Expand to include all transitive dependencies.
        all_needed = self._transitive_deps(requested)
        ordered = [n for n in self.dependency_order() if n in all_needed]

        # Optional instrument filter.
        working = data
        if instrument_ids is not None and "instrument_id" in data.schema.names:
            mask = pc.is_in(
                data.column("instrument_id"),
                value_set=pa.array(instrument_ids, type=pa.string()),
            )
            working = data.filter(mask)

        # Compute each feature, appending result columns.
        for name in ordered:
            result = self._features[name].compute(working)
            col = pa.array(result.values, type=pa.float64())
            working = working.append_column(pa.field(name, pa.float64()), col)

        return working

    # ------------------------------------------------------------------
    # Dependency graph
    # ------------------------------------------------------------------

    @property
    def registered(self) -> list[str]:
        """Alphabetically sorted list of registered feature names."""
        return sorted(self._features)

    def dependency_order(self) -> list[str]:
        """Topologically sorted feature names (dependencies first).

        Raises:
            ValueError: When the dependency graph contains a cycle.
        """
        # Kahn's algorithm.
        in_degree: dict[str, int] = {n: 0 for n in self._features}
        dependants: dict[str, list[str]] = {n: [] for n in self._features}

        for name, feat in self._features.items():
            for dep in feat.dependencies:
                if dep in self._features:
                    in_degree[name] += 1
                    dependants[dep].append(name)

        queue: deque[str] = deque(sorted(n for n, d in in_degree.items() if d == 0))
        order: list[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for child in sorted(dependants[node]):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(order) != len(self._features):
            cycle_nodes = [n for n, d in in_degree.items() if d > 0]
            raise ValueError(f"Cyclic dependency detected among features: {sorted(cycle_nodes)}")
        return order

    def _transitive_deps(self, names: set[str]) -> set[str]:
        """Return *names* plus all transitive dependencies."""
        result: set[str] = set()
        stack = list(names)
        while stack:
            n = stack.pop()
            if n in result:
                continue
            result.add(n)
            feat = self._features.get(n)
            if feat is not None:
                for dep in feat.dependencies:
                    if dep not in result:
                        stack.append(dep)
        return result


__all__ = ["FeatureRegistry"]
