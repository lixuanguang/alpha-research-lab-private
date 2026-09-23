"""Exercise installed economics, fresh-process recovery and tracked vectorbt publication."""

from __future__ import annotations

# standard library imports
import os
import shutil
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# third party library imports
from msgspec.structs import replace

# project library imports
import simulation
from applications.backtest import (
    compare_parameters,
    compare_vectorbt,
    qualify_scheduled_features,
    run_backtest,
    run_configured,
)
from configuration import Configuration
from financial_units import ExactRatio
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import SourceRequest
from market_data.datasets import DatasetPublication
from market_data.query import QueryReader
from market_data.storage import RawFiles, RawStore
from market_data.validation import Correction, QualityPolicy, TradeRevision
from reference_data.catalogs import CatalogSnapshot
from reference_data.eligibility import EligibilityAssertions
from research.experiments import (
    AttemptStore,
    BacktestRun,
    BenchmarkPeriod,
    ClearMLDestination,
    ClearMLPublication,
    ComparisonStudy,
    PublicationReceipt,
    ReportPolicy,
    ResultManifest,
    TemporalSplit,
    TimeWindow,
)
from research.features import (
    ScheduledFeatureCheckpoint,
    ScheduledFeatureParity,
    ScheduledFeatures,
    TrailingReturn,
    WindowPolicy,
)
from serialization import DomainCodec
from simulation import (
    BacktestSpec,
    EconomicCheckpoint,
    EconomicResult,
    VectorbtAdapter,
    VectorbtResult,
)


class _ReportInterruption:
    """Interrupt the real atomic report rename after earlier output files exist."""

    def __init__(self) -> None:
        """Keep the actual filesystem operation for unrelated attempt records."""
        self._replace = os.replace

    def __call__(self, source: Path, destination: Path) -> None:
        """Fail at report visibility while leaving staging and completed earlier artifacts."""
        if destination.name == "artifact-report-html.bin":
            assert source.is_file() and not destination.exists()
            raise OSError("injected report publication interruption")
        self._replace(source, destination)


