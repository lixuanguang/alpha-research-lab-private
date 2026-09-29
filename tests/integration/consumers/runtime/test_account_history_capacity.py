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
    configuration,
    create_template_journal,
    replay_check,
)

# project library imports
from execution.account_state import AccountStateStore
from serialization import DomainCodec


def _counts(path: Path) -> tuple[int, int, int]:
    """Count decisions, batches and traces."""
    with closing(sqlite3.connect(path)) as connection:
        return cast(
            tuple[int, int, int],
            connection.execute(
                "SELECT (SELECT count(*) FROM decisions), (SELECT count(*) FROM portfolio_batches),"
                " (SELECT count(*) FROM paper_traces)"
            ).fetchone(),
        )


def test_small_run_fills_measures_and_keeps_a_verifiable_journal(tmp_path: Path) -> None:
    """History, measured commits and the template stay in one verifiable journal."""
    output = tmp_path / "run"
    summary = HistoryCapacity(
        output,
        batches=8,
        commits=3,
        opens=2,
        fresh_opens=1,
        memory_commits=2,
        host=lambda: {"host": "test"},
    ).run()

    journal = output / "journal.sqlite3"
    assert _counts(journal) == (2 * (1 + 8 + 3), 1 + 8 + 3, 1 + 8 + 3)
    assert len(AccountStateStore.verify(journal, configuration(), DomainCodec())) == 1
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


def test_synthetic_items_have_fresh_identities_and_declared_checkpoints(tmp_path: Path) -> None:
    """Clones differ only by identity, digest and checkpoint from the real template."""
    output = tmp_path / "items"
    output.mkdir()
    create_template_journal(output / "journal.sqlite3")
    items = HistoryItems(
        AccountStateStore(output / "journal.sqlite3", configuration(), DomainCodec())
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


def _report(trial: str, hashes: dict[str, str], *, equal: bool = True) -> dict[str, object]:
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


def test_replay_check_requires_equal_facts_and_original_hashes(tmp_path: Path) -> None:
    """Identity mismatch is ignored; an unequal field or changed hash fails."""
    original = tmp_path / "original.json"
    original.write_bytes(msgspec.json.encode(_report("initial", {"okx": "a"})))
    same = tmp_path / "same.json"
    same.write_bytes(msgspec.json.encode(_report("initial", {"okx": "a"})))
    suffix = tmp_path / "suffix.json"
    suffix.write_bytes(msgspec.json.encode(_report("recovery", {"okx": "z"})))
    assert replay_check((same, suffix), original, tmp_path / "pass.json")["passed"] is True

    changed = tmp_path / "changed.json"
    changed.write_bytes(msgspec.json.encode(_report("initial", {"okx": "b"})))
    assert replay_check((changed,), original, tmp_path / "hash.json")["passed"] is False
    unequal = tmp_path / "unequal.json"
    unequal.write_bytes(msgspec.json.encode(_report("recovery", {"okx": "z"}, equal=False)))
    assert replay_check((unequal,), original, tmp_path / "unequal-out.json")["passed"] is False
