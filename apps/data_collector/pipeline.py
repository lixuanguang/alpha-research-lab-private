"""End-to-end polling ingestion pipeline."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

import alpha_core.events.models as event_models
import alpha_core.events.quality as event_quality
import alpha_core.storage.bronze_writer as storage_bronze
import alpha_core.storage.lineage as storage_lineage
import alpha_core.storage.parquet_writer as storage_parquet
import apps.data_collector.connectors._polling as connector_polling
import apps.data_collector.event_types as collector_event_types


class PollingPipeline:
    """End-to-end: poll → normalise → store bronze → store silver → validate."""

    def __init__(
        self,
        connector: connector_polling.PollingConnector,
        bronze_writer: storage_bronze.BronzeWriter,
        silver_writer: storage_parquet.ParquetEventWriter,
        quality_checker: event_quality.EventQualityChecker,
        lineage_store: storage_lineage.LineageStore,
    ) -> None:
        self.connector = connector
        self._bronze_writer = bronze_writer
        self._silver_writer = silver_writer
        self._quality_checker = quality_checker
        self._lineage_store = lineage_store

    async def execute(self) -> storage_lineage.IngestionRun:
        """Run one polling cycle with full pipeline."""
        default_event_types = self.connector.event_types()
        run = self._lineage_store.start_run(
            venue=self.connector.venue,
            connector_type="polling",
            event_types=default_event_types,
            config_snapshot={
                "connector_id": self.connector.connector_id,
                "interval_seconds": self.connector.interval_seconds,
                "executed_at": datetime.now(tz=UTC).isoformat(),
            },
        )

        try:
            batch = await self.connector.execute_cycle()
            self._write_bronze(
                events=batch.events,
                raw_payloads=batch.raw_payloads,
                run_id=run.run_id,
            )

            valid_events, rejected_count = self._filter_quality(batch.events)
            written_counts = self._write_silver(valid_events)

            counts = {
                "events_raw": len(batch.events),
                "rejected": rejected_count,
                **written_counts,
            }
            self._lineage_store.complete_run(run.run_id, counts=counts, errors=[])
            completed = self._lineage_store.get_run(run.run_id)
            if completed is None:
                raise RuntimeError("Lineage run was not persisted")
            return completed
        except Exception as exc:
            self._lineage_store.fail_run(run.run_id, str(exc))
            failed = self._lineage_store.get_run(run.run_id)
            if failed is None:
                raise RuntimeError("Lineage run was not persisted") from exc
            return failed

    def _write_bronze(
        self,
        *,
        events: list[event_models.CanonicalMarketEvent],
        raw_payloads: dict[str, list[dict[str, object]]],
        run_id: str,
    ) -> None:
        if any(raw_payloads.values()):
            for event_type, payloads in raw_payloads.items():
                if not payloads:
                    continue
                self._bronze_writer.write_raw_events(
                    payloads,
                    venue=self.connector.venue,
                    event_type=event_type,
                    run_id=run_id,
                )
            return

        grouped_payloads: dict[str, list[dict[str, object]]] = defaultdict(list)
        for event in events:
            event_type = collector_event_types.dataset_key_for_event(event)
            grouped_payloads[event_type].append(event.model_dump(mode="json"))

        for event_type, payloads in grouped_payloads.items():
            self._bronze_writer.write_raw_events(
                payloads,
                venue=self.connector.venue,
                event_type=event_type,
                run_id=run_id,
            )

    def _filter_quality(
        self,
        events: list[event_models.CanonicalMarketEvent],
    ) -> tuple[list[event_models.CanonicalMarketEvent], int]:
        valid_events: list[event_models.CanonicalMarketEvent] = []
        rejected = 0
        for event in events:
            report = self._quality_checker.check(event)
            if report.is_valid:
                valid_events.append(event)
                continue
            rejected += 1
        return valid_events, rejected

    def _write_silver(self, events: list[event_models.CanonicalMarketEvent]) -> dict[str, int]:
        trades: list[event_models.CanonicalTrade] = []
        books: list[event_models.CanonicalBookSnapshot] = []
        candles: list[event_models.CanonicalOHLCV] = []
        metadata_updates = 0

        for event in events:
            if isinstance(event, event_models.CanonicalTrade):
                trades.append(event)
            elif isinstance(event, event_models.CanonicalBookSnapshot):
                books.append(event)
            elif isinstance(event, event_models.CanonicalOHLCV):
                candles.append(event)
            elif isinstance(event, event_models.CanonicalMetadataUpdate):
                metadata_updates += 1

        if trades:
            self._silver_writer.write_trades(trades)
        if books:
            self._silver_writer.write_books(books)
        if candles:
            self._silver_writer.write_ohlcv(candles)

        return {
            "events_silver": len(trades) + len(books) + len(candles),
            "trades_written": len(trades),
            "books_written": len(books),
            "ohlcv_written": len(candles),
            "metadata_skipped": metadata_updates,
        }


__all__ = ["PollingPipeline"]
