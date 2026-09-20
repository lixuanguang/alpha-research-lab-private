"""Inspect one configured saved query and emit retainable JSON attempt records."""

from __future__ import annotations

# standard library imports
import hashlib
import resource
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

# third party library imports
import msgspec

# project library imports
from market_data.adapters.sources import SourceAdapters
from market_data.query import QueryBatch, QueryReader
from market_data.storage import RawStore
from research.experiments import (
    AttemptHistory,
    AttemptStore,
    ClearMLDestination,
    ClearMLPublication,
    ExperimentSpec,
)
from research.exploration import (
    EdaQuery,
    ExplorationStudy,
    FeatureStudy,
    QuerySummary,
    ResearchReader,
    ResearchSelection,
    TradeResearchInput,
)
from runtime import ImplementationIdentity
from serialization import DomainCodec


def inspect_eda(
    config: Path,
    snapshots: Path,
    raw: RawStore,
    *,
    report: Callable[[dict[str, object]], None],
    consume: Callable[[QueryBatch], None] | None = None,
) -> dict[str, object]:
    """Resolve config, verify the snapshot, summarize batches and report the complete attempt.

    Args:
        config: Strict EdaQuery or ResearchSelection JSON, limited to one MiB.
            Multi-input selections return typed native inputs under ``dataset``.
        snapshots: Existing immutable snapshot root; no acquisition is performed.
        raw: Retained raw store for complete snapshot verification.
        report: Synchronous retention sink for started, complete or failed attempt records.
            Persist the complete record to retain resolved config, evidence and identities.
        consume: Optional trade-batch observer shared with notebook plots; its failures propagate.
            Book results remain in the typed dataset and are never sent as trade batches.

    Returns:
        Completed report. Multi-input reports retain the dataset, trade summaries and total
        duration. Single-query reports also include separate query time and resource metrics.
        RSS is the process lifetime high-water mark (macOS/Linux); input-block delta is
        OS block I/O, not application reads, and may be zero for cached inputs.

    Raises:
        ValueError: Configuration, budget, admission or query validation fails.
        OSError: A required input or report sink is unavailable.
        Exception: Consumer or reporting failure propagates after a failed attempt report.
    """
    started, before = perf_counter(), resource.getrusage(resource.RUSAGE_SELF)
    record: dict[str, object] = {"status": "started", "stage": "configuration"}
    try:
        report(dict(record))
        codec = DomainCodec()
        with config.open("rb") as source:
            payload = source.read(1_048_577)
        if len(payload) > 1_048_576:
            raise ValueError("EDA config exceeds one MiB")
        fields = msgspec.json.decode(payload, type=dict[str, msgspec.Raw])
        version = codec.decode_json(fields.get("schema_version", b'"eda-query-v1"'), str)
        if version == "research-selection-v1":
            selection = codec.decode_json(payload, ResearchSelection)
            record.update(
                config=selection,
                config_identity=hashlib.sha256(codec.encode_json(selection)).hexdigest(),
                selection_identity=selection.identity,
                implementation_identity=ImplementationIdentity.sha256(),
                stage="research_inputs",
            )
            dataset = ResearchReader(snapshots, raw, readers=SourceAdapters()).read(selection)
            summaries = tuple(
                (item.name, QuerySummary.collect(item.batches, consume=consume))
                for item in dataset.inputs
                if isinstance(item, TradeResearchInput)
            )
            record.update(
                status="complete",
                dataset=dataset,
                trade_summaries=summaries,
                duration_seconds=perf_counter() - started,
            )
            report(dict(record))
            return record
        selected = codec.decode_json(payload, EdaQuery)
        record.update(
            config=selected,
            config_identity=hashlib.sha256(codec.encode_json(selected)).hexdigest(),
            implementation_identity=ImplementationIdentity.sha256(),
            stage="snapshot",
        )
        reader = QueryReader.read(
            snapshots,
            raw,
            readers=SourceAdapters(),
            identity=selected.snapshot_id,
            max_bytes=selected.max_bytes,
            precedence=selected.precedence,
        )
        query_started = perf_counter()
        record["stage"] = "query"
        summary = QuerySummary.collect(
            reader.batches(
                selected.instruments,
                start=selected.start,
                end=selected.end,
                known_at=selected.known_at,
                columns=selected.columns,
                batch_size=selected.batch_size,
                mode=selected.mode,
            ),
            consume=consume,
        )
        usage = resource.getrusage(resource.RUSAGE_SELF)
        record.update(
            summary,
            status="complete",
            query_seconds=perf_counter() - query_started,
            duration_seconds=perf_counter() - started,
            process_peak_rss_bytes=usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
            process_input_blocks=usage.ru_inblock - before.ru_inblock,
        )
        report(dict(record))
        return record
    except (Exception, KeyboardInterrupt) as error:
        record.update(
            status="failed",
            error_type=type(error).__name__,
            diagnostic=str(error),
            duration_seconds=perf_counter() - started,
        )
        report(dict(record))
        raise


