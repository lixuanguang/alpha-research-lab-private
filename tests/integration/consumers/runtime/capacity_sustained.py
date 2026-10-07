"""Declare the sustained workload: 50-minute native load and a low-order mix."""

from __future__ import annotations

# standard library imports
import hashlib
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import ClassVar, Literal

# third party library imports
import msgspec
from capacity_inputs import CapacityNativeFixture, CapacityVariant, CapacityWorkload
from paper_services import PaperServiceWorkload

# project library imports
from accounting import AccountLedger
from configuration import (
    BookRegistryConfiguration,
    BookSelection,
    PaperServiceConfiguration,
    PaperServiceSource,
    PaperSourceChain,
    PaperTelemetryRetention,
)
from execution import AccountJournal, AccountObservation, AccountQuote
from financial_units import Money, Price, Quantity
from market_data.adapters.sources import BookAdapters
from market_data.books import BookProjection, BookRegistry, CaptureReplay
from market_data.collection import CaptureTransport
from market_data.contracts import CaptureRecord, CaptureRequest
from portfolio import PortfolioContext
from research.observations import LiveBookDecisionSource
from runtime import SharedDecisionRuntime, SharedPaperCaptureObserver, SharedStrategyBinding


class SustainedNativeFixture(CapacityNativeFixture):
    """Emit the declared sustained schedule: 25 Hz with a 10-second 100 Hz burst every 5 minutes.

    Each 300-second period holds 7,250 base slots and then 1,000 burst slots in its last
    ten seconds, so ten periods cover 3,000 seconds with 82,500 socket messages. Native
    frames, reconnect anchoring and receipt retention are the baseline fixture's own.
    """

    period_seconds: ClassVar[int] = 300
    base_slots: ClassVar[int] = 7250
    burst_slots: ClassVar[int] = 1000
    periods: ClassVar[int] = 10
    frame_count = periods * (base_slots + burst_slots)

    def __init__(
        self,
        source: PaperServiceSource,
        *,
        variant: CapacityVariant = "base",
        start_high: bool = False,
        epoch_path: Path | None = None,
    ) -> None:
        """Admit only the base schedule; fault variants remain baseline inputs."""
        if variant != "base":
            raise ValueError("sustained fixture declares only its base schedule")
        super().__init__(source, variant=variant, start_high=start_high, epoch_path=epoch_path)

    def _identity(self, high: bool) -> str:
        """Hash the source, periodic schedule and opening state into a distinct input."""
        return hashlib.sha256(
            self.codec.encode_json(
                (
                    "capacity-sustained-native",
                    self.source.capture,
                    self.frame_count,
                    self.period_seconds,
                    self.base_slots,
                    self.burst_slots,
                    high,
                )
            )
        ).hexdigest()

    @classmethod
    def elapsed_seconds(cls, index: int) -> float:
        """Return the authored monotonic offset of one socket-message slot."""
        if type(index) is not int or not 0 <= index < cls.frame_count:
            raise ValueError("capacity slot lies outside the finite schedule")
        period, slot = divmod(index, cls.base_slots + cls.burst_slots)
        if slot < cls.base_slots:
            offset = slot / 25
        else:
            offset = cls.period_seconds - 10 + (slot - cls.base_slots) / 100
        return period * cls.period_seconds + offset

    @classmethod
    def slot_ns(cls, index: int) -> int:
        """Return one slot's exact authored offset in integer nanoseconds."""
        if type(index) is not int or not 0 <= index < cls.frame_count:
            raise ValueError("capacity slot lies outside the finite schedule")
        period, slot = divmod(index, cls.base_slots + cls.burst_slots)
        offset = (
            slot * 40_000_000
            if slot < cls.base_slots
            else (cls.period_seconds - 10) * 1_000_000_000 + (slot - cls.base_slots) * 10_000_000
        )
        return period * cls.period_seconds * 1_000_000_000 + offset

    def authored_distribution(self) -> dict[str, object]:
        """Predeclare exact frame sizes and the periodic burst windows."""
        distribution = super().authored_distribution()
        return {
            **distribution,
            "burst_seconds": tuple(
                (period * self.period_seconds + 290, (period + 1) * self.period_seconds)
                for period in range(self.periods)
            ),
        }


