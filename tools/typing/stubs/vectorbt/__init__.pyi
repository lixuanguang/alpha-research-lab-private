"""Type only the exercised vectorbt 1.1.0 portfolio adapter boundary."""

class _Values:
    """Expose one-dimensional analytical portfolio results."""
    def tolist(self) -> list[float]:
        """Return approximate scalar values."""
        ...

class Portfolio:
    """Describe the pinned target-amount execution consumer."""
    @classmethod
    def from_orders(
        cls,
        close: list[float],
        *,
        size: list[float],
        size_type: str,
        direction: str,
        price: list[float],
        fees: float,
        fixed_fees: list[float],
        slippage: float,
        init_cash: float,
        cash_sharing: bool,
        allow_partial: bool,
        raise_reject: bool,
        lock_cash: bool,
        ffill_val_price: bool,
        update_value: bool,
        reject_prob: float,
        seed: int,
        engine: str,
    ) -> Portfolio:
        """Build the supported analytical portfolio.

        Args:
            close: Explicit reference marks in quote units.
            size: Absolute target quantities; NaN skips an order.
            size_type: Target-amount sizing mode.
            direction: Long-only scope.
            price: Explicit delayed effective execution prices.
            fees: Percentage fee, zero because fixed fees are already rounded.
            fixed_fees: Exact rounded fees projected to floats.
            slippage: Percentage cost, zero because prices already include adverse ticks.
            init_cash: Initial isolated capital.
            cash_sharing: Whether columns share capital; false here.
            allow_partial: Whether resizing is allowed; false here.
            raise_reject: Raise for an unsupported rejection.
            lock_cash: Prevent borrowing.
            ffill_val_price: Whether marks may be filled forward; false here.
            update_value: Update valuation after orders.
            reject_prob: Random rejection probability; zero here.
            seed: Explicit deterministic seed.
            engine: Explicit Numba backend selection.

        Returns:
            Executed portfolio with approximate analytical values.
        """
        ...
    def cash(self) -> _Values:
        """Return approximate cash.

        Returns:
            One-dimensional analytical series.
        """
        ...
    def assets(self) -> _Values:
        """Return approximate held quantities.

        Returns:
            One-dimensional analytical series.
        """
        ...
    def value(self) -> _Values:
        """Return approximate NAV.

        Returns:
            One-dimensional analytical series.
        """
        ...
