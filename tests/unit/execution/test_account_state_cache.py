"""Keep decoded account state reusable only while fresh SQLite bytes agree."""

from __future__ import annotations

# standard library imports
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace
from test_account_journal import TestAccountJournal as _AccountFixture

# project library imports
from execution import AccountJournal
from execution.account_state import AccountStateStore
from serialization import DomainCodec


def test_open_reader_reuses_exact_bytes_but_sees_another_writer(tmp_path: Path) -> None:
    """A warm reader observes the next committed account fact from another store."""
    fixture = _AccountFixture
    config = fixture._config()
    path = tmp_path / "shared.sqlite3"
    reader = AccountJournal(path, config)
    writer = AccountJournal(path, config)
    before = reader._store.read()
    assert reader._store.read() is before
    assert before.accounts[0].reconciled_at is None

    assert writer.reconcile(
        fixture._observation("opening", fixture.opening_at, fixture._opening_snapshot())
    )
    changed = reader._store.read()
    assert changed is not before
    assert changed.accounts[0].reconciled_at == fixture.opening_at
    assert reader._store.read() is changed
    assert reader.accounts()[0] == changed.accounts[0]
    assert writer._store.read() is writer._store.read()

    with reader._store.write() as transaction:
        transaction.state = replace(transaction.state, stopped_instances=("alpha",))
    assert reader._store.read().stopped_instances == ("alpha",)
    assert writer._store.read() == reader._store.read()
    reopened = AccountJournal(path, config)
    assert reopened._store.read() == reader._store.read()


def test_warm_cache_rejects_changed_configuration_and_malformed_payload(tmp_path: Path) -> None:
    """The cached typed value never hides altered on-disk authority or state bytes."""
    fixture = _AccountFixture
    config = fixture._config()
    path = tmp_path / "tampered.sqlite3"
    codec = DomainCodec()
    store = AccountStateStore(path, config, codec)
    with store.write() as transaction:
        transaction.state = replace(transaction.state, stopped_instances=("alpha",))
    original = store.read()
    assert store.read() is original

    with closing(sqlite3.connect(path)) as connection:
        connection.execute("UPDATE firm SET configuration=? WHERE id=1", (b"{}",))
        connection.commit()
    with pytest.raises(ValueError, match="configuration or state schema differs"):
        store.read()

    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "UPDATE firm SET configuration=?, payload=? WHERE id=1",
            (codec.encode_json(config), b"{"),
        )
        connection.commit()
    with pytest.raises(msgspec.DecodeError):
        store.read()


def test_rolled_back_stage_never_becomes_cached_state(tmp_path: Path) -> None:
    """An exception after staging cannot expose uncommitted selective controls."""
    store = AccountStateStore(
        tmp_path / "rollback.sqlite3", _AccountFixture._config(), DomainCodec()
    )
    original = store.read()
    with pytest.raises(RuntimeError, match="cancel staged mutation"):
        with store.write() as transaction:
            transaction.state = replace(transaction.state, stopped_instances=("alpha",))
            raise RuntimeError("cancel staged mutation")
    after = store.read()
    assert after is original
    assert after.stopped_instances == ()

    with store.write() as transaction:
        transaction.state = replace(transaction.state, stopped_instances=("alpha",))
    committed = store.read()
    assert committed.stopped_instances == ("alpha",)
    assert committed is store.read()


def test_invalid_staged_schema_preserves_durable_and_cached_state(tmp_path: Path) -> None:
    """A staged activation/schema mismatch cannot become a committed cached value."""
    path = tmp_path / "invalid-stage.sqlite3"
    codec = DomainCodec()
    store = AccountStateStore(path, _AccountFixture._config(), codec)
    original = store.read()
    payload = codec.encode_json(original)

    with pytest.raises(ValueError, match="unsupported account journal state schema"):
        with store.write() as transaction:
            transaction.state = replace(transaction.state, schema_version="account-journal-v3")

    assert store.read() is original
    with closing(sqlite3.connect(path)) as connection:
        row = cast(
            tuple[object, ...] | None,
            connection.execute("SELECT payload FROM firm WHERE id=1").fetchone(),
        )
    assert row == (payload,)
    assert AccountStateStore(path, _AccountFixture._config(), codec).read() == original
