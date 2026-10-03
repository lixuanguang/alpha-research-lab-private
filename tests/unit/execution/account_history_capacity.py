"""Measure account-journal commit, open, memory and disk cost at a 24-hour history."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import math
import platform
import resource
import sqlite3
import subprocess  # nosec B404  # [owner=runtime; rationale=fresh local interpreters of this consumer; expires=2027-03-01]
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import cast

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
from accounting import AccountSnapshot
from configuration import (
    AccountConfiguration,
    InstrumentFeeRate,
    OpeningAccount,
    PaperExecutionScenario,
)
from execution import (
    AccountDecision,
    AccountJournal,
    AccountObservation,
    AccountPaperTrace,
    AccountQuote,
    OrderDecision,
    PaperMarket,
    PortfolioBatch,
    PortfolioContext,
    PortfolioDecision,
)
from execution.account_state import (
    AccountStateStore,
    AccountTransaction,
    SavedDecision,
    SavedPortfolioBatch,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent

_CURRENCY = Currency.from_code("USDT")
_DIMENSION = Dimension(
    instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
    kind=QuantityKind.BASE_UNIT,
)
_OPENING_AT = datetime(2026, 9, 25, 12, tzinfo=UTC)
_ACCOUNT = "shared"
_INSTANCES = ("alpha", "beta")
_TEMPLATE_BATCH = "template-batch"
_CHECKPOINT_BYTES = 675
_FILL_BATCHES = 100
_LEVELS = (0, 25, 50, 75, 100)
# Mean item bytes of the measured single-document OKX shared journal.
_REFERENCE_BYTES = {"portfolio_batches": 6574, "decisions": 2722, "paper_traces": 2757}
_TARGETS_NS = {"batch_commit": 5_000_000, "trace_commit": 5_000_000, "cold_open": 100_000_000}
_MEMORY_GROWTH_BYTES = 16 * 1024 * 1024
_CANONICAL_BUDGET_BYTES = 120 * 1024**3
_ACCOUNTS = 4
# ``ru_maxrss`` is bytes on macOS and KiB on Linux.
_RSS_UNIT = 1 if sys.platform == "darwin" else 1024


class HistoryCapacityCommand:
    """Dispatch the benchmark run, its fresh-interpreter probes or the replay check."""

    @staticmethod
    def run(arguments: Sequence[str] | None = None) -> int:
        """Dispatch the run, its fresh-interpreter probes or the replay check."""
        parser = argparse.ArgumentParser(description=__doc__)
        commands = parser.add_subparsers(dest="command", required=True)
        run = commands.add_parser("run")
        run.add_argument("--output", type=Path, required=True)
        memory = commands.add_parser("memory")
        memory.add_argument("--journal", type=Path, required=True)
        memory.add_argument("--commits", type=int, required=True)
        fresh = commands.add_parser("fresh-open")
        fresh.add_argument("--journal", type=Path, required=True)
        replay = commands.add_parser("replay-check")
        replay.add_argument("--parity", type=Path, action="append", required=True)
        replay.add_argument("--original", type=Path, required=True)
        replay.add_argument("--output", type=Path, required=True)
        parsed = parser.parse_args(arguments, namespace=_Arguments())
        if parsed.command == "run":
            summary = HistoryCapacity(parsed.output.absolute()).run()
            outcome: dict[str, object] = {"qualified": summary["qualified"]}
            print(msgspec.json.encode(outcome).decode(), flush=True)
            return 0 if summary["qualified"] is True else 1
        if parsed.command == "memory":
            print(
                msgspec.json.encode(
                    HistoryMeasurements.memory_probe(parsed.journal, parsed.commits)
                ).decode()
            )
            return 0
        if parsed.command == "fresh-open":
            print(
                msgspec.json.encode(HistoryMeasurements.fresh_open_probe(parsed.journal)).decode()
            )
            return 0
        checked = HistoryMeasurements.replay_check(parsed.parity, parsed.original, parsed.output)
        passed: dict[str, object] = {"passed": checked["passed"]}
        print(msgspec.json.encode(passed).decode(), flush=True)
        return 0 if checked["passed"] is True else 1


class HistoryJournalFixture:
    """Author the declared account configuration, scenario, decisions and template journal."""

    @staticmethod
    def money(value: str) -> Money:
        """Build exact quote currency."""
        return Money(value=Decimal(value), currency=_CURRENCY)

    @staticmethod
    def quantity(value: str) -> Quantity:
        """Build exact base units."""
        return Quantity(value=Decimal(value), dimension=_DIMENSION)

    @staticmethod
    def price(value: str) -> Price:
        """Build an exact quote price per base unit."""
        return Price(value=Decimal(value), currency=_CURRENCY, per=_DIMENSION)

    @staticmethod
    def configuration() -> AccountConfiguration:
        """Fund two independently limited instances in one shared spot account."""
        spot_limits: tuple[SpotLimits, ...] = (
            SpotLimits(
                maximum=HistoryJournalFixture.quantity("10"),
                lot=HistoryJournalFixture.quantity("1"),
                tick=HistoryJournalFixture.price("0.01"),
                product="spot",
            ),
        )
        return AccountConfiguration(
            mode="paper",
            opening_at=_OPENING_AT,
            accounts=(
                OpeningAccount(account_id=_ACCOUNT, cash=(HistoryJournalFixture.money("1000"),)),
            ),
            instruments=spot_limits,
            fee_rates=tuple(
                # The worst case admission sizes reserves for; the scenario charges this rate.
                InstrumentFeeRate(
                    instrument_id=limits.maximum.dimension.instrument_id, rate=Decimal("0.005")
                )
                for limits in spot_limits
            ),
            budgets=BudgetPolicy(
                valuation_currency=_CURRENCY,
                firm_maximum=HistoryJournalFixture.money("1000"),
                accounts=(
                    AccountLimit(account_id=_ACCOUNT, maximum=HistoryJournalFixture.money("1000")),
                ),
                instances=tuple(
                    InstanceLimit(
                        instance_id=instance,
                        account_id=_ACCOUNT,
                        maximum=HistoryJournalFixture.money("1000"),
                        instruments=(_DIMENSION.instrument_id,),
                    )
                    for instance in _INSTANCES
                ),
                max_quote_age_us=1_000_000,
                max_state_age_us=86_400_000_000,
                max_price_deviation_bps=2000,
                max_order_notional=HistoryJournalFixture.money("1000"),
            ),
        )

    @staticmethod
    def scenario() -> PaperExecutionScenario:
        """Declare one finite public feed scenario."""
        return PaperExecutionScenario(
            venue="okx",
            instrument_id=_DIMENSION.instrument_id,
            entry_delay_us=0,
            cancel_delay_us=0,
            adverse=HistoryJournalFixture.price("0.01"),
            fee_rate=Decimal("0.005"),
            take_fraction=Decimal("1"),
            gas_inapplicable_reason="off-chain spot order matching",
        )

    @staticmethod
    def decision(instance_id: str, at: datetime) -> AccountDecision:
        """Build an owned buy with a fee reserve and independent quote."""
        return AccountDecision(
            account_id=_ACCOUNT,
            instance_id=instance_id,
            decision=OrderDecision(
                identity=f"{instance_id}-decision",
                at=at,
                intent=OrderIntent(
                    side="buy",
                    quantity=HistoryJournalFixture.quantity("3"),
                    limit=HistoryJournalFixture.price("1.10"),
                    time_in_force="gtc",
                ),
            ),
            quote=AccountQuote(price=HistoryJournalFixture.price("1.00"), at=at),
            maximum_fee=HistoryJournalFixture.money("0.50"),
            checkpoint=f"{instance_id}-decision".encode(),
        )

    @staticmethod
    def create_template_journal(path: Path) -> None:
        """Write real decision, batch and trace items through the public journal."""
        scenario = HistoryJournalFixture.scenario()
        journal = AccountJournal(path, HistoryJournalFixture.configuration())
        journal.bind_paper_scenario(_ACCOUNT, scenario)
        if not journal.reconcile(
            AccountObservation(
                identity="opening",
                at=_OPENING_AT,
                snapshot=AccountSnapshot(
                    account_id=_ACCOUNT,
                    instance_id=None,
                    cash=(HistoryJournalFixture.money("1000"),),
                    positions=(),
                    fees=(HistoryJournalFixture.money("0"),),
                    rebates=(HistoryJournalFixture.money("0"),),
                    transfers=(HistoryJournalFixture.money("1000"),),
                    fill_ids=(),
                    posting_ids=("opening:USDT",),
                ),
                open_orders=(),
            )
        ):
            raise ValueError("template opening reconciliation failed")
        at = _OPENING_AT + timedelta(seconds=1)
        journal.observe(AccountQuote(price=HistoryJournalFixture.price("1.00"), at=at))
        committed = journal.coordinate(
            PortfolioBatch(
                identity=_TEMPLATE_BATCH,
                at=at + timedelta(microseconds=1),
                decisions=tuple(
                    PortfolioDecision(
                        request=HistoryJournalFixture.decision(instance, at),
                        context=PortfolioContext(
                            portfolio_id="reference",
                            strategy_id=instance,
                            model_revision="v1",
                            config_revision="v1",
                            horizon="one-minute",
                            reason="history-capacity",
                            venue="OKX",
                            settlement="spot-immediate",
                            risk_bucket="spot",
                            authority_scope="paper",
                        ),
                    )
                    for instance in _INSTANCES
                ),
            )
        )
        if committed.status != "committed":
            raise ValueError("template portfolio batch was not committed")
        journal.match_public_market(
            _ACCOUNT,
            PaperMarket(
                identity="template-market",
                at=at + timedelta(seconds=1),
                bid=HistoryJournalFixture.price("0.90"),
                ask=HistoryJournalFixture.price("1.00"),
                bid_quantity=HistoryJournalFixture.quantity("3"),
                ask_quantity=HistoryJournalFixture.quantity("3"),
            ),
            scenario,
        )


class HistoryMeasurements:
    """Fill, commit, open, probe and compare account journals at a 24-hour history."""

    @staticmethod
    def fill(store: AccountStateStore, items: HistoryItems, start: int, stop: int) -> None:
        """Append batches and traces ``[start, stop)`` in unmeasured transactions."""
        for chunk in range(start, stop, _FILL_BATCHES):
            with store.write() as transaction:
                for index in range(chunk, min(chunk + _FILL_BATCHES, stop)):
                    batch, decisions = items.batch_items(index)
                    transaction.append_decisions(*decisions)
                    transaction.append_batch(batch)
                    transaction.append_trace(items.trace_item(index))

    @staticmethod
    def batch_commit(store: AccountStateStore, items: HistoryItems, index: int) -> int:
        """Time one complete coordination-shaped store transaction."""
        batch, decisions = items.batch_items(index)
        started = time.perf_counter_ns()
        with store.write() as transaction:
            if transaction.find_batch(batch.batch.identity) is not None:
                raise ValueError("synthetic batch identity repeats")
            for saved in decisions:
                request = saved.request
                if (
                    transaction.find_decision(request.instance_id, request.decision.identity)
                    is not None
                ):
                    raise ValueError("synthetic decision identity repeats")
                transaction.latest_checkpoint(request.instance_id)
            transaction.append_decisions(*decisions)
            transaction.append_batch(batch)
        return time.perf_counter_ns() - started

    @staticmethod
    def trace_commit(store: AccountStateStore, items: HistoryItems, index: int) -> int:
        """Time one complete matching-shaped store transaction."""
        trace = items.trace_item(index)
        scenario = trace.scenario
        started = time.perf_counter_ns()
        with store.write() as transaction:
            HistoryMeasurements.match_lookups(transaction, trace, scenario)
            transaction.append_trace(trace)
        return time.perf_counter_ns() - started

    @staticmethod
    def match_lookups(
        transaction: AccountTransaction,
        trace: AccountPaperTrace,
        scenario: PaperExecutionScenario,
    ) -> None:
        """Perform the public-market match's idempotency and ordering lookups."""
        identity = trace.market.identity
        if (
            transaction.find_trace(
                identity, venue=scenario.venue, instrument_id=scenario.instrument_id
            )
            is not None
        ):
            raise ValueError("synthetic market identity repeats")
        transaction.find_trace(
            identity,
            account_id=trace.account_id,
            venue=scenario.venue,
            instrument_id=scenario.instrument_id,
        )
        next(
            transaction.iter_traces(
                trace.account_id, instrument_id=scenario.instrument_id, newest_first=True
            ),
            None,
        )

    @staticmethod
    def cold_open(path: Path) -> int:
        """Time one application-cold open through the first read."""
        config = HistoryJournalFixture.configuration()
        started = time.perf_counter_ns()
        AccountStateStore(path, config, DomainCodec()).read()
        return time.perf_counter_ns() - started

    @staticmethod
    def percentiles(samples: Sequence[int]) -> dict[str, int]:
        """Summarize samples with empirical nearest-rank percentiles."""
        ordered = sorted(samples)
        rank = partial(HistoryMeasurements.nearest_rank, ordered)

        return {
            "sample_count": len(ordered),
            "minimum_ns": ordered[0],
            "p50_ns": rank(50),
            "p95_ns": rank(95),
            "p99_ns": rank(99),
            "maximum_ns": ordered[-1],
        }

    @staticmethod
    def nearest_rank(ordered: Sequence[int], percent: int) -> int:
        """Return one empirical nearest-rank percentile of ordered samples."""
        return ordered[max(0, math.ceil(percent / 100 * len(ordered)) - 1)]

    @staticmethod
    def copy_journal(source: Path, destination: Path) -> None:
        """Take a consistent standalone copy through the SQLite backup API."""
        with (
            closing(sqlite3.connect(source)) as origin,
            closing(sqlite3.connect(destination)) as target,
        ):
            origin.backup(target)

    @staticmethod
    def disk_bytes(path: Path) -> int:
        """Checkpoint the WAL and return the database and sidecar bytes."""
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return sum(
            candidate.stat().st_size
            for candidate in (path, path.with_name(path.name + "-wal"))
            if candidate.exists()
        )

    @staticmethod
    def item_bytes(path: Path) -> dict[str, float]:
        """Return each history table's mean item bytes."""
        means: dict[str, float] = {}
        with closing(sqlite3.connect(path)) as connection:
            for table, query in (
                ("portfolio_batches", "SELECT avg(length(payload)) FROM portfolio_batches"),
                ("decisions", "SELECT avg(length(payload)) FROM decisions"),
                ("paper_traces", "SELECT avg(length(payload)) FROM paper_traces"),
            ):
                row = cast(tuple[float], connection.execute(query).fetchone())
                means[table] = row[0]
        return means

    @staticmethod
    def subprocess_probe(arguments: Sequence[str]) -> dict[str, int]:
        """Run this consumer in a fresh interpreter and read its JSON line."""
        result = subprocess.run(  # nosec B603  # [owner=runtime; rationale=fixed argv of this consumer in the current interpreter; expires=2027-03-01]
            [sys.executable, str(Path(__file__).resolve()), *arguments],
            check=True,
            capture_output=True,
            timeout=600,
        )
        return msgspec.json.decode(result.stdout, type=dict[str, int])

    @staticmethod
    def memory_probe(path: Path, commits: int) -> dict[str, int]:
        """Open a journal copy, run hot-path commits and report peak resident bytes."""
        store = AccountStateStore(path, HistoryJournalFixture.configuration(), DomainCodec())
        items = HistoryItems(store)
        opened = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * _RSS_UNIT
        base = 10_000_000
        for offset in range(commits):
            HistoryMeasurements.batch_commit(store, items, base + offset)
            HistoryMeasurements.trace_commit(store, items, base + offset)
        return {
            "opened_peak_rss_bytes": opened,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * _RSS_UNIT,
        }

    @staticmethod
    def fresh_open_probe(path: Path) -> dict[str, int]:
        """Time one open in this interpreter after imports."""
        return {"open_ns": HistoryMeasurements.cold_open(path)}

    @staticmethod
    def replay_check(parities: Sequence[Path], original: Path, output: Path) -> dict[str, object]:
        """Apply the declared replay criterion to economic parity results."""
        reference = msgspec.json.decode(original.read_bytes(), type=_ParityReport)
        expected = {
            account.account: {
                field: result.replay_sha256 for field, result in (account.comparisons or {}).items()
            }
            for account in reference.accounts
        }
        trials: list[dict[str, object]] = []
        for path in parities:
            report = msgspec.json.decode(path.read_bytes(), type=_ParityReport)
            accounts: list[dict[str, object]] = []
            for account in report.accounts:
                comparisons = account.comparisons or {}
                equal = len(comparisons) == 7 and all(item.equal for item in comparisons.values())
                original_equal: bool | None = None
                if report.signed_trial == reference.signed_trial:
                    original_equal = bool(comparisons) and all(
                        result.replay_sha256 == expected.get(account.account, {}).get(field)
                        for field, result in comparisons.items()
                    )
                accounts.append(
                    {
                        "account": account.account,
                        "failure": account.failure,
                        "all_seven_equal": equal,
                        "equal_to_original_replay": original_equal,
                        "passed": equal and original_equal is not False,
                    }
                )
            trials.append(
                {
                    "parity": str(path),
                    "parity_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "signed_trial": report.signed_trial,
                    "installed_identity_match": report.installed_identity_match,
                    "accounts": accounts,
                    "passed": bool(accounts) and all(item["passed"] is True for item in accounts),
                }
            )
        result: dict[str, object] = {
            "schema": "account-history-replay",
            "original_parity": str(original),
            "original_parity_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
            "trials": trials,
            "passed": bool(trials) and all(trial["passed"] is True for trial in trials),
        }
        output.write_bytes(msgspec.json.format(msgspec.json.encode(result)) + b"\n")
        return result


