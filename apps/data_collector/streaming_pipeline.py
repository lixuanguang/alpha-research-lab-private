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
import apps.data_collector.connectors._streaming as connector_streaming
import apps.data_collector.connectors._types as connector_types
import apps.data_collector.event_types as collector_event_types

_LOGGER = logging.getLogger(__name__)


class StreamingPipeline:
    """Continuous: stream → quality filter → store bronze → buffer silver → flush.

    The pipeline wires a :class:`~connector_streaming.StreamingConnector` to storage.
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
        connector: connector_streaming.StreamingConnector,
        bronze_writer: storage_bronze.BronzeWriter,
        streaming_writer: storage_streaming.StreamingParquetWriter,
        quality_checker: event_quality.EventQualityChecker,
        lineage_store: storage_lineage.LineageStore,
        max_events: int | None = None,
    ) -> None:
        if max_events is not None and max_events <= 0:
            raise ValueError("`max_events` must be > 0 when configured")
        self._connector = connector
        self._bronze_writer = bronze_writer
        self._streaming_writer = streaming_writer
        self._quality_checker = quality_checker
        self._lineage_store = lineage_store
        self._max_events = max_events

        # Mutable counters accumulated during a run.
        self._counts: dict[str, int] = defaultdict(int)
        self._errors: list[str] = []
        self._run: storage_lineage.IngestionRun | None = None
        self._stop_requested = False

        # Wire the emit callback.
        self._connector.set_emit_callback(self._on_events)

    @property
    def connector_id(self) -> str:
        """Expose connector id for runtime orchestration and logging."""
        return self._connector.connector_id

    async def run(self) -> storage_lineage.IngestionRun:
        """Start the connector and run until it stops.

        Returns the completed (or failed) :class:`~storage_lineage.IngestionRun`.
        """
        run_id = self._begin_run()
        try:
            await self._run_connector()
        except asyncio.CancelledError:
            self._errors.append("streaming pipeline cancelled")
        except Exception as exc:
            _LOGGER.error("Streaming pipeline error: %s", exc)
            self._errors.append(str(exc))
        finally:
            await self._shutdown_connector()
            self._close_streaming_writer()

        self._capture_connector_error_state()
        if self._errors:
            return self._finalize_failed_run(run_id=run_id)

        return self._finalize_completed_run(run_id=run_id)

    async def stop(self) -> None:
        """Request connector shutdown for external orchestration paths."""
        await self._connector.stop()
        await self._connector.cancel_run_task()

    # ------------------------------------------------------------------
    # emit callback — called for each batch from the connector
    # ------------------------------------------------------------------

    def _on_events(self, events: list[event_models.CanonicalMarketEvent]) -> None:
        if not events:
            return

        self._counts["events_raw"] += len(events)

        # Log gap markers for observability; they flow through like any other event.
        for event in events:
            if event.is_reconnect_gap:
                _LOGGER.warning(
                    "Reconnect gap marker received: connector=%s instrument=%s",
                    self._connector.connector_id,
                    event.instrument_id,
                )
                self._counts["reconnect_gaps"] += 1

        valid_events = self._filter_valid_events(events)
        if valid_events:
            self._write_bronze_events(valid_events)
            self._append_silver_events(valid_events)
        self._maybe_request_stop()

    def _begin_run(self) -> str:
        self._counts.clear()
        self._errors.clear()
        self._stop_requested = False
        self._run = self._lineage_store.start_run(
            venue=self._connector.venue,
            connector_type="streaming",
            event_types=["trades", "books"],
            config_snapshot={
                "connector_id": self._connector.connector_id,
                "started_at": datetime.now(tz=UTC).isoformat(),
            },
        )
        return self._run.run_id

    async def _run_connector(self) -> None:
        await self._connector.start()
        await self._connector.wait_until_stopped()

    async def _shutdown_connector(self) -> None:
        await self._connector.cancel_run_task()

    def _close_streaming_writer(self) -> None:
        try:
            self._streaming_writer.close()
        except Exception as exc:
            _LOGGER.error("Streaming writer close error: %s", exc)
            self._errors.append(f"streaming writer close error: {exc}")

    def _capture_connector_error_state(self) -> None:
        if self._connector.state is not connector_types.ConnectorState.ERROR or self._errors:
            return
        connector_errors = self._connector.metrics().errors
        if connector_errors:
            self._errors.append(connector_errors[-1])
        else:
            self._errors.append("connector entered error state")

    def _finalize_completed_run(self, *, run_id: str) -> storage_lineage.IngestionRun:
        self._lineage_store.complete_run(
            run_id,
            counts=dict(self._counts),
            errors=[],
        )
        completed = self._lineage_store.get_run(run_id)
        if completed is None:
            raise RuntimeError("Lineage run was not persisted")
        return completed

    def _filter_valid_events(
        self,
        events: list[event_models.CanonicalMarketEvent],
    ) -> list[event_models.CanonicalMarketEvent]:
        valid_events: list[event_models.CanonicalMarketEvent] = []
        for event in events:
            if self._quality_checker.check(event).is_valid:
                valid_events.append(event)
            else:
                self._counts["rejected"] += 1
        return valid_events

    def _write_bronze_events(self, events: list[event_models.CanonicalMarketEvent]) -> None:
        grouped_payloads = self._group_bronze_payloads(events)
        run_id = self._run.run_id if self._run is not None else "unknown"
        for event_type, payloads in grouped_payloads.items():
            try:
                self._bronze_writer.write_raw_events(
                    payloads,
                    venue=self._connector.venue,
                    event_type=event_type,
                    run_id=run_id,
                )
            except Exception as exc:
                self._raise_fatal_error(f"bronze write error: {exc}", cause=exc)

    def _group_bronze_payloads(
        self,
        events: list[event_models.CanonicalMarketEvent],
    ) -> dict[str, list[dict[str, object]]]:
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for event in events:
            grouped[collector_event_types.dataset_key_for_event(event)].append(
                event.model_dump(mode="json")
            )
        return grouped

    def _append_silver_events(self, events: list[event_models.CanonicalMarketEvent]) -> None:
        for event in events:
            if isinstance(event, event_models.CanonicalMetadataUpdate):
                self._counts["metadata_skipped"] += 1
                continue
            try:
                self._streaming_writer.append(event)
                self._counts["events_silver"] += 1
            except Exception as exc:
                self._raise_fatal_error(f"streaming writer error: {exc}", cause=exc)

    def _maybe_request_stop(self) -> None:
        if (
            self._max_events is None
            or self._counts["events_raw"] < self._max_events
            or self._stop_requested
        ):
            return
        self._stop_requested = True
        try:
            asyncio.get_running_loop().create_task(self._connector.stop())
        except RuntimeError:
            pass

    def _raise_fatal_error(self, message: str, *, cause: Exception) -> None:
        self._errors.append(message)
        raise connector_types.FatalConnectorError(message) from cause

    def _finalize_failed_run(self, *, run_id: str) -> storage_lineage.IngestionRun:
        self._lineage_store.fail_run(run_id, self._errors)
        failed = self._lineage_store.get_run(run_id)
        if failed is None:
            raise RuntimeError("Lineage run was not persisted")
        return failed


__all__ = ["StreamingPipeline"]
