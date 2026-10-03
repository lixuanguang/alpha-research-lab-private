"""Check exact integrated feature clocks, quality, schedules and evidence counts."""

from __future__ import annotations

# standard library imports
import multiprocessing
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from multiprocessing.connection import Connection
from pathlib import Path
from types import TracebackType
from typing import cast
from uuid import uuid4

# third party library imports
import msgspec
import pytest
from capacity_deliveries import _IndexedSharedDelivery
from capacity_feature_results import FeatureCohortResults, _Interval, _Publication
from capacity_features import CapacityFeatureObserver, _FeatureSource, _PublicationLock
from capacity_inputs import CapacityNativeFixture, CapacityWorkload
from capacity_reads import _RetainedBookIndex, _SourceIndex
from msgspec.structs import replace

# project library imports
from market_data.adapters.sources import BookAdapters
from market_data.books import BookProjection, CaptureReplay
from market_data.contracts import CaptureRecord, CaptureRequest
from market_data.storage import CaptureJournal
from research.features import FeatureStoreDefinition, VersionedFeatureStore
from runtime import LiveBookDelivery, SharedBookDelivery
from serialization import DomainCodec


class _SignalledLock:
    """Expose an attempted reader acquisition while retaining an actual mutex."""

    def __init__(self) -> None:
        """Retain synchronization independently of the feature-store operation."""
        self.lock = threading.Lock()
        self.waiting = threading.Event()

    def __enter__(self) -> None:
        """Signal before blocking so publication can advance deterministically."""
        self.waiting.set()
        self.lock.acquire()

    def __exit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release the same mutex used by the actual reader."""
        self.lock.release()


class _SignalledPublicationLock(_PublicationLock):
    """Signal before blocking on the cross-process publication lock."""

    def __init__(self, path: Path) -> None:
        """Bind the real lock file."""
        super().__init__(path)
        self.waiting = threading.Event()

    def __enter__(self) -> None:
        """Signal, then wait for the publisher in the other process."""
        self.waiting.set()
        super().__enter__()


def _publish_while_holding(
    lock_path: str,
    store_path: str,
    definition: FeatureStoreDefinition,
    entity: str,
    control: Connection[object, object],
) -> None:
    """Hold a source's lock in another process, activate a version on request, release."""
    store = VersionedFeatureStore.open(Path(store_path))
    with _PublicationLock(Path(lock_path)):
        control.send("held")
        if control.recv() != "publish":
            return
        published_at = datetime.now(UTC)
        previous = store.active_version(definition)
        store.materialize(definition, "cross-process", published_at, (entity,))
        store.activate_if_current(definition, "cross-process", expected_version=previous)
    control.send(published_at)
    control.close()


