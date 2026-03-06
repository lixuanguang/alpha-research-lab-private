"""Performance boundary protocol interfaces.

Contract-only module — implementations live in the Research Plane MVP and
later optimisation stages.  All protocols are ``@runtime_checkable`` so
downstream code can use ``isinstance`` guards without importing concrete
classes.

Design rules
------------
1. **Identical signatures** — every accelerated implementation must have the
   exact same method signatures as its baseline counterpart.
2. **No side effects on inputs** — both baseline and accelerated paths must
   treat their arguments as read-only.
3. **Parity obligation** — every accelerated path must pass a
   :func:`~alpha_core.performance.parity.check_feature_parity` or
   :func:`~alpha_core.performance.parity.check_simulation_parity` gate before
   being promoted to the default code path.

Protocols
---------
FeatureTransform   — apply a named numeric transform to a sequence of floats
SimulationKernel   — advance a simulation one step given state + event

Usage::

    from alpha_core.performance.interfaces import FeatureTransform, SimulationKernel
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class FeatureTransform(Protocol):
    """Apply a named numeric transform to a sequence of float observations.

    Implementations cover rolling/EWM statistics, cross-sectional
    normalization, and any other per-column feature engineering kernel.

    Contract
    --------
    - ``name`` must be a non-empty string that uniquely identifies the
      transform variant (for example ``"ewm_mean_alpha0.1"``).
    - ``compute`` must be deterministic: same inputs always yield the same
      outputs.
    - The output sequence must have the same length as the input sequence.
    - ``nan``-handling policy (propagate vs. fill) is implementation-defined
      but must be documented on the concrete class.
    """

    @property
    def name(self) -> str:
        """Human-readable identifier for this transform variant."""
        ...

    def compute(self, values: Sequence[float]) -> Sequence[float]:
        """Apply the transform and return a same-length sequence of floats.

        Parameters
        ----------
        values:
            Input observations in chronological order (oldest-first).

        Returns
        -------
        Sequence[float]
            Transformed values; length must equal ``len(values)``.
        """
        ...


@runtime_checkable
class SimulationKernel(Protocol):
    """Advance simulation state one step given the current state and an event.

    Implementations cover event-driven mark-to-market, PnL attribution,
    execution simulation, and any other stateful tick-by-tick computation.

    Contract
    --------
    - ``name`` must be a non-empty string that uniquely identifies the kernel.
    - ``step`` must not mutate the ``state`` or ``event`` arguments; it must
      return a new state mapping.
    - ``step`` must be deterministic for identical ``(state, event)`` pairs.
    - The returned mapping must contain at minimum all keys present in the
      input ``state`` (monotone key set).
    """

    @property
    def name(self) -> str:
        """Human-readable identifier for this kernel variant."""
        ...

    def step(
        self,
        state: Mapping[str, Any],
        event: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Advance state by one event and return the updated state mapping.

        Parameters
        ----------
        state:
            Current simulation state (read-only).
        event:
            Incoming market event to process (read-only).

        Returns
        -------
        Mapping[str, Any]
            Updated state; must include all keys from the input ``state``.
        """
        ...
