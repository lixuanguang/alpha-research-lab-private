"""Compose exact versioned features with finite native-book capacity trials.

Copy this consumer alongside capacity_reads. It reads retained public inputs and
has no account, trading or transport authority. Runtime online access uses the
existing local versioned store; the isolated Feast boundary is qualified by the
separate research workload.
"""

from __future__ import annotations

# standard library imports
import hashlib
import math
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, Literal

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
from configuration import PaperServiceConfiguration
from financial_units import ExactRatio
from market_data.books import BookDepth
from market_data.contracts import BookLookup
from research.features import (
    FeatureSchema,
    FeatureSession,
    FeatureStoreDefinition,
    ProjectionFeature,
    StoredFeature,
    VersionedFeatureStore,
)
from research.observations import (
    DecisionInputs,
    InputRequirement,
    LiveBookDecisionSource,
    NamedObservation,
    NumericField,
)
from runtime import InstalledIdentity, SharedBookDelivery
from serialization import DomainCodec

if TYPE_CHECKING:
    # third party library imports
    from capacity_reads import _RetainedBookIndex, _SourceIndex


class _ProbeKind(msgspec.Struct, frozen=True):
    """Select capture timing rows without treating queue rows as observations."""

    kind: str


class _DurableProbe(msgspec.Struct, frozen=True):
    """Join one native position to its actual monotonic durable completion."""

    kind: str
    schema_version: str
    cursor: int
    durable_ns: int