def inspect_experiment(
    config: Path,
    snapshots: Path,
    raw: RawStore,
    *,
    attempts: Path,
    tracking: ClearMLDestination | None = None,
) -> AttemptHistory:
    """Retain a pinned exploration study and its complete evidence through the attempt core.

    Args:
        config: Strict ExplorationStudy or FeatureStudy JSON, limited to one MiB; no fitting.
        snapshots: Existing immutable snapshot root; missing inputs fail the retained attempt.
        raw: Retained originals required for snapshot admission.
        attempts: Local retained single-writer root containing the complete family history.
        tracking: Explicit ClearML destination for formal tracked invocations; omitted for
            compatibility with existing local exploratory consumers.

    Returns:
        Completed history containing encoded dataset, summaries and explicit no-fit status.
        Final holdout access is recorded before reading values, including failed reads.

    Raises:
        ValueError: Invalid configuration, changed frozen holdout or incompatible data.
        OSError: Missing inputs, unavailable store or writer contention.
        Exception: Workflow failures propagate after retaining an unsuccessful outcome.
    """
    codec = DomainCodec()
    with config.open("rb") as source:
        payload = source.read(1_048_577)
    if len(payload) > 1_048_576:
        raise ValueError("study config exceeds one MiB")
    fields = msgspec.json.decode(payload, type=dict[str, msgspec.Raw])
    version = codec.decode_json(fields.get("schema_version", b'"exploration-study-v1"'), str)
    study: ExplorationStudy | FeatureStudy = (
        codec.decode_json(payload, FeatureStudy)
        if version == "feature-study-v1"
        else codec.decode_json(payload, ExplorationStudy)
    )
    spec = study.specification(
        implementation=ImplementationIdentity.sha256(),
        environment=ExperimentSpec.installed_environment(),
    )
    with AttemptStore(attempts) as store:
        publication = None if tracking is None else ClearMLPublication(store, tracking)
        before = {history.start.attempt_id for history in store.histories()}
        try:
            start = store.start(
                spec,
                at=datetime.now(UTC),
                invocation=f"inspect_experiment(config={config!s}, snapshots={snapshots!s})",
                request=payload,
            )
        except ValueError:
            # The store retains a changed-holdout rejection before raising.
            if publication is not None:
                for history in store.histories():
                    if history.start.attempt_id not in before:
                        publication.enqueue(history.start.attempt_id)
                        publication.publish(history.start.attempt_id)
            raise
        if publication is not None:
            publication.enqueue(start.attempt_id)
        try:
            if study.partition == "holdout":
                try:
                    store.consume_holdout(
                        start.attempt_id,
                        at=datetime.now(UTC),
                        reason="declared final inspection or unchanged reproduction",
                    )
                except ValueError as error:
                    store.finish(
                        start.attempt_id, status="rejected", at=datetime.now(UTC), reason=str(error)
                    )
                    raise
            reader = ResearchReader(snapshots, raw, readers=SourceAdapters())
            if isinstance(study, FeatureStudy):
                result = study.evaluate(reader)
            else:
                dataset = reader.read(study.selection)
                summaries = tuple(
                    (item.name, QuerySummary.collect(item.batches))
                    for item in dataset.inputs
                    if isinstance(item, TradeResearchInput)
                )
                result = codec.encode_json(
                    {
                        "dataset": dataset,
                        "trade_summaries": summaries,
                        "fitting": "not applicable: exploration inspection has no fitted state",
                        "split_identity": study.split.identity,
                    }
                )
            completed = store.finish(
                start.attempt_id,
                status="completed",
                at=datetime.now(UTC),
                reason="verified pinned exploration completed",
                result=result,
            )
        except (Exception, KeyboardInterrupt) as error:
            # A failure after atomic publication can have an uncertain outcome.
            # Reload before deciding whether a failure event is still permissible.
            if store.read(start.attempt_id).status == "incomplete":
                store.finish(
                    start.attempt_id,
                    status="abandoned" if isinstance(error, KeyboardInterrupt) else "failed",
                    at=datetime.now(UTC),
                    reason=f"{type(error).__name__}: {error}",
                )
            if publication is not None:
                publication.publish(start.attempt_id)
            raise
        if publication is not None:
            publication.publish(start.attempt_id)
        return completed
