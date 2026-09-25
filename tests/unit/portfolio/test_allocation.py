"""Check exact and monotone physical-to-strategy spot allocation."""

from __future__ import annotations

# standard library imports
from decimal import Decimal, localcontext
from fractions import Fraction

# third party library imports
import pytest

# project library imports
from financial_units import UnitError
from portfolio import ProRataAllocator


class TestProRataAllocator:
    """Use independently counted atomic units as the allocation oracle."""

    def test_uneven_partial_fills_preserve_each_child_and_total(self) -> None:
        """A 5:3:2 parent can fill one atom at a time without clawbacks."""
        allocator = ProRataAllocator()
        weights = (Decimal("5e-18"), Decimal("3e-18"), Decimal("2e-18"))
        prior: tuple[Decimal, ...] = (Decimal(0), Decimal(0), Decimal(0))
        observed: list[tuple[Decimal, ...]] = []
        for atoms in range(1, 11):
            delta = allocator.increment(
                cumulative=Decimal(atoms).scaleb(-18),
                weights=weights,
                prior=prior,
                identities=("a", "b", "c"),
            )
            prior = tuple(before + added for before, added in zip(prior, delta, strict=True))
            observed.append(delta)
            assert sum(prior) == Decimal(atoms).scaleb(-18)
            assert all(Decimal(0) <= held <= cap for held, cap in zip(prior, weights, strict=True))
        assert prior == weights
        assert observed == [
            tuple(Decimal(value).scaleb(-18) for value in atoms)
            for atoms in (
                (1, 0, 0),
                (0, 1, 0),
                (0, 0, 1),
                (1, 0, 0),
                (1, 0, 0),
                (0, 1, 0),
                (1, 0, 0),
                (0, 0, 1),
                (0, 1, 0),
                (1, 0, 0),
            )
        ]

    def test_reachable_asymmetric_prefix_never_overallocates(self) -> None:
        """A valid 15-atom prefix stays valid when newer quota floors sum to 17."""
        allocator = ProRataAllocator()
        weights = tuple(Decimal(value).scaleb(-18) for value in (1, 5, 21, 21))
        prior: tuple[Decimal, ...] = (Decimal(0), Decimal(0), Decimal(0), Decimal(0))
        for atoms in range(1, 16):
            delta = allocator.increment(
                cumulative=Decimal(atoms).scaleb(-18),
                weights=weights,
                prior=prior,
                identities=("a", "b", "c", "d"),
            )
            prior = tuple(before + added for before, added in zip(prior, delta, strict=True))
        assert prior == tuple(Decimal(value).scaleb(-18) for value in (1, 2, 6, 6))
        delta = allocator.increment(
            cumulative=Decimal("16e-18"),
            weights=weights,
            prior=prior,
            identities=("a", "b", "c", "d"),
        )
        assert delta == (Decimal(0), Decimal(0), Decimal("1e-18"), Decimal(0))

    def test_ties_follow_identity_order_and_respect_prior(self) -> None:
        """Equal deficits have a stable identity order independent of tuple order."""
        allocator = ProRataAllocator()
        assert allocator.increment(
            cumulative=Decimal("1e-18"),
            weights=(Decimal("2e-18"), Decimal("2e-18")),
            prior=(Decimal(0), Decimal(0)),
            identities=("z", "a"),
        ) == (Decimal(0), Decimal("1e-18"))
        assert allocator.increment(
            cumulative=Decimal("2e-18"),
            weights=(Decimal("2e-18"), Decimal("2e-18")),
            prior=(Decimal(0), Decimal("1e-18")),
            identities=("z", "a"),
        ) == (Decimal("1e-18"), Decimal(0))

    def test_large_residual_is_exact_under_low_decimal_precision(self) -> None:
        """A unit fill at the atomic grid has a quintillion candidate atoms."""
        allocator = ProRataAllocator()
        with localcontext() as context:
            context.prec = 6
            parts = allocator.increment(
                cumulative=Decimal("1"),
                weights=(Decimal("1"), Decimal("2")),
                prior=(Decimal(0), Decimal(0)),
                identities=("a", "b"),
            )
        assert parts == (Decimal("0.333333333333333333"), Decimal("0.666666666666666667"))

    def test_custom_quantum_preserves_exact_child_cash(self) -> None:
        """Every quantity atom at 100.01 has an exact C03 cash value."""
        allocator = ProRataAllocator()
        parts = allocator.increment(
            cumulative=Decimal("1"),
            weights=(Decimal("1"), Decimal("2")),
            prior=(Decimal(0), Decimal(0)),
            identities=("a", "b"),
            quantum=Decimal("1e-16"),
        )
        assert parts == (Decimal("0.3333333333333333"), Decimal("0.6666666666666667"))
        assert all(
            (Fraction(part) * Fraction(Decimal("100.01")) * 10**18).denominator == 1
            for part in parts
        )

    def test_custom_quantum_caps_nonmultiple_weights(self) -> None:
        """A child cannot receive a quantum larger than its remaining capacity."""
        allocator = ProRataAllocator()
        weights = (Decimal("0.75"), Decimal("0.25"))
        assert allocator.increment(
            cumulative=Decimal("0.9"),
            weights=weights,
            prior=(Decimal(0), Decimal(0)),
            identities=("a", "b"),
            quantum=Decimal("0.1"),
        ) == (Decimal("0.7"), Decimal("0.2"))
        with pytest.raises(ValueError, match="allocation exceeds reserved quantity"):
            allocator.increment(
                cumulative=Decimal("1"),
                weights=weights,
                prior=(Decimal(0), Decimal(0)),
                identities=("a", "b"),
                quantum=Decimal("0.1"),
            )

    def test_custom_quantum_applies_to_new_fill_only(self) -> None:
        """A new fill must fit its grid while earlier fills retain their atoms."""
        allocator = ProRataAllocator()
        for cumulative, prior in (
            (Decimal("0.15"), Decimal(0)),
            (Decimal("0.2"), Decimal("0.05")),
        ):
            with pytest.raises(ValueError, match="outside requested quantum"):
                allocator.increment(
                    cumulative=cumulative,
                    weights=(Decimal("1"),),
                    prior=(prior,),
                    identities=("a",),
                    quantum=Decimal("0.1"),
                )
        assert allocator.increment(
            cumulative=Decimal("0.25"),
            weights=(Decimal("1"),),
            prior=(Decimal("0.05"),),
            identities=("a",),
            quantum=Decimal("0.1"),
        ) == (Decimal("0.2"),)
        with pytest.raises(ValueError, match="quantum must be positive"):
            allocator.increment(
                cumulative=Decimal(0),
                weights=(Decimal("1"),),
                prior=(Decimal(0),),
                identities=("a",),
                quantum=Decimal(0),
            )

    def test_varying_fill_prices_keep_prior_quantity(self) -> None:
        """A later 100.01 fill uses its own cash-safe grid after a 100 fill."""
        allocator = ProRataAllocator()
        weights = (Decimal("1"), Decimal("2"))
        first = allocator.increment(
            cumulative=Decimal("2e-18"),
            weights=weights,
            prior=(Decimal(0), Decimal(0)),
            identities=("a", "b"),
        )
        assert first == (Decimal("1e-18"), Decimal("1e-18"))
        second = allocator.increment(
            cumulative=Decimal("102e-18"),
            weights=weights,
            prior=first,
            identities=("a", "b"),
            quantum=Decimal("1e-16"),
        )
        assert second == (Decimal(0), Decimal("1e-16"))
        assert all(
            (Fraction(part) * Fraction(Decimal("100.01")) * 10**18).denominator == 1
            for part in second
        )

    @pytest.mark.parametrize("invalid", [Decimal("NaN"), Decimal("Infinity"), Decimal("1e18")])
    def test_invalid_c03_amounts_fail_closed(self, invalid: Decimal) -> None:
        """Neither allocation path accepts nonfinite or overflowing amounts."""
        allocator = ProRataAllocator()
        with pytest.raises(UnitError):
            allocator.increment(
                cumulative=invalid,
                weights=(Decimal("1"),),
                prior=(Decimal(0),),
                identities=("a",),
            )
        with pytest.raises(UnitError):
            allocator.split_capped(
                amount=invalid,
                capacities=(Decimal("1"),),
                identities=("a",),
            )

    def test_fee_residual_and_low_decimal_context(self) -> None:
        """One final atomic fee unit goes to a stable child and never exceeds caps."""
        allocator = ProRataAllocator()
        with localcontext() as context:
            context.prec = 6
            amounts = allocator.split_capped(
                amount=Decimal("0.000000000000000001"),
                capacities=(Decimal("0.01"), Decimal("0.01")),
                identities=("a", "b"),
            )
        assert amounts == (Decimal("1e-18"), Decimal(0))

    def test_fee_cap_rejects_unfunded_physical_cost(self) -> None:
        """A physical fee cannot be charged beyond gross child reservations."""
        allocator = ProRataAllocator()
        try:
            allocator.split_capped(
                amount=Decimal("1.01"),
                capacities=(Decimal("0.50"), Decimal("0.50")),
                identities=("a", "b"),
            )
        except ValueError as error:
            assert str(error) == "fee exceeds child reservations"
        else:
            raise AssertionError("unreserved fee was allocated")