class _FeatureSource:
    """Bind one native source to a two-value exact projection and durable versions."""

    def __init__(self, source: _SourceIndex, freshness_us: int, root: Path) -> None:
        """Preserve native entity, currency, source identity and selected freshness."""
        self.source = source
        self.entity = str(source.request.config.instrument_id)
        units = f"{source.request.config.quote_currency}/{source.request.config.base_currency}"
        fields = tuple(NumericField(name=name, units=units) for name in ("bid_price", "ask_price"))
        self.definition = FeatureStoreDefinition(
            name=f"{source.name}-visible-touch",
            entity_type="instrument",
            schema=FeatureSchema(
                implementation="named-projection",
                inputs=tuple(
                    InputRequirement(
                        name=source.name,
                        family="book",
                        clock="receipt",
                        field=field,
                        max_age_us=freshness_us,
                    )
                    for field in fields
                ),
                outputs=fields,
                parameters=(),
                mode="batch",
                ttl_us=5_000_000,
            ),
        )
        self.session = FeatureSession(
            ProjectionFeature(self.definition.schema), instance=source.name, entity=self.entity
        )
        self.store = VersionedFeatureStore.open(root / f"{source.name}.sqlite3")
        self.store.register(self.definition)
        self.publication_lock = threading.Lock()
        self.causal_source = LiveBookDecisionSource(
            source.request,
            InputRequirement(
                name=source.name,
                family="book",
                clock="receipt",
                field=NumericField(name="imbalance", units="dimensionless"),
                max_age_us=freshness_us,
            ),
            history_capacity=10_000,
        )
        self.source_cursor = 0
        self.codec = DomainCodec()
        self.probe_offset = 0
        self.durable_probes: dict[int, int] = {}

    @staticmethod
    def utc_from_ns(value: int) -> datetime:
        """Admit nanosecond source clocks conservatively into microsecond contracts."""
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=(value + 999) // 1000)

    def inputs(self, lookup: BookLookup, at: datetime) -> DecisionInputs:
        """Keep source quality and clocks while projecting exact visible prices."""
        quote = lookup.quote
        lineage = hashlib.sha256(
            DomainCodec().encode_json((self.source.request.identity, lookup))
        ).hexdigest()
        observations: list[NamedObservation] = []
        for index, requirement in enumerate(self.definition.schema.inputs):
            side = None if quote is None else (quote.bid if index == 0 else quote.ask)
            reason = (
                lookup.reason if quote is None else "missing_side" if side is None else "observed"
            )
            if quote is not None and quote.market_state != "two_sided":
                side, reason = None, f"book_{quote.market_state}"
            observations.append(
                NamedObservation(
                    input=requirement,
                    entity=self.entity,
                    event_at=at
                    if quote is None or quote.received_ns is None
                    else self.utc_from_ns(quote.received_ns),
                    available_at=None
                    if quote is None or quote.available_ns is None
                    else self.utc_from_ns(quote.available_ns),
                    value=None if side is None else ExactRatio.from_fraction(Fraction(side.price)),
                    reason=reason,
                    lineage=lineage,
                )
            )
        return DecisionInputs(entity=self.entity, decision_at=at, observations=tuple(observations))

    def lookup(self, index: _RetainedBookIndex, at: datetime) -> BookLookup:
        """Reuse native causal admission so proved controls preserve the original market age."""
        index.poll()
        with index.lock:
            lookup = index.registry.lookup(self.source.key, cutoff_ns=index._unix_ns(at))
            retained = tuple(
                encoded
                for quote, encoded, _ in self.source.history
                if quote.position >= self.source_cursor
            )
        for encoded in retained:
            delivery = self.codec.decode_json(encoded, SharedBookDelivery).source
            if delivery.book.position != self.source_cursor:
                raise ValueError("feature causal source lost its retained native prefix")
            self.causal_source.accept(
                delivery.record, delivery.book, available_at=delivery.available_at
            )
            self.source_cursor += 1
        decision = self.causal_source.read(self.entity, at)
        book = self.causal_source.book_at(self.entity, at)
        observation = decision.observations[0]
        if lookup.reason not in ("eligible", "unavailable"):
            return lookup
        if book is None:
            return replace(lookup, quote=None, reason=observation.reason)
        if observation.available_at is None:
            raise ValueError("eligible native feature input has no original availability")
        quote = BookDepth.touch_quote(
            book,
            venue=self.source.request.config.venue,
            instrument_id=self.source.request.config.instrument_id,
            source_id=self.source.request.identity,
            channel=self.source.request.config.channel,
            available_ns=index._unix_ns(observation.available_at),
        )
        return replace(lookup, quote=quote, reason="eligible")

    def poll_probes(self, path: Path | None) -> None:
        """Read only a finite complete timing prefix and reject conflicting cursor retries."""
        if path is None or not path.is_file():
            return
        retained_end = path.stat().st_size
        with path.open("rb") as stream:
            stream.seek(self.probe_offset)
            while stream.tell() < retained_end:
                line = stream.readline(retained_end - stream.tell())
                if not line.endswith(b"\n"):
                    break
                if msgspec.json.decode(line, type=_ProbeKind).kind == "capture_boundary":
                    probe = msgspec.json.decode(line, type=_DurableProbe)
                    if (
                        probe.schema_version != "runtime-measurement"
                        or probe.cursor < 1
                        or probe.durable_ns < 0
                        or self.durable_probes.get(probe.cursor, probe.durable_ns)
                        != probe.durable_ns
                    ):
                        raise ValueError("feature source has an invalid durable timing boundary")
                    self.durable_probes[probe.cursor] = probe.durable_ns
                self.probe_offset = stream.tell()


