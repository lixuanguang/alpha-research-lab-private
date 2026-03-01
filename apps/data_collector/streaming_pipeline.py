"""End-to-end streaming ingestion pipeline."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime

import alpha_core.events.models as event_models
import alpha_core.events.quality as event_quality
import alpha_core.storage.bronze_writer as storage_bronze
import alpha_core.storage.lineage as storage_lineage
import alpha_core.storage.streaming_writer as storage_streaming
import apps.data_collector.connectors.base as connector_base

_LOGGER = logging.getLogger(__name__)


class StreamingPipeline:
    """Continuous: stream → quality filter → store bronze → buffer silver → flush.

    The pipeline wires a :class:`~connector_base.StreamingConnector` to storage.
    Events flow through the connector's ``emit`` callback and are:

    1. Quality-filtered by :class:`~event_quality.EventQualityChecker`.
    2. Written to bronze in batches (one batch per emit invocation).
    3. Appended to the :class:`~storage_streaming.StreamingParquetWriter`, which
       handles its own size/time-based flush schedule.

    A single :class:`~storage_lineage.IngestionRun` spans the entire session and
    is completed (or failed) when :meth:`run` exits.

    Args:
        connector:        Streaming connector to start and supervise.
        bronze_writer:    Writes raw event payloads to the bronze tier.
        streaming_writer: Buffers and periodically flushes silver Parquet.
        quality_checker:  Validates each event before storage.
        lineage_store:    Records run metadata for auditability.
    """

    def __init__(
        self,
        connector: connector_base.StreamingConnector,
        bronze_writer: storage_bronze.BronzeWriter,
        streaming_writer: storage_streaming.StreamingParquetWriter,
        quality_checker: event_quality.EventQualityChecker,
        lineage_store: storage_lineage.LineageStore,
    ) -> None:
        self._connector = connector
        self._bronze_writer = bronze_writer
        self._streaming_writer = streaming_writer
        self._quality_checker = quality_checker
        self._lineage_store = lineage_store

        # Mutable counters accumulated during a run.
        self._counts: dict[str, int] = defaultdict(int)
        self._errors: list[str] = []
        self._run: storage_lineage.IngestionRun | None = None

        # Wire the emit callback.
        self._connector.set_emit_callback(self._on_events)

    async def run(self) -> storage_lineage.IngestionRun:
        """Start the connector and run until it stops.

        Returns the completed (or failed) :class:`~storage_lineage.IngestionRun`.
        """
        self._counts.clear()
        self._errors.clear()
        self._run = self._lineage_store.start_run(
            venue=self._connector.venue,
            connector_type="streaming",
            event_types=["trades", "books"],
            config_snapshot={
                "connector_id": self._connector.connector_id,
                "started_at": datetime.now(tz=UTC).isoformat(),
            },
        )
        run_id = self._run.run_id

        try:
            await self._connector.start()
            # Wait until the connector task finishes (e.g. stop() was called).
            await self._connector.wait_until_stopped()
        except asyncio.CancelledError:
            self._errors.append("streaming pipeline cancelled")
        except Exception as exc:
            _LOGGER.error("Streaming pipeline error: %s", exc)
            self._errors.append(str(exc))
        finally:
            await self._connector.cancel_run_task()
            try:
                self._streaming_writer.close()
            except Exception as exc:
                _LOGGER.error("Streaming writer close error: %s", exc)
                self._errors.append(f"streaming writer close error: {exc}")

        if self._connector.state is connector_base.ConnectorState.ERROR and not self._errors:
            connector_errors = self._connector.metrics().errors
            if connector_errors:
                self._errors.append(connector_errors[-1])
            else:
                self._errors.append("connector entered error state")

        if self._errors:
            return self._finalize_failed_run(run_id=run_id)

        self._lineage_store.complete_run(
            run_id,
            counts=dict(self._counts),
            errors=[],
        )
        completed = self._lineage_store.get_run(run_id)
        if completed is None:
            raise RuntimeError("Lineage run was not persisted")
        return completed

    # ------------------------------------------------------------------
    # emit callback — called for each batch from the connector
    # ------------------------------------------------------------------

    def _on_events(self, events: list[event_models.CanonicalMarketEvent]) -> None:
        if not events:
            return

        self._counts["events_raw"] += len(events)

        # Quality filter.
        valid: list[event_models.CanonicalMarketEvent] = []
        for event in events:
            report = self._quality_checker.check(event)
            if report.is_valid:
                valid.append(event)
            else:
                self._counts["rejected"] += 1

        # Bronze: store raw event payloads (serialised from canonical model).
        if valid:
            grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
            for event in valid:
                grouped[_event_type_key(event)].append(event.model_dump(mode="json"))
            run_id = self._run.run_id if self._run is not None else "unknown"
            for event_type, payloads in grouped.items():
                try:
                    self._bronze_writer.write_raw_events(
                        payloads,
                        venue=self._connector.venue,
                        event_type=event_type,
                        run_id=run_id,
                    )
                except Exception as exc:
                    message = f"bronze write error: {exc}"
                    self._errors.append(message)
                    raise connector_base.FatalConnectorError(message) from exc

        # Silver: buffer into streaming writer (auto-flush on size/time).
        for event in valid:
            try:
                self._streaming_writer.append(event)
                self._counts["events_silver"] += 1
            except Exception as exc:
                message = f"streaming writer error: {exc}"
                self._errors.append(message)
                raise connector_base.FatalConnectorError(message) from exc

    def _finalize_failed_run(self, *, run_id: str) -> storage_lineage.IngestionRun:
        self._lineage_store.fail_run(run_id, self._errors)
        failed = self._lineage_store.get_run(run_id)
        if failed is None:
            raise RuntimeError("Lineage run was not persisted")
        return failed


def _event_type_key(event: event_models.CanonicalMarketEvent) -> str:
    if isinstance(event, event_models.CanonicalTrade):
        return "trades"
    if isinstance(event, event_models.CanonicalBookSnapshot):
        return "books"
    if isinstance(event, event_models.CanonicalOHLCV):
        return "ohlcv"
    return "metadata"


__all__ = ["StreamingPipeline"]
