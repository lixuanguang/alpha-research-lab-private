"""Extend served candidates' feature streams from the paper supervisor's live recordings."""

from __future__ import annotations

# standard library imports
import fcntl
import hashlib
import os
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

# third party library imports
import msgspec

# project library imports
from applications.execute.service_candidates import PaperServiceCandidates
from applications.execute.services import PaperServices
from configuration import PackagedCandidate, PaperServiceConfiguration, PaperServiceInstance
from market_data.adapters.sources import BookAdapters
from market_data.storage import CaptureRecording, RecordingFollower
from research.features import (
    FeastServingBridge,
    FeastWorkerSession,
    FeatureAccessError,
    FeatureMaterializer,
    FeatureStoreError,
    VersionedFeatureStore,
)
from research.observations import (
    DecisionSource,
    LiveBookDecisionSource,
    LiveTradeDecisionSource,
)
from runtime import FollowedFeed, LiveInputs, LoadedCandidate
from serialization import DomainCodec


class StreamPublication(Protocol):
    """Publish one served stream's snapshot at a cutoff, Feast-verified first."""

    def publish(self, at: datetime) -> None:
        """Materialize and activate the stream's snapshot at ``at``."""
        ...

    def latest(self) -> datetime | None:
        """Return the stream's latest snapshot cutoff, or None before its first."""
        ...


class MaterializedStream:
    """Publish a served candidate's pinned version through fitted materialization.

    Rows carry the live projection as their source and the supervisor run as their
    dataset; checkpoints are scoped to that run, so a new run starts its own.
    """

    def __init__(
        self,
        loaded: LoadedCandidate,
        inputs: LiveInputs,
        *,
        store: VersionedFeatureStore,
        bridge: FeastServingBridge,
        serving_root: Path,
        run_id: str,
        configuration: str,
        recordings: tuple[str, ...],
    ) -> None:
        """Bind the loaded candidate's stored definition, version, kernel and transform.

        Raises:
            ValueError: The candidate is not served from a batch feature definition.
        """
        definition, version = loaded.store_definition, loaded.deployment.feature_version
        if definition is None or version is None:
            raise ValueError("published stream requires a feature-served candidate")
        if definition.schema.mode != "batch":
            raise ValueError("the feature publisher serves batch feature definitions only")
        self.loaded, self.inputs = loaded, inputs
        self.definition, self.version = definition, version
        self._store, self._bridge, self._serving_root = store, bridge, serving_root
        self._instance = f"paper-publisher:{run_id}"
        self._dataset = f"paper-run:{run_id}"
        self._configuration = configuration
        self._recordings = hashlib.sha256(DomainCodec().encode_json(recordings)).hexdigest()

    def publish(self, at: datetime) -> None:
        """Materialize the entity's vector at ``at`` and publish its snapshot."""
        FeatureMaterializer().materialize(
            self._store,
            self.definition,
            source=self.inputs,
            kernel=self.loaded.feature,
            instance=self._instance,
            entities=(self.loaded.deployment.entity,),
            decisions=(at,),
            source_version=self.inputs.identity,
            source_sha256=self._recordings,
            dataset_version=self._dataset,
            dataset_sha256=self._configuration,
            version=self.version,
            bridge=self._bridge,
            serving_root=self._serving_root,
            transform=self.loaded.transform,
            transform_version=self.loaded.transform_version,
        )

    def latest(self) -> datetime | None:
        """Return the version stream's latest snapshot cutoff."""
        try:
            return self._store.get_materialization(self.definition, self.version).at
        except FeatureStoreError:
            return None