class CapacityFeatureObserver:
    """Materialize at one hertz and serve eight instance readers at four hertz.

    A materialization observation is one atomic two-value instrument version,
    never two scalar samples. Each source needs 1,000 observations independently.
    The 60-second finite interval yields 60/source and 1,920 retrieval requests.
    Calculation availability and observed durable publication are retained as
    distinct clocks; latency uses the actual monotonic publication completion.
    """

    def __init__(
        self,
        output: Path,
        config: PaperServiceConfiguration,
        index: _RetainedBookIndex,
        *,
        measurement_root: Path | None = None,
        cohort: Literal["initial_steady", "recovery_steady"] = "initial_steady",
    ) -> None:
        """Bind existing source and instance selections without extending their lifetimes."""
        if len(config.sources) != 4 or len(config.accounts) != 4 or len(config.active) != 8:
            raise ValueError(
                "integrated feature workload requires four sources/owners/eight instances"
            )
        self.output, self.config, self.index = output, config, index
        self.measurement_root = measurement_root
        self.cohort = cohort
        self.codec = DomainCodec()
        self.sources: dict[str, _FeatureSource] = {}
        self.threads: list[threading.Thread] = []
        self.stop = threading.Event()
        self.write_lock = threading.Lock()
        self.failures: list[str] = []
        self.started_ns = 0
        self.stop_ns = 0
        self.initialization_seconds = 0.0

    def prepare(self) -> None:
        """Initialize and prime the actual stores before the measured interval."""
        began = time.monotonic()
        self.output.mkdir(parents=True, exist_ok=False)
        for source in self.config.sources:
            self.sources[source.name] = _FeatureSource(
                self.index.sources[source.name], source.freshness_us, self.output
            )
        self.index.poll()
        for feature_source in self.sources.values():
            self.publish(feature_source, datetime.now(UTC), slot=-1, due_ns=time.monotonic_ns())
        self.initialization_seconds = time.monotonic() - began
        plan = {
            "schema_version": "finite-feature-sampling",
            "implementation": InstalledIdentity.sha256(),
            "consumer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "cache_class": "warm_initialized_versioned_sqlite_store_os_cache_uncontrolled",
            "configuration": self.config.identity,
            "cohort": self.cohort,
            "feature_definitions": {
                name: source.definition for name, source in self.sources.items()
            },
            "native_selections": {
                name: source.request.config for name, source in self.index.sources.items()
            },
            "active_instances": self.config.active,
            "materialization_unit": "one_two_value_instrument_version",
            "materialization_cadence_ns": 1_000_000_000,
            "reader_cadence_ns": 250_000_000,
            "ttl_us": 5_000_000,
            "minimum_samples_per_materialization_source": 1000,
            "minimum_samples_per_retrieval_boundary": 1000,
            "cohort_plan": (
                "one_initial_steady_interval_separate_from_17_homogeneous_recovery_steady_intervals"
            ),
            "expected_materializations_per_source_per_60s": 60,
            "expected_retrievals_per_60s": 1920,
            "runtime_online_boundary": "VersionedFeatureStore.retrieve_online",
            "publication_read_boundary": (
                "per_source_atomic_publication_and_consuming_cutoff_wait_included"
            ),
            "native_admission_boundary": "LiveBookDecisionSource_original_market_age",
            "feast_boundary": "separate_research_qualification",
        }
        (self.output / "sampling-plan.json").write_bytes(self.codec.encode_json(plan))

    def _record(self, name: str, row: object) -> None:
        """Retain full individual observations with serialized concurrent writes."""
        with self.write_lock, (self.output / name).open("ab") as stream:
            stream.write(self.codec.encode_json(row) + b"\n")

    def _probe_path(self, source: _FeatureSource) -> Path | None:
        """Select the exact current recording's opt-in monotonic capture probes."""
        if self.measurement_root is None:
            return None
        paths = tuple(
            self.measurement_root.glob(
                f"*/{source.source.name}/{source.source.request.recording_id}.capture.jsonl"
            )
        )
        if len(paths) > 1:
            raise ValueError("feature recording has ambiguous capture timing files")
        return paths[0] if paths else None

    def publish(self, source: _FeatureSource, at: datetime, *, slot: int, due_ns: int) -> None:
        """Publish one exact causal version and retain the actual durable completion."""
        began_ns = time.monotonic_ns()
        lookup = source.lookup(self.index, at)
        inputs = source.inputs(lookup, at)
        vector = source.session.evaluate(inputs)
        calculated_at = datetime.now(UTC)
        vector = replace(
            vector, available_at=calculated_at, expires_at=calculated_at + timedelta(seconds=5)
        )
        feature = StoredFeature(
            definition_identity=source.definition.identity,
            vector=vector,
            source_version=source.source.request.recording_id,
            source_sha256=source.source.request.identity,
            dataset_version=f"native-book-projection-{source.source.request.recording_id}",
            dataset_sha256=inputs.identity,
            revision_identity=inputs.identity,
        )
        version = f"{source.source.request.recording_id}-{slot}"
        with source.publication_lock:
            previous = source.store.active_version(source.definition)
            source.store.append(source.definition, feature)
            snapshot = source.store.materialize(
                source.definition, version, calculated_at, (source.entity,)
            )
            source.store.activate_if_current(source.definition, version, expected_version=previous)
            completed_ns, published_at = time.monotonic_ns(), datetime.now(UTC)
        source.poll_probes(self._probe_path(source))
        quote = lookup.quote
        durable_ns = None if quote is None else source.durable_probes.get(quote.position + 1)
        if durable_ns is not None and durable_ns > began_ns:
            raise ValueError("feature publication precedes its durable native input")
        offline = source.store.retrieve_offline(source.definition, source.entity, calculated_at)
        if snapshot.rows[0].feature != feature or offline.feature != feature:
            raise AssertionError("materialized feature differs from exact offline version")
        self._record(
            "materialization-samples.jsonl",
            {
                "source": source.source.name,
                "slot": slot,
                "phase": "initialization" if slot < 0 else "steady",
                "due_ns": due_ns,
                "began_ns": began_ns,
                "completed_ns": completed_ns,
                "completed_within_interval": slot < 0 or completed_ns <= self.stop_ns,
                "durable_ns": durable_ns,
                "durable_to_available_ns": None
                if durable_ns is None
                else completed_ns - durable_ns,
                "service_ns": completed_ns - began_ns,
                "published_at": published_at,
                "calculated_at": calculated_at,
                "inputs": inputs,
                "quote": quote,
                "native_position": None if quote is None else quote.position,
                "source_request_identity": source.source.request.identity,
                "feature": feature,
                "materialization_identity": snapshot.identity,
                "version": version,
                "parity": True,
                "quality": snapshot.rows[0].status,
                "status": "ok",
            },
        )

    def start(self, started: float, stop: float) -> None:
        """Share the original finite interval with concurrent depth and dashboard work."""
        self.started_ns, self.stop_ns = round(started * 1_000_000_000), round(stop * 1_000_000_000)
        self.threads = [threading.Thread(target=self._materialize, daemon=True)]
        self.threads.extend(
            threading.Thread(
                target=self._read, args=(instance.instance_id, instance.source), daemon=True
            )
            for instance in self.config.instances
            if instance.instance_id in self.config.active
        )
        for thread in self.threads:
            thread.start()

    def _materialize(self) -> None:
        """Keep all due one-second versions or retain a failure without stretching time."""
        slot = 0
        try:
            while (due_ns := self.started_ns + slot * 1_000_000_000) < self.stop_ns:
                if self.stop.wait(max(0.0, (due_ns - time.monotonic_ns()) / 1_000_000_000)):
                    return
                if time.monotonic_ns() >= self.stop_ns:
                    self.failures.append("materialization schedule did not complete")
                    return
                for source in self.sources.values():
                    self.publish(source, datetime.now(UTC), slot=slot, due_ns=due_ns)
                slot += 1
        except (OSError, ValueError, RuntimeError, AssertionError, sqlite3.Error) as error:
            self.failures.append(f"materialization: {type(error).__name__}: {error}")

    def _read(self, instance: str, source_name: str) -> None:
        """Serve each due request with an actual consuming cutoff and exact version parity."""
        source = self.sources[source_name]
        slot = 0
        while (due_ns := self.started_ns + slot * 250_000_000) < self.stop_ns:
            if self.stop.wait(max(0.0, (due_ns - time.monotonic_ns()) / 1_000_000_000)):
                return
            began_ns, requested_at = time.monotonic_ns(), datetime.now(UTC)
            at, acquired_ns = requested_at, began_ns
            if began_ns >= self.stop_ns:
                return
            try:
                with source.publication_lock:
                    acquired_ns, at = time.monotonic_ns(), datetime.now(UTC)
                    online = source.store.retrieve_online(
                        source.definition,
                        source.entity,
                        at,
                        max_materialization_age_us=5_000_000,
                    )
                    completed_ns = time.monotonic_ns()
                offline = (
                    None
                    if online.materialized_at is None
                    else source.store.retrieve_offline(
                        source.definition, source.entity, online.materialized_at
                    )
                )
                parity = offline is not None and offline.feature == online.feature
                if not parity:
                    raise AssertionError(
                        "online feature differs from matched-cutoff offline values"
                    )
                result: dict[str, object] = {
                    "status": "ok",
                    "quality": online.status,
                    "parity": parity,
                    "version": online.version,
                    "matched_cutoff": online.materialized_at,
                    "feature_identity": None if online.feature is None else online.feature.identity,
                }
            except (OSError, ValueError, RuntimeError, AssertionError, sqlite3.Error) as error:
                completed_ns = time.monotonic_ns()
                result = {"status": "failed", "error": f"{type(error).__name__}: {error}"}
            self._record(
                "retrieval-samples.jsonl",
                {
                    "reader": instance,
                    "source": source_name,
                    "slot": slot,
                    "due_ns": due_ns,
                    "began_ns": began_ns,
                    "completed_ns": completed_ns,
                    "completed_within_interval": completed_ns <= self.stop_ns,
                    "requested_at": requested_at,
                    "at": at,
                    "publication_wait_ns": acquired_ns - began_ns,
                    "service_ns": completed_ns - began_ns,
                    "response_ns": completed_ns - due_ns,
                    **result,
                },
            )
            slot += 1

    @staticmethod
    def summarize(values_ns: list[int], *, budgets_ms: tuple[int, int, int]) -> dict[str, object]:
        """Report empirical nearest ranks only for at least 1,000 real observations."""
        ordered = sorted(values_ns)
        result: dict[str, object] = {
            "sample_count": len(ordered),
            "minimum_ns": ordered[0] if ordered else None,
            "maximum_ns": ordered[-1] if ordered else None,
            "method": "empirical_nearest_rank",
            "status": "unmeasured",
        }
        if len(ordered) < 1000:
            result["reason"] = "fewer_than_1000_same_boundary_cache_class_samples"
            return result
        ranks = tuple(ordered[math.ceil(len(ordered) * rank) - 1] for rank in (0.50, 0.95, 0.99))
        result.update(zip(("p50_ns", "p95_ns", "p99_ns"), ranks, strict=True))
        result["status"] = (
            "pass"
            if all(
                measured <= budget * 1_000_000
                for measured, budget in zip(ranks, budgets_ms, strict=True)
            )
            else "fail"
        )
        return result

    def finish(self, deadline: float) -> dict[str, object]:
        """Join on the shared shutdown deadline and retain all schedules and missingness."""
        for thread in self.threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        self.stop.set()
        if any(thread.is_alive() for thread in self.threads):
            self.failures.append("feature worker exceeded shared shutdown deadline")
        publications = self._rows("materialization-samples.jsonl")
        reads = self._rows("retrieval-samples.jsonl")
        materializations: dict[str, object] = {}
        expected_versions = math.ceil((self.stop_ns - self.started_ns) / 1_000_000_000)
        for name in self.sources:
            rows = [
                row for row in publications if row["source"] == name and row["phase"] == "steady"
            ]
            durations = [
                self._integer(row, "durable_to_available_ns")
                for row in rows
                if row["durable_to_available_ns"] is not None
                and row["completed_within_interval"]
                and row["quality"] == "ready"
            ]
            materializations[name] = {
                **self.summarize(durations, budgets_ms=(2000, 2000, 2000)),
                "expected_versions": expected_versions,
                "observed_versions": len(rows),
                "unit": "one_two_value_instrument_version",
                "missing_durable_probe_count": sum(row["durable_ns"] is None for row in rows),
                "unique_versions": len({str(row["version"]) for row in rows}),
                "unique_native_inputs": len(
                    {str(row["quote"]) for row in rows if row["quote"] is not None}
                ),
            }
            if (
                {self._integer(row, "slot") for row in rows} != set(range(expected_versions))
                or len(rows) != expected_versions
                or any(
                    row["quality"] != "ready" or not row["completed_within_interval"]
                    for row in rows
                )
            ):
                self.failures.append(f"{name}: incomplete ready materialization schedule")
        expected_reads = len(self.config.active) * math.ceil(
            (self.stop_ns - self.started_ns) / 250_000_000
        )
        successes = [
            row
            for row in reads
            if row["status"] == "ok"
            and row["completed_within_interval"]
            and row["quality"] == "ready"
        ]
        service = self.summarize(
            [self._integer(row, "service_ns") for row in successes], budgets_ms=(20, 75, 200)
        )
        response = self.summarize(
            [self._integer(row, "response_ns") for row in successes], budgets_ms=(20, 75, 200)
        )
        if service["status"] == "fail" or response["status"] == "fail":
            self.failures.append("observed feature retrieval exceeded its declared latency budget")
        if len(successes) != expected_reads:
            self.failures.append(
                "eight-reader feature schedule has failed, late or nonready requests"
            )
        self._validate_read_schedule(reads)
        quality_probes = self._quality_probes()
        result: dict[str, object] = {
            "status": "pass_observed_schedule" if not self.failures else "fail",
            "initialization_seconds": self.initialization_seconds,
            "initialization_cache_class": "application_cold_os_cache_uncontrolled",
            "expected_retrievals": expected_reads,
            "observed_retrievals": len(reads),
            "ready_retrievals": len(successes),
            "service_latency": service,
            "response_latency": response,
            "materialization_per_source": materializations,
            "matched_cutoff_parity": all(row.get("parity") is True for row in successes),
            "quality_probes": quality_probes,
            "failures": self.failures,
            "sampling_plan": str(self.output / "sampling-plan.json"),
        }
        (self.output / "summary.json").write_bytes(self.codec.encode_json(result))
        return result

    def _validate_read_schedule(self, rows: list[dict[str, object]]) -> None:
        """Refuse duplicate, misbound or fabricated reader/arrival observations."""
        bindings = {
            item.instance_id: item.source
            for item in self.config.instances
            if item.instance_id in self.config.active
        }
        slots = math.ceil((self.stop_ns - self.started_ns) / 250_000_000)
        expected = {(reader, slot) for reader in bindings for slot in range(slots)}
        observed: set[tuple[str, int]] = set()
        for row in rows:
            reader, slot = str(row["reader"]), self._integer(row, "slot")
            key = reader, slot
            due = self._integer(row, "due_ns")
            began = self._integer(row, "began_ns")
            completed = self._integer(row, "completed_ns")
            if (
                key in observed
                or key not in expected
                or row["source"] != bindings.get(reader)
                or due != self.started_ns + slot * 250_000_000
                or not due <= began <= completed
                or self._integer(row, "service_ns") != completed - began
                or self._integer(row, "response_ns") != completed - due
            ):
                self.failures.append("invalid or duplicate feature reader schedule observation")
                return
            observed.add(key)
        if observed != expected:
            self.failures.append("feature reader schedule omitted a due request")

    def _quality_probes(self) -> dict[str, object]:
        """Retain actual inclusive TTL, stale, missing and future outcomes after timing."""
        findings: dict[str, object] = {}
        for name, source in self.sources.items():
            version = source.store.active_version(source.definition)
            if version is None:
                self.failures.append(f"{name}: no active version for quality probes")
                continue
            snapshot = source.store.get_materialization(source.definition, version)
            statuses = {
                "ttl_inclusive": source.store.retrieve_online(
                    source.definition,
                    source.entity,
                    snapshot.at + timedelta(seconds=5),
                    max_materialization_age_us=5_000_000,
                ).status,
                "stale": source.store.retrieve_online(
                    source.definition,
                    source.entity,
                    snapshot.at + timedelta(seconds=5, microseconds=1),
                    max_materialization_age_us=5_000_000,
                ).status,
                "missing": source.store.retrieve_online(
                    source.definition, "unselected-entity", snapshot.at
                ).status,
                "future": source.store.retrieve_online(
                    source.definition, source.entity, snapshot.at - timedelta(microseconds=1)
                ).status,
            }
            findings[name] = statuses
            if statuses != {
                "ttl_inclusive": "ready",
                "stale": "stale",
                "missing": "missing",
                "future": "future",
            }:
                self.failures.append(f"{name}: explicit feature quality probes differ")
        return findings

    def _rows(self, name: str) -> list[dict[str, object]]:
        """Read complete retained observations without synthesizing omitted samples."""
        path = self.output / name
        return (
            []
            if not path.is_file()
            else [
                msgspec.json.decode(line, type=dict[str, object])
                for line in path.read_bytes().splitlines()
            ]
        )

    @staticmethod
    def _integer(row: dict[str, object], name: str) -> int:
        """Require actual nonnegative monotonic durations before percentile admission."""
        value = row[name]
        if type(value) is not int or value < 0:
            raise ValueError(f"invalid feature measurement: {name}")
        return value
