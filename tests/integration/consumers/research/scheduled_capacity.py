"""Profile a tiny admitted scheduled-price path through an installed distribution.

This three-query-row synthetic diagnostic is not representative-input acceptance.
Copy this consumer and its explicit configuration inputs outside the checkout,
then run it with the installed interpreter and a fresh output directory.
"""

from __future__ import annotations

# standard library imports
import argparse
import cProfile
import hashlib
import math
import platform
import resource
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter_ns
from typing import Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from configuration import Configuration
from financial_units import Dimension, Price, QuantityKind
from market_data.adapters.providers.tardis import TardisDecoder
from market_data.adapters.sources import SourceAdapters
from market_data.adapters.venues.binance import BinancePayloadDecoder
from market_data.contracts import Occurrence, RawObject, SourceRequest, Trade
from market_data.query import InputBinding, QueryReader
from market_data.validation import Correction, QualityPolicy, TradeRevision
from reference_data.catalogs import CatalogSnapshot
from reference_data.eligibility import EligibilityAssertions
from research.features import ScheduledFeatures, ScheduledFeatureSpec
from runtime import ImplementationIdentity
from serialization import DomainCodec


class _Arguments(argparse.Namespace):
    """Select copied source contracts and a fresh diagnostic output directory."""

    job_config: Path
    catalog: Path
    eligibility: Path
    output: Path
    count: int
    profile: bool


