"""Exercise installed economics, fresh-process recovery and tracked vectorbt publication."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# third party library imports
from msgspec.structs import replace

# project library imports
import simulation
from applications.backtest import compare_vectorbt, run_backtest
from configuration import Configuration
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
    ClearMLDestination,
    ClearMLPublication,
    PublicationReceipt,
    TemporalSplit,
    TimeWindow,
)
from serialization import DomainCodec
from simulation import (
    BacktestSpec,
    EconomicCheckpoint,
    EconomicResult,
    VectorbtAdapter,
    VectorbtResult,
)


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
    def unavailable(self: ClearMLPublication, attempt_id: str) -> PublicationReceipt:
        """Simulate unavailable publication without replacing the retained economic execution."""
        raise ConnectionError("explicitly unavailable test transport")

    @staticmethod
    def configure_tracking(output: Path) -> bool:
        """Read the explicitly selected private test credentials without logging them."""
        location = os.environ.get("ALPHA_CLEARML_LOCAL_ENV")
        if location is None:
            return False
        values = dict(
            line.split("=", 1)
            for line in Path(location).read_text().splitlines()
            if line and not line.startswith("#")
        )
        os.environ.update(
            CLEARML_API_HOST="http://127.0.0.1:18008",
            CLEARML_WEB_HOST="http://127.0.0.1:18080",
            CLEARML_FILES_HOST="http://127.0.0.1:18081",
            CLEARML_API_ACCESS_KEY=values["CLEARML_LOCAL_ACCESS_KEY"],
            CLEARML_API_SECRET_KEY=values["CLEARML_LOCAL_SECRET_KEY"],
            CLEARML_CACHE_DIR=str(output / "sdk-cache"),
        )
        return True


def main() -> None:
    """Prove installed execution and separately optional actual-server publication/reopen.

    Raises:
        AssertionError: Exact economics, recovery or retained publication differs.
    """
    inputs, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    assert "site-packages" in Path(simulation.__file__).parts
    codec = DomainCodec()
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
        attempt_id = history.start.attempt_id
    if _SavedEconomy.configure_tracking(output):
        with AttemptStore(attempts) as store:
            publication = ClearMLPublication(store, destination)
            receipt = publication.publish(attempt_id)
            assert publication.publish(attempt_id) == receipt
            # Verify remote bytes through the real SDK after a fresh task lookup.
            # third party library imports
            from clearml import Task

            tasks = Task.get_tasks(
                project_name=destination.project,
                task_name=f"^attempt-{attempt_id}$",
                allow_archived=True,
            )
            assert len(tasks) == 1 and tasks[0].id == receipt.task_id
            task = tasks[0]
            for name in ("economic-reference", "vectorbt-comparison"):
                downloaded = task.artifacts[name].get_local_copy()
                assert downloaded is not None
                assert (
                    hashlib.sha256(Path(downloaded).read_bytes()).hexdigest()
                    == hashlib.sha256(store.artifact(attempt_id, name)).hexdigest()
                )
            (output / "clearml-receipt.json").write_bytes(codec.encode_json(receipt))
            print("Verified ClearML task:", receipt.task_id)
    print(
        "Installed economics: exact NAV", exact.terminal.nav.value, "; vectorbt NAV", vector.nav[-1]
    )
    print(
        "Saved-source admission, pending-intent resume, typed reopen and transport failure passed"
    )


if __name__ == "__main__":
    main()
