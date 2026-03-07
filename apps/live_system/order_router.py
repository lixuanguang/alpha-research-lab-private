"""Order routing boundary — adapter-facing layer between the live runtime and venues.

This module defines:

- :class:`VenueAdapter` — Protocol that venue connectors must satisfy.  The
  live runtime submits :class:`~alpha_core.strategy_framework.models.OrderIntent`
  objects here; the adapter translates them to venue-specific API calls.

- :class:`SubmissionResult` — per-order outcome returned by an adapter.

- :class:`RoutingResult` — aggregate result of routing a batch of orders,
  including per-order details and summary counters.

- :class:`OrderRouter` — concrete router that fans out a list of
  :class:`OrderIntent` objects to a :class:`VenueAdapter` and records routing
  metrics.  Failures are isolated per-order and never abort the whole batch.
  An optional :class:`~alpha_core.execution.pretrade.PreTradeValidator` can be
  injected; when set, each order is validated **before** :meth:`VenueAdapter.submit`
  is called.  Pre-trade rejections are counted separately from adapter rejections.

Usage::

    from alpha_core.execution.pretrade import PreTradeConfig, PreTradeValidator

    validator = PreTradeValidator(PreTradeConfig(allow_market_orders=False))
    router = OrderRouter(adapter, validator=validator)
    result = router.route(orders, state)
    for detail in result.details:
        if not detail.accepted:
            log.warning("Rejected: %s pretrade=%s reason=%s",
                        detail.order_id, detail.pretrade_rejected, detail.reject_reason)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import alpha_core.strategy_framework.models as strategy_models

if TYPE_CHECKING:
    from alpha_core.execution.pretrade import PreTradeValidator

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# VenueAdapter protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class VenueAdapter(Protocol):
    """Protocol that any venue connector must satisfy to work with :class:`OrderRouter`.

    A minimal NOOP implementation sufficient for unit tests can be:

    .. code-block:: python

        class NoopAdapter:
            def submit(self, order: strategy_models.OrderIntent) -> SubmissionResult:
                return SubmissionResult(order_id=order.instrument_id, accepted=True)
            def cancel(self, order_id: str) -> bool:
                return True
            def adapter_id(self) -> str:
                return "noop"
    """

    def submit(self, order: strategy_models.OrderIntent) -> "SubmissionResult":
        """Submit a single order intent to the venue.

        Should raise on unrecoverable infrastructure errors.  Logical rejects
        (e.g. insufficient liquidity) should be returned as
        ``SubmissionResult(accepted=False, reject_reason=...)``.
        """
        ...

    def cancel(self, order_id: str) -> bool:
        """Request cancellation of an outstanding order by its venue order ID.

        Returns ``True`` if the cancel was acknowledged, ``False`` if not found
        or already filled.
        """
        ...

    def adapter_id(self) -> str:
        """Return a stable identifier for this adapter (e.g. ``"polymarket"``).

        Used in routing logs and metrics labels.
        """
        ...


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubmissionResult:
    """Result of submitting a single :class:`~alpha_core.strategy_framework.models.OrderIntent`
    to a :class:`VenueAdapter`.
    """

    order_id: str
    """Venue-assigned order identifier, or the instrument_id if the adapter does
    not assign IDs at submission time."""

    accepted: bool
    """``True`` if the venue acknowledged the order for processing."""

    reject_reason: str | None = None
    """Human-readable reason when ``accepted=False``."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Optional adapter-specific fields (e.g. venue order UUID, timestamp)."""


@dataclass(frozen=True)
class RoutingRecord:
    """Per-order routing record included in :class:`RoutingResult`."""

    instrument_id: str
    order_type: str
    direction: str
    accepted: bool
    order_id: str | None
    reject_reason: str | None
    routed_at: datetime
    pretrade_rejected: bool = False
    """``True`` when the order was stopped by the pre-trade validator before
    reaching the venue adapter."""


@dataclass
class RoutingResult:
    """Aggregate result of one :meth:`OrderRouter.route` call."""

    adapter_id: str
    routed_at: datetime
    total: int
    accepted: int
    rejected: int
    errors: int
    pretrade_rejected: int = 0
    """Count of orders stopped by the pre-trade validator (subset of ``rejected``)."""
    details: list[RoutingRecord] = field(default_factory=list)

    @property
    def all_accepted(self) -> bool:
        return self.rejected == 0 and self.errors == 0


# ---------------------------------------------------------------------------
# OrderRouter
# ---------------------------------------------------------------------------


