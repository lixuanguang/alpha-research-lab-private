"""Retain bounded local operator-alert attempts independently of protective controls."""

from __future__ import annotations

# standard library imports
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal, cast

# project library imports
from serialization import DomainCodec, WireRecord
from telemetry.health import HealthAlert


class OperationAlert(WireRecord, frozen=True):
    """Retain local socket acceptance, failure or an interrupted delivery attempt.

    ``delivered`` means the local datagram socket accepted the alert, not that
    an operator or remote service acknowledged it. A pending attempt is never
    silently replayed; callers can issue an explicit separately identified retry.
    """

    identity: str
    control_sha256: str
    address: str
    status: Literal["pending", "delivered", "failed"]

    def __post_init__(self) -> None:
        """Keep retained alert context bounded and free of arbitrary message content."""
        if (
            type(self.identity) is not str
            or not 1 <= len(self.identity) <= 256
            or type(self.control_sha256) is not str
            or len(self.control_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.control_sha256)
            or type(self.address) is not str
            or not self.address.startswith("/")
            or len(self.address.encode()) > 100
            or "\0" in self.address
            or self.status not in ("pending", "delivered", "failed")
        ):
            raise ValueError("invalid bounded operational alert")


class OperationalAlerts:
    """Journal each local delivery after the independent hard control has committed."""

    def __init__(self, path: Path) -> None:
        """Bind one explicitly selected alert database without opening it."""
        self.path = path
        self.codec = DomainCodec()

    def send(self, *, identity: str, control_sha256: str, address: str) -> OperationAlert:
        """Retain an intent, attempt local delivery once, then retain its outcome.

        Identical retries return the saved outcome, including an interrupted
        ``pending`` attempt. Changed identity bytes fail. SQLite or disk failures
        propagate; callers must already have stopped risk before invoking this
        operation. No telemetry response can release an account block.
        """
        pending = OperationAlert(
            identity=identity, control_sha256=control_sha256, address=address, status="pending"
        )
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = cast(
                tuple[object, ...] | None,
                connection.execute(
                    "SELECT payload FROM alerts WHERE identity=?", (identity,)
                ).fetchone(),
            )
            if row is not None:
                saved = self._decode(row)
                if (saved.control_sha256, saved.address) != (control_sha256, address):
                    raise ValueError("operational alert identity reused with different content")
                return saved
            connection.execute(
                "INSERT INTO alerts(identity, payload) VALUES (?, ?)",
                (identity, self.codec.encode_json(pending)),
            )
            connection.commit()
        delivered = HealthAlert.deliver(address, f"account-control:{control_sha256}")
        result = OperationAlert(
            identity=identity,
            control_sha256=control_sha256,
            address=address,
            status="delivered" if delivered else "failed",
        )
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE alerts SET payload=? WHERE identity=?",
                (self.codec.encode_json(result), identity),
            )
            connection.commit()
        return result

    def read(self) -> tuple[OperationAlert, ...]:
        """Read retained delivery outcomes without creating an absent store."""
        if not self.path.exists():
            return ()
        with closing(
            sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
        ) as connection:
            rows = cast(
                list[tuple[object, ...]],
                connection.execute("SELECT payload FROM alerts ORDER BY rowid").fetchall(),
            )
        return tuple(self._decode(row) for row in rows)

    def _connect(self) -> sqlite3.Connection:
        """Open a bounded durable local alert journal."""
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS alerts (identity TEXT PRIMARY KEY, payload BLOB NOT NULL)"
        )
        return connection

    def _decode(self, row: tuple[object, ...]) -> OperationAlert:
        """Validate the SQLite blob boundary before decoding the retained attempt."""
        if len(row) != 1 or type(row[0]) is not bytes:
            raise ValueError("invalid operational alert storage")
        return self.codec.decode_json(row[0], OperationAlert)
