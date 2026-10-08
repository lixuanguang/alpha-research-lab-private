"""Verify installed native registry replay and selected-venue paper economics."""

from __future__ import annotations

# standard library imports
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
import market_data
from accounting import Ledger, LedgerState
from configuration import (
    BookEquivalence,
    BookRegistryConfiguration,
    BookSelection,
    PaperExecutionScenario,
)
from execution import OrderDecision, PaperMarket, PaperMatcher, PaperOrderJournal
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from market_data.adapters.sources import BookAdapters
from market_data.books import BookProjection, BookRegistry, CaptureReplay
from market_data.contracts import BookQuote, BookQuoteSide, CaptureRecord, CaptureRequest
from market_data.storage import CaptureJournal
from reference_data.instruments import InstrumentId
from risk import SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent

_CODEC = DomainCodec()


@dataclass(frozen=True, slots=True)
class _NativeInput:
    """Keep one completed original capture and its admitted source selection."""

    directory: Path
    request: CaptureRequest
    records: tuple[CaptureRecord, ...]
    selection: BookSelection
    group: str


class _NativeRegistryAcceptance:
    """Own installed native capture, registry and historical query verification."""

    @staticmethod
    def _read_capture(directory: Path) -> _NativeInput:
        """Verify original completed bytes and bind their source capability before replay."""
        request = _CODEC.decode_json((directory / "request.json").read_bytes(), CaptureRequest)
        if request.config.venue not in ("okx", "bitfinex"):
            raise ValueError("registry installed acceptance requires OKX or Bitfinex spot")
        records = tuple(CaptureJournal(directory, request).records())
        if not records or records[0].kind != "session" or records[-1].kind != "end":
            raise ValueError("registry acceptance requires a completed native journal")
        selection = BookSelection.from_capture(
            request.config,
            source_id=request.identity,
            capability=BookAdapters.capability(request.config),
            max_age_ns=request.config.idle_seconds * 1_000_000_000,
            allow_degraded=True,
        )
        return _NativeInput(
            directory=directory,
            request=request,
            records=records,
            selection=selection,
            group=f"native:{request.config.venue}:{request.config.quote_currency}",
        )

    @staticmethod
    def _native_config(inputs: tuple[_NativeInput, ...]) -> BookRegistryConfiguration:
        """Keep USD and USDT in their own authored singleton reference groups."""
        groups = tuple(
            BookEquivalence(
                name=source.group,
                reference=f"original-capture:{source.request.identity}",
                members=(source.selection.key,),
                known_ns=0,
                valid_from_ns=0,
            )
            for source in inputs
        )
        return BookRegistryConfiguration(
            selections=tuple(source.selection for source in inputs),
            equivalences=groups,
            history_capacity=max(len(source.records) for source in inputs),
        )

    @staticmethod
    def _ordered_events(
        inputs: tuple[_NativeInput, ...],
    ) -> tuple[tuple[_NativeInput, int, CaptureRecord], ...]:
        """Merge independent receipts without reordering a native venue's own positions."""
        events: list[tuple[_NativeInput, int, CaptureRecord]] = []
        for source in inputs:
            events.extend(
                (source, position, record) for position, record in enumerate(source.records)
            )
        events.sort(key=_NativeRegistryAcceptance._event_order)
        return tuple(events)

    @staticmethod
    def _event_order(item: tuple[_NativeInput, int, CaptureRecord]) -> tuple[int, str, int]:
        """Break equal receipt times by venue and native position only."""
        source, position, record = item
        return record.received_ns, source.request.config.venue, position

    @staticmethod
    def _native_pass(
        config: BookRegistryConfiguration,
        inputs: tuple[_NativeInput, ...],
    ) -> tuple[BookRegistry, dict[str, tuple[BookQuote, ...]], dict[str, str], dict[str, int]]:
        """Apply actual journal records through registry and an independent native projection."""
        registry = BookRegistry(config)
        references: dict[str, CaptureReplay] = {}
        traces: dict[str, list[BookQuote]] = {}
        hashes: dict[str, hashlib._Hash] = {}
        for source in inputs:
            registry.attach(source.request, book_factory=BookAdapters.create)
            venue = source.request.config.venue
            references[venue] = CaptureReplay(
                source.request.config, book_factory=BookAdapters.create
            )
            traces[venue] = []
            hashes[venue] = hashlib.sha256()
        coverage = {"selected": 0, "eligible": 0, "partial_queries": 0}
        for source, position, record in _NativeRegistryAcceptance._ordered_events(inputs):
            venue = source.request.config.venue
            expected_replay = references[venue]
            outcome = expected_replay.apply(record)
            expected = BookProjection.quote(
                position,
                record,
                outcome,
                expected_replay,
                source_id=source.request.identity,
                available_ns=record.received_ns,
            )
            actual = registry.apply(source.selection.key, record, available_ns=record.received_ns)
            if actual != expected:
                raise AssertionError(
                    f"registry diverged from native projection: {venue}/{position}"
                )
            traces[venue].append(actual)
            hashes[venue].update(_CODEC.encode_json(actual))
            # Both selected venues are queried at every native receipt, yet their
            # reference groups and economic units remain independent.
            for member in inputs:
                consolidated = registry.consolidated(member.group, cutoff_ns=record.received_ns)
                if (
                    consolidated.selected_keys != (member.selection.key,)
                    or len(consolidated.books) != 1
                ):
                    raise AssertionError("native singleton coverage changed")
                coverage["selected"] += len(consolidated.selected_keys)
                coverage["eligible"] += len(consolidated.eligible_keys)
                coverage["partial_queries"] += consolidated.partial
        for source in inputs:
            venue = source.request.config.venue
            saved = msgspec.json.decode(
                (source.directory / "summary.json").read_bytes(), type=dict[str, msgspec.Raw]
            )
            for key in ("book_identity", "trace_identity"):
                if references[venue].summary()[key] != msgspec.json.decode(saved[key], type=str):
                    raise AssertionError(f"original {venue} {key} changed")
        return (
            registry,
            {venue: tuple(quotes) for venue, quotes in traces.items()},
            {venue: digest.hexdigest() for venue, digest in hashes.items()},
            coverage,
        )

    @staticmethod
    def _historical_queries(
        registry: BookRegistry,
        inputs: tuple[_NativeInput, ...],
        traces: dict[str, tuple[BookQuote, ...]],
    ) -> tuple[str, dict[str, int]]:
        """Query cutoffs backward after all later frames have been cached."""
        digest = hashlib.sha256()
        reasons: Counter[str] = Counter()
        for source in inputs:
            quotes = traces[source.request.config.venue]
            cutoffs = sorted(
                {quote.received_ns for quote in quotes if quote.received_ns is not None},
                reverse=True,
            )
            if not cutoffs:
                raise AssertionError("native recording lacks original receipts")
            cutoffs.append(cutoffs[-1] - 1)
            for cutoff in cutoffs:
                expected = next(
                    (
                        quote
                        for quote in reversed(quotes)
                        if quote.received_ns is not None and quote.received_ns <= cutoff
                    ),
                    None,
                )
                lookup = registry.lookup(source.selection.key, cutoff_ns=cutoff)
                if lookup.boundary != expected:
                    raise AssertionError("later cached native quote leaked into historical cutoff")
                consolidated = registry.consolidated(source.group, cutoff_ns=cutoff)
                if consolidated.books != (lookup,):
                    raise AssertionError("per-venue and consolidated lookup disagree")
                reasons[lookup.reason] += 1
                digest.update(_CODEC.encode_json((source.group, cutoff, consolidated)))
        return digest.hexdigest(), dict(sorted(reasons.items()))


