"""Derive a candidate's capability requirements from its inputs and intent family."""

from __future__ import annotations

# project library imports
from configuration import CapabilityField, CapabilityKind, CapabilityRequirement
from research.observations import InputRequirement

_SERVICES: tuple[tuple[str, CapabilityKind], ...] = (
    ("calendar", "calendar"),
    ("valuation", "valuation"),
    ("account", "account"),
    ("execution", "execution"),
)


class CandidateRequirements:
    """Declare one source requirement per named input, reference data and paper services.

    Authored and packaged candidates use the same rule, so a packaged study's
    requirements are exactly those an authored candidate with its inputs declares.
    """

    def __init__(
        self, *, venue: str, product: str = "spot", calendar: str = "continuous-utc"
    ) -> None:
        """Bind the venue, product and calendar every requirement declares."""
        self.venue, self.product, self.calendar = venue, product, calendar

    def derive(
        self,
        inputs: tuple[InputRequirement, ...],
        output: str,
        order_types: tuple[str, ...],
    ) -> tuple[CapabilityRequirement, ...]:
        """Declare the inputs' sources, then reference data and the four service families."""
        sources: dict[str, tuple[InputRequirement, ...]] = {}
        for item in inputs:
            sources[item.name] = (*sources.get(item.name, ()), item)
        declared = [
            CapabilityRequirement(
                name=named,
                kind="reference_data" if rows[0].family == "reference" else "market_data",
                product=self.product,
                venue=self.venue,
                calendar=self.calendar,
                channel=rows[0].family,
                clock=rows[0].clock,
                max_freshness_us=min(row.max_age_us for row in rows),
                fields=tuple(
                    CapabilityField(name=row.field.name, units=row.field.units) for row in rows
                ),
            )
            for named, rows in sources.items()
        ]
        if not any(item.kind == "reference_data" for item in declared):
            declared.append(
                CapabilityRequirement(
                    name="reference",
                    kind="reference_data",
                    product=self.product,
                    venue=self.venue,
                    calendar=self.calendar,
                )
            )
        declared.extend(
            CapabilityRequirement(
                name=named,
                kind=kind,
                product=self.product,
                venue=self.venue,
                calendar=self.calendar,
                operations=(f"intent:{output}",) if kind == "execution" else (),
                order_types=order_types if kind == "execution" else (),
            )
            for named, kind in _SERVICES
        )
        return tuple(declared)
