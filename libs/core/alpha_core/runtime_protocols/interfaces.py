"""Provider-agnostic runtime protocol interfaces.

Contract-only module — implementations live in the Data, Live, and Research
stages, not here.  All four protocols are ``@runtime_checkable`` so downstream
code can use ``isinstance`` guards without importing concrete classes.

Protocols
---------
AccountStateProvider   — read positions, balances, and buying power
MarketStateProvider    — read instrument status and top-of-book
OrderRouter            — submit, cancel, and query order lifecycle
ExecutionAcknowledger  — handle acks, rejects, and fills from the venue

Design notes
~~~~~~~~~~~~
- Protocol methods are synchronous; async variants are deferred to the
  Live Plane MVP where concrete event-loop constraints are known.
- ``OrderRouter.submit_order`` accepts ``strategy_models.OrderIntent`` so the
  full strategy pipeline (signal → target → order intent → router) composes
  without type gymnastics.
- All type annotations are strings at runtime thanks to
  ``from __future__ import annotations``; no circular imports occur.

Usage::

    from alpha_core.runtime_protocols.interfaces import OrderRouter, ExecutionAcknowledger
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import alpha_core.runtime_protocols.models as _m
    import alpha_core.strategy_framework.models as _sm


# ---------------------------------------------------------------------------
# AccountStateProvider
# ---------------------------------------------------------------------------


@runtime_checkable
class AccountStateProvider(Protocol):
    """Read current account state: positions, balances, and buying power.

    Implementors may poll the venue on each call or maintain a locally
    cached state refreshed from a websocket feed — callers do not need
    to know which approach is used.
    """

    def get_account_snapshot(self) -> _m.AccountSnapshot:
        """Return a point-in-time snapshot of the full account state."""
        ...

    def get_buying_power(self) -> Decimal:
        """Return the maximum notional currently available for new orders."""
        ...


# ---------------------------------------------------------------------------
# MarketStateProvider
# ---------------------------------------------------------------------------


@runtime_checkable
class MarketStateProvider(Protocol):
    """Read market-facing state for instruments: top-of-book and lifecycle.

    Callers should not assume any specific refresh rate; implementations
    may back this with a polling connector, a book-aggregation layer, or
    a cached snapshot from the Data Plane.
    """

    def get_top_of_book(self, instrument_id: str) -> _m.TopOfBook:
        """Return the best bid/ask for ``instrument_id`` at call time."""
        ...

    def get_instrument_status(self, instrument_id: str) -> _m.InstrumentStatus:
        """Return the lifecycle and tradability status for ``instrument_id``."""
        ...


# ---------------------------------------------------------------------------
# OrderRouter
# ---------------------------------------------------------------------------


@runtime_checkable
class OrderRouter(Protocol):
    """Submit, cancel, and query orders at the venue.

    Accepts ``OrderIntent`` from the strategy framework so the full pipeline
    composes without an intermediate translation step.  Concrete routing
    logic (venue selection, fee estimation, pre-trade checks) is deferred
    to the Live Plane MVP.
    """

    def submit_order(self, order: _sm.OrderIntent) -> str:
        """Submit an order; return the venue-assigned order ID.

        Raises ``ValueError`` if the order fails basic sanity checks.
        Downstream callers should expect ``OrderAck`` or ``OrderReject``
        via a paired :class:`ExecutionAcknowledger`.
        """
        ...

    def cancel_order(self, order_id: str) -> bool:
        """Request cancellation of ``order_id``.

        Returns ``True`` if the cancellation request was accepted by the
        venue (not necessarily confirmed); ``False`` otherwise.
        """
        ...

    def query_order(self, order_id: str) -> _m.OrderStatus:
        """Return the current status of an order by venue-assigned ID."""
        ...


# ---------------------------------------------------------------------------
# ExecutionAcknowledger
# ---------------------------------------------------------------------------


@runtime_checkable
class ExecutionAcknowledger(Protocol):
    """Receive and handle execution lifecycle events from the venue.

    Implementations might update position state, emit metrics, write to a
    ledger, or forward events to a risk service.  The three callback methods
    cover the full lifecycle: acknowledge → (fill | reject).
    """

    def on_ack(self, ack: _m.OrderAck) -> None:
        """Handle a venue acknowledgement of a submitted order."""
        ...

    def on_reject(self, reject: _m.OrderReject) -> None:
        """Handle a venue rejection of a submitted order."""
        ...

    def on_fill(self, fill: _m.OrderFill) -> None:
        """Handle a partial or full fill event."""
        ...
