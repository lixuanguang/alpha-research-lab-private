"""Gate freshness-dependent use of durably observed native book state."""

from __future__ import annotations

# project library imports
from market_data.contracts import CaptureRecord


class ContinuousQuality:
    """Keep constant-size progress and recovery state for one configured binding.

    The watermark covers local receipt, not an invented exchange clock. Native
    decoders enforce their source ordering separately. Only exploratory degraded
    book use is admitted: recorder coverage and execution suitability are unproven.
    """

    def __init__(self, scope: str, *, lateness_ns: int, freshness_ns: int) -> None:
        """Bind explicit receipt lateness and market-progress freshness budgets.

        Args:
            scope: Instrument, native source and stream scope of this state.
            lateness_ns: Maximum receipt regression relative to observed high water.
            freshness_ns: Maximum age of a snapshot or economic update, in nanoseconds.

        Raises:
            ValueError: Scope or either finite nonnegative integer budget is invalid.
        """
        if (
            not isinstance(scope, str)
            or not scope
            or any(
                type(value) is not int or value < minimum
                for value, minimum in ((lateness_ns, 0), (freshness_ns, 1))
            )
        ):
            raise ValueError("quality requires a scope and integer nanosecond budgets")
        self.scope, self.lateness_ns, self.freshness_ns = scope, lateness_ns, freshness_ns
        self.status, self.reason = "unavailable", "no durable input"
        self.transition_ns = 0
        self.last_durable_ns = 0
        self.last_market_ns: int | None = None
        self.watermark_ns = 0
        self.source_watermark_ns: int | None = None
        self._recovering = True
        self._failed = False

    def observe(
        self, record: CaptureRecord, outcome: str, *, ready: bool, source_ns: int | None = None
    ) -> bool:
        """Advance only after persistence and native message validation.

        Args:
            record: Exact durable receipt, including session/gap boundaries.
            outcome: Native decoder classification; invalid input retains its raw bytes.
            ready: Native reconstruction readiness after this whole message.
            source_ns: Exact source time on a snapshot/update, or explicit unknown.

        Returns:
            False when receipt lateness exceeds policy and reconstruction must restart.
            Allowed late receipts never move progress or availability backwards.

        Raises:
            ValueError: A decoder result or source clock is malformed.
        """
        record.__post_init__()
        if (
            type(ready) is not bool
            or not isinstance(outcome, str)
            or not outcome
            or (source_ns is not None and (type(source_ns) is not int or source_ns < 0))
        ):
            raise ValueError("invalid quality decoder result or source clock")
        late = record.received_ns < self.watermark_ns or (
            source_ns is not None
            and self.source_watermark_ns is not None
            and source_ns < self.source_watermark_ns
        )
        self.last_durable_ns = max(self.last_durable_ns, record.received_ns)
        self.watermark_ns = max(0, self.last_durable_ns - self.lateness_ns)
        if source_ns is not None:
            self.source_watermark_ns = max(
                self.source_watermark_ns or 0, source_ns - self.lateness_ns
            )
        if record.kind == "session":
            self._recovering = True
            self._failed = False
            self.last_market_ns = None
        if late or record.kind == "gap" or outcome == "invalid_frame":
            self._recovering = True
            self._failed = True
            self._transition(
                "recovering", "event beyond watermark" if late else record.reason or outcome
            )
        elif record.kind in ("end", "session_end"):
            self._recovering = True
            self._transition("unavailable", record.reason or "session closed")
        else:
            if ready and not self._failed and outcome in ("snapshot", "update"):
                self._recovering = False
            if ready and not self._recovering and outcome in ("snapshot", "update"):
                self.last_market_ns = max(
                    self.last_market_ns or 0,
                    min(source_ns or self.last_durable_ns, self.last_durable_ns),
                )
            self._refresh(self.last_durable_ns)
        return not late

    def require_usable(self, *, now_ns: int, allow_degraded: bool = False) -> None:
        """Refuse stale, unsynchronized or unqualified freshness-dependent consumers.

        Args:
            now_ns: Explicit current UTC nanoseconds; never earlier than durable progress.
            allow_degraded: Explicit opt-in to exploratory visible-book limitations.

        Raises:
            ValueError: Time regresses or the selected consumer cannot use this state.
        """
        if type(now_ns) is not int or now_ns < self.last_durable_ns:
            raise ValueError("quality observation time precedes durable progress")
        if self.status != "unavailable":
            self._refresh(now_ns)
        if self.status != "degraded" or not allow_degraded:
            raise ValueError(f"book consumer refused: {self.status}: {self.reason}")

    def _refresh(self, now_ns: int) -> None:
        """Keep heartbeat receipt separate from advancing economic state."""
        if self._recovering or self.last_market_ns is None:
            self._transition("recovering", "validated snapshot required", now_ns)
        elif now_ns - self.last_market_ns > self.freshness_ns:
            self._transition("stale", "market progress exceeded freshness budget", now_ns)
        else:
            self._transition("degraded", "visible depth only; recorder coverage unproven", now_ns)

    def _transition(self, status: str, reason: str, now_ns: int | None = None) -> None:
        """Retain the first time of a status/reason change, including explicit clock checks."""
        if (status, reason) != (self.status, self.reason):
            self.status, self.reason = status, reason
            self.transition_ns = self.last_durable_ns if now_ns is None else now_ns

    def summary(self) -> dict[str, object]:
        """Expose scoped status and durable progress without claiming complete coverage.

        Returns:
            Deterministic report suitable for a retained message-boundary quality history.
        """
        return {
            "status": self.status,
            "reason": self.reason,
            "scope": self.scope,
            "transition_ns": self.transition_ns,
            "last_durable_ns": self.last_durable_ns,
            "last_market_ns": self.last_market_ns,
            "watermark_ns": self.watermark_ns,
            "source_watermark_ns": self.source_watermark_ns,
            "lateness_ns": self.lateness_ns,
            "freshness_ns": self.freshness_ns,
        }