class _SelectedVenuePaperAcceptance:
    """Own synthetic comparable quotes and one selected-venue paper account."""

    def __init__(self, output: Path, inputs: tuple[_NativeInput, ...]) -> None:
        """Bind an independent synthetic USD spot instrument and output."""
        self.output, self.inputs = output, inputs
        self.currency = Currency(code="USD", minor_unit=Decimal("0.01"))
        self.dimension = Dimension(
            instrument_id=InstrumentId.from_canonical_text("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            kind=QuantityKind.BASE_UNIT,
        )

    def _quantity(self, value: str) -> Quantity:
        """Use the selected venue's base-unit dimension."""
        return Quantity(value=Decimal(value), dimension=self.dimension)

    def _price(self, value: str) -> Price:
        """Use exact USD price per selected base unit."""
        return Price(value=Decimal(value), currency=self.currency, per=self.dimension)

    def _money(self, value: str) -> Money:
        """Represent independently expected USD cash and fees."""
        return Money(value=Decimal(value), currency=self.currency)

    @staticmethod
    def _synthetic_quote(
        selection: BookSelection,
        *,
        at_ns: int,
        bid: str,
        bid_size: str,
        ask: str,
        ask_size: str,
    ) -> BookQuote:
        """Author comparable USD quotes distinct from the retained USD/USDT captures."""
        return BookQuote(
            venue=selection.key.venue,
            instrument_id=selection.key.instrument_id,
            source_id=selection.source_id,
            channel=selection.capability.channel,
            position=0,
            epoch=0,
            sequence=0,
            source_time=str(at_ns // 1_000_000)
            if selection.capability.source_clock == "milliseconds"
            else None,
            received_ns=at_ns,
            available_ns=at_ns,
            outcome="snapshot",
            status="degraded",
            reason="synthetic_comparable_quote",
            state_identity=hashlib.sha256(selection.source_id.encode()).hexdigest(),
            bid=BookQuoteSide(Decimal(bid), Decimal(bid_size), 1),
            ask=BookQuoteSide(Decimal(ask), Decimal(ask_size), 1),
        )

    def run(self) -> dict[str, object]:
        """Show a modeled fill at the selected venue, while the other venue wins BBO."""
        output, inputs = self.output, self.inputs
        by_venue = {source.request.config.venue: source for source in inputs}
        okx, bitfinex = by_venue["okx"], by_venue["bitfinex"]
        usd_id = self.dimension.instrument_id
        okx_usd = replace(
            okx.request.config,
            instrument_id=usd_id,
            symbol="BTC-USD",
            quote_currency="USD",
        )
        synthetic = (
            BookSelection.from_capture(
                okx_usd,
                source_id="synthetic-okx-btc-usd",
                capability=BookAdapters.capability(okx_usd),
                max_age_ns=5_000_000_000,
                allow_degraded=True,
            ),
            BookSelection.from_capture(
                bitfinex.request.config,
                source_id="synthetic-bitfinex-btc-usd",
                capability=BookAdapters.capability(bitfinex.request.config),
                max_age_ns=5_000_000_000,
                allow_degraded=True,
            ),
        )
        group = BookEquivalence(
            name="synthetic-btc-usd",
            reference="synthetic:authored-comparability",
            members=tuple(source.key for source in synthetic),
            known_ns=0,
            valid_from_ns=0,
        )
        registry = BookRegistry(
            BookRegistryConfiguration(
                selections=synthetic, equivalences=(group,), history_capacity=2
            )
        )
        decision_at = datetime(2025, 1, 1, tzinfo=UTC)
        market_at = decision_at + timedelta(seconds=1)
        elapsed = market_at - datetime(1970, 1, 1, tzinfo=UTC)
        at_ns = (
            elapsed.days * 86_400 + elapsed.seconds
        ) * 1_000_000_000 + elapsed.microseconds * 1000
        own = self._synthetic_quote(
            synthetic[0], at_ns=at_ns, bid="99", bid_size="4", ask="101", ask_size="2"
        )
        other = self._synthetic_quote(
            synthetic[1], at_ns=at_ns, bid="99", bid_size="3", ask="100", ask_size="1"
        )
        registry.accept(own)
        registry.accept(other)
        consolidated = registry.consolidated(group.name, cutoff_ns=at_ns)
        if (
            consolidated.ask is None
            or consolidated.ask.price != Decimal("100")
            or consolidated.ask.venues != ("bitfinex",)
            or consolidated.eligible_keys != group.members
        ):
            raise AssertionError("synthetic comparable consolidation changed")
        selected = registry.lookup(synthetic[0].key, cutoff_ns=at_ns).quote
        if selected is None or selected.bid is None or selected.ask is None:
            raise AssertionError("selected venue has no eligible two-sided quote")
        limits = SpotLimits(
            maximum=self._quantity("10"),
            lot=self._quantity("1"),
            tick=self._price("0.01"),
            product="spot",
        )
        initial = LedgerState(initial_cash=self._money("1000"), dimension=self.dimension)
        scenario = PaperExecutionScenario(
            venue="okx",
            instrument_id=self.dimension.instrument_id,
            entry_delay_us=0,
            cancel_delay_us=0,
            adverse=self._price("0"),
            fee_rate=Decimal("0.005"),
            take_fraction=Decimal("1"),
            gas_inapplicable_reason="off-chain spot orders have no on-chain settlement",
        )
        path = output / "selected-venue-paper.sqlite3"
        market = PaperMarket(
            identity=hashlib.sha256(
                _CODEC.encode_json(
                    (selected.venue, selected.source_id, selected.position, selected.state_identity)
                )
            ).hexdigest(),
            at=market_at,
            bid=self._price(str(selected.bid.price)),
            ask=self._price(str(selected.ask.price)),
            bid_quantity=self._quantity(str(selected.bid.quantity)),
            ask_quantity=self._quantity(str(selected.ask.quantity)),
        )
        with PaperOrderJournal(
            path,
            account="synthetic-selected-venue",
            instance="engineering-reference",
            binding_identity="c" * 64,
            mode="paper",
            limits=limits,
            ledger_state=initial,
            fee_rate=Decimal("0.005"),
        ) as journal:
            epoch = journal.claim("installed-consumer")
            admitted = journal.commit_step(
                epoch=epoch,
                step_id="synthetic-buy",
                checkpoint=b"selected-venue-paper",
                decision=OrderDecision(
                    identity="selected-venue-buy",
                    at=decision_at,
                    intent=OrderIntent(
                        side="buy",
                        quantity=self._quantity("2"),
                        limit=self._price("102"),
                        time_in_force="ioc",
                    ),
                ),
                touch=None,
                maximum_fee=self._money("2"),
            )
            if admitted.status != "committed" or len(admitted.orders) != 1:
                raise AssertionError("selected venue order was not admitted")
            PaperMatcher(journal, lot=self._quantity("1"), scenario=scenario).match(
                market, epoch=epoch
            )
            fills = journal.ledger_state().fills
            balance = Ledger(journal.ledger_state()).balance
            if (
                len(fills) != 1
                or fills[0].quantity.value != Decimal("2")
                or fills[0].effective.value != Decimal("101")
                or fills[0].fee.value != Decimal("1.01")
                or balance.cash.value != Decimal("796.99")
                or balance.holding.value != Decimal("2")
            ):
                raise AssertionError(
                    "paper fill used consolidated price or changed expected economics"
                )
            before = (journal.orders(), journal.events(), journal.ledger_state())
        with PaperOrderJournal(
            path,
            account="synthetic-selected-venue",
            instance="engineering-reference",
            binding_identity="c" * 64,
            mode="paper",
            limits=limits,
            ledger_state=initial,
            fee_rate=Decimal("0.005"),
        ) as recovered:
            epoch = recovered.claim("installed-restart")
            PaperMatcher(recovered, lot=self._quantity("1"), scenario=scenario).match(
                market, epoch=epoch
            )
            if (recovered.orders(), recovered.events(), recovered.ledger_state()) != before:
                raise AssertionError("paper restart duplicated selected-venue effects")
        return {
            "scope": "synthetic_comparable_quote_and_modeled_paper_fill",
            "mapping_identity": registry.config.identity,
            "selected_venue": selected.venue,
            "selected_source_id": selected.source_id,
            "selected_ask": str(selected.ask.price),
            "other_best_ask": str(consolidated.ask.price),
            "consolidated_ask_venues": consolidated.ask.venues,
            "modeled_fill_price": str(fills[0].effective.value),
            "modeled_fill_quantity": str(fills[0].quantity.value),
            "modeled_fee": str(fills[0].fee.value),
            "modeled_final_cash": str(balance.cash.value),
            "selected_market_identity": market.identity,
            "submission_attempted": False,
            "restart_exact": True,
        }


def main() -> None:
    """Reopen two original captures through installed public APIs outside the checkout."""
    if len(sys.argv) != 4:
        raise SystemExit("usage: book_registry.py OUTPUT OKX_CAPTURE BITFINEX_CAPTURE")
    installed = Path(market_data.__file__).resolve()
    if "site-packages" not in installed.parts:
        raise AssertionError("registry consumer did not import installed market_data")
    output = Path(sys.argv[1]).resolve()
    sources = tuple(
        _NativeRegistryAcceptance._read_capture(Path(raw).resolve()) for raw in sys.argv[2:]
    )
    by_venue = {source.request.config.venue: source for source in sources}
    if len(sources) != 2 or set(by_venue) != {"okx", "bitfinex"}:
        raise ValueError("registry consumer requires one distinct OKX and Bitfinex recording")
    if sources[0].request.config.quote_currency == sources[1].request.config.quote_currency:
        raise ValueError("initial source evidence should retain distinct USD/USDT markets")
    output.mkdir(parents=True, exist_ok=False)
    config = _NativeRegistryAcceptance._native_config(sources)
    original, traces, trace_hashes, coverage = _NativeRegistryAcceptance._native_pass(
        config, sources
    )
    history_hash, reasons = _NativeRegistryAcceptance._historical_queries(original, sources, traces)
    restored, replay_traces, replay_hashes, replay_coverage = (
        _NativeRegistryAcceptance._native_pass(config, sources)
    )
    replay_history_hash, replay_reasons = _NativeRegistryAcceptance._historical_queries(
        restored, sources, replay_traces
    )
    if (trace_hashes, history_hash, coverage, reasons) != (
        replay_hashes,
        replay_history_hash,
        replay_coverage,
        replay_reasons,
    ):
        raise AssertionError("fresh registry reconstruction changed saved source results")
    synthetic = _SelectedVenuePaperAcceptance(output, sources).run()
    report: dict[str, object] = {
        "installed_package": str(installed),
        "native_clock_assumption": "receipt-clock-as-availability; original delivery unknown",
        "native_scope": "exploratory_degraded_per_venue_public_spot_books",
        "configuration_identity": config.identity,
        "inputs": [
            {
                "venue": source.request.config.venue,
                "quote_currency": source.request.config.quote_currency,
                "request_identity": source.request.identity,
                "records": len(source.records),
                "accepted_quote_boundaries": sum(
                    quote.market_state != "unavailable"
                    for quote in traces[source.request.config.venue]
                ),
                "quote_trace_sha256": trace_hashes[source.request.config.venue],
                "source_group": source.group,
            }
            for source in sources
        ],
        "native_selected_coverage": coverage["selected"],
        "native_eligible_coverage": coverage["eligible"],
        "native_partial_queries": coverage["partial_queries"],
        "reversed_cutoff_trace_sha256": history_hash,
        "reversed_cutoff_reasons": reasons,
        "fresh_registry_replay_equal": True,
        "synthetic": synthetic,
        "limitations": [
            "original native delivery clocks absent; receipt-based replay is an explicit scenario",
            "retained OKX BTC-USDT and Bitfinex BTC-USD are separate markets",
            "visible public depth does not prove whole-venue coverage or executable fills",
            "synthetic comparable quotes and paper fills prove software behavior only",
        ],
    }
    (output / "result.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