class ScheduledCapacityDiagnostic:
    """Own one self-contained native admission and scheduled-close measurement."""

    _cadence_seconds = 10
    _trades: tuple[tuple[int, str, int], ...] = (
        (9, "100.03", 1),
        (19, "100.04", 2),
        (19, "999", 2),
        (29, "101", 3),
    )

    def __init__(self, args: _Arguments) -> None:
        """Bind the selected source contracts, schedule and evidence destination."""
        if args.count not in (32, 128, 8192):
            raise ValueError("diagnostic count must be 32, 128 or 8192")
        self.args = args
        self.output = args.output
        self.codec = DomainCodec()
        self.started_ns = perf_counter_ns()
        self.warm_seconds: list[float] = []
        self.facts: dict[str, object] = {
            "scope": "three-query-row synthetic diagnostic; not representative acceptance",
            "count": args.count,
            "cadence_seconds": self._cadence_seconds,
            "authored_native_occurrences": len(self._trades),
            "authored_correction_count": 1,
            "expected_query_history_rows": 3,
            "profiler_active": args.profile,
            "cache_condition": "fresh process and reader; OS page cache uncontrolled",
        }

    def run(self) -> None:
        """Retain raw samples and a complete or failed summary for one selected scale."""
        self.output.mkdir(parents=True, exist_ok=False)
        self.output = self.output.resolve()
        before = resource.getrusage(resource.RUSAGE_SELF)
        profiler = cProfile.Profile() if self.args.profile else None
        status, reason = "failed", "interrupted before completion"
        try:
            self.facts["consumer_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            self._execute(profiler)
            status, reason = "complete", ""
        except BaseException as error:
            reason = f"{type(error).__name__}: {error}"
            raise
        finally:
            try:
                if profiler is not None:
                    profiler.disable()
                    profiler.dump_stats(str(self.output / "profile.pstats"))
            finally:
                self._finish(status, reason, before)

    def _execute(self, profiler: cProfile.Profile | None) -> None:
        """Admit the corrected native rows, then time cold and warm closes separately."""
        implementation = ImplementationIdentity.sha256()
        self.facts["implementation_sha256"] = implementation
        for name, path in (
            ("job_config", self.args.job_config),
            ("catalog", self.args.catalog),
            ("eligibility", self.args.eligibility),
        ):
            self.facts[f"{name}_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        started = perf_counter_ns()
        reader, request, canonical_sha256, quality_scope = self._source(implementation)
        definition = self._definition(request)
        self.facts.update(
            source_request_identity=request.identity,
            query_reader_identity=reader.identity,
            config_identity=definition.identity,
            canonical_sha256=canonical_sha256,
            quality_scope=quality_scope,
            source_interval_end=request.end,
            scheduled_interval_end=definition.end,
        )
        self._record("source_setup", 0, perf_counter_ns() - started)
        if profiler is not None:
            profiler.enable()
        started = perf_counter_ns()
        scheduled = ScheduledFeatures(reader, definition, batch_size=1)
        self._record("scheduled_constructor", 0, perf_counter_ns() - started)
        for index in range(1, self.args.count + 1):
            at = definition.start + timedelta(seconds=index * self._cadence_seconds)
            self.facts["attempted_close"] = index
            started = perf_counter_ns()
            scheduled.evaluate(at)
            elapsed_ns = perf_counter_ns() - started
            phase: Literal["first_close", "warm_close"] = (
                "first_close" if index == 1 else "warm_close"
            )
            self._record(phase, index, elapsed_ns)
            if index > 1:
                self.warm_seconds.append(elapsed_ns / 1_000_000_000)
        self.facts["values_sha256"] = scheduled.checkpoint.values_sha256
        self.facts["completed_closes"] = len(scheduled.checkpoint.values)
        if profiler is not None:
            profiler.disable()
        query_rows = sum(
            len(batch.rows)
            for batch in reader.batches(
                (definition.binding[2],),
                start=definition.start,
                end=definition.end,
                known_at=definition.end,
                columns=("revision",),
                batch_size=1,
                mode="history",
            )
        )
        if query_rows != 3:
            raise ValueError("scheduled diagnostic query history differs from three rows")
        self.facts["admitted_query_history_rows"] = query_rows

    def _source(self, implementation: str) -> tuple[QueryReader, SourceRequest, str, str]:
        """Admit four native lines, one correction and three query-history rows."""
        configuration = Configuration.read(self.args.job_config)
        catalog = self.codec.decode_json(self.args.catalog.read_bytes(), CatalogSnapshot)
        manifest = configuration.resolve(
            "both-fixture", catalog, implementation_identity=implementation
        )
        request = SourceRequest(
            manifest=manifest, instrument=manifest.instruments[0], offset_minutes=0
        )
        lines = tuple(
            self._line(request, second, price, trade_id) for second, price, trade_id in self._trades
        )
        native = b"".join(lines)
        origin = RawObject(
            sha256=hashlib.sha256(native).hexdigest(),
            size_bytes=len(native),
            request_identity=request.identity,
            retrieval_reference="synthetic:scheduled-capacity-diagnostic",
            ts_received=request.start + timedelta(days=1),
            ts_ingested=request.start + timedelta(days=1),
        )
        decoder = TardisDecoder(
            BinancePayloadDecoder(request.manifest.instruments), request.instrument.source
        )
        items: list[Occurrence] = []
        for position, raw in enumerate(lines):
            at = request.start + timedelta(seconds=self._trades[position][0])
            event = decoder.decode_line(
                raw.decode().rstrip("\n"),
                source_sequence=position,
                source_digest=origin.sha256,
                local_received=origin.ts_received,
                local_ingested=origin.ts_ingested,
                disconnect_capture_time=at,
            )
            if not isinstance(event, Trade):
                raise ValueError("scheduled diagnostic requires native trades")
            items.append(
                Occurrence(request=request, origin=origin, position=position, raw=raw, event=event)
            )
        history = self.codec.decode_json(self.args.eligibility.read_bytes(), EligibilityAssertions)
        correction_at = request.start + timedelta(seconds=25)
        correction = Correction(
            supersedes=TradeRevision(occurrences=(items[1],)).identity,
            replacement=TradeRevision(occurrences=(items[2],)).identity,
            ts_published=correction_at,
            ts_available=correction_at,
            evidence_reference="synthetic:scheduled-capacity-correction",
        )
        quality = QualityPolicy(
            use="exploratory", known_at=request.start, max_gap=timedelta(hours=1)
        ).validate(
            request,
            tuple(items),
            eligibility=replace(history, catalog=request.manifest.catalog),
            corrections=(correction,),
            verifier=SourceAdapters.verifier(request),
        )
        canonical = quality.require_canonical()
        binding: InputBinding = (
            request.instrument.source,
            request.manifest.job.stream,
            request.instrument.instrument_id,
        )
        reader = QueryReader(
            (canonical,), readers=SourceAdapters(), precedence=(binding,), max_bytes=262_144
        )
        return reader, request, hashlib.sha256(canonical).hexdigest(), quality.scope

    def _line(self, request: SourceRequest, second: int, price: str, trade_id: int) -> bytes:
        """Author one captured native frame with explicit event and knowledge clocks."""
        at = request.start + timedelta(seconds=second)
        timestamp_ms = int(at.timestamp() * 1000)
        payload = self.codec.encode_json(
            {
                "stream": request.instrument.symbol.lower() + "@trade",
                "data": {
                    "e": "trade",
                    "E": timestamp_ms,
                    "T": timestamp_ms,
                    "s": request.instrument.symbol,
                    "t": trade_id,
                    "p": price,
                    "q": "2.0",
                    "m": True,
                },
            }
        )
        return at.isoformat().replace("+00:00", "Z").encode() + b" " + payload + b"\n"

    def _definition(self, request: SourceRequest) -> ScheduledFeatureSpec:
        """Keep the original ten-second schedule and exact spot price dimensions."""
        instrument = request.instrument
        return ScheduledFeatureSpec(
            instance="scheduled-capacity-diagnostic",
            binding=(instrument.source, request.manifest.job.stream, instrument.instrument_id),
            tick=Price(
                value=Decimal("0.01"),
                currency=instrument.quote_currency,
                per=Dimension(instrument_id=instrument.instrument_id, kind=QuantityKind.BASE_UNIT),
            ),
            start=request.start,
            end=request.start + timedelta(seconds=(self.args.count + 1) * self._cadence_seconds),
            cadence_seconds=self._cadence_seconds,
            max_age_seconds=5,
        )

    def _record(self, phase: str, index: int, elapsed_ns: int) -> None:
        """Flush one complete raw timing sample before attempting the next close."""
        sample = {"phase": phase, "close_index": index, "elapsed_ns": elapsed_ns}
        with (self.output / "samples.jsonl").open("ab") as output:
            output.write(self.codec.encode_json(sample) + b"\n")

    @staticmethod
    def _percentiles(values: list[float]) -> dict[str, float] | None:
        """Use empirical nearest ranks only after at least 1,000 warm samples."""
        if len(values) < 1000:
            return None
        ordered = sorted(values)
        return {
            str(percent): ordered[math.ceil(percent / 100 * len(ordered)) - 1]
            for percent in (50, 95, 99)
        }

    def _finish(self, status: str, reason: str, before: resource.struct_rusage) -> None:
        """Write identities, summary timing and process resources even after failure."""
        after = resource.getrusage(resource.RUSAGE_SELF)
        scale = 1 if sys.platform == "darwin" else 1024
        summary = {
            **self.facts,
            "status": status,
            "reason": reason,
            "elapsed_total_seconds": (perf_counter_ns() - self.started_ns) / 1_000_000_000,
            "warm_close_count": len(self.warm_seconds),
            "warm_close_total_seconds": sum(self.warm_seconds),
            "warm_close_min_seconds": min(self.warm_seconds) if self.warm_seconds else None,
            "warm_close_max_seconds": max(self.warm_seconds) if self.warm_seconds else None,
            "warm_nearest_rank_seconds": self._percentiles(self.warm_seconds),
            "cpu_user_seconds": after.ru_utime - before.ru_utime,
            "cpu_system_seconds": after.ru_stime - before.ru_stime,
            "peak_rss_bytes": after.ru_maxrss * scale,
            "input_blocks_delta": after.ru_inblock - before.ru_inblock,
            "output_blocks_delta": after.ru_oublock - before.ru_oublock,
            "platform": platform.platform(),
            "python": sys.version,
            "representative_acceptance": False,
        }
        (self.output / "measurement.json").write_bytes(self.codec.encode_json(summary))
        print(self.codec.encode_json(summary).decode(), flush=True)


def main() -> None:
    """Run one installed diagnostic with copied contracts and retained evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-config", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--eligibility", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, choices=(32, 128, 8192), required=True)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args(namespace=_Arguments())
    ScheduledCapacityDiagnostic(args).run()


if __name__ == "__main__":
    main()
