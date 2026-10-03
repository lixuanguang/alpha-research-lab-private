"""Keep growing account state in verified rows and the account head independent of history."""

from __future__ import annotations

# standard library imports
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from functools import partial
from pathlib import Path
from typing import cast

# third party library imports
import pytest
from msgspec.structs import replace
from test_account_history_scaling import _SharedFirmHistory

# project library imports
from execution import AccountJournal
from execution.account_state import (
    AccountStateStore,
    HistoryDigest,
    HistorySummary,
    RowSummary,
    StateRows,
)
from serialization import DomainCodec


class _CommitBeforeRowLoad:
    """Commit from another journal between the head select and the row selects."""

    def __init__(
        self,
        history: _SharedFirmHistory,
        load: Callable[[sqlite3.Connection, HistorySummary], dict[str, tuple[object, ...]]],
    ) -> None:
        """Bind the other writer and the original row loader."""
        self._history = history
        self._load = load

    def __call__(
        self, connection: sqlite3.Connection, summary: HistorySummary
    ) -> dict[str, tuple[object, ...]]:
        """Commit through the other journal, then load rows as before."""
        self._history.round_trip()
        return self._load(connection, summary)


class TestAccountStateRows:
    """Exercise the row-kept state fields and postings through the account journal."""

    def test_head_size_does_not_grow_with_orders_events_or_postings(self, tmp_path: Path) -> None:
        """History lives in rows; the head holds only current, bounded state."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        sizes: list[int] = []
        for orders in (10, 100):
            while history.orders < orders:
                history.round_trip()
            sizes.append(TestAccountStateRows.head_bytes(history.journal.path))
        # Only digits of row counts may differ.
        assert abs(sizes[1] - sizes[0]) < 64
        reopened = AccountJournal(history.journal.path, history._config())
        assert reopened._store.read() == history.journal._store.read()
        assert reopened.orders() == history.journal.orders()

    def test_every_row_field_leaves_the_head_and_returns_from_rows(self, tmp_path: Path) -> None:
        """Stripping and assembling cover exactly the row-kept fields, whichever they are."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        for _ in range(3):
            history.round_trip()
        state = history.journal._store.read()
        stripped = StateRows.strip(state)
        assert not any(StateRows.row_values(stripped).values())
        assert StateRows.assemble(stripped, StateRows.row_values(state)) == state

    @pytest.mark.parametrize("digest", ["g" * 64, "A" * 64, "a" * 63, ""])
    def test_history_and_row_digests_share_one_rule(self, digest: str) -> None:
        """Row summaries refuse exactly the digests that history digests refuse."""
        with pytest.raises(ValueError, match="invalid account history digest"):
            HistoryDigest(count=1, sha256=digest)
        with pytest.raises(ValueError, match="invalid account state row summary"):
            RowSummary(field="events", count=1, sha256=digest)

    def test_order_lookups_follow_the_staged_orders(self, tmp_path: Path) -> None:
        """Indexed lookups see an order saved in place and refuse unknown identities."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        history.round_trip()
        with history.journal._store.write() as transaction:
            first = transaction.state.orders[0]
            assert transaction.order(first.order.identity) is first
            saved = replace(first, instance_id=first.instance_id)
            transaction.save_order(saved)
            assert transaction.order(first.order.identity) is saved
            assert transaction.find_order("absent") is None
            assert transaction.find_net_order("absent") is None
            with pytest.raises(ValueError, match="unknown child order"):
                transaction.order("absent")
            with pytest.raises(ValueError, match="unknown physical order"):
                transaction.net_order("absent")

    def test_another_process_sees_every_commit(self, tmp_path: Path) -> None:
        """Two journals on one file each read the other's changed rows after every commit."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        other = AccountJournal(history.journal.path, history._config())
        for _ in range(6):
            history.round_trip()
            fresh = AccountStateStore(history.journal.path, history._config(), DomainCodec())
            assert other._store.read() == fresh.read() == history.journal._store.read()
            assert other.orders() == history.journal.orders()
            # The other client writes too; the first must see it.
            other.bind_paper_scenario("quiet", history.scenario)
            history.tick("quiet")
            assert other._store.read() == history.journal._store.read()

    def test_read_is_one_snapshot_while_another_process_commits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A commit between the head select and the row selects cannot split a read."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        history.round_trip()
        reader = AccountStateStore(history.journal.path, history._config(), DomainCodec())
        before = reader.read()
        load_after_commit = _CommitBeforeRowLoad(history, reader._rows.load)

        # A different head forces the reader past its cache into the row selects.
        history.round_trip()
        monkeypatch.setattr(reader._rows, "load", load_after_commit)
        state = reader.read()
        assert len(state.orders) > len(before.orders)
        monkeypatch.undo()
        assert reader.read() == history.journal._store.read()

    @pytest.mark.parametrize(
        "tamper",
        [
            "UPDATE state_rows SET payload=CAST(payload || ' ' AS BLOB) "
            "WHERE field='events' AND seq=1",
            "DELETE FROM state_rows WHERE field='orders' AND seq=(SELECT max(seq) FROM "
            "state_rows WHERE field='orders')",
            "UPDATE state_rows SET seq=-1 WHERE field='orders' AND seq=0;"
            "UPDATE state_rows SET seq=0 WHERE field='orders' AND seq=1;"
            "UPDATE state_rows SET seq=1 WHERE field='orders' AND seq=-1;",
            "INSERT INTO state_rows SELECT 'unexpected', seq, sha256, payload FROM state_rows "
            "WHERE field='orders' AND seq=0",
        ],
        ids=["changed", "missing", "reordered", "unexpected"],
    )
    def test_verify_and_open_refuse_altered_rows(self, tmp_path: Path, tamper: str) -> None:
        """A changed, missing, reordered or unexpected row is refused."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        for _ in range(3):
            history.round_trip()
        path, config = history.journal.path, history._config()
        assert AccountJournal.verify(path, config)
        TestAccountStateRows.execute(path, tamper)
        with pytest.raises(ValueError, match="state rows differ from its head"):
            AccountJournal.verify(path, config)
        if not tamper.startswith("INSERT"):
            with pytest.raises(ValueError, match="state rows differ from its head"):
                AccountJournal(path, config).orders()

    def test_head_digest_mismatch_is_refused(self, tmp_path: Path) -> None:
        """A head whose row summary no longer matches the stored rows is refused."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        history.round_trip()
        path, config = history.journal.path, history._config()
        with closing(sqlite3.connect(path)) as connection:
            row = cast(
                tuple[object, ...],
                connection.execute("SELECT payload FROM firm WHERE id=1").fetchone(),
            )
            payload = cast(bytes, row[0])
            marker = b'"field":"events","sha256":"'
            start = payload.index(marker) + len(marker)
            digit = b"0" if payload[start : start + 1] != b"0" else b"1"
            tampered = payload[:start] + digit + payload[start + 1 :]
            connection.execute("UPDATE firm SET payload=? WHERE id=1", (tampered,))
            connection.commit()
        with pytest.raises(ValueError, match="state rows differ from its head"):
            AccountJournal.verify(path, config)
        with pytest.raises(ValueError, match="state rows differ from its head"):
            AccountJournal(path, config).orders()

    def test_journal_in_the_single_document_layout_is_refused(self, tmp_path: Path) -> None:
        """A journal without state rows is an unsupported schema, never read or migrated."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        path, config = history.journal.path, history._config()
        TestAccountStateRows.execute(path, "DROP TABLE state_rows")
        refusals: tuple[Callable[[], object], ...] = (
            partial(AccountJournal, path, config),
            partial(AccountJournal.verify, path, config),
        )
        for refusal in refusals:
            with pytest.raises(ValueError, match="unsupported account journal schema"):
                refusal()

    @pytest.mark.performance
    def test_round_trip_cost_is_flat_in_filled_orders(self, tmp_path: Path) -> None:
        """Admitting and filling an order costs about the same at 40 and 400 filled orders."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        medians: list[float] = []
        for orders in (40, 400):
            while history.orders < orders:
                history.round_trip()
            medians.append(history.median_seconds(history.round_trip, repeats=9))
        print(f"round trip at 40/400 filled orders: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Rewriting the whole head and re-adding every posting grew with history.
        assert medians[1] < 1.5 * medians[0]

    @pytest.mark.performance
    def test_row_write_skips_unchanged_fields(self, tmp_path: Path) -> None:
        """A commit that changes no row-kept field costs the same at 100 and 1,000 orders."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        store = history.journal._store
        medians: list[float] = []
        for orders in (100, 1000):
            while history.orders < orders:
                history.round_trip()
            values = StateRows.row_values(store.read())
            samples: list[float] = []
            with closing(sqlite3.connect(store.path)) as connection:
                for _ in range(31):
                    started = time.perf_counter()
                    store._rows.write(connection, values, values)
                    samples.append(time.perf_counter() - started)
                connection.rollback()
            medians.append(sorted(samples)[15])
        print(f"unchanged row write at 100/1000 orders: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Walking, copying and re-hashing every row of every field grew with history.
        assert medians[1] < 2 * medians[0]

    @staticmethod
    def head_bytes(path: Path) -> int:
        """Return the size of the committed firm head."""
        with closing(sqlite3.connect(path)) as connection:
            row = cast(
                tuple[object, ...],
                connection.execute("SELECT payload FROM firm WHERE id=1").fetchone(),
            )
        assert type(row[0]) is bytes
        return len(row[0])

    @staticmethod
    def execute(path: Path, statement: str) -> None:
        """Change the stored rows outside the journal."""
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript(statement)
            connection.commit()
