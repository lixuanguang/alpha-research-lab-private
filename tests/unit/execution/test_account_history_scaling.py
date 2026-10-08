"""Measure shared account journal costs as retained paper history grows."""

from __future__ import annotations

# standard library imports
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MethodType

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger, AccountSnapshot
from configuration import AccountConfiguration, OpeningAccount, PaperExecutionScenario
from configuration.accounts import InstrumentFeeRate
from execution import (
    AccountDecision,
    AccountExecutionRequest,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    OrderDecision,
    PaperMarket,
)
from execution.account_admission import AccountAdmission
from execution.account_paper import AccountPaperMatching
from execution.account_records import AccountPaperTrace
from execution.records import OrderEvent
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent


class _SharedFirmHistory:
    """Grow one busy account's paper history beside a quiet account in one firm journal."""

    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)
    accounts = ("busy", "quiet")

    def __init__(self, path: Path) -> None:
        """Open, bind and reconcile both accounts before any market."""
        self.scenario = PaperExecutionScenario(
            venue="okx",
            instrument_id=self.dimension.instrument_id,
            entry_delay_us=0,
            cancel_delay_us=0,
            adverse=self._price("0.01"),
            fee_rate=Decimal("0.001"),
            take_fraction=Decimal("1"),
            gas_inapplicable_reason="off-chain spot order matching",
        )
        self.journal = AccountJournal(path, self._config())
        for account in self.accounts:
            self.journal.bind_paper_scenario(account, self.scenario)
            assert self.journal.reconcile(self._opening(account))
        self.at = self.opening_at + timedelta(seconds=1)
        self.markets = 0
        self.orders = 0

    def tick(self, account_id: str) -> None:
        """Match one never-seen public market for an account."""
        self.at += timedelta(milliseconds=1)
        self.markets += 1
        # Alternating touches start a fresh displayed-size segment on each market.
        is_odd = self.markets % 2 == 1
        market = PaperMarket(
            identity=f"market-{self.markets}",
            at=self.at,
            bid=self._price("0.89" if is_odd else "0.90"),
            ask=self._price("1.01" if is_odd else "1.00"),
            bid_quantity=self._quantity("3"),
            ask_quantity=self._quantity("3"),
        )
        self.journal.apply_public_market(account_id, market, self.scenario)

    def round_trip(self) -> None:
        """Fill one IOC buy and one IOC sell of a single unit for the busy account."""
        for side, limit in (("buy", "1.10"), ("sell", "0.80")):
            self.at += timedelta(milliseconds=1)
            self.orders += 1
            quote = AccountQuote(price=self._price("1.00"), at=self.at)
            self.journal.observe(quote)
            admitted = self.journal.admit(
                AccountDecision(
                    account_id="busy",
                    instance_id="busy-alpha",
                    decision=OrderDecision(
                        identity=f"order-{self.orders}",
                        at=self.at,
                        intent=OrderIntent(
                            side="buy" if side == "buy" else "sell",
                            quantity=self._quantity("1"),
                            limit=self._price(limit),
                            time_in_force="ioc",
                        ),
                    ),
                    quote=quote,
                    maximum_fee=self._money("0.01"),
                    checkpoint=f"order-{self.orders}".encode(),
                )
            )
            assert admitted.status == "committed", admitted.reason
            self.tick("busy")

    def busy_tick(self) -> None:
        """Match one idle market for the busy account."""
        self.tick("busy")

    def rebind(self) -> None:
        """Repeat the busy account's existing scenario binding, which stages nothing."""
        self.journal.bind_paper_scenario("busy", self.scenario)

    def busy_report(self) -> int:
        """Project the busy account's owned fills and their cost links."""
        fills, costs = self.journal.paper_report_facts("busy")
        return len(fills) + len(costs)

    def quiet_traces(self) -> int:
        """Read every retained trace of the quiet account."""
        return len(self.journal.paper_traces("quiet"))

    @staticmethod
    def median_seconds(operation: Callable[[], object], repeats: int = 31) -> float:
        """Time an operation repeatedly and return its median wall-clock seconds."""
        samples: list[float] = []
        for _ in range(repeats):
            started = time.perf_counter()
            operation()
            samples.append(time.perf_counter() - started)
        return sorted(samples)[repeats // 2]

    @classmethod
    def _money(cls, value: str) -> Money:
        """Build exact quote currency."""
        return Money(value=Decimal(value), currency=cls.currency)

    @classmethod
    def _price(cls, value: str) -> Price:
        """Build an exact quote price per base unit."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Build exact base units."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _config(cls) -> AccountConfiguration:
        """Fund two independently limited accounts in one firm journal."""
        spot_limits: tuple[SpotLimits, ...] = (
            SpotLimits(
                maximum=cls._quantity("10"),
                lot=cls._quantity("1"),
                tick=cls._price("0.01"),
                product="spot",
            ),
        )
        return AccountConfiguration(
            mode="paper",
            opening_at=cls.opening_at,
            accounts=tuple(
                OpeningAccount(account_id=account, cash=(cls._money("1000"),))
                for account in cls.accounts
            ),
            instruments=spot_limits,
            fee_rates=tuple(
                InstrumentFeeRate(
                    instrument_id=limits.maximum.dimension.instrument_id, rate=Decimal("0.001")
                )
                for limits in spot_limits
            ),
            budgets=BudgetPolicy(
                valuation_currency=cls.currency,
                firm_maximum=cls._money("2000"),
                accounts=tuple(
                    AccountLimit(account_id=account, maximum=cls._money("1000"))
                    for account in cls.accounts
                ),
                instances=tuple(
                    InstanceLimit(
                        instance_id=f"{account}-alpha",
                        account_id=account,
                        maximum=cls._money("1000"),
                        instruments=(cls.dimension.instrument_id,),
                    )
                    for account in cls.accounts
                ),
                max_quote_age_us=1_000_000,
                max_state_age_us=86_400_000_000,
                max_residual_age_us=86_400_000_000,
                max_price_deviation_bps=2000,
                max_order_notional=cls._money("1000"),
            ),
        )

    @classmethod
    def _opening(cls, account_id: str) -> AccountObservation:
        """Author each account's independent opening cash observation."""
        return AccountObservation(
            identity=f"opening-{account_id}",
            at=cls.opening_at,
            snapshot=AccountSnapshot(
                account_id=account_id,
                instance_id=None,
                cash=(cls._money("1000"),),
                positions=(),
                fees=(cls._money("0"),),
                rebates=(cls._money("0"),),
                transfers=(cls._money("1000"),),
                fill_ids=(),
                posting_ids=("opening:USDT",),
            ),
            open_orders=(),
        )


class _CountingOwner:
    """Count owner resolutions and resolve each as the original does."""

    def __init__(self, owner: Callable[[dict[str, str], str, str], str]) -> None:
        """Wrap the original resolver with no resolutions counted."""
        self._owner = owner
        self.resolved = 0

    def __call__(self, accounts: dict[str, str], order_id: str, missing: str) -> str:
        """Count one owner resolution and resolve it as before."""
        self.resolved += 1
        return self._owner(accounts, order_id, missing)


class _CountingTraceFacts:
    """Record each trace a journal's reader decodes for report facts."""

    def __init__(
        self, add: Callable[[AccountPaperTrace, list[OrderEvent], set[str]], None]
    ) -> None:
        """Wrap the original fact folder with no traces recorded."""
        self._add = add
        self.decoded: list[str] = []

    def __call__(self, trace: AccountPaperTrace, events: list[OrderEvent], ids: set[str]) -> None:
        """Record the decoded trace and fold it as before."""
        self.decoded.append(trace.market.identity)
        self._add(trace, events, ids)


class _CountingTraceDecodes:
    """Record each paper trace a codec decodes, then return it unchanged."""

    def __init__(self, decode: Callable[[DomainCodec, bytes, type[object]], object]) -> None:
        """Wrap the original codec decoder with no traces recorded."""
        self._decode = decode
        self.decoded: list[str] = []

    def __get__(self, codec: DomainCodec | None, owner: type[DomainCodec]) -> object:
        """Bind to a codec as the replaced method does."""
        return self if codec is None else MethodType(self, codec)

    def __call__(self, codec: DomainCodec, payload: bytes, target: type[object]) -> object:
        """Decode as before and record a decoded trace's market identity."""
        value = self._decode(codec, payload, target)
        if isinstance(value, AccountPaperTrace):
            self.decoded.append(value.market.identity)
        return value


class TestAccountHistoryScaling:
    """Bound per-operation growth with another account's retained history."""

    def test_account_time_resolves_only_appended_event_owners(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Account time resolves each event's owner once, not on every admission step."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        counting = _CountingOwner(AccountAdmission._owner)
        monkeypatch.setattr(AccountAdmission, "_owner", staticmethod(counting))
        per_round_trip: list[int] = []
        for orders in (20, 200):
            while history.orders < orders:
                history.round_trip()
            counting.resolved = 0
            history.round_trip()
            per_round_trip.append(counting.resolved)
        # Re-resolving every retained event on each of about 12 calls grew tenfold here.
        assert per_round_trip[1] <= per_round_trip[0]

    @pytest.mark.performance
    def test_one_account_trace_read_ignores_other_accounts_history(self, tmp_path: Path) -> None:
        """Reading a quiet account's traces stays flat while a busy account's history grows."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        history.tick("quiet")
        medians: list[float] = []
        for size in (500, 4000):
            while history.markets - 1 < size:
                history.tick("busy")
            medians.append(history.median_seconds(history.quiet_traces))
        print(f"quiet trace read at 500/4000 busy traces: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Scanning every account's rows grows about eightfold here; the index stays flat.
        assert medians[1] < 2 * medians[0]

    @pytest.mark.performance
    def test_idle_paper_tick_ignores_terminal_order_history(self, tmp_path: Path) -> None:
        """An idle tick stays near flat while filled orders and their events accumulate."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        medians: list[float] = []
        for orders in (40, 200):
            while history.orders < orders:
                history.round_trip()
            medians.append(history.median_seconds(history.busy_tick, repeats=21))
        print(f"idle tick at 40/200 filled orders: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Re-validating every order and event against every order grew about 11x here.
        assert medians[1] < 3 * medians[0]

    @pytest.mark.performance
    def test_report_facts_grow_no_faster_than_their_fills(self, tmp_path: Path) -> None:
        """Report projection decodes each trace once and joins through maps, not scans."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        medians: list[float] = []
        for orders in (40, 200):
            while history.orders < orders:
                history.round_trip()
            medians.append(history.median_seconds(history.busy_report, repeats=9))
        print(f"report facts at 40/200 filled orders: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Five times the fills may cost at most about five times as much.
        assert medians[1] < 7 * medians[0]

    @pytest.mark.performance
    def test_admission_and_fill_round_trip_does_not_replay_account_history(
        self, tmp_path: Path
    ) -> None:
        """Admitting and filling orders stays near linear as postings accumulate."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        medians: list[float] = []
        for orders in (40, 200):
            while history.orders < orders:
                history.round_trip()
            medians.append(history.median_seconds(history.round_trip, repeats=9))
        print(f"round trip at 40/200 filled orders: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Replaying and re-validating every posting per ledger grew quadratically here.
        assert medians[1] < 8 * medians[0]

    @pytest.mark.performance
    def test_unchanged_write_does_not_rewrite_the_account_head(self, tmp_path: Path) -> None:
        """A write transaction that stages nothing leaves the growing head unwritten."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        medians: list[float] = []
        for orders in (40, 400):
            while history.orders < orders:
                history.round_trip()
            medians.append(history.median_seconds(history.rebind))
        print(f"unchanged write at 40/400 filled orders: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Re-encoding and fsyncing the whole head grew with every retained fact.
        assert medians[1] < 3 * medians[0]

    @staticmethod
    def _read_after_commit(history: _SharedFirmHistory, reader: AccountJournal) -> float:
        """Commit a tick through the first journal and time the second journal's ledgers."""
        history.busy_tick()
        started = time.perf_counter()
        for view in reader.accounts():
            AccountLedger(view.ledger).snapshot()
        return time.perf_counter() - started

    @pytest.mark.performance
    def test_read_after_another_writer_commits_does_not_replay_ledgers(
        self, tmp_path: Path
    ) -> None:
        """A second journal's ledgers stay near flat after each commit by the first."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        # A second journal object keeps its own decoded rows, like another process.
        reader = AccountJournal(tmp_path / "firm.sqlite3", history._config())
        medians: list[float] = []
        for orders in (40, 400):
            while history.orders < orders:
                history.round_trip()
            self._read_after_commit(history, reader)
            medians.append(sorted(self._read_after_commit(history, reader) for _ in range(9))[4])
        print(f"read after commit at 40/400 filled orders: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Re-validating every posting twice and replaying each ledger grew about tenfold.
        assert medians[1] < 3 * medians[0]


class TestBoundedMonitoringReads:
    """Monitoring reads stay bounded while the paper trace history grows."""

    def test_incremental_report_facts_equal_a_full_scan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reads decode each committed trace once and always equal a fresh journal's scan."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        counting = _CountingTraceFacts(AccountPaperMatching._add_trace_facts)
        decoded = counting.decoded
        monkeypatch.setattr(AccountPaperMatching, "_add_trace_facts", staticmethod(counting))
        seen: list[str] = []
        for step in range(6):
            history.round_trip() if step % 2 == 0 else history.busy_tick()
            decoded.clear()
            cached = history.journal.paper_report_facts("busy")
            # The long-lived journal never decodes a committed trace a second time.
            assert not set(decoded) & set(seen)
            seen.extend(decoded)
            fresh = AccountJournal(tmp_path / "firm.sqlite3", history._config())
            assert cached == fresh.paper_report_facts("busy")
        assert len(history.journal.paper_report_facts("busy")[0]) == history.orders

    def test_a_cold_report_decodes_only_fill_bearing_traces(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fresh journal reads only indexed fill traces; books that filled nothing stay unread."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        for _ in range(3):
            history.round_trip()
            for _ in range(20):
                history.busy_tick()
        traces = history.journal.paper_traces("busy")
        filled = [trace.market.identity for trace in traces if trace.filled]
        # Each round trip fills an IOC buy and an IOC sell on its own book.
        assert len(filled) == history.orders == 6 and len(traces) == 66
        expected = [event.fill for trace in traces for event in trace.child_fill_events]
        counting = _CountingTraceDecodes(DomainCodec.decode_json)
        decoded = counting.decoded
        monkeypatch.setattr(DomainCodec, "decode_json", counting)
        fresh = AccountJournal(tmp_path / "firm.sqlite3", history._config())
        fills, costs = fresh.paper_report_facts("busy")
        monitoring = fresh.result_snapshot(
            AccountExecutionRequest(action="inspect", account_id="busy", projection="monitoring")
        )
        monkeypatch.undo()
        assert [item.fill for item in fills] == expected and len(costs) == len(expected)
        assert monitoring.paper_fills == fills and monitoring.paper_costs == costs
        # The cold read decodes the six fill traces once; monitoring adds only the newest.
        assert sorted(decoded) == sorted([*filled, traces[-1].market.identity])

    def test_monitoring_projection_keeps_only_the_newest_trace(self, tmp_path: Path) -> None:
        """Monitoring equals the full inspection except that it carries the newest trace only."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        for _ in range(3):
            history.round_trip()
        history.busy_tick()
        full = history.journal.result_snapshot(
            AccountExecutionRequest(action="inspect", account_id="busy")
        )
        monitoring = history.journal.result_snapshot(
            AccountExecutionRequest(action="inspect", account_id="busy", projection="monitoring")
        )
        assert len(full.paper_traces) > 1
        assert monitoring.paper_traces == (full.paper_traces[-1],)
        assert replace(monitoring, paper_traces=full.paper_traces) == full
        with pytest.raises(ValueError, match="requires inspection"):
            AccountExecutionRequest(action="quote", projection="monitoring")

    def test_monitoring_response_size_ignores_trace_history(self, tmp_path: Path) -> None:
        """The bounded read stays one size as traces accumulate; the full read keeps growing."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        history.round_trip()
        codec = DomainCodec()
        sizes: dict[str, list[int]] = {"full": [], "monitoring": []}
        for ticks in (10, 200):
            while history.markets < ticks:
                history.busy_tick()
            for projection in ("full", "monitoring"):
                result = history.journal.result_snapshot(
                    AccountExecutionRequest(
                        action="inspect", account_id="busy", projection=projection
                    )
                )
                sizes[projection].append(len(codec.encode_json(result)))
        # Only identifier lengths in the newest trace may differ.
        assert abs(sizes["monitoring"][1] - sizes["monitoring"][0]) < 100
        assert sizes["full"][1] > 5 * sizes["full"][0]
