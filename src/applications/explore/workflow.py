"""Inspect one configured saved query and emit retainable JSON attempt records."""

from __future__ import annotations

# standard library imports
import hashlib
import resource
import sys
from collections.abc import Callable
from pathlib import Path
from time import perf_counter

# third party library imports
import msgspec

# project library imports
from market_data.adapters.sources import SourceAdapters
from market_data.query import QueryBatch, QueryReader
from market_data.storage import RawStore
from research.exploration import (
    EdaQuery,
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
