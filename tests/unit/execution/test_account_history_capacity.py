"""Keep the account history capacity consumer's workload and criteria exact."""

from __future__ import annotations

# standard library imports
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

# third party library imports
import msgspec
import pytest
from account_history_capacity import (
    HistoryCapacity,
    HistoryItems,
    HistoryJournalFixture,
    HistoryMeasurements,
)

# project library imports
from execution.account_state import AccountStateStore
from serialization import DomainCodec


class TestAccountHistoryCapacity:
    """Fill, measure and replay-check a small account-journal history run."""

    def test_small_run_fills_measures_and_keeps_a_verifiable_journal(self, tmp_path: Path) -> None:
        """History, measured commits and the template stay in one verifiable journal."""
        output = tmp_path / "run"
        summary = HistoryCapacity(
            output,
            batches=8,
            commits=3,
            opens=2,
            fresh_opens=1,
            memory_commits=2,
            host=_Constant(dict[str, object](host="test")),
        ).run()

        journal = output / "journal.sqlite3"
        assert HistoryCapacityChecks.counts(journal) == (2 * (1 + 8 + 3), 1 + 8 + 3, 1 + 8 + 3)
        assert (
            len(
                AccountStateStore.verify(
                    journal, HistoryJournalFixture.configuration(), DomainCodec()
                )
            )
            == 1
        )
        workload = cast(dict[str, object], summary["workload"])
        assert (workload["batches"], workload["decisions"], workload["traces"]) == (8, 16, 8)
        latency = cast(dict[str, dict[str, int]], summary["latency"])
        assert {name: value["sample_count"] for name, value in latency.items()} == {
            "batch_commit": 3,
            "trace_commit": 3,
            "cold_open": 2,
        }
        memory = cast(dict[str, dict[str, dict[str, int]]], summary["memory"])
        assert set(memory["levels_percent"]) == {"0", "25", "50", "75", "100"}
        assert set(cast(dict[str, bool], summary["passed"])) == {
            "batch_commit",
            "trace_commit",
            "cold_open",
            "memory",
        }
        assert (output / "samples.json").is_file()
        assert not any(output.glob("level-*.sqlite3"))

    def test_trace_count_is_independent_and_every_reader_is_probed(self, tmp_path: Path) -> None:
        """Eventless history traces fill to their own count; each reader reports its cost."""
        output = tmp_path / "run"
        summary = HistoryCapacity(
            output,
            batches=4,
            traces=12,
            commits=1,
            opens=1,
            fresh_opens=1,
            memory_commits=1,
            host=_Constant(dict[str, object](host="test")),
        ).run()

        journal = output / "journal.sqlite3"
        # The template's batch and trace, the history, then one measured commit each.
        assert HistoryCapacityChecks.counts(journal) == (2 * (1 + 4 + 1), 1 + 4 + 1, 1 + 12 + 1)
        store = AccountStateStore(journal, HistoryJournalFixture.configuration(), DomainCodec())
        with store.snapshot() as snapshot:
            history = tuple(
                trace
                for trace in snapshot.iter_traces("shared")
                if trace.market.identity.startswith("history-market-")
            )
        assert len(history) == 12
        assert all(
            trace.status == "committed"
            and not trace.physical_events
            and not trace.child_fill_events
            for trace in history
        )
        workload = cast(dict[str, object], summary["workload"])
        assert (workload["batches"], workload["traces"]) == (4, 12)
        readers = cast(dict[str, dict[str, int]], summary["readers_fresh_interpreter"])
        assert set(readers) == {"monitoring", "facts", "traces", "verify", "newest", "retry"}
        # Template plus history: the template trace fills both instances; 13 traces.
        assert readers["monitoring"]["traces"] == 13
        assert readers["facts"]["items"] == 2
        assert readers["newest"]["items"] == 1
        assert readers["verify"]["items"] == 1
        assert readers["retry"]["lookup_sample_count"] == 1000
        assert all("elapsed_ns" in value for name, value in readers.items() if name != "retry")
        occupancy = cast(dict[str, object], summary["disk"])["allocated_bytes_by_table_and_index"]
        with closing(sqlite3.connect(":memory:")) as connection:
            options = cast(
                list[tuple[str]], connection.execute("PRAGMA compile_options").fetchall()
            )
        if ("ENABLE_DBSTAT_VTAB",) in options:
            assert {"paper_traces", "paper_traces_account"} <= set(cast(dict[str, int], occupancy))
        else:
            assert occupancy == "unmeasured: this SQLite has no dbstat"

    def test_synthetic_items_have_fresh_identities_and_declared_checkpoints(
        self, tmp_path: Path
    ) -> None:
        """Clones differ only by identity, digest and checkpoint from the real template."""
        output = tmp_path / "items"
        output.mkdir()
        HistoryJournalFixture.create_template_journal(output / "journal.sqlite3")
        items = HistoryItems(
            AccountStateStore(
                output / "journal.sqlite3", HistoryJournalFixture.configuration(), DomainCodec()
            )
        )
        batch, decisions = items.batch_items(7)
        assert batch.batch.identity == "batch-7"
        assert [saved.request.decision.identity for saved in decisions] == ["alpha-7", "beta-7"]
        assert all(len(saved.request.checkpoint) == 675 for saved in decisions)
        assert tuple(item.request for item in batch.batch.decisions) == tuple(
            saved.request for saved in decisions
        )
        trace = items.trace_item(7)
        assert trace.market.identity == "market-7"
        assert trace.input_sha256 != items.trace.input_sha256
        with pytest.raises(ValueError, match="fresh absolute"):
            HistoryCapacity(output, batches=8)

    def test_replay_check_requires_equal_facts_and_original_hashes(self, tmp_path: Path) -> None:
        """Identity mismatch and older reports are accepted; unequal facts or hashes fail."""
        original = tmp_path / "original.json"
        reference = HistoryCapacityChecks.report("initial", {"okx": "a"})
        del reference["installed_identity_match"]
        original.write_bytes(msgspec.json.encode(reference))
        same = tmp_path / "same.json"
        same.write_bytes(msgspec.json.encode(HistoryCapacityChecks.report("initial", {"okx": "a"})))
        suffix = tmp_path / "suffix.json"
        suffix.write_bytes(
            msgspec.json.encode(HistoryCapacityChecks.report("recovery", {"okx": "z"}))
        )
        assert (
            HistoryMeasurements.replay_check((same, suffix), original, tmp_path / "pass.json")[
                "passed"
            ]
            is True
        )

        changed = tmp_path / "changed.json"
        changed.write_bytes(
            msgspec.json.encode(HistoryCapacityChecks.report("initial", {"okx": "b"}))
        )
        assert (
            HistoryMeasurements.replay_check((changed,), original, tmp_path / "hash.json")["passed"]
            is False
        )
        unequal = tmp_path / "unequal.json"
        unequal.write_bytes(
            msgspec.json.encode(HistoryCapacityChecks.report("recovery", {"okx": "z"}, equal=False))
        )
        assert (
            HistoryMeasurements.replay_check((unequal,), original, tmp_path / "unequal-out.json")[
                "passed"
            ]
            is False
        )


