"""Prove causal monitoring, exact diagnostics and visible bounded telemetry loss."""

from __future__ import annotations

# standard library imports
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import cast

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from financial_units import ExactRatio
from serialization import DomainCodec
from telemetry import (
    DelayedLabelError,
    MetricInput,
    MetricRegistry,
    MetricSpec,
    MonitoringEvent,
    MonitoringIdentity,
    MonitoringQuery,
    SeriesMetric,
    TelemetryStore,
)


class MonitoringFixture:
    """Author a small independent exact workload with separate knowledge clocks."""

    at = datetime(2026, 9, 26, tzinfo=UTC)

    @classmethod
    def event(
        cls,
        sample: str = "one",
        *,
        name: str = "prediction",
        value: Fraction | None = Fraction(2),
        seconds: int = 0,
        available: int = 0,
        recorded: int = 0,
        revision: int = 0,
    ) -> MonitoringEvent:
        """Retain authored source timing independently of diagnostic evaluation time."""
        return MonitoringEvent(
            context=MonitoringIdentity(scope="strategy:one", mode="paper", model="model-a"),
            name=name,
            version="v1",
            sample=sample,
            at=cls.at + timedelta(seconds=seconds),
            available_at=cls.at + timedelta(seconds=available),
            recorded_at=cls.at + timedelta(seconds=recorded),
            units="return",
            value=None if value is None else ExactRatio.from_fraction(value),
            missing_reason="source unavailable" if value is None else None,
            revision=revision,
        )

    @classmethod
    def query(cls, cutoff: int = 10) -> MonitoringQuery:
        """Select the prediction window using an explicit later knowledge cutoff."""
        return MonitoringQuery(
            scope="strategy:one",
            mode="paper",
            start=cls.at,
            end=cls.at + timedelta(seconds=5),
            as_of=cls.at + timedelta(seconds=cutoff),
        )

    @staticmethod
    def metric() -> MetricSpec:
        """Select exact mean aggregation with no imputation and a 30-second age budget."""
        return MetricSpec(
            name="mean-prediction",
            version="v1",
            implementation_sha256="a" * 64,
            inputs=(MetricInput(name="prediction", version="v1", units="return"),),
            units="return",
            modes=("paper", "research"),
            aggregation="mean",
            missingness="propagate",
            stale_after_seconds=30,
        )


