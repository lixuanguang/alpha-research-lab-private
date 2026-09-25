"""Allocate physical spot fills and costs on the exact C03 atomic grid."""

from __future__ import annotations

# standard library imports
from decimal import Decimal
from fractions import Fraction

# project library imports
from financial_units import DecimalGrid


class ProRataAllocator:
    """Use monotone cumulative quotas with stable identity residual priority.

    Quantity allocation uses the original shares of the child orders.
    Each later fill raises cumulative quotas without reversing earlier fills.
    Fees use available child fee capacity; exact residual atoms go to the
    largest fractional deficit, then the lexically smallest child identity.
    """

    _scale = 10**18

    def increment(
        self,
        *,
        cumulative: Decimal,
        weights: tuple[Decimal, ...],
        prior: tuple[Decimal, ...],
        identities: tuple[str, ...],
        quantum: Decimal = Decimal("1e-18"),
    ) -> tuple[Decimal, ...]:
        """Assign a new fill in exact quanta without reversing earlier fills."""
        if not weights or len(weights) != len(prior) or len(weights) != len(identities):
            raise ValueError("allocation dimensions differ")
        if len(set(identities)) != len(identities):
            raise ValueError("allocation identities repeat")
        quantum_units = self._units(quantum)
        if quantum_units <= 0:
            raise ValueError("allocation quantum must be positive")
        total_units = self._units(cumulative)
        weight_units = tuple(self._units(weight) for weight in weights)
        previous_units = tuple(self._units(value) for value in prior)
        residual_units = total_units - sum(previous_units)
        if (
            residual_units < 0
            or total_units > sum(weight_units)
            or any(
                weight <= 0 or used < 0 or used > weight
                for weight, used in zip(weight_units, previous_units, strict=True)
            )
        ):
            raise ValueError("allocation exceeds reserved quantity")
        if residual_units % quantum_units:
            raise ValueError("allocation increment is outside requested quantum")
        rooms = tuple(
            (weight - used) // quantum_units
            for weight, used in zip(weight_units, previous_units, strict=True)
        )
        residual = residual_units // quantum_units
        if residual > sum(rooms):
            raise ValueError("allocation exceeds reserved quantity on requested quantum")
        weight_sum = sum(weight_units)
        assigned = [0] * len(weights)
        if residual:
            starts = tuple(
                used * weight_sum - total_units * weight
                for used, weight in zip(previous_units, weight_units, strict=True)
            )
            stride = quantum_units * weight_sum
            low = min(start for start, room in zip(starts, rooms, strict=True) if room)
            high = max(
                start + (room - 1) * stride
                for start, room in zip(starts, rooms, strict=True)
                if room
            )
            while low < high:
                middle = (low + high) // 2
                if self._count_at_most(middle, starts, rooms, stride) >= residual:
                    high = middle
                else:
                    low = middle + 1
            threshold = low
            for index, (start, room) in enumerate(zip(starts, rooms, strict=True)):
                below = min(room, max(0, (threshold - start - 1) // stride + 1))
                assigned[index] += below
                residual -= below
            tied = sorted(
                (identities[index], index)
                for index, room in enumerate(rooms)
                if assigned[index] < room and starts[index] + assigned[index] * stride == threshold
            )
            for _, index in tied[:residual]:
                assigned[index] += 1
        return tuple(self._decimal(value * quantum_units) for value in assigned)

    @staticmethod
    def _count_at_most(
        threshold: int, starts: tuple[int, ...], rooms: tuple[int, ...], stride: int
    ) -> int:
        """Count available deficit priorities no greater than one threshold."""
        return sum(
            min(room, max(0, (threshold - start) // stride + 1))
            for start, room in zip(starts, rooms, strict=True)
        )

    def split_capped(
        self,
        *,
        amount: Decimal,
        capacities: tuple[Decimal, ...],
        identities: tuple[str, ...],
    ) -> tuple[Decimal, ...]:
        """Allocate one nonnegative fee among remaining exact child fee reserves."""
        if not capacities or len(capacities) != len(identities):
            raise ValueError("fee allocation dimensions differ")
        if len(set(identities)) != len(identities):
            raise ValueError("fee allocation identities repeat")
        total = self._units(amount)
        limits = tuple(self._units(capacity) for capacity in capacities)
        available = sum(limits)
        if total < 0 or any(limit < 0 for limit in limits) or total > available:
            raise ValueError("fee exceeds child reservations")
        if available == 0:
            return tuple(self._decimal(0) for _ in capacities)
        assigned = [total * limit // available for limit in limits]
        residual = total - sum(assigned)
        priorities = sorted(
            (-(total * limits[i] % available), identities[i], i) for i in range(len(limits))
        )
        for _, _, index in priorities:
            if residual == 0:
                break
            if assigned[index] < limits[index]:
                assigned[index] += 1
                residual -= 1
        if residual:
            raise ValueError("fee residual cannot fit child reservations")
        return tuple(self._decimal(value) for value in assigned)

    @classmethod
    def _units(cls, value: Decimal) -> int:
        """Convert a bounded decimal to its integer C03 atomic units."""
        DecimalGrid.require_decimal(value)
        scaled = Fraction(value) * cls._scale
        if scaled.denominator != 1:
            raise ValueError("amount is outside exact allocation grid")
        return scaled.numerator

    @classmethod
    def _decimal(cls, value: int) -> Decimal:
        """Return an exact bounded decimal from atomic units."""
        return DecimalGrid.exact_decimal(Fraction(value, cls._scale))