class _Arguments(argparse.Namespace):
    """Hold one subcommand's typed arguments."""

    command: str
    output: Path
    journal: Path
    commits: int
    parity: list[Path]
    original: Path


class _Comparison(msgspec.Struct):
    """Read one economic-fact comparison of a parity report."""

    equal: bool
    replay_sha256: str


class _ParityAccount(msgspec.Struct):
    """Read one account of a parity report."""

    account: str
    comparisons: dict[str, _Comparison] | None = None
    failure: str | None = None


class _ParityReport(msgspec.Struct):
    """Read the parts of a parity report the replay criterion uses."""

    signed_trial: str
    accounts: list[_ParityAccount]
    installed_identity_match: bool | None = None


class HistoryItems:
    """Clone the journal's real items with fresh identities."""

    def __init__(self, store: AccountStateStore) -> None:
        """Read the template batch, its decisions and the template trace."""
        self.codec = store.codec
        with store.snapshot() as snapshot:
            batch = snapshot.find_batch(_TEMPLATE_BATCH)
            decisions = tuple(
                snapshot.find_decision(instance, f"{instance}-decision") for instance in _INSTANCES
            )
            trace = next(snapshot.iter_traces(_ACCOUNT), None)
        if batch is None or trace is None or any(item is None for item in decisions):
            raise ValueError("template history items are missing")
        self.batch = batch
        self.decisions = cast(tuple[SavedDecision, ...], decisions)
        self.trace = trace

    def batch_items(self, index: int) -> tuple[SavedPortfolioBatch, tuple[SavedDecision, ...]]:
        """Return one fresh batch and its two decisions."""
        decisions = tuple(
            replace(
                saved,
                request=replace(
                    saved.request,
                    decision=replace(
                        saved.request.decision, identity=f"{saved.request.instance_id}-{index}"
                    ),
                    checkpoint=self.checkpoint(f"{saved.request.instance_id}-{index}"),
                ),
            )
            for saved in self.decisions
        )
        requests: tuple[PortfolioDecision, ...] = tuple(
            replace(item, request=saved.request)
            for item, saved in zip(self.batch.batch.decisions, decisions, strict=True)
        )
        batch = replace(
            self.batch,
            batch=replace(self.batch.batch, identity=f"batch-{index}", decisions=requests),
        )
        return batch, decisions

    def trace_item(self, index: int) -> AccountPaperTrace:
        """Return one fresh trace whose input digest matches its market."""
        market = replace(self.trace.market, identity=f"market-{index}")
        digest = hashlib.sha256(
            self.codec.encode_json((self.trace.account_id, market, self.trace.scenario))
        ).hexdigest()
        liquidity = self.trace.liquidity
        if liquidity is not None:
            liquidity = replace(liquidity, last_market_identity=market.identity)
        return replace(self.trace, market=market, input_sha256=digest, liquidity=liquidity)

    @staticmethod
    def checkpoint(identity: str) -> bytes:
        """Derive a deterministic synthetic strategy continuation."""
        seed = hashlib.sha256(identity.encode()).digest()
        return (seed * (_CHECKPOINT_BYTES // len(seed) + 1))[:_CHECKPOINT_BYTES]


class HistoryCapacity:
    """Run the declared workload and write raw samples and a summary."""

    def __init__(
        self,
        output: Path,
        *,
        batches: int = 30_000,
        commits: int = 1_000,
        opens: int = 1_000,
        fresh_opens: int = 20,
        memory_commits: int = 200,
        host: Callable[[], dict[str, object]] | None = None,
    ) -> None:
        """Bind an absent output directory, the workload size and the host reader."""
        if not output.is_absolute() or output.exists():
            raise ValueError("history capacity requires a fresh absolute output directory")
        if batches % 4 or batches <= 0:
            raise ValueError("history size must split evenly into quarter levels")
        self.output = output
        self.host = self._host if host is None else host
        self.batches, self.commits, self.opens = batches, commits, opens
        self.fresh_opens, self.memory_commits = fresh_opens, memory_commits

    def run(self) -> dict[str, object]:
        """Fill, measure and summarize one history capacity run."""
        self.output.mkdir(parents=True)
        journal = self.output / "journal.sqlite3"
        HistoryJournalFixture.create_template_journal(journal)
        store = AccountStateStore(journal, HistoryJournalFixture.configuration(), DomainCodec())
        items = HistoryItems(store)
        filled = 0
        memory: dict[str, dict[str, int]] = {}
        for level in _LEVELS:
            target = self.batches * level // 100
            HistoryMeasurements.fill(store, items, filled, target)
            filled = target
            copy = self.output / f"level-{level}.sqlite3"
            HistoryMeasurements.copy_journal(journal, copy)
            memory[str(level)] = HistoryMeasurements.subprocess_probe(
                ("memory", "--journal", str(copy), "--commits", str(self.memory_commits))
            )
            copy.unlink()
        full_bytes = HistoryMeasurements.disk_bytes(journal)
        means = HistoryMeasurements.item_bytes(journal)
        started = time.perf_counter_ns()
        AccountStateStore.verify(journal, HistoryJournalFixture.configuration(), DomainCodec())
        verify_ns = time.perf_counter_ns() - started
        batch_samples: list[int] = []
        trace_samples: list[int] = []
        for offset in range(self.commits):
            batch_samples.append(
                HistoryMeasurements.batch_commit(store, items, self.batches + offset)
            )
            trace_samples.append(
                HistoryMeasurements.trace_commit(store, items, self.batches + offset)
            )
        open_samples = [HistoryMeasurements.cold_open(journal) for _ in range(self.opens)]
        fresh_samples = [
            HistoryMeasurements.subprocess_probe(("fresh-open", "--journal", str(journal)))[
                "open_ns"
            ]
            for _ in range(self.fresh_opens)
        ]
        latency = {
            "batch_commit": HistoryMeasurements.percentiles(batch_samples),
            "trace_commit": HistoryMeasurements.percentiles(trace_samples),
            "cold_open": HistoryMeasurements.percentiles(open_samples),
        }
        growth = memory["100"]["peak_rss_bytes"] - memory["0"]["peak_rss_bytes"]
        passed = {name: latency[name]["p99_ns"] <= target for name, target in _TARGETS_NS.items()}
        passed["memory"] = growth <= _MEMORY_GROWTH_BYTES
        summary: dict[str, object] = {
            "schema": "account-history-capacity",
            "workload": {
                "batches": self.batches,
                "decisions": 2 * self.batches,
                "traces": self.batches,
                "measured_commits_per_kind": self.commits,
                "cold_opens": self.opens,
                "fresh_process_opens": self.fresh_opens,
                "memory_commits_per_kind": self.memory_commits,
                "checkpoint_bytes": _CHECKPOINT_BYTES,
                "mean_item_bytes": means,
                "reference_mean_item_bytes": _REFERENCE_BYTES,
            },
            "host": self.host(),
            "latency": latency,
            "fresh_process_open": HistoryMeasurements.percentiles(fresh_samples),
            "memory": {
                "levels_percent": memory,
                "growth_bytes": growth,
                "limit_bytes": _MEMORY_GROWTH_BYTES,
            },
            "disk": {
                "full_history_bytes": full_bytes,
                "four_account_days_in_canonical_budget": _CANONICAL_BUDGET_BYTES
                / (_ACCOUNTS * full_bytes),
                "canonical_budget_bytes": _CANONICAL_BUDGET_BYTES,
            },
            "verify_ns": verify_ns,
            "targets_ns": _TARGETS_NS,
            "passed": passed,
            "qualified": all(passed.values()),
        }
        samples: dict[str, list[int]] = {
            "batch_commit_ns": batch_samples,
            "trace_commit_ns": trace_samples,
            "cold_open_ns": open_samples,
            "fresh_process_open_ns": fresh_samples,
        }
        (self.output / "samples.json").write_bytes(msgspec.json.encode(samples))
        (self.output / "summary.json").write_bytes(
            msgspec.json.format(msgspec.json.encode(summary)) + b"\n"
        )
        return summary

    @staticmethod
    def _command(*arguments: str) -> str:
        """Read one fixed local command's output."""
        return subprocess.run(  # nosec B603  # [owner=runtime; rationale=fixed local host fact commands; expires=2027-03-01]
            arguments, check=True, capture_output=True, text=True
        ).stdout.strip()

    @staticmethod
    def _host() -> dict[str, object]:
        """Record the host, power and exact declared inputs."""
        repository = Path(__file__).resolve().parents[3]
        command = HistoryCapacity._command

        declaration = repository / "docs/roadmap/account-journal-history.md"
        return {
            "platform": platform.platform(),
            "cpu": command("/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"),
            "logical_cores": int(command("/usr/sbin/sysctl", "-n", "hw.ncpu")),
            "ram_bytes": int(command("/usr/sbin/sysctl", "-n", "hw.memsize")),
            "power": command("/usr/bin/pmset", "-g", "batt"),
            "base_commit": command("/usr/bin/git", "-C", str(repository), "rev-parse", "HEAD"),
            "declaration_sha256": hashlib.sha256(declaration.read_bytes()).hexdigest(),
            "consumer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "cache": "uncontrolled; warm after first read",
        }


if __name__ == "__main__":
    sys.exit(HistoryCapacityCommand.run())