class TestCapacityFeatures:
    """Exercise the real local feature store over four native source protocols."""

    def _observer(self, tmp_path: Path) -> CapacityFeatureObserver:
        """Prepare a small admitted native sample with distinct currencies and original clocks."""
        base = datetime.now(UTC) - timedelta(milliseconds=100)
        workload = CapacityWorkload(opening_at=base, socket_root=Path("/private/tmp/feature-tests"))
        config = workload.service_configuration()
        codec = DomainCodec()
        sources: list[_SourceIndex] = []
        self._journals: dict[str, CaptureJournal] = {}
        probes = tmp_path / "measurements"
        for source in config.sources:
            request = CaptureRequest(
                config=source.capture,
                recording_id=str(uuid4()),
                implementation_identity="a" * 64,
            )
            capture_root = tmp_path / "capture" / source.name
            journal = CaptureJournal(capture_root, request)
            journal.start()
            self._journals[source.name] = journal
            replay = CaptureReplay(source.capture, book_factory=BookAdapters.create)
            fixture = CapacityNativeFixture(source)
            origin = _RetainedBookIndex._unix_ns(base)
            records = [CaptureRecord(kind="session", epoch=0, received_ns=origin)]
            for slot in range(4):
                fixture.index = slot + 1
                records.append(
                    CaptureRecord(
                        kind="frame",
                        epoch=0,
                        received_ns=origin + (slot + 1) * 1_000_000,
                        raw=fixture._native_frame(origin // 1_000_000 + slot + 1),
                    )
                )
            deliveries = tmp_path / f"{source.name}.jsonl"
            probe_path = probes / "run" / source.name / f"{request.recording_id}.capture.jsonl"
            probe_path.parent.mkdir(parents=True)
            durable_origin = time.monotonic_ns() - 100_000_000
            with deliveries.open("wb") as output, probe_path.open("wb") as timings:
                for position, record in enumerate(records):
                    journal.append(record)
                    outcome = replay.apply(record)
                    book = BookProjection.capture(position, record, outcome, replay)
                    output.write(
                        codec.encode_json(
                            SharedBookDelivery(
                                source=LiveBookDelivery(
                                    record=record,
                                    book=book,
                                    available_at=base + timedelta(milliseconds=position + 1),
                                ),
                                inputs=(),
                                coordinated_at=None,
                            )
                        )
                        + b"\n"
                    )
                    timings.write(
                        codec.encode_json(
                            {
                                "schema_version": "runtime-measurement",
                                "kind": "capture_boundary",
                                "cursor": position + 1,
                                "durable_ns": durable_origin + position * 1_000_000,
                            }
                        )
                        + b"\n"
                    )
            sources.append(_SourceIndex(source.name, request, capture_root, deliveries, 10_000))
        index = _RetainedBookIndex(config, tuple(sources))
        assert index.poll() == 20
        return CapacityFeatureObserver(
            tmp_path / "features", config, index, measurement_root=probes
        )

    def _append_native(self, source: _SourceIndex, record: CaptureRecord) -> None:
        """Append a real adapter projection after the observer's previously indexed prefix."""
        codec = DomainCodec()
        replay = CaptureReplay(source.request.config, book_factory=BookAdapters.create)
        for _, encoded, _ in source.history:
            replay.apply(codec.decode_json(encoded, SharedBookDelivery).source.record)
        outcome = replay.apply(record)
        row = BookProjection.capture(source.deliveries, record, outcome, replay)
        self._journals[source.name].append(record)
        with source.delivery_path.open("ab") as stream:
            stream.write(
                codec.encode_json(
                    SharedBookDelivery(
                        source=LiveBookDelivery(
                            record=record,
                            book=row,
                            available_at=datetime.now(UTC) - timedelta(microseconds=1),
                        ),
                        inputs=(),
                        coordinated_at=None,
                    )
                )
                + b"\n"
            )

    def test_sequenced_unchanged_heartbeat_keeps_original_native_prices_and_age(
        self, tmp_path: Path
    ) -> None:
        """Reuse causal native admission when only the Bitfinex sequence changed."""
        observer = self._observer(tmp_path)
        observer.prepare()
        source = observer.sources["bitfinex-eth-book"]
        original = observer.index.registry.lookup(
            source.source.key, cutoff_ns=observer.index._unix_ns(datetime.now(UTC))
        ).quote
        assert original is not None and original.sequence == 2
        assert original.received_ns is not None and original.available_ns is not None
        self._append_native(
            source.source,
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=observer.index._unix_ns(datetime.now(UTC) - timedelta(milliseconds=2)),
                raw=b'[7,"hb",3]',
            ),
        )
        observer.index.poll()
        at = datetime.now(UTC)
        generic = observer.index.registry.lookup(
            source.source.key, cutoff_ns=observer.index._unix_ns(at)
        )
        assert generic.quote is None and generic.reason == "unavailable"
        causal = source.lookup(observer.index, at)
        assert causal.quote == original
        assert causal.boundary is not None and causal.boundary.sequence == 3
        inputs = source.inputs(causal, at)
        assert all(row.value is not None for row in inputs.observations)
        assert all(
            row.event_at == source.utc_from_ns(original.received_ns)
            and row.available_at == source.utc_from_ns(original.available_ns)
            for row in inputs.observations
        )
        observer.stop_ns = time.monotonic_ns() + 1_000_000_000
        observer.publish(source, datetime.now(UTC), slot=0, due_ns=time.monotonic_ns())
        assert observer._rows("materialization-samples.jsonl")[-1]["quality"] == "ready"
        stale = source.lookup(observer.index, datetime.now(UTC) + timedelta(minutes=1))
        assert stale.quote is None and "stale" in stale.reason

    def test_publication_refreshes_retained_prefix_and_a_native_gap_stays_missing(
        self, tmp_path: Path
    ) -> None:
        """Admit a later actual update before publishing, then preserve its explicit gap."""
        observer = self._observer(tmp_path)
        observer.prepare()
        source = observer.sources["bitfinex-eth-book"]
        old_cursor = source.source.deliveries
        self._append_native(
            source.source,
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=observer.index._unix_ns(datetime.now(UTC) - timedelta(milliseconds=2)),
                raw=b'[7,[1,"99",5],3]',
            ),
        )
        assert source.source.deliveries == old_cursor
        observer.stop_ns = time.monotonic_ns() + 1_000_000_000
        observer.publish(source, datetime.now(UTC), slot=0, due_ns=time.monotonic_ns())
        published = observer._rows("materialization-samples.jsonl")[-1]
        assert published["quality"] == "ready" and published["native_position"] == old_cursor
        self._append_native(
            source.source,
            CaptureRecord(
                kind="gap",
                epoch=0,
                received_ns=observer.index._unix_ns(datetime.now(UTC) - timedelta(milliseconds=2)),
                reason="disconnect_unknown_loss",
            ),
        )
        observer.publish(source, datetime.now(UTC), slot=1, due_ns=time.monotonic_ns())
        missing = observer._rows("materialization-samples.jsonl")[-1]
        assert missing["quality"] == "missing" and missing["quote"] is None

    def test_causal_source_cannot_override_original_source_clock_protection(
        self, tmp_path: Path
    ) -> None:
        """A receipt-based feature still refuses an original OKX source clock in the future."""
        observer = self._observer(tmp_path)
        observer.prepare()
        source = observer.sources["okx-btc-book"]
        original = observer.index.registry.lookup(
            source.source.key, cutoff_ns=observer.index._unix_ns(datetime.now(UTC))
        ).quote
        assert original is not None and original.sequence is not None
        future = observer.index._unix_ns(datetime.now(UTC) + timedelta(seconds=30)) // 1_000_000
        self._append_native(
            source.source,
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=observer.index._unix_ns(datetime.now(UTC) - timedelta(milliseconds=2)),
                raw=DomainCodec().encode_json(
                    {
                        "arg": {"channel": "books", "instId": source.source.request.config.symbol},
                        "action": "update",
                        "data": [
                            {
                                "bids": [],
                                "asks": [["100.00", "5", "0", "1"]],
                                "ts": str(future),
                                "seqId": original.sequence + 1,
                                "prevSeqId": original.sequence,
                            }
                        ],
                    }
                ),
            ),
        )
        at = datetime.now(UTC)
        observed = source.lookup(observer.index, at)
        assert observed.quote is None and observed.reason == "future_source_time"
        assert all(row.value is None for row in source.inputs(observed, at).observations)

    def test_small_native_sample_materializes_exact_two_value_versions(
        self, tmp_path: Path
    ) -> None:
        """Match independently visible native bid/ask, source lineage and offline/online bytes."""
        observer = self._observer(tmp_path)
        observer.prepare()
        rows = observer._rows("materialization-samples.jsonl")
        assert len(rows) == 4
        for source in observer.sources.values():
            online = source.store.retrieve_online(
                source.definition, source.entity, datetime.now(UTC)
            )
            assert online.status == "ready" and online.materialized_at is not None
            offline = source.store.retrieve_offline(
                source.definition, source.entity, online.materialized_at
            )
            assert online.feature == offline.feature
            feature = online.require_ready()
            assert [
                (value.numerator, value.denominator)
                for value in feature.values
                if value is not None
            ] == [("99", "1"), ("100", "1")]
            expected_units = "USD" if source.source.request.config.venue == "bitfinex" else "USDT"
            assert all(field.units.startswith(expected_units + "/") for field in feature.fields)
            assert feature.event_at < feature.decision_at <= feature.available_at
            assert feature.expires_at - feature.available_at == timedelta(seconds=5)
            assert online.feature is not None
            assert online.feature.source_sha256 == source.source.request.identity
            assert online.feature.source_version == source.source.request.recording_id
        assert all(row["phase"] == "initialization" for row in rows)
        assert all(row["durable_to_available_ns"] is not None for row in rows)

    def test_index_fed_causal_source_matches_retained_redecoding(self, tmp_path: Path) -> None:
        """Deliveries handed over by the index poll give the same lookups as re-decoding."""
        observer = self._observer(tmp_path)
        streamed = _RetainedBookIndex(
            observer.config,
            tuple(
                _SourceIndex(
                    name, source.request, source.capture_root, source.delivery_path, 10_000
                )
                for name, source in observer.index.sources.items()
            ),
        )
        freshness = {source.name: source.freshness_us for source in observer.config.sources}
        (tmp_path / "redecoded").mkdir()
        (tmp_path / "fed").mkdir()
        fed = {
            name: _FeatureSource(source, freshness[name], tmp_path / "fed")
            for name, source in streamed.sources.items()
        }
        for name, feature_source in fed.items():
            streamed.sources[name].delivered = feature_source.accept_delivery
        assert streamed.poll() == 20
        at = datetime.now(UTC)
        for name, source in observer.index.sources.items():
            redecoded = _FeatureSource(source, freshness[name], tmp_path / "redecoded")
            assert fed[name].source_cursor == streamed.sources[name].deliveries == 5
            assert fed[name].lookup(streamed, at) == redecoded.lookup(observer.index, at)
            assert fed[name].source_cursor == redecoded.source_cursor == 5

    def test_retained_deliveries_decode_once_to_the_public_bytes(self, tmp_path: Path) -> None:
        """The validate-once schema keeps every retained envelope byte-identical."""
        observer = self._observer(tmp_path)
        codec = DomainCodec()
        for source in observer.index.sources.values():
            for _, encoded, _ in source.history:
                fast = codec.decode_json(encoded, _IndexedSharedDelivery)
                assert codec.encode_json(fast) == codec.encode_json(
                    codec.decode_json(encoded, SharedBookDelivery)
                )

    @pytest.mark.parametrize("field", ("size", "order_count"))
    def test_corrupted_retained_depth_is_still_refused(self, tmp_path: Path, field: str) -> None:
        """Decoding still validates each native level once, so a bad level stops publication."""
        observer = self._observer(tmp_path)
        source = observer.index.sources["okx-btc-book"]

        def bids(delivery: dict[str, object]) -> list[list[object]]:
            """Reach the encoded book's bid levels."""
            book = cast(dict[str, object], cast(dict[str, object], delivery["source"])["book"])
            return cast(list[list[object]], book["bids"])

        decoded = [
            msgspec.json.decode(encoded, type=dict[str, object]) for _, encoded, _ in source.history
        ]
        position = next(index for index, delivery in enumerate(decoded) if bids(delivery))
        quote, _, length = source.history[position]
        level = cast(dict[str, object], bids(decoded[position])[0][1])
        level[field] = "0" if field == "size" else 0
        source.history[position] = (quote, msgspec.json.encode(decoded[position]), length)
        with pytest.raises(ValueError, match="aggregate levels"):
            observer.prepare()

    def test_future_source_and_stale_source_stay_missing(self, tmp_path: Path) -> None:
        """A future or source-aged quote cannot become a ready feature by projection."""
        observer = self._observer(tmp_path)
        observer.prepare()
        source = next(iter(observer.sources.values()))
        lookup = observer.index.registry.lookup(source.source.key, cutoff_ns=0)
        missing = source.inputs(lookup, datetime.now(UTC))
        assert all(row.value is None for row in missing.observations)
        old = observer.index.registry.lookup(
            source.source.key,
            cutoff_ns=observer.index._unix_ns(datetime.now(UTC) + timedelta(minutes=1)),
        )
        stale = source.inputs(old, datetime.now(UTC) + timedelta(minutes=1))
        assert all(row.value is None for row in stale.observations)
        assert all("stale" in row.reason for row in stale.observations)

    def test_inclusive_ttl_and_missing_future_stale_outcomes(self, tmp_path: Path) -> None:
        """Observe the actual store's distinct refusal outcomes at exact UTC cutoffs."""
        observer = self._observer(tmp_path)
        observer.prepare()
        findings = observer._quality_probes()
        assert not observer.failures
        assert len(findings) == 4
        assert all(
            value
            == {
                "ttl_inclusive": "ready",
                "stale": "stale",
                "missing": "missing",
                "future": "future",
            }
            for value in findings.values()
        )

    def test_new_active_version_is_future_at_a_prepublication_cutoff(self, tmp_path: Path) -> None:
        """A legal concurrent activation explains the former parity assertion failure."""
        observer = self._observer(tmp_path)
        observer.prepare()
        source = next(iter(observer.sources.values()))
        requested_at = datetime.now(UTC)
        published_at = datetime.now(UTC) + timedelta(microseconds=1)
        previous = source.store.active_version(source.definition)
        source.store.materialize(source.definition, "concurrent", published_at, (source.entity,))
        source.store.activate_if_current(source.definition, "concurrent", expected_version=previous)
        online = source.store.retrieve_online(source.definition, source.entity, requested_at)
        assert online.status == "future" and online.feature is None
        assert online.materialized_at == published_at
        offline = source.store.retrieve_offline(source.definition, source.entity, published_at)
        assert offline.status == "ready" and offline.feature is not None

    def test_read_cutoff_waits_for_publication_and_retains_wait_in_latency(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Advance the real store after request arrival while its reader waits on publication."""
        observer = self._observer(tmp_path)
        observer.prepare()
        source = next(iter(observer.sources.values()))
        gate = _SignalledLock()
        monkeypatch.setattr(source, "publication_lock", gate)
        instance = next(
            item
            for item in observer.config.instances
            if item.source == source.source.name and item.instance_id in observer.config.active
        )
        reader = threading.Thread(
            target=observer._read, args=(instance.instance_id, source.source.name), daemon=True
        )
        observer.started_ns = time.monotonic_ns()
        observer.stop_ns = observer.started_ns + 250_000_000
        with gate:
            gate.waiting.clear()
            reader.start()
            assert gate.waiting.wait(2)
            publication_at = datetime.now(UTC)
            previous = source.store.active_version(source.definition)
            source.store.materialize(
                source.definition, "concurrent", publication_at, (source.entity,)
            )
            source.store.activate_if_current(
                source.definition, "concurrent", expected_version=previous
            )
        reader.join(2)
        assert not reader.is_alive()
        rows = observer._rows("retrieval-samples.jsonl")
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "ok" and row["quality"] == "ready" and row["parity"] is True
        assert row["version"] == "concurrent"
        assert str(row["requested_at"]) < publication_at.isoformat().replace("+00:00", "Z")
        assert str(row["at"]) >= publication_at.isoformat().replace("+00:00", "Z")
        assert (
            0
            < observer._integer(row, "publication_wait_ns")
            <= observer._integer(row, "service_ns")
        )

    def test_cross_process_publication_holds_the_reader_cutoff(self, tmp_path: Path) -> None:
        """A publisher in another process makes the reader wait and read its new version."""
        observer = self._observer(tmp_path)
        observer.prepare()
        source = next(iter(observer.sources.values()))
        instance = next(
            item
            for item in observer.config.instances
            if item.source == source.source.name and item.instance_id in observer.config.active
        )
        lock_path = tmp_path / "features" / f"{source.source.name}.publication.lock"
        context = multiprocessing.get_context("spawn")
        parent, child = cast(
            "tuple[Connection[object, object], Connection[object, object]]", context.Pipe()
        )
        publisher = context.Process(
            target=_publish_while_holding,
            args=(
                str(lock_path),
                str(tmp_path / "features" / f"{source.source.name}.sqlite3"),
                source.definition,
                source.entity,
                child,
            ),
            daemon=True,
        )
        publisher.start()
        assert parent.poll(30) and parent.recv() == "held"
        gate = _SignalledPublicationLock(lock_path)
        source.publication_lock = gate
        reader = threading.Thread(
            target=observer._read, args=(instance.instance_id, source.source.name), daemon=True
        )
        observer.started_ns = time.monotonic_ns()
        observer.stop_ns = observer.started_ns + 250_000_000
        reader.start()
        assert gate.waiting.wait(2)
        parent.send("publish")
        assert parent.poll(30)
        publication_at = cast(datetime, parent.recv())
        publisher.join(5)
        reader.join(5)
        assert not reader.is_alive() and publisher.exitcode == 0
        row = observer._rows("retrieval-samples.jsonl")[0]
        assert row["status"] == "ok" and row["quality"] == "ready" and row["parity"] is True
        assert row["version"] == "cross-process"
        assert str(row["requested_at"]) < publication_at.isoformat().replace("+00:00", "Z")
        assert str(row["at"]) >= publication_at.isoformat().replace("+00:00", "Z")
        assert observer._integer(row, "publication_wait_ns") > 0

    def test_one_second_schedule_has_32_reads_and_one_version_per_source(
        self, tmp_path: Path
    ) -> None:
        """Keep scalar counts separate and do not invent tail percentiles for a small sample."""
        observer = self._observer(tmp_path)
        observer.prepare()
        pids = observer.launch()
        assert set(pids) == {
            "materializer",
            *(item.account_id for item in observer.config.accounts),
        }
        assert os.getpid() not in pids.values()
        began = time.monotonic() + 0.5
        observer.start(began, began + 1)
        threading.Event().wait(max(0.0, began + 1 - time.monotonic()))
        summary = observer.finish(began + 3)
        assert summary["status"] == "pass_observed_schedule", summary["failures"]
        assert summary["process_pids"] == pids
        assert all(not process.is_alive() for process, _ in observer.children.values())
        assert summary["observed_retrievals"] == summary["ready_retrievals"] == 32
        assert summary["matched_cutoff_parity"] is True
        timings = cast(dict[str, object], summary["service_latency"])
        assert timings["sample_count"] == 32 and "p99_ns" not in timings
        materializations = cast(dict[str, dict[str, object]], summary["materialization_per_source"])
        assert len(materializations) == 4
        for result in materializations.values():
            assert result["sample_count"] == result["observed_versions"] == 1
            assert result["unit"] == "one_two_value_instrument_version" and "p99_ns" not in result

    def test_unavailable_durable_probe_remains_a_measurement_dependency(
        self, tmp_path: Path
    ) -> None:
        """Missing physical/timing counters do not turn successful runtime work into failure."""
        observer = self._observer(tmp_path)
        observer.measurement_root = None
        observer.prepare()
        source = next(iter(observer.sources.values()))
        observer.stop_ns = time.monotonic_ns() + 1_000_000_000
        observer.publish(source, datetime.now(UTC), slot=0, due_ns=time.monotonic_ns())
        rows = observer._rows("materialization-samples.jsonl")
        assert rows[-1]["quality"] == "ready"
        assert rows[-1]["durable_ns"] is rows[-1]["durable_to_available_ns"] is None
        assert not observer.failures

    def test_partial_timing_row_is_retained_until_complete_and_conflicts_fail(
        self, tmp_path: Path
    ) -> None:
        """Never join a partial or replaced monotonic probe to a native input."""
        observer = self._observer(tmp_path)
        observer.prepare()
        source = next(iter(observer.sources.values()))
        path = observer._probe_path(source)
        assert path is not None
        payload = (
            DomainCodec().encode_json(
                {
                    "schema_version": "runtime-measurement",
                    "kind": "capture_boundary",
                    "cursor": 6,
                    "durable_ns": 1,
                }
            )
            + b"\n"
        )
        original_offset = source.probe_offset
        with path.open("ab") as stream:
            stream.write(payload[:10])
        source.poll_probes(path)
        assert source.probe_offset == original_offset and 6 not in source.durable_probes
        with path.open("ab") as stream:
            stream.write(payload[10:])
        source.poll_probes(path)
        assert source.durable_probes[6] == 1
        with path.open("ab") as stream:
            stream.write(payload.replace(b'"durable_ns":1', b'"durable_ns":2'))
        with pytest.raises(ValueError, match="invalid durable timing boundary"):
            source.poll_probes(path)

    def test_percentiles_require_1000_actual_same_boundary_observations(self) -> None:
        """Use nearest ranks with no scalar expansion or percentile claim for 999 operations."""
        short = CapacityFeatureObserver.summarize(list(range(999)), budgets_ms=(20, 75, 200))
        assert short["status"] == "unmeasured" and "p99_ns" not in short
        qualified = CapacityFeatureObserver.summarize(list(range(1000)), budgets_ms=(20, 75, 200))
        assert (
            qualified["p50_ns"] == 499 and qualified["p95_ns"] == 949 and qualified["p99_ns"] == 989
        )

    def test_cohort_validation_refuses_duplicate_versions_and_changed_durations(
        self, tmp_path: Path
    ) -> None:
        """A real two-value publication counts once and its measured duration cannot be edited."""
        observer = self._observer(tmp_path)
        observer.prepare()
        source = next(iter(observer.sources.values()))
        due = time.monotonic_ns()
        observer.started_ns, observer.stop_ns = due, due + 60_000_000_000
        observer.publish(source, datetime.now(UTC), slot=0, due_ns=due)
        row = DomainCodec().decode_json(
            (observer.output / "materialization-samples.jsonl").read_bytes().splitlines()[-1],
            _Publication,
        )
        interval = _Interval(
            started_monotonic_ns=due,
            scheduled_stop_monotonic_ns=observer.stop_ns,
            steady_ended_monotonic_ns=observer.stop_ns,
            steady_duration_seconds=60,
            postprocess_status="pass",
            poll_failure=False,
        )
        versions: set[str] = set()
        FeatureCohortResults._validate(row, interval, versions)
        assert len(versions) == 1
        with pytest.raises(ValueError, match="invalid same-boundary"):
            FeatureCohortResults._validate(row, interval, versions)
        assert row.durable_to_available_ns is not None
        with pytest.raises(ValueError, match="invalid same-boundary"):
            FeatureCohortResults._validate(
                replace(row, durable_to_available_ns=row.durable_to_available_ns + 1),
                interval,
                set(),
            )

    def test_cohort_requires_the_declared_finite_run_count_and_separate_phase(
        self, tmp_path: Path
    ) -> None:
        """Do not substitute one short run or initial steady for the recovery-steady population."""
        with pytest.raises(ValueError, match="17 distinct finite runs"):
            FeatureCohortResults((tmp_path,))
        roots = tuple(tmp_path / str(index) for index in range(17))
        for root in roots:
            root.mkdir()
            (root / "sampling-plan.json").write_bytes(
                DomainCodec().encode_json({"cohort": "initial_steady"})
            )
        with pytest.raises(ValueError, match="cannot pool"):
            FeatureCohortResults(roots).collect()