class HistoryCapacityChecks:
    """Count journal rows and author replay-check reports."""

    @staticmethod
    def counts(path: Path) -> tuple[int, int, int]:
        """Count decisions, batches and traces."""
        with closing(sqlite3.connect(path)) as connection:
            return cast(
                tuple[int, int, int],
                connection.execute(
                    "SELECT (SELECT count(*) FROM decisions), "
                    "(SELECT count(*) FROM portfolio_batches),"
                    " (SELECT count(*) FROM paper_traces)"
                ).fetchone(),
            )

    @staticmethod
    def report(trial: str, hashes: dict[str, str], *, equal: bool = True) -> dict[str, object]:
        """Build one parity report with seven comparisons per account."""
        return {
            "signed_trial": trial,
            "installed_identity_match": False,
            "accounts": [
                {
                    "account": account,
                    "comparisons": {
                        field: {"equal": equal, "replay_sha256": digest}
                        for field in (
                            "ledger",
                            "orders",
                            "net_orders",
                            "paper_fills",
                            "paper_costs",
                            "paper_traces",
                            "checkpoints",
                        )
                    },
                }
                for account, digest in hashes.items()
            ],
        }


class _Constant[T]:
    """Return one fixed value on every call, standing in for a zero-argument callable."""

    def __init__(self, value: T) -> None:
        """Bind the value to return."""
        self.value = value

    def __call__(self) -> T:
        """Return the bound value."""
        return self.value