class StreamSchedule:
    """Publish one stream at its grid instants once every followed feed has passed them.

    Records are accepted in receipt order across feeds. An instant is published only
    when each feed holds a durable record available after it, so its inputs are
    complete; an instant not published within ``max_lag`` of it is skipped. A failed
    publication is retried until then. Publication resumes after the stream's
    latest snapshot and starts no earlier than the first followed record.
    """

    def __init__(
        self,
        publication: StreamPublication,
        feeds: tuple[FollowedFeed, ...],
        *,
        starts_at: datetime,
        cadence: timedelta,
        max_lag: timedelta,
    ) -> None:
        """Bind the publication, its feeds and the candidates' shared decision grid."""
        if not feeds or cadence <= timedelta(0) or max_lag <= timedelta(0):
            raise ValueError("stream schedule requires feeds, a cadence and a lag bound")
        self.publication, self.feeds = publication, feeds
        self.starts_at, self.cadence, self.max_lag = starts_at, cadence, max_lag
        self.next_at: datetime | None = None
        self.published = 0
        self.skipped = 0
        self.failures = 0
        self.last_published: datetime | None = None
        self.last_error: str | None = None

    @property
    def finished(self) -> bool:
        """Report that every followed recording is complete and fully accepted."""
        return all(feed.finished for feed in self.feeds)

    def advance(self, now: datetime) -> bool:
        """Accept records and publish or skip due instants; report whether anything moved."""
        progressed = False
        while True:
            heads = tuple((feed.next_available_at(), feed) for feed in self.feeds)
            durable = tuple((at, feed) for at, feed in heads if at is not None)
            if self.next_at is None:
                if not durable:
                    return progressed
                self.next_at = self._first(min(at for at, _ in durable))
            due = self.next_at
            earliest = min(durable, key=self._available, default=None)
            if earliest is not None and earliest[0] <= due:
                earliest[1].accept()
                progressed = True
                continue
            if now - due > self.max_lag:
                self.skipped += 1
            elif len(durable) == len(self.feeds):
                try:
                    self.publication.publish(due)
                except (FeatureAccessError, FeatureStoreError, OSError, sqlite3.Error) as error:
                    self.failures += 1
                    self.last_error = f"{type(error).__name__}: {error}"
                    return progressed
                self.published += 1
                self.last_published = due
            else:
                return progressed
            self.next_at = due + self.cadence
            progressed = True

    def _first(self, available: datetime) -> datetime:
        """Return the first grid instant at or after the first record and the latest snapshot."""
        floor = available
        latest = self.publication.latest()
        if latest is not None and latest + timedelta(microseconds=1) > floor:
            floor = latest + timedelta(microseconds=1)
        if floor <= self.starts_at:
            return self.starts_at
        steps = -((self.starts_at - floor) // self.cadence)
        return self.starts_at + steps * self.cadence

    @staticmethod
    def _available(item: tuple[datetime, FollowedFeed]) -> datetime:
        """Order pending heads by receipt availability."""
        return item[0]


class SupervisorStatus(msgspec.Struct, frozen=True, kw_only=True):
    """Read the supervisor status fields that bind the publisher to its run."""

    configuration: str
    run_id: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class PublishedStreamReport:
    """Summarize one stream's publication for the command result."""

    stream: str
    entity: str
    instances: tuple[str, ...]
    published: int
    skipped: int
    failures: int
    last_published: datetime | None
    last_error: str | None


class FeaturePublisher:
    """Run the signed live feature publisher beside one paper supervisor run.

    It binds the supervisor's run through its status file, follows each served
    stream's book and trades recordings read-only, and publishes each stream's
    snapshots at its candidates' grid instants. It writes only the feature store
    and the Feast generation root and holds no account or venue authority. Its
    life ends when every followed recording is complete and accepted, or at the
    supervisor's own end.
    """

    def __init__(
        self,
        configuration: PaperServiceConfiguration,
        candidates: Path,
        root: Path,
        *,
        clock: Callable[[], datetime] | None = None,
        poll_seconds: float = 0.1,
    ) -> None:
        """Bind the signed configuration, release candidates and supervisor root.

        Raises:
            ValueError: The configuration declares no publisher, or paths are relative.
        """
        configuration.__post_init__()
        serving = configuration.features
        if serving is None or serving.publisher is None:
            raise ValueError("paper configuration declares no feature publisher")
        if not root.is_absolute() or not candidates.is_absolute():
            raise ValueError("feature publisher requires absolute paths")
        self.config, self.root = configuration, root
        self.resolved = PaperServiceCandidates(configuration, candidates)
        self.store = VersionedFeatureStore.open(Path(serving.store_path))
        self.worker = FeastWorkerSession(
            serving.worker, timeout_seconds=serving.worker_timeout_seconds
        )
        self.bridge = FeastServingBridge(self.worker)
        self.serving_root = Path(serving.serving_root)
        self.max_lag = timedelta(seconds=serving.publisher.max_lag_seconds)
        self._clock = clock
        self._poll_seconds = poll_seconds
        self._codec = DomainCodec()

    def run(self) -> dict[str, object]:
        """Hold the serving root's publisher fence and publish under it.

        Raises:
            ValueError: Another publisher already owns this serving root.
        """
        self.serving_root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.serving_root / "publisher.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "a+b") as fence:
            try:
                fcntl.flock(fence.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("a feature publisher already owns this serving root") from None
            try:
                self.worker.start()
                return self._publish()
            finally:
                self.worker.close()

    def _publish(self) -> dict[str, object]:
        """Publish until every followed recording completes or the service life ends."""
        deadline = (
            time.monotonic()
            + self.config.duration_seconds
            + PaperServices.drain_reserve(self.config.duration_seconds)
        )
        run_id = self._run_id(deadline)
        streams = self._streams(run_id, deadline) if run_id is not None else ()
        stopped = "supervisor_not_found" if run_id is None else "deadline"
        while streams and time.monotonic() < deadline:
            moved = [schedule.advance(self._now()) for schedule, _, _ in streams]
            if all(schedule.finished for schedule, _, _ in streams):
                stopped = "recordings_complete"
                break
            if not any(moved):
                time.sleep(self._poll_seconds)
        return {
            "schema_version": "paper-feature-publisher",
            "configuration": self.config.identity,
            "run_id": run_id,
            "stopped": stopped,
            "streams": tuple(
                PublishedStreamReport(
                    stream=VersionedFeatureStore.stream_identity(
                        publication.definition, publication.version
                    ),
                    entity=publication.loaded.deployment.entity,
                    instances=instances,
                    published=schedule.published,
                    skipped=schedule.skipped,
                    failures=schedule.failures,
                    last_published=schedule.last_published,
                    last_error=schedule.last_error,
                )
                for schedule, publication, instances in streams
            ),
        }

    def served(self) -> tuple[PaperServiceInstance, ...]:
        """Return the instances whose candidates read a published feature stream."""
        return tuple(
            instance
            for instance in self.config.instances
            if isinstance(instance.candidate, PackagedCandidate)
            and instance.candidate.feature_version is not None
        )

    def _now(self) -> datetime:
        """Read the injected or system UTC clock."""
        return datetime.now(UTC) if self._clock is None else self._clock()

    def _run_id(self, deadline: float) -> str | None:
        """Wait for a status this supervisor wrote after the publisher started; return its run.

        Raises:
            ValueError: The status names another configuration.
        """
        started = self._now()
        path = self.root / "status.json"
        while time.monotonic() < deadline:
            if path.is_file():
                status = self._codec.decode_json(path.read_bytes(), SupervisorStatus)
                if status.configuration != self.config.identity:
                    raise ValueError("supervisor status names another configuration")
                if status.observed_at >= started:
                    return status.run_id
            time.sleep(self._poll_seconds)
        return None

    def _streams(
        self, run_id: str, deadline: float
    ) -> tuple[tuple[StreamSchedule, MaterializedStream, tuple[str, ...]], ...]:
        """Group served instances by stream and entity and bind each group's feeds.

        Raises:
            ValueError: Instances sharing a stream differ in grid, or a feed is missing.
        """
        groups: dict[tuple[str, str], list[PaperServiceInstance]] = {}
        for instance in self.served():
            loaded = self.resolved.candidate(instance)
            definition, version = loaded.store_definition, loaded.deployment.feature_version
            if definition is None or version is None:
                raise ValueError("served candidate has no feature-store binding")
            key = (
                VersionedFeatureStore.stream_identity(definition, version),
                loaded.deployment.entity,
            )
            groups.setdefault(key, []).append(instance)
        streams: list[tuple[StreamSchedule, MaterializedStream, tuple[str, ...]]] = []
        for members in groups.values():
            selected = tuple(self.resolved.candidate(item) for item in members)
            grids = {(item.deployment.starts_at, item.definition.cadence_us) for item in selected}
            if len(grids) != 1 or len({item.source for item in members}) != 1:
                raise ValueError("instances sharing a served stream differ in grid or source")
            streams.append(self._stream(run_id, tuple(members), selected[0], deadline))
        return tuple(streams)

    def _stream(
        self,
        run_id: str,
        members: tuple[PaperServiceInstance, ...],
        loaded: LoadedCandidate,
        deadline: float,
    ) -> tuple[StreamSchedule, MaterializedStream, tuple[str, ...]]:
        """Follow the source's book and, when the kernel reads trades, its trades recording.

        Raises:
            ValueError: The kernel reads other inputs, or a feed is not configured.
        """
        source = self.resolved.source(members[0])
        requirements = loaded.feature.schema.inputs
        book = tuple(item for item in requirements if item.family == "book")
        trades = tuple(item for item in requirements if item.family == "trade")
        if len(book) + len(trades) != len(requirements):
            raise ValueError("published feature inputs must be book or trade fields")
        if trades and source.trades is None:
            raise ValueError("published feature reads trades its source does not capture")
        feeds: list[FollowedFeed] = []
        sources: list[DecisionSource] = []
        if book:
            recording = self._recording(
                run_id, PaperServices.feed_key(source.name, "book"), deadline
            )
            live_book = LiveBookDecisionSource(recording.request, book, history_capacity=1000)
            feeds.append(
                FollowedFeed(RecordingFollower(recording), live_book, natives=BookAdapters.create)
            )
            sources.append(live_book)
        if trades:
            recording = self._recording(
                run_id, PaperServices.feed_key(source.name, "trades"), deadline
            )
            live_trades = LiveTradeDecisionSource(
                recording.request, trades, tapes=BookAdapters.trades, history_capacity=1000
            )
            feeds.append(
                FollowedFeed(RecordingFollower(recording), live_trades, natives=BookAdapters.create)
            )
            sources.append(live_trades)
        publication = MaterializedStream(
            loaded,
            LiveInputs(requirements, tuple(sources)),
            store=self.store,
            bridge=self.bridge,
            serving_root=self.serving_root,
            run_id=run_id,
            configuration=self.config.identity,
            recordings=tuple(feed.follower.recording.identity for feed in feeds),
        )
        schedule = StreamSchedule(
            publication,
            tuple(feeds),
            starts_at=loaded.deployment.starts_at,
            cadence=timedelta(microseconds=loaded.definition.cadence_us),
            max_lag=self.max_lag,
        )
        return schedule, publication, tuple(item.instance_id for item in members)

    def _recording(self, run_id: str, feed: str, deadline: float) -> CaptureRecording:
        """Wait for the supervisor's one recording of a feed in this run.

        Raises:
            ValueError: The feed has several recordings (a restarted source) or none by the end.
        """
        directory = self.root / "runs" / run_id / feed
        while time.monotonic() < deadline:
            found = CaptureRecording.discover(directory) if directory.is_dir() else ()
            if len(found) > 1:
                raise ValueError("feature publisher follows one recording per feed")
            if found:
                return found[0]
            time.sleep(self._poll_seconds)
        raise ValueError("supervisor started no recording for a followed feed")