class TestTelemetryStore:
    """Exercise committed facts, query availability, retention and unsafe retries."""

    def test_query_payload_reuse_checks_database_and_public_mutation(self, tmp_path: Path) -> None:
        """Warm reads still admit another writer's revision and recover exact retained bytes."""
        path = tmp_path / "telemetry.sqlite3"
        store = TelemetryStore(path)
        original = MonitoringFixture.event(value=Fraction(2))
        assert store.append((original,)) == 1
        selected = store.query(MonitoringFixture.query())[0]
        force_setattr(selected, "value", ExactRatio(numerator="99", denominator="1"))
        assert store.query(MonitoringFixture.query()) == (original,)
        correction = MonitoringFixture.event(
            value=Fraction(7), available=12, recorded=20, revision=1
        )
        assert TelemetryStore(path).append((correction,)) == 1
        assert store.query(MonitoringFixture.query(19)) == (original,)
        assert store.query(MonitoringFixture.query(20)) == (correction,)
        assert store.prune(MonitoringFixture.at + timedelta(seconds=1)) == 2
        with pytest.raises(ValueError, match="predates retained history"):
            store.query(MonitoringFixture.query())

    def test_revisions_have_independent_knowledge_and_receipt_cutoffs(self, tmp_path: Path) -> None:
        """A source correction cannot revise an earlier retained diagnostic."""
        store = TelemetryStore(tmp_path / "telemetry.sqlite")
        first = MonitoringFixture.event()
        correction = MonitoringFixture.event(
            value=Fraction(7), available=12, recorded=20, revision=1
        )
        assert store.append((first, correction)) == 2
        assert store.append((first, correction)) == 0
        assert store.query(MonitoringFixture.query(15)) == (first,)
        assert TelemetryStore(store.path).query(MonitoringFixture.query(20)) == (correction,)
        assert (
            DomainCodec().decode_json(DomainCodec().encode_json(correction), MonitoringEvent)
            == correction
        )

    def test_revision_conflict_rolls_back_the_whole_batch(self, tmp_path: Path) -> None:
        """Changed retries cannot append a preceding valid record from the same batch."""
        store = TelemetryStore(tmp_path / "telemetry.sqlite")
        first = MonitoringFixture.event()
        store.append((first,))
        with pytest.raises(ValueError, match="reused with different bytes"):
            store.append(
                (
                    MonitoringFixture.event("two"),
                    replace(first, value=ExactRatio(numerator="9", denominator="1")),
                )
            )
        assert store.query(MonitoringFixture.query()) == (first,)

    def test_revisions_cannot_change_units_context_or_regress_time(self, tmp_path: Path) -> None:
        """Revision number does not authorize relabeling source facts or knowledge."""
        store = TelemetryStore(tmp_path / "telemetry.sqlite")
        first = MonitoringFixture.event(available=5, recorded=8)
        store.append((first,))
        for revised in (
            replace(first, units="USD", revision=1),
            replace(first, context=replace(first.context, model="different"), revision=1),
            replace(first, recorded_at=MonitoringFixture.at + timedelta(seconds=6), revision=1),
        ):
            with pytest.raises(ValueError, match="changed sample identity or regressed clocks"):
                store.append((revised,))

    def test_late_recovered_source_availability_preserves_receipt_cutoff(
        self, tmp_path: Path
    ) -> None:
        """A recovered source label cannot revise a view from before its receipt."""
        store = TelemetryStore(tmp_path / "telemetry.sqlite")
        pending = MonitoringFixture.event(value=None, available=8, recorded=8)
        recovered = MonitoringFixture.event(value=Fraction(3), available=5, recorded=12, revision=1)
        store.append((pending, recovered))
        assert store.query(MonitoringFixture.query(10)) == (pending,)
        assert store.query(MonitoringFixture.query(12)) == (recovered,)

    def test_capacity_and_query_bounds_do_not_truncate(self, tmp_path: Path) -> None:
        """Finite capacity fails atomically; readers never turn a truncated scan into a metric."""
        store = TelemetryStore(tmp_path / "telemetry.sqlite", max_events=2)
        first, second = MonitoringFixture.event(), MonitoringFixture.event("two")
        store.append((first, second))
        with pytest.raises(ValueError, match="capacity exhausted"):
            store.append((MonitoringFixture.event("three"),))
        with pytest.raises(ValueError, match="result limit"):
            store.query(replace(MonitoringFixture.query(), limit=1))
        assert len(store.query(MonitoringFixture.query())) == 2

    def test_stored_event_count_tracks_every_insert_retry_and_prune(self, tmp_path: Path) -> None:
        """Capacity reads a trigger-maintained count equal to the rows actually retained."""
        path = tmp_path / "telemetry.sqlite"
        store, other = TelemetryStore(path, max_events=3), TelemetryStore(path, max_events=3)
        first = MonitoringFixture.event()
        later = MonitoringFixture.event("two", seconds=2, available=2, recorded=2)
        assert store.append((first,)) == 1
        assert other.append((first, later)) == 1
        assert self._counts(path) == (2, 2)
        assert store.prune(MonitoringFixture.at + timedelta(seconds=1)) == 1
        assert self._counts(path) == (1, 1)
        third = MonitoringFixture.event("three", seconds=3, available=3, recorded=3)
        fourth = MonitoringFixture.event("four", seconds=4, available=4, recorded=4)
        assert other.append((third, fourth)) == 2
        with pytest.raises(ValueError, match="capacity exhausted"):
            store.append((MonitoringFixture.event("five", seconds=4, available=4, recorded=4),))
        assert self._counts(path) == (3, 3)

    def test_store_without_a_stored_event_count_is_refused(self, tmp_path: Path) -> None:
        """A telemetry file in the earlier layout is refused, never counted or extended."""
        path = tmp_path / "telemetry.sqlite"
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE metadata (version TEXT NOT NULL, floor TEXT)")
            connection.execute("INSERT INTO metadata VALUES ('telemetry-store', NULL)")
            connection.execute(
                "CREATE TABLE events (scope TEXT, mode TEXT, name TEXT, "
                "version TEXT, sample TEXT, revision INTEGER, at TEXT, available TEXT, "
                "recorded TEXT, payload BLOB, "
                "PRIMARY KEY(scope, mode, name, version, sample, revision))"
            )
            connection.commit()
        before = path.read_bytes()
        with pytest.raises(ValueError, match="unsupported telemetry store schema"):
            TelemetryStore(path).append((MonitoringFixture.event(),))
        with pytest.raises(ValueError, match="unsupported telemetry store schema"):
            TelemetryStore(path).query(MonitoringFixture.query())
        assert path.read_bytes() == before

    def test_store_whose_count_trigger_changed_under_its_name_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Matching table and trigger names are not enough; their definitions must match."""
        path = tmp_path / "telemetry.sqlite"
        TelemetryStore(path).append((MonitoringFixture.event(),))
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("DROP TRIGGER event_count_insert")
            connection.execute(
                "CREATE TRIGGER event_count_insert AFTER INSERT ON events "
                "BEGIN UPDATE metadata SET event_count = event_count + 2; END"
            )
            connection.commit()
        with pytest.raises(ValueError, match="unsupported telemetry store schema"):
            TelemetryStore(path).query(MonitoringFixture.query())

    @pytest.mark.performance
    def test_append_cost_does_not_grow_with_retained_rows(self, tmp_path: Path) -> None:
        """Capacity enforcement reads a stored count instead of counting every row."""
        medians: list[float] = []
        for rows in (20_000, 400_000):
            path = tmp_path / f"telemetry-{rows}.sqlite"
            store = TelemetryStore(path)
            store.append((MonitoringFixture.event("seed"),))
            with closing(sqlite3.connect(path)) as connection:
                connection.executemany(
                    "INSERT INTO events VALUES ('filler', 'paper', 'n', 'v1', ?, 0, "
                    "'2020-01-01T00:00:00.000000+00:00', "
                    "'2020-01-01T00:00:00.000000+00:00', "
                    "'2020-01-01T00:00:00.000000+00:00', x'00')",
                    ((str(index),) for index in range(rows - 1)),
                )
                connection.commit()
            samples: list[float] = []
            for index in range(9):
                event = MonitoringFixture.event(f"sample-{index}")
                started = time.perf_counter()
                assert store.append((event,)) == 1
                samples.append(time.perf_counter() - started)
            medians.append(sorted(samples)[4])
        print(f"one-event append at 20,000/400,000 rows: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # COUNT(*) on every append grew linearly with the retained rows.
        assert medians[1] < 1.5 * medians[0]

    @staticmethod
    def _counts(path: Path) -> tuple[object, object]:
        """Return the stored event count and the actual row count."""
        with closing(sqlite3.connect(path)) as connection:
            stored = cast(
                tuple[object], connection.execute("SELECT event_count FROM metadata").fetchone()
            )
            actual = cast(
                tuple[object], connection.execute("SELECT COUNT(*) FROM events").fetchone()
            )
        return stored[0], actual[0]

    def test_retention_floor_survives_restart_and_rejects_expired_queries(
        self, tmp_path: Path
    ) -> None:
        """Expired observations cannot be confused with a healthy empty window."""
        store = TelemetryStore(tmp_path / "telemetry.sqlite")
        first = MonitoringFixture.event()
        later = MonitoringFixture.event("two", seconds=2, available=2, recorded=2)
        store.append((first, later))
        cutoff = MonitoringFixture.at + timedelta(seconds=1)
        assert store.prune(cutoff) == 1
        reopened = TelemetryStore(store.path)
        with pytest.raises(ValueError, match="predates retained history"):
            reopened.query(MonitoringFixture.query())
        with pytest.raises(ValueError, match="predates retained history"):
            reopened.append((first,))
        assert reopened.query(replace(MonitoringFixture.query(), start=cutoff)) == (later,)

    def test_foreign_account_database_is_never_modified(self, tmp_path: Path) -> None:
        """A mistaken monitoring path cannot add telemetry tables to authoritative account state."""
        path = tmp_path / "account.sqlite"
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE accounts (value TEXT)")
            connection.commit()
        before = path.read_bytes()
        with pytest.raises(ValueError, match="not a telemetry journal"):
            TelemetryStore(path).append((MonitoringFixture.event(),))
        assert path.read_bytes() == before

    def test_scope_mode_and_window_are_independent(self, tmp_path: Path) -> None:
        """Other strategies, operating modes and end-boundary samples cannot leak into a query."""
        first = MonitoringFixture.event()
        store = TelemetryStore(tmp_path / "telemetry.sqlite")
        store.append(
            (
                first,
                replace(first, context=replace(first.context, scope="strategy:two")),
                replace(first, context=replace(first.context, mode="research")),
                MonitoringFixture.event("end", seconds=5, available=5, recorded=5),
            )
        )
        assert store.query(MonitoringFixture.query()) == (first,)


class TestMonitoringMetrics:
    """Keep exact expected values independent of the implementation's aggregation paths."""

    def test_exact_mean_missingness_staleness_and_applicability(self) -> None:
        """Two unequal exact values yield 8/3; no missing/stale value becomes zero."""
        spec = MonitoringFixture.metric()
        registry = MetricRegistry((SeriesMetric(spec),))
        rows = (
            MonitoringFixture.event(value=Fraction(7, 3)),
            MonitoringFixture.event("two", value=Fraction(3), seconds=1, available=1, recorded=1),
        )
        result = registry.evaluate(spec.identity, MonitoringFixture.query(), rows)
        assert result.value == ExactRatio(numerator="8", denominator="3")
        assert result.status == "ok"
        missing = registry.evaluate(
            spec.identity, MonitoringFixture.query(), (MonitoringFixture.event(value=None),)
        )
        assert missing.value is None and missing.status == "missing"
        stale = registry.evaluate(spec.identity, MonitoringFixture.query(60), rows)
        assert stale.value is None and stale.status == "stale"
        other = registry.evaluate(
            spec.identity, replace(MonitoringFixture.query(), mode="data"), ()
        )
        assert other.status == "inapplicable"

    def test_unit_future_scope_and_duplicate_rejections(self) -> None:
        """The public evaluator refuses a caller's malformed query result."""
        spec = MonitoringFixture.metric()
        registry = MetricRegistry((SeriesMetric(spec),))
        first = MonitoringFixture.event()
        for rows in (
            (replace(first, units="USD"),),
            (replace(first, context=replace(first.context, scope="another")),),
            (MonitoringFixture.event(available=20, recorded=20),),
            (first, first),
        ):
            with pytest.raises(ValueError):
                registry.evaluate(spec.identity, MonitoringFixture.query(), rows)
        with pytest.raises(ValueError, match="unregistered"):
            registry.evaluate("b" * 64, MonitoringFixture.query(), (first,))

    def test_semantic_versions_coexist_without_implicit_substitution(self) -> None:
        """A pinned v1 metric ignores v2 and remains missing if v1 was never observed."""
        spec = MonitoringFixture.metric()
        registry = MetricRegistry((SeriesMetric(spec),))
        first = MonitoringFixture.event()
        newer = replace(first, version="v2", value=ExactRatio(numerator="99", denominator="1"))
        result = registry.evaluate(spec.identity, MonitoringFixture.query(), (first, newer))
        assert result.value == first.value and result.input_ids == (first.identity,)
        missing = registry.evaluate(spec.identity, MonitoringFixture.query(), (newer,))
        assert missing.status == "missing" and missing.value is None

    def test_last_uses_receipt_order_when_event_clocks_tie(self) -> None:
        """Sample identifier spelling does not override a later observed fact."""
        spec = replace(MonitoringFixture.metric(), aggregation="last")
        registry = MetricRegistry((SeriesMetric(spec),))
        older = MonitoringFixture.event("z", value=Fraction(2), available=1, recorded=1)
        later = MonitoringFixture.event("a", value=Fraction(9), available=8, recorded=8)
        result = registry.evaluate(spec.identity, MonitoringFixture.query(), (older, later))
        assert result.value == ExactRatio(numerator="9", denominator="1")

    def test_delayed_labels_and_corrections_never_leak_backwards(self, tmp_path: Path) -> None:
        """Pending points remain gaps; available errors are 1/4 and later 9/4 exactly."""
        store = TelemetryStore(tmp_path / "telemetry.sqlite")
        prediction = MonitoringFixture.event(value=Fraction(1, 2))
        label = MonitoringFixture.event(
            name="outcome", value=Fraction(1), available=15, recorded=18
        )
        revised = replace(
            label,
            value=ExactRatio(numerator="2", denominator="1"),
            revision=1,
            available_at=MonitoringFixture.at + timedelta(seconds=25),
            recorded_at=MonitoringFixture.at + timedelta(seconds=25),
        )
        store.append((prediction, label, revised))
        spec = MetricSpec(
            name="prediction-error",
            version="v1",
            implementation_sha256="b" * 64,
            inputs=(
                MetricInput(name="prediction", version="v1", units="return"),
                MetricInput(name="outcome", version="v1", units="return"),
            ),
            units="(return)^2",
            modes=("research", "paper"),
            aggregation="custom",
            missingness="pending labels remain gaps; mean uses observed pairs",
        )
        registry = MetricRegistry((DelayedLabelError(spec),))
        early = MonitoringFixture.query(16)
        pending = registry.evaluate(spec.identity, early, store.query(early))
        assert pending.value is None and pending.points[0].missing_reason == "pending label"
        for cutoff, expected in ((18, "1"), (25, "9")):
            query = MonitoringFixture.query(cutoff)
            result = registry.evaluate(spec.identity, query, store.query(query))
            assert result.value == ExactRatio(numerator=expected, denominator="4")
        assert registry.evaluate(spec.identity, early, store.query(early)) == pending

    def test_ambiguous_constructor_clocks_and_missingness_fail(self) -> None:
        """Wire decode and direct construction enforce the same temporal and numeric boundary."""
        first = MonitoringFixture.event()
        with pytest.raises(ValueError, match="causally ordered"):
            replace(first, recorded_at=first.at - timedelta(seconds=1))
        with pytest.raises(ValueError, match="exact ratio"):
            replace(first, missing_reason="contradicts present value")
        with pytest.raises(ValueError, match="Invalid enum value"):
            DomainCodec().decode_json(
                DomainCodec()
                .encode_json(first)
                .replace(b"monitoring-event", b"monitoring-event-unsupported"),
                MonitoringEvent,
            )

    def test_text_admission_preserves_control_and_utf8_boundaries(self) -> None:
        """Reject original control bytes while keeping exact Unicode and byte-limit semantics."""
        for character in range(32):
            with pytest.raises(ValueError, match="bounded and nonempty"):
                MonitoringIdentity(scope=f"account{chr(character)}one", mode="paper")
        for scope in (" ", "é" * 129):
            with pytest.raises(ValueError, match="bounded and nonempty"):
                MonitoringIdentity(scope=scope, mode="paper")
        for scope in ("é" * 128, "scope\u007f", "市场:账户", "with space"):
            assert MonitoringIdentity(scope=scope, mode="paper").scope == scope

    def test_grouped_evaluation_preserves_version_units_and_full_query_cutoffs(self) -> None:
        """Grouping cannot discard an unrelated future fact or substitute a newer version."""
        spec = MonitoringFixture.metric()
        registry = MetricRegistry((SeriesMetric(spec),))
        first = MonitoringFixture.event()
        newer = replace(first, version="v2", value=ExactRatio(numerator="99", denominator="1"))
        query = MonitoringFixture.query()
        direct = registry.evaluate(spec.identity, query, (first, newer))
        assert registry.evaluate_many((spec.identity,), query, (first, newer)) == (direct,)
        for invalid in (
            replace(
                first,
                name="unselected",
                available_at=MonitoringFixture.at + timedelta(seconds=20),
                recorded_at=MonitoringFixture.at + timedelta(seconds=20),
            ),
            replace(first, units="USD"),
            replace(first, context=replace(first.context, scope="different")),
        ):
            with pytest.raises(ValueError):
                registry.evaluate_many((spec.identity,), query, (invalid,))

    def test_grouped_evaluation_keeps_revision_and_nested_ratio_admission(self) -> None:
        """Selected duplicate revisions and an unselected force-mutated value remain invalid."""
        spec = MonitoringFixture.metric()
        registry = MetricRegistry((SeriesMetric(spec),))
        first = MonitoringFixture.event()
        with pytest.raises(ValueError, match="selected revision"):
            registry.evaluate_many(
                (spec.identity,), MonitoringFixture.query(), (first, replace(first, revision=1))
            )
        unrelated = MonitoringFixture.event(name="unselected")
        assert unrelated.value is not None
        force_setattr(unrelated.value, "numerator", "invalid")
        with pytest.raises(ValueError):
            registry.evaluate_many((spec.identity,), MonitoringFixture.query(), (unrelated,))