class _SavedEconomy:
    """Reopen fully native-verified saved synthetic partitions in an isolated interpreter."""

    @staticmethod
    def prepare(inputs: Path, output: Path) -> None:
        """Publish a real saved archive with explicitly synthetic revision availability."""
        codec = DomainCodec()
        spec = codec.decode_json((inputs / "spec.json").read_bytes(), BacktestSpec)
        config = Configuration.read(inputs / "binance-archive.json")
        catalog = codec.decode_json(
            (inputs / "binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        run = config.resolve("btc-archive", catalog, implementation_identity="a" * 64)
        request = SourceRequest.partition(run)[0]
        rows = b""
        clocks = (50, 110, 121, 170, 181, 230)
        for trade_id, (second, price) in enumerate(
            zip(clocks, ("100", "110", "111", "105", "104", "106"), strict=True)
        ):
            for value in ("1", price):
                rows += (
                    f"{trade_id},{value},2,2,{1717200000000 + second * 1000},true,true\n".encode()
                )
        source = output / "synthetic.zip"
        member = ZipInfo("BTCUSDT-trades-2024-06-01.csv")
        member.compress_type = ZIP_DEFLATED
        with ZipFile(source, "w") as archive:
            archive.writestr(member, rows)
        origin = RawFiles.describe(
            source,
            request=request.binding,
            retrieval_reference="synthetic:economic-revision-availability",
            ts_received=spec.start + timedelta(days=1),
            ts_ingested=spec.start + timedelta(days=1),
        )
        (output / "raw").mkdir()
        (output / "snapshots").mkdir()
        raw = RawStore(output / "raw")
        raw.publish(source, descriptor=origin, request=request.binding)
        acquisition = AcquisitionManifest(run=run, completed=(origin,))
        publisher = DatasetPublication(SourceAdapters(), "a" * 64)
        occurrences = tuple(publisher.occurrences(acquisition, raw, max_bytes=2_000_000))
        corrections = tuple(
            Correction(
                supersedes=TradeRevision(occurrences=(occurrences[2 * i],)).identity,
                replacement=TradeRevision(occurrences=(occurrences[2 * i + 1],)).identity,
                ts_published=spec.start + timedelta(seconds=second),
                ts_available=spec.start + timedelta(seconds=second),
                evidence_reference="synthetic:known-economic-trade",
            )
            for i, second in enumerate(clocks)
        )
        identity = publisher.publish(
            (acquisition,),
            raw,
            output / "snapshots",
            max_bytes=2_000_000,
            policy=QualityPolicy(
                use="exploratory", known_at=spec.start, max_gap=timedelta(hours=1)
            ),
            eligibility=EligibilityAssertions.read(
                inputs / "membership-corrections.json", catalog=catalog
            ),
            corrections={run.identity: corrections},
        )
        (output / "snapshot-id").write_text(identity)
        spec = replace(
            spec, binding=(request.instrument.source, "trade", request.instrument.instrument_id)
        )
        (output / "spec.json").write_bytes(codec.encode_json(spec))

    @staticmethod
    def inputs(directory: Path) -> tuple[QueryReader, BacktestSpec]:
        """Reopen saved raw objects and snapshot manifests through full native admission."""
        spec = DomainCodec().decode_json((directory / "spec.json").read_bytes(), BacktestSpec)
        reader = QueryReader.read(
            directory / "snapshots",
            RawStore(directory / "raw"),
            readers=SourceAdapters(),
            identity=(directory / "snapshot-id").read_text(),
            precedence=(spec.binding,),
            max_bytes=2_000_000,
        )
        return reader, spec

    @staticmethod
    def feature_parity(output: Path, *, resume: bool = False) -> None:
        """Verify installed batch state and command output outside the source checkout."""
        codec = DomainCodec()
        reader, spec = _SavedEconomy.inputs(output)
        expected = codec.decode_json((output / "expected.json").read_bytes(), EconomicResult)
        if resume:
            checkpoint = codec.decode_json(
                (output / "feature-checkpoint.json").read_bytes(), ScheduledFeatureCheckpoint
            )
            running = ScheduledFeatures(
                reader, checkpoint.definition, checkpoint=checkpoint, batch_size=1
            )
            parity = codec.decode_json(
                (output / "feature-parity.json").read_bytes(), ScheduledFeatureParity
            )
            for row in parity.batch.values[len(checkpoint.values) :]:
                running.evaluate(row.observation.closed_at)
            assert running.checkpoint == parity.batch
            return
        parity = qualify_scheduled_features(reader, expected, batch_size=1)
        assert parity.is_equal and len(parity.batch.values) == 3
        assert parity.replay.input_identity == reader.identity
        assert expected.limitations == parity.limitations[2:]
        (output / "feature-parity.json").write_bytes(codec.encode_json(parity))
        running = ScheduledFeatures(reader, parity.batch.definition)
        running.evaluate(spec.start + timedelta(seconds=spec.cadence_seconds))
        (output / "feature-checkpoint.json").write_bytes(codec.encode_json(running.checkpoint))
        subprocess.run(
            [sys.executable, "-I", __file__, str(output), str(output), "feature-resume"],
            check=True,
            cwd=output,
        )
        command = Path(sys.executable).parent / "alpha-backtest"
        invocation = [
            str(command),
            "qualify-features",
            "--config",
            str(output / "configured.json"),
            "--snapshots",
            str(output / "snapshots"),
            "--raw",
            str(output / "raw"),
            "--reference",
            str(output / "expected.json"),
            "--max-bytes",
            "2000000",
            "--output",
            str(output / "feature-command.json"),
        ]
        subprocess.run(invocation, check=True, cwd=output)
        assert (output / "feature-command.json").read_bytes() == codec.encode_json(parity)
        changed = replace(
            expected,
            spec=replace(expected.spec, instance="different"),
            checkpoint=replace(
                expected.checkpoint,
                spec_identity=replace(expected.spec, instance="different").identity,
            ),
        )
        (output / "wrong-feature-reference.json").write_bytes(codec.encode_json(changed))
        invocation[invocation.index("--reference") + 1] = str(
            output / "wrong-feature-reference.json"
        )
        invocation[invocation.index("--output") + 1] = str(output / "rejected-feature.json")
        failure = subprocess.run(invocation, cwd=output, capture_output=True, check=False)
        assert failure.returncode == 2 and b"configured economics" in failure.stderr
        assert not (output / "rejected-feature.json").exists()
        print("Installed scheduled features: exact parity, fresh-process restart and CLI refusal")

    @staticmethod
    def comparison(output: Path, *, resume: bool = False) -> None:
        """Resume the installed Optuna study in a fresh process and reopen every artifact."""
        codec = DomainCodec()
        attempts = output / "comparison-attempts"
        config = output / "comparison.json"
        destination = codec.decode_json((output / "tracking.json").read_bytes(), ClearMLDestination)
        if not resume:
            base = codec.decode_json((output / "configured.json").read_bytes(), BacktestRun)
            control = replace(
                base,
                economics=replace(
                    base.economics,
                    instance="synthetic-reversal",
                    rule="completed-price-reversal-v1",
                ),
            )
            selected = ComparisonStudy(
                name="installed-spot-comparison",
                variants=(base, control),
                budget=2,
                seed=23,
                minimum_return=ExactRatio.from_fraction(Fraction(-1)),
            )
            config.write_bytes(codec.encode_json(selected))
        before = tuple(h.start.attempt_id for h in AttemptStore(attempts).histories())
        with patch.object(ClearMLPublication, "publish", _SavedEconomy.unavailable):
            try:
                compare_parameters(
                    config,
                    output / "snapshots",
                    output / "raw",
                    attempts=attempts,
                    journal=output / "comparison-journal.jsonl",
                    max_bytes=2_000_000,
                    tracking=destination,
                    max_trials=1,
                )
            except ConnectionError:
                pass
            else:
                raise AssertionError("unavailable comparison publication was hidden")
        store = AttemptStore(attempts)
        histories = store.histories()
        assert len(histories) == (2 if resume else 1)
        assert all(h.status == "completed" for h in histories)
        assert set(before) < {h.start.attempt_id for h in histories}
        for history in histories:
            ResultManifest.read(store, history.start.attempt_id)
        if resume:
            return
        first = codec.encode_json(histories[0])
        subprocess.run(
            [sys.executable, "-I", __file__, str(output), str(output), "comparison-resume"],
            check=True,
            cwd=output,
        )
        assert codec.encode_json(store.read(histories[0].start.attempt_id)) == first
        assert (
            len(
                {
                    store.artifact(h.start.attempt_id, "selection-identity")
                    for h in store.histories()
                }
            )
            == 1
        )

    @staticmethod
    def configured(
        output: Path, spec: BacktestSpec, split: TemporalSplit, destination: ClearMLDestination
    ) -> None:
        """Retain repeat/resume results and failed report publication through installed APIs."""
        codec = DomainCodec()
        selected = BacktestRun(
            family="configured-synthetic-economics",
            snapshot_id=(output / "snapshot-id").read_text(),
            economics=spec,
            split=split,
            feature=TrailingReturn(
                policy=WindowPolicy(
                    lookback_us=60_000_000, min_trades=2, max_staleness_us=60_000_000
                ),
                cadence_us=60_000_000,
                processing_delay_us=0,
            ),
            report=ReportPolicy(
                benchmark_name="retained-flat-synthetic-control",
                benchmark=tuple(
                    BenchmarkPeriod(
                        end=spec.start + timedelta(minutes=i),
                        value=ExactRatio.from_fraction(Fraction(0)),
                    )
                    for i in range(1, 5)
                ),
                cadence_seconds=60,
                periods_per_year=525600,
                annual_risk_free=ExactRatio.from_fraction(Fraction(0)),
            ),
        )
        config = output / "configured.json"
        config.write_bytes(codec.encode_json(selected))
        (output / "tracking.json").write_bytes(codec.encode_json(destination))
        attempts = output / "configured-attempts"
        attempts.mkdir()
        for iteration in range(3):
            before = {h.start.attempt_id for h in AttemptStore(attempts).histories()}
            with patch.object(ClearMLPublication, "publish", _SavedEconomy.unavailable):
                try:
                    run_configured(
                        config,
                        output / "snapshots",
                        output / "raw",
                        attempts=attempts,
                        max_bytes=2_000_000,
                        tracking=destination,
                        stop_at=spec.start + timedelta(seconds=120) if iteration == 1 else None,
                        resume=output / "configured-checkpoint.json" if iteration == 2 else None,
                    )
                except ConnectionError:
                    pass
                else:
                    raise AssertionError("unavailable configured publication was hidden")
            store = AttemptStore(attempts)
            history = next(h for h in store.histories() if h.start.attempt_id not in before)
            attempt = history.start.attempt_id
            if iteration == 1:
                assert history.status == "abandoned"
                (output / "configured-checkpoint.json").write_bytes(
                    store.artifact(attempt, "checkpoint")
                )
            else:
                manifest = ResultManifest.read(store, attempt)
                exact = store.artifact(attempt, "economic-reference")
                assert exact == (output / "expected.json").read_bytes()
                if iteration == 0:
                    (output / "configured-expected.json").write_bytes(codec.encode_json(manifest))
                else:
                    assert (
                        codec.encode_json(manifest)
                        == (output / "configured-expected.json").read_bytes()
                    )
        with patch.object(os, "replace", _ReportInterruption()):
            try:
                run_configured(
                    config,
                    output / "snapshots",
                    output / "raw",
                    attempts=attempts,
                    max_bytes=2_000_000,
                    tracking=destination,
                )
            except OSError:
                pass
            else:
                raise AssertionError("report failure was hidden")
        histories = AttemptStore(attempts).histories()
        assert sorted(h.status for h in histories) == [
            "abandoned",
            "completed",
            "completed",
            "failed",
        ]
        failed = next(h for h in histories if h.status == "failed")
        assert "economic-reference" in AttemptStore(attempts).artifacts(failed.start.attempt_id)
        assert "report-html" not in AttemptStore(attempts).artifacts(failed.start.attempt_id)
        assert tuple((attempts / failed.start.attempt_id).glob(".pending-*"))
        try:
            ResultManifest.read(AttemptStore(attempts), failed.start.attempt_id)
        except ValueError:
            pass
        else:
            raise AssertionError("partial reports became a successful result")
        _SavedEconomy.refusals(output, selected)
        print("Configured run, complete report, checkpoint resume and failed publication verified")

    @staticmethod
    def refusals(output: Path, selected: BacktestRun) -> None:
        """Exercise malformed config, missing saved bytes and incompatible checkpoint via CLI."""
        command = Path(sys.executable).parent / "alpha-backtest"
        attempts = output / "refused-attempts"
        attempts.mkdir()
        malformed = output / "malformed.json"
        malformed.write_bytes(b'{"unexpected": true}')
        changed = output / "changed.json"
        changed.write_bytes(DomainCodec().encode_json(replace(selected, family="changed-study")))
        missing = output / "missing-raw"
        shutil.copytree(output / "raw", missing)
        next(p for p in missing.rglob("*") if p.is_file()).unlink()
        for config, raw, resume, code in (
            (malformed, output / "raw", None, 2),
            (changed, output / "raw", output / "configured-checkpoint.json", 2),
            (output / "configured.json", missing, None, 2),
        ):
            argv = [
                str(command),
                "run",
                "--config",
                str(config),
                "--snapshots",
                str(output / "snapshots"),
                "--raw",
                str(raw),
                "--attempts",
                str(attempts),
                "--tracking",
                str(output / "tracking.json"),
                "--max-bytes",
                "2000000",
            ]
            if resume is not None:
                argv.extend(("--resume", str(resume)))
            completed = subprocess.run(argv, cwd=output, capture_output=True, check=False)
            assert completed.returncode == code, completed.stderr
            assert completed.stderr
        histories = AttemptStore(attempts).histories()
        assert len(histories) == 1 and histories[0].status == "failed"

    @staticmethod
    def unavailable(self: ClearMLPublication, attempt_id: str) -> PublicationReceipt:
        """Simulate unavailable publication without replacing the retained economic execution."""
        raise ConnectionError("explicitly unavailable test transport")


def main() -> None:
    """Prove installed execution, publication failure and fresh-process reopen offline.

    Raises:
        AssertionError: Exact economics, recovery or retained publication differs.
    """
    inputs, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    assert "site-packages" in Path(simulation.__file__).parts
    codec = DomainCodec()
    if len(sys.argv) == 4 and sys.argv[3] == "feature-resume":
        _SavedEconomy.feature_parity(output, resume=True)
        return
    if len(sys.argv) == 4 and sys.argv[3] == "comparison-resume":
        _SavedEconomy.comparison(output, resume=True)
        return
    if len(sys.argv) != 4:
        _SavedEconomy.prepare(inputs, output)
    reader, spec = _SavedEconomy.inputs(output)
    if len(sys.argv) == 4 and sys.argv[3] == "resume":
        restored = codec.decode_json((output / "checkpoint.json").read_bytes(), EconomicCheckpoint)
        result = run_backtest(reader, spec, batch_size=2, checkpoint=restored)
        assert isinstance(result, EconomicResult)
        assert codec.encode_json(result) == (output / "expected.json").read_bytes()
        return
    exact = run_backtest(reader, spec)
    assert isinstance(exact, EconomicResult)
    assert exact.terminal.nav.value == Decimal("999.99276500")
    checkpoint = run_backtest(
        reader, spec, batch_size=1, stop_at=spec.start + timedelta(seconds=120)
    )
    assert isinstance(checkpoint, EconomicCheckpoint) and checkpoint.state.pending is not None
    (output / "checkpoint.json").write_bytes(codec.encode_json(checkpoint))
    (output / "expected.json").write_bytes(codec.encode_json(exact))
    subprocess.run(
        [sys.executable, "-I", __file__, str(inputs), str(output), "resume"], check=True, cwd=output
    )
    vector = VectorbtAdapter.run(exact)
    (output / "vectorbt.json").write_bytes(codec.encode_json(vector))
    assert codec.decode_json((output / "vectorbt.json").read_bytes(), VectorbtResult) == vector
    attempts = output / "attempts"
    attempts.mkdir()
    split = TemporalSplit(
        training=None,
        validation=TimeWindow(start=spec.start, end=spec.end),
        holdout=TimeWindow(start=spec.end, end=spec.end + timedelta(minutes=1)),
        samples=(),
        fit_mode="none",
        fit_cutoff=None,
        embargo_us=0,
        rationale="Synthetic integration study only; the reserved future window is never read.",
    )
    destination = ClearMLDestination(
        project="alpha-economic-integration",
        api_uri="http://127.0.0.1:18008",
        files_uri="http://127.0.0.1:18081",
    )
    _SavedEconomy.configured(output, spec, split, destination)
    _SavedEconomy.feature_parity(output)
    _SavedEconomy.comparison(output)
    with patch.object(ClearMLPublication, "publish", _SavedEconomy.unavailable):
        try:
            compare_vectorbt(
                reader,
                spec,
                family="synthetic-economics",
                split=split,
                attempts=attempts,
                tracking=destination,
            )
        except ConnectionError:
            pass
        else:
            raise AssertionError("unavailable publication was hidden")
    with AttemptStore(attempts) as store:
        history = store.histories()[0]
        assert history.status == "completed"
        assert store.artifact(history.start.attempt_id, "economic-reference") == codec.encode_json(
            exact
        )
        assert (
            codec.decode_json(
                store.artifact(history.start.attempt_id, "vectorbt-comparison"), VectorbtResult
            )
            == vector
        )
    print(
        "Installed economics: exact NAV", exact.terminal.nav.value, "; vectorbt NAV", vector.nav[-1]
    )
    print(
        "Saved-source admission, pending-intent resume, typed reopen and transport failure passed"
    )


if __name__ == "__main__":
    main()