class DayNativeFixture(SustainedNativeFixture):
    """Emit the day run: 291 periods (87,300 seconds), 2,400,750 socket messages a source."""

    periods: ClassVar[int] = 291
    frame_count = periods * (SustainedNativeFixture.base_slots + SustainedNativeFixture.burst_slots)


class DayRehearsalFixture(SustainedNativeFixture):
    """Emit a day-run rehearsal: 26 periods (7,800 seconds), 214,500 socket messages a source."""

    periods: ClassVar[int] = 26
    frame_count = periods * (SustainedNativeFixture.base_slots + SustainedNativeFixture.burst_slots)


class SustainedWorkload(CapacityWorkload):
    """Select the sustained topology: four sources and owners, two target-holding instances each.

    Sources capture 30-minute, 75,000-message, 256 MiB segments in one chain per
    recording, and model paper fills at the touch without an adverse cost, so a held
    target is reachable by the account's own immediate-or-cancel lowering. Account
    owners declare a 50-minute service life; the supervisor runs inside it.
    """

    instance_policies: ClassVar[
        tuple[tuple[str, Literal["fixed_clip", "liquidity_clip", "target_clip"], str], ...]
    ] = (("hold-a", "target_clip", "1"), ("hold-b", "target_clip", "1"))
    service_life_seconds: ClassVar[int] = 3000
    supervisor_seconds: ClassVar[int] = 2880
    # Paper facts refresh each account inside its unchanged 120-second state-age budget.
    reconcile_seconds: ClassVar[int] = 60
    chain: ClassVar[PaperSourceChain] = PaperSourceChain(
        max_messages=100_000, max_bytes=1024**3, max_segments=4
    )
    fixture: ClassVar[type[SustainedNativeFixture]] = SustainedNativeFixture
    # The offline projection replays six authored minutes, scaled to this window.
    projection_window_minutes: ClassVar[int] = 45

    def service_configuration(self) -> PaperServiceConfiguration:
        """Derive sustained sources, owners and duration from the four-owner baseline topology."""
        selected = super().service_configuration()
        sources = tuple(
            msgspec.structs.replace(
                source,
                capture=msgspec.structs.replace(
                    source.capture,
                    duration_seconds=1800,
                    max_messages=75_000,
                    max_bytes=268_435_456,
                    max_frame_bytes=8_000_000,
                    queue_capacity=2048,
                    retries=1,
                ),
                scenario=msgspec.structs.replace(
                    source.scenario,
                    adverse=Price(
                        value=Decimal(0),
                        currency=source.scenario.adverse.currency,
                        per=source.scenario.adverse.per,
                    ),
                ),
                chain=self.chain,
            )
            for source in selected.sources
        )
        accounts = tuple(
            msgspec.structs.replace(
                account,
                configuration=msgspec.structs.replace(
                    account.configuration, service_life_seconds=self.service_life_seconds
                ),
            )
            for account in selected.accounts
        )
        service = msgspec.structs.replace(
            selected,
            accounts=accounts,
            sources=sources,
            duration_seconds=self.supervisor_seconds,
            # A one-hour dashboard window of 36 metrics stays inside 10,000 events.
            telemetry_seconds=15,
        )
        service.__post_init__()
        return service

    def fixture_transports(
        self,
        service: PaperServiceConfiguration,
        *,
        variant: CapacityVariant = "base",
        exclude_venue: Literal["okx", "bitfinex"] | None = None,
        start_high: frozenset[str] = frozenset(),
        epoch_root: Path | None = None,
    ) -> dict[str, CaptureTransport]:
        """Select the sustained native schedule for every fixture route."""
        if (
            service != self.service_configuration()
            or variant != "base"
            or exclude_venue not in (None, "okx", "bitfinex")
            or not start_high.issubset(source.name for source in service.sources)
            or (epoch_root is not None and not epoch_root.is_absolute())
        ):
            raise ValueError("sustained fixture requires the exact prepared service")
        return {
            source.name: self.fixture(
                source,
                start_high=source.name in start_high,
                epoch_path=None if epoch_root is None else epoch_root / f"{source.name}.epoch",
            )
            for source in service.sources
            if source.capture.venue != exclude_venue
        }

    def first_touch_oracle(self) -> dict[str, tuple[Money, Money, tuple[Quantity, ...]]]:
        """Return each owner's held target economics: one unit per instance at the 100 ask.

        Paper fills carry no adverse cost here, so two units cost 200 plus the declared
        0.1 percent fee of 0.20 on either venue.
        """
        result: dict[str, tuple[Money, Money, tuple[Quantity, ...]]] = {}
        for venue in self.venues:
            workload = self.venue_workloads[venue]
            for role, dimension in (
                ("shared", workload.dimensions[0]),
                ("isolated", workload.dimensions[1]),
            ):
                result[f"{venue}-{role}"] = (
                    workload.money("99799.80")
                    if self.mode == "paper"
                    else workload.money("100000"),
                    workload.money("0.20") if self.mode == "paper" else workload.money("0"),
                    (workload.quantity("2", dimension),) if self.mode == "paper" else (),
                )
        return result

    def projection(
        self,
        scratch: Path,
        *,
        minutes: int,
        window_minutes: int,
        reconcile_seconds: int | None = 60,
    ) -> dict[str, object]:
        """Project the sustained load and replay the authored order mix offline for each account.

        The first ``minutes`` of every source are replayed through the installed
        reconstruction, shared paper observer, account journal and selected policies,
        with each book delivered at its authored receipt plus one millisecond. Measured
        orders per account are then scaled to the declared measured window.
        """
        service = self.service_configuration()
        fixture = self.fixture(service.sources[0])
        slots = sum(
            1
            for index in range(fixture.frame_count)
            if fixture.elapsed_seconds(index) < window_minutes * 60
        )
        sources = {
            source.name: {
                "segment_seconds": source.capture.duration_seconds,
                "window_messages": slots,
                "window_segments": math.ceil(window_minutes * 60 / source.capture.duration_seconds),
                "authored": self.fixture(source).authored_distribution(),
            }
            for source in service.sources
        }
        accounts: dict[str, object] = {}
        for account in service.accounts:
            source = next(
                item
                for item in service.sources
                if any(
                    instance.account_id == account.account_id and instance.source == item.name
                    for instance in service.instances
                )
            )
            replayed = self._replay_mix(
                service,
                account.account_id,
                source,
                minutes,
                scratch / account.account_id,
                reconcile_seconds,
            )
            opening, steady = replayed["opening_orders"], replayed["steady_orders"]
            if type(opening) is not int or type(steady) is not int:
                raise ValueError("sustained projection lacks order counts")
            cadence_us = min(
                PaperServiceWorkload.reference(item).cadence_us
                for item in service.instances
                if item.account_id == account.account_id
            )
            selected = window_minutes * 60 * 1_000_000 // cadence_us
            # The opening happens once per recording; only steady orders scale with time.
            steady_window = math.ceil(steady * window_minutes / minutes)
            accounts[account.account_id] = {
                **replayed,
                "window_selected_books": selected,
                "window_steady_orders_projected": steady_window,
                "window_orders_projected": opening + steady_window,
                "grant_maximum_orders": 80,
                "daily_order_target": 40,
            }
        return {
            "schema_version": "runtime-capacity-sustained-projection",
            "replayed_minutes": minutes,
            "window_minutes": window_minutes,
            "sources": sources,
            "accounts": accounts,
        }

    def prepare(self, output: Path) -> dict[str, object]:
        """Write the sustained input definitions, authored distributions and order projection."""
        output.mkdir(parents=True, exist_ok=False)
        service = self.service_configuration()
        (output / "services-initial.json").write_bytes(self.codec.encode_json(service))
        for account in service.accounts:
            (output / f"account-{account.account_id}.json").write_bytes(
                self.codec.encode_json(account.configuration)
            )
        summary: dict[str, object] = {
            "schema_version": "runtime-capacity-sustained-preparation",
            "mode": self.mode,
            "implementation": "resolved-after-signed-install",
            "selection": service.identity,
            "accounts": tuple(
                (
                    account.account_id,
                    hashlib.sha256(self.codec.encode_json(account.configuration)).hexdigest(),
                )
                for account in service.accounts
            ),
            "sources": tuple(
                (
                    source.name,
                    self.venue_workload(source.capture.venue).input_identity(source),
                    self.fixture(source).identity,
                    self.fixture(source, start_high=True).identity,
                )
                for source in service.sources
            ),
            "strategies": tuple(
                (
                    instance.instance_id,
                    PaperServiceWorkload.reference(instance).formula,
                    instance.source,
                )
                for instance in service.instances
            ),
            "account_service_seconds": self.service_life_seconds,
            "supervisor_seconds": self.supervisor_seconds,
            "reconcile_seconds": self.reconcile_seconds,
            "projection": self.projection(
                output / "projection",
                minutes=6,
                window_minutes=self.projection_window_minutes,
                reconcile_seconds=self.reconcile_seconds,
            ),
        }
        (output / "preparation.json").write_bytes(self.codec.encode_json(summary))
        return summary

    def _replay_mix(
        self,
        service: PaperServiceConfiguration,
        account_id: str,
        source: PaperServiceSource,
        minutes: int,
        scratch: Path,
        reconcile_seconds: int | None,
    ) -> dict[str, object]:
        """Drive one account's selected books through its policies and a fresh journal."""
        account = next(item for item in service.accounts if item.account_id == account_id)
        venue = self.venue_workload(source.capture.venue)
        opening = self.opening_at + timedelta(seconds=1)
        scratch.mkdir(parents=True, exist_ok=False)
        journal = AccountJournal(scratch / "account.sqlite3", account.configuration)
        journal.observe(
            AccountQuote(
                price=venue.price("100", source.scenario.adverse.per),
                at=opening - timedelta(microseconds=1),
            )
        )
        if not journal.reconcile(venue.opening_observation(account_id, opening)):
            raise ValueError("sustained projection opening reconciliation failed")
        instances = tuple(item for item in service.instances if item.account_id == account_id)
        bindings = tuple(
            SharedStrategyBinding(
                instance_id=instance.instance_id,
                account_id=account_id,
                entity=str(source.scenario.instrument_id),
                candidate=venue.candidates(source).load(
                    PaperServiceWorkload.reference(instance),
                    instance=instance.instance_id,
                    entity=str(source.scenario.instrument_id),
                    quantity=instance.quantity,
                    lot=instance.lot,
                    currency=source.scenario.adverse.currency,
                    tick=service.instance_limits(instance).tick,
                    source_identity=venue.input_identity(source),
                ),
                context=PortfolioContext(
                    portfolio_id="reference",
                    strategy_id=instance.instance_id,
                    model_revision="rule-only",
                    config_revision="paper-services",
                    horizon="capture",
                    reason="engineering-reference",
                    venue=source.capture.venue,
                    settlement="spot",
                    risk_bucket="cash",
                    authority_scope=account.configuration.mode,
                ),
                maximum_fee=instance.maximum_fee,
            )
            for instance in instances
        )
        request = CaptureRequest(
            config=source.capture,
            recording_id="00000000-0000-4000-8000-000000000a2a",
            implementation_identity="0" * 64,
        )
        clock = _ProjectionClock(opening)
        observer = SharedPaperCaptureObserver(
            source=LiveBookDecisionSource(
                request, venue.candidates(source).inputs, history_capacity=1000
            ),
            books=BookRegistry(
                BookRegistryConfiguration(
                    selections=(
                        BookSelection.from_capture(
                            source.capture,
                            source_id=request.identity,
                            capability=BookAdapters.capability(source.capture),
                            max_age_ns=source.freshness_us * 1000,
                            allow_degraded=True,
                        ),
                    ),
                    equivalences=(),
                    history_capacity=1000,
                )
            ),
            journal=journal,
            runtime=SharedDecisionRuntime(journal, bindings),
            account_id=account_id,
            scenario=source.scenario,
            delivery_path=scratch / "deliveries.jsonl",
            clock=clock,
        )
        fixture = self.fixture(source)
        replay = CaptureReplay(source.capture, book_factory=BookAdapters.create)
        records = [CaptureRecord(kind="session", epoch=0, received_ns=clock.ns(opening))]
        for index in range(fixture.frame_count):
            elapsed = fixture.elapsed_seconds(index)
            if elapsed >= minutes * 60:
                break
            at = opening + timedelta(seconds=elapsed)
            fixture.index = index + 1
            records.append(
                CaptureRecord(
                    kind="frame",
                    epoch=0,
                    received_ns=clock.ns(at),
                    raw=fixture._native_frame(clock.ns(at) // 1_000_000),
                )
            )
        reconciled_at, reconciliations = opening, 0
        for position, record in enumerate(records):
            clock.at = clock.from_ns(record.received_ns) + timedelta(milliseconds=1)
            if reconcile_seconds is not None and clock.at - reconciled_at >= timedelta(
                seconds=reconcile_seconds
            ):
                # Paper facts are the account's own settled ledger and open physical orders.
                reconciled_at = clock()
                if not journal.reconcile(
                    AccountObservation(
                        identity=f"projection-{reconciliations}",
                        at=reconciled_at,
                        snapshot=AccountLedger(journal.accounts()[0].ledger).snapshot(),
                        open_orders=tuple(
                            item.order
                            for item in journal.net_orders()
                            if not item.order.is_terminal
                        ),
                    )
                ):
                    raise ValueError("sustained projection reconciliation failed")
                reconciliations += 1
            outcome = replay.apply(record)
            observer.observe(record, BookProjection.capture(position, record, outcome, replay))
        reasons: dict[str, int] = {}
        for commit in observer.decisions:
            reasons[commit.reason] = reasons.get(commit.reason, 0) + 1
        orders = journal.orders()
        first = min((tagged.order.decision_at for tagged in orders), default=None)
        ledger = AccountLedger(journal.accounts()[0].ledger)
        snapshot = ledger.snapshot()
        holdings = {
            instance.instance_id: tuple(
                str(item.value)
                for item in ledger.snapshot(instance_id=instance.instance_id).positions
            )
            for instance in instances
        }
        return {
            "replayed_messages": len(records) - 1,
            "reconciliations": reconciliations,
            "committed_checkpoints": len(observer.decisions),
            "commit_reasons": reasons,
            "orders": len(orders),
            # Orders decided at the first committed checkpoint open the held targets.
            "opening_orders": sum(tagged.order.decision_at == first for tagged in orders),
            "steady_orders": sum(
                first is not None and tagged.order.decision_at > first for tagged in orders
            ),
            "filled_orders": sum(tagged.order.filled.value > 0 for tagged in orders),
            "holdings": holdings,
            "final_economics": (snapshot.cash, snapshot.fees, snapshot.positions),
        }


class _ProjectionClock:
    """Advance a strictly increasing UTC clock from each authored delivery instant."""

    def __init__(self, at: datetime) -> None:
        """Start at the account opening instant."""
        self.at = at

    def __call__(self) -> datetime:
        """Return the next microsecond after the last reading."""
        self.at += timedelta(microseconds=1)
        return self.at

    @staticmethod
    def ns(at: datetime) -> int:
        """Convert an exact UTC instant to Unix nanoseconds."""
        elapsed = at - datetime(1970, 1, 1, tzinfo=at.tzinfo)
        return (
            elapsed.days * 86_400 + elapsed.seconds
        ) * 1_000_000_000 + elapsed.microseconds * 1000

    @staticmethod
    def from_ns(value: int) -> datetime:
        """Convert Unix nanoseconds to an exact UTC instant at microsecond resolution."""
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=value // 1000)


class DayWorkload(SustainedWorkload):
    """Select the counted day run: the sustained topology under a 25-hour cap and 26-hour grants.

    Owners declare the approved 90,000-second service-life cap; each invocation is set
    by the cohort's timings. Chains hold the whole day's 30-minute segments.
    """

    fixture: ClassVar[type[SustainedNativeFixture]] = DayNativeFixture
    service_life_seconds: ClassVar[int] = 90_000
    supervisor_seconds: ClassVar[int] = 87_000
    grant_seconds: ClassVar[int] = 26 * 3600
    chain: ClassVar[PaperSourceChain] = PaperSourceChain(
        max_messages=2_500_000, max_bytes=4 * 1024**3, max_segments=50
    )
    projection_window_minutes: ClassVar[int] = 1440

    def service_configuration(self) -> PaperServiceConfiguration:
        """Declare the profile's telemetry: at most eight million events, seven days old."""
        service = msgspec.structs.replace(
            super().service_configuration(),
            telemetry=PaperTelemetryRetention(max_events=8_000_000, retention_days=7),
        )
        service.__post_init__()
        return service


class DayRehearsalWorkload(DayWorkload):
    """Select a 2-hour day-run rehearsal under the same cap and grant life."""

    fixture: ClassVar[type[SustainedNativeFixture]] = DayRehearsalFixture
    supervisor_seconds: ClassVar[int] = 7_800
    chain: ClassVar[PaperSourceChain] = PaperSourceChain(
        max_messages=250_000, max_bytes=1024**3, max_segments=6
    )
    projection_window_minutes: ClassVar[int] = 120