class OrderRouter:
    """Routes a batch of :class:`~alpha_core.strategy_framework.models.OrderIntent`
    objects to a single :class:`VenueAdapter`.

    Per-order exceptions are caught, logged, and counted as ``errors`` so that
    one bad order never prevents the rest of the batch from being submitted.

    Args:
        adapter: A :class:`VenueAdapter`-compatible object.
        dry_run: When ``True``, orders are *not* forwarded to the adapter.
            Instead every order is recorded as accepted with ``order_id="dry_run"``.
            Useful for plan-only CLI modes and offline tests.
    """

    def __init__(
        self,
        adapter: VenueAdapter,
        *,
        dry_run: bool = False,
        validator: PreTradeValidator | None = None,
    ) -> None:
        self._adapter = adapter
        self._dry_run = dry_run
        self._validator = validator
        self._total_routed = 0
        self._total_accepted = 0
        self._total_rejected = 0
        self._total_errors = 0
        self._total_pretrade_rejected = 0

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def route(
        self,
        orders: list[strategy_models.OrderIntent],
        state: strategy_models.MarketState,
    ) -> RoutingResult:
        """Route *orders* to the configured adapter and return an aggregate result.

        If a :class:`~alpha_core.execution.pretrade.PreTradeValidator` was
        provided at construction, each order is validated first.  Orders that
        fail pre-trade checks are recorded as rejected (``pretrade_rejected=True``)
        without ever reaching the adapter.

        Args:
            orders: Order intents produced by the strategy execution layer.
            state:  Market state snapshot passed to the pre-trade validator.
        """
        routed_at = datetime.now(tz=UTC)
        details: list[RoutingRecord] = []
        accepted = rejected = errors = pretrade_rejected = 0

        for order in orders:
            record = self._route_one(order, state=state, routed_at=routed_at)
            details.append(record)
            if record.accepted:
                accepted += 1
            elif record.pretrade_rejected:
                rejected += 1
                pretrade_rejected += 1
            elif record.order_id is not None:
                # order_id is set when submit() returned a result (even rejected)
                rejected += 1
            else:
                # order_id is None when submit() raised an exception
                errors += 1

        self._total_routed += len(orders)
        self._total_accepted += accepted
        self._total_rejected += rejected
        self._total_errors += errors
        self._total_pretrade_rejected += pretrade_rejected

        adapter_label = self._adapter.adapter_id()
        log.info(
            "routed adapter=%s total=%d accepted=%d rejected=%d pretrade=%d errors=%d",
            adapter_label,
            len(orders),
            accepted,
            rejected,
            pretrade_rejected,
            errors,
        )
        return RoutingResult(
            adapter_id=adapter_label,
            routed_at=routed_at,
            total=len(orders),
            accepted=accepted,
            rejected=rejected,
            errors=errors,
            pretrade_rejected=pretrade_rejected,
            details=details,
        )

    def _route_one(
        self,
        order: strategy_models.OrderIntent,
        *,
        state: strategy_models.MarketState,
        routed_at: datetime,
    ) -> RoutingRecord:
        # Pre-trade validation (if a validator is configured)
        if self._validator is not None:
            validated = self._validator.validate(order, state=state)
            if not validated.is_valid:
                return RoutingRecord(
                    instrument_id=order.instrument_id,
                    order_type=order.order_type.value,
                    direction=order.direction.value,
                    accepted=False,
                    order_id=None,
                    reject_reason=(
                        f"pretrade:{validated.reject_reason_code} — "
                        f"{validated.reject_reason_detail}"
                    ),
                    routed_at=routed_at,
                    pretrade_rejected=True,
                )

        if self._dry_run:
            return RoutingRecord(
                instrument_id=order.instrument_id,
                order_type=order.order_type.value,
                direction=order.direction.value,
                accepted=True,
                order_id="dry_run",
                reject_reason=None,
                routed_at=routed_at,
            )

        try:
            result = self._adapter.submit(order)
        except Exception as exc:
            log.exception(
                "Adapter error submitting order instrument=%s: %s",
                order.instrument_id,
                exc,
            )
            return RoutingRecord(
                instrument_id=order.instrument_id,
                order_type=order.order_type.value,
                direction=order.direction.value,
                accepted=False,
                order_id=None,
                reject_reason=f"adapter_exception: {exc}",
                routed_at=routed_at,
            )

        if not result.accepted:
            log.warning(
                "Order rejected instrument=%s reason=%s",
                order.instrument_id,
                result.reject_reason,
            )
        return RoutingRecord(
            instrument_id=order.instrument_id,
            order_type=order.order_type.value,
            direction=order.direction.value,
            accepted=result.accepted,
            order_id=result.order_id,
            reject_reason=result.reject_reason,
            routed_at=routed_at,
        )

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @property
    def total_routed(self) -> int:
        return self._total_routed

    @property
    def total_accepted(self) -> int:
        return self._total_accepted

    @property
    def total_rejected(self) -> int:
        return self._total_rejected

    @property
    def total_errors(self) -> int:
        return self._total_errors

    @property
    def total_pretrade_rejected(self) -> int:
        """Orders stopped by the pre-trade validator (subset of total_rejected)."""
        return self._total_pretrade_rejected


__all__ = [
    "OrderRouter",
    "RoutingRecord",
    "RoutingResult",
    "SubmissionResult",
    "VenueAdapter",
]
