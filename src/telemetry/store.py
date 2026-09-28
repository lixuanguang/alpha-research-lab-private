"""Retain revision-aware telemetry with explicit capacity and retention boundaries."""

from __future__ import annotations

# standard library imports
import sqlite3
from collections import OrderedDict
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import cast

# project library imports
from serialization import DomainCodec
from telemetry.events import MonitoringEvent, MonitoringQuery


class TelemetryStore:
    """Own a separate SQLite journal; failure never modifies account or risk state.

    Writers wait at most 50ms for a competing database lock. Explicit retention
    removes whole event-time samples and records a floor; older queries fail.
    Retries are byte-identical and idempotent. Capacity exhaustion is visible.
    """

    def __init__(self, path: Path, *, max_events: int = 1_000_000) -> None:
        """Bind a telemetry database and finite row budget without opening it."""
        if type(max_events) is not int or not 1 <= max_events <= 10_000_000:
            raise ValueError("invalid telemetry capacity")
        self.path = path
        self.max_events = max_events
        self.codec = DomainCodec()
        self._query_payloads: OrderedDict[bytes, MonitoringEvent] = OrderedDict()

    def append(self, events: tuple[MonitoringEvent, ...]) -> int:
        """Atomically retain up to 10,000 facts, rejecting changed retries and revisions.

        Returns:
            Number of newly retained revisions; exact retries contribute zero.

        Raises:
            ValueError: A fact conflicts with prior bytes, retention or capacity.
            OSError: The selected storage path is unavailable.
            sqlite3.Error: The bounded journal transaction cannot commit.
        """
        if type(events) is not tuple or len(events) > 10_000:
            raise ValueError("telemetry append requires a bounded immutable batch")
        for event in events:
            if type(event) is not MonitoringEvent:
                raise TypeError("telemetry store requires monitoring events")
            event.__post_init__()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            floor = self._floor(connection)
            inserted = 0
            for event in events:
                if floor is not None and event.at < floor:
                    raise ValueError("telemetry event predates retained history")
                previous = self._rows(
                    connection.execute(
                        "SELECT payload FROM events WHERE scope=? AND mode=? AND name=? "
                        "AND version=? AND sample=? ORDER BY revision",
                        (
                            event.context.scope,
                            event.context.mode,
                            event.name,
                            event.version,
                            event.sample,
                        ),
                    )
                )
                retry = False
                for saved in previous:
                    if saved.revision == event.revision:
                        if saved != event:
                            raise ValueError("telemetry revision reused with different bytes")
                        retry = True
                    elif (
                        (saved.context, saved.at, saved.units)
                        != (event.context, event.at, event.units)
                        or (
                            saved.revision < event.revision
                            and saved.recorded_at > event.recorded_at
                        )
                        or (
                            saved.revision > event.revision
                            and saved.recorded_at < event.recorded_at
                        )
                    ):
                        raise ValueError(
                            "telemetry revision changed sample identity or regressed clocks"
                        )
                if retry:
                    continue
                connection.execute(
                    "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.context.scope,
                        event.context.mode,
                        event.name,
                        event.version,
                        event.sample,
                        event.revision,
                        event.at.isoformat(timespec="microseconds"),
                        event.available_at.isoformat(timespec="microseconds"),
                        event.recorded_at.isoformat(timespec="microseconds"),
                        self.codec.encode_json(event),
                    ),
                )
                inserted += 1
            count = cast(
                tuple[object, ...] | None,
                connection.execute("SELECT COUNT(*) FROM events").fetchone(),
            )
            if count is None or type(count[0]) is not int or count[0] > self.max_events:
                raise ValueError("telemetry capacity exhausted; explicit retention required")
            return inserted

    def query(self, query: MonitoringQuery) -> tuple[MonitoringEvent, ...]:
        """Read latest known revisions, with a hard result bound and no hidden truncation."""
        query.__post_init__()
        if not self.path.exists():
            return ()
        with closing(
            sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=0.05)
        ) as connection:
            connection.execute("BEGIN")
            floor = self._floor(connection)
            if floor is not None and query.start < floor:
                raise ValueError("monitoring query predates retained history")
            rows = self._query_rows(
                connection.execute(
                    "SELECT payload FROM (SELECT payload, at, name, sample, "
                    "ROW_NUMBER() OVER (PARTITION BY name, version, sample "
                    "ORDER BY revision DESC) rank "
                    "FROM events WHERE scope=? AND mode=? AND at>=? AND at<? "
                    "AND available<=? AND recorded<=?) WHERE rank=1 "
                    "ORDER BY at, name, sample LIMIT ?",
                    (
                        query.scope,
                        query.mode,
                        query.start.isoformat(timespec="microseconds"),
                        query.end.isoformat(timespec="microseconds"),
                        query.as_of.isoformat(timespec="microseconds"),
                        query.as_of.isoformat(timespec="microseconds"),
                        query.limit + 1,
                    ),
                )
            )
        if len(rows) > query.limit:
            raise ValueError("monitoring query exceeds its explicit result limit")
        return rows

    def prune(self, before: datetime) -> int:
        """Remove complete samples before a UTC floor; retained dashboards are independent.

        The caller explicitly chooses retention. This operation cannot erase an
        account/order journal, and never silently reinterprets expired queries.
        """
        MonitoringEvent._require_utc(before, field_name="telemetry retention")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            floor = self._floor(connection)
            if floor is not None and before < floor:
                raise ValueError("telemetry retention cannot move backwards")
            result = connection.execute(
                "DELETE FROM events WHERE at<?", (before.isoformat(timespec="microseconds"),)
            )
            connection.execute(
                "UPDATE metadata SET floor=?", (before.isoformat(timespec="microseconds"),)
            )
            return result.rowcount

    def _connect(self) -> sqlite3.Connection:
        """Create a monitoring-only journal with a fixed compatible storage schema."""
        connection = sqlite3.connect(self.path, timeout=0.05)
        try:
            tables = cast(
                list[tuple[object, ...]],
                connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
            )
            if tables and {row[0] for row in tables} != {"metadata", "events"}:
                raise ValueError("selected file is not a telemetry journal")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS metadata (version TEXT NOT NULL, floor TEXT)"
            )
            existing = cast(
                tuple[object, ...] | None, connection.execute("SELECT 1 FROM metadata").fetchone()
            )
            if existing is None:
                connection.execute("INSERT INTO metadata VALUES ('telemetry-store-v1', NULL)")
            self._floor(connection)
            connection.execute(
                "CREATE TABLE IF NOT EXISTS events (scope TEXT, mode TEXT, name TEXT, "
                "version TEXT, sample TEXT, revision INTEGER, at TEXT, available TEXT, "
                "recorded TEXT, payload BLOB, "
                "PRIMARY KEY(scope, mode, name, version, sample, revision))"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS event_time ON events(scope, mode, at)")
            connection.commit()
            return connection
        except sqlite3.Error, TypeError, ValueError:
            connection.close()
            raise

    def _rows(self, cursor: sqlite3.Cursor) -> tuple[MonitoringEvent, ...]:
        """Narrow database values before decoding strict monitoring records."""
        rows = cast(list[tuple[object, ...]], cursor.fetchall())
        result: list[MonitoringEvent] = []
        for row in rows:
            if len(row) != 1 or type(row[0]) is not bytes:
                raise ValueError("invalid monitoring payload")
            result.append(self.codec.decode_json(row[0], MonitoringEvent))
        return tuple(result)

    def _query_rows(self, cursor: sqlite3.Cursor) -> tuple[MonitoringEvent, ...]:
        """Reuse at most 10,000 exact payloads while checking every returned immutable event.

        The SQL snapshot still selects current causal revisions and the retention
        floor on every query. A changed database payload or a force-mutated public
        object is decoded again through the strict wire boundary.
        """
        rows = cast(list[tuple[object, ...]], cursor.fetchall())
        result: list[MonitoringEvent] = []
        for row in rows:
            if len(row) != 1 or type(row[0]) is not bytes:
                raise ValueError("invalid monitoring payload")
            payload = row[0]
            event = self._query_payloads.get(payload)
            if event is None or self.codec.encode_json(event) != payload:
                event = self.codec.decode_json(payload, MonitoringEvent)
                self._query_payloads[payload] = event
            else:
                event.__post_init__()
                self._query_payloads.move_to_end(payload)
            result.append(event)
            if len(self._query_payloads) > 10_000:
                self._query_payloads.popitem(last=False)
        return tuple(result)

    @staticmethod
    def _floor(connection: sqlite3.Connection) -> datetime | None:
        """Validate metadata and reject unknown or malformed storage versions."""
        rows = cast(
            list[tuple[object, ...]],
            connection.execute("SELECT version, floor FROM metadata").fetchall(),
        )
        if len(rows) != 1 or len(rows[0]) != 2 or rows[0][0] != "telemetry-store-v1":
            raise ValueError("unsupported telemetry store schema")
        value = rows[0][1]
        if value is None:
            return None
        if type(value) is not str:
            raise ValueError("invalid telemetry retention floor")
        result = datetime.fromisoformat(value)
        MonitoringEvent._require_utc(result, field_name="telemetry retention")
        return result
