"""Bind Tardis Binance trade fixtures to resolved source requests."""

from __future__ import annotations

# standard library imports
from datetime import datetime, timedelta

# project library imports
from configuration import ResolvedManifest
from market_data.adapters.providers.tardis.decoder import TardisDecoder
from market_data.adapters.venues.binance import BinancePayloadDecoder, MarketEventCodec
from market_data.contracts import FixtureReader, MarketEventRecord, SourceRequest, Trade


class TardisTradeFixture(FixtureReader):
    """Decode one Tardis Binance trade fixture under a resolved job boundary."""

    __slots__ = ("_decoder", "_manifest")

    def __init__(self, manifest: ResolvedManifest) -> None:
        """Bind the configured Tardis and Binance decoders to a fixture manifest.

        Args:
            manifest: Resolved fixture selection with Tardis Binance trade metadata.

        Raises:
            TypeError: The supplied value is not a resolved manifest.
            ValueError: The manifest is invalid or is not a dataset fixture job.
        """
        if type(manifest) is not ResolvedManifest:
            raise TypeError("fixture requires a ResolvedManifest")
        manifest.__post_init__()
        if manifest.job.pipeline != "dataset.inspect":
            raise ValueError("fixture inspection requires the dataset.inspect pipeline")
        self._manifest = manifest
        self._decoder = TardisDecoder(
            BinancePayloadDecoder(manifest.instruments),
            source_id=manifest.instruments[0].source,
        )

    def decode(
        self,
        line: str,
        *,
        local_received: datetime,
        local_ingested: datetime,
        source_sequence: int,
        source_digest: str,
    ) -> tuple[SourceRequest, MarketEventRecord]:
        """Decode one Tardis line and bind its trade to the capture minute.

        Args:
            line: One bounded Tardis source line without its file terminator.
            local_received: Original local receipt timestamp retained by the caller.
            local_ingested: Original local durable-ingestion timestamp.
            source_sequence: Original zero-based source line position.
            source_digest: SHA-256 digest of the retained source bytes.

        Returns:
            The source request for the capture minute and its canonical trade event.

        Raises:
            ValueError: The stream, capture interval, or event codec contract is invalid.
            TypeError: A decoder boundary value has an invalid type.
        """
        self._manifest.__post_init__()
        event = self._decoder.decode_line(
            line,
            source_sequence=source_sequence,
            local_received=local_received,
            local_ingested=local_ingested,
            source_digest=source_digest,
        )
        if not isinstance(event, Trade):
            raise ValueError("configured stream is trade; fixture contains a different event kind")
        capture = event.provenance.ts_source_received
        if capture is None or not self._manifest.job.start <= capture < self._manifest.job.end:
            raise ValueError(
                "fixture capture timestamp is outside the configured half-open interval"
            )
        request = SourceRequest(
            manifest=self._manifest,
            instrument=next(
                item
                for item in self._manifest.instruments
                if item.instrument_id == event.instrument_id
            ),
            offset_minutes=(capture - self._manifest.job.start) // timedelta(minutes=1),
        )
        MarketEventCodec.validate(event)
        return request, event
