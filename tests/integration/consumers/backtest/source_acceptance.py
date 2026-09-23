"""Retain actual saved-source refusal and economic non-admission without inventing evidence."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
from datetime import timedelta
from pathlib import Path

# third party library imports
from msgspec.structs import replace

# project library imports
import simulation
from applications.backtest import run_backtest
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import ArchiveTrade, SourceRequest
from market_data.datasets import DatasetPublication
from market_data.query import QueryReader
from market_data.storage import RawStore
from market_data.validation import QualityPolicy, QualityReport
from reference_data.eligibility import EligibilityAssertions
from research.experiments import ExperimentSpec
from research.studies import ResultManifest
from runtime import ImplementationIdentity
from serialization import DomainCodec
from simulation import BacktestSpec, EconomicCheckpoint, EconomicResult


class _Arguments(argparse.Namespace):
    """Keep the manual installed consumer's explicit inputs typed."""

    manifest: Path
    raw: Path
    spec: Path
    control: Path
    output: Path
    max_bytes: int
    reopen: Path | None


class _Evidence:
    """Retain immutable acceptance artifacts and their small reproducible inventory."""

    def __init__(self, output: Path) -> None:
        """Bind a fresh attempt directory without modifying original source inputs.

        Args:
            output: New directory reserved for this manual execution.
        """
        output.mkdir(parents=True, exist_ok=False)
        self.output = output
        self.digests: dict[str, str] = {}
        self.codec = DomainCodec()

    def retain(self, name: str, value: object) -> None:
        """Atomically retain exact output bytes and add their digest to the inventory.

        Args:
            name: Consumer-owned artifact basename.
            value: Typed artifact or summary encoded with the installed domain codec.
        """
        payload = self.codec.encode_json(value)
        ResultManifest.export(self.output / f"{name}.json", payload)
        self.digests[name] = hashlib.sha256(payload).hexdigest()

    def quality(self, identity: str, report: QualityReport) -> None:
        """Retain the actual causal publication outcome before its refusal propagates.

        Args:
            identity: Acquisition identity from the existing publication callback.
            report: Actual quality outcome, including every unresolved source fact.
        """
        self.retain("causal-quality", (identity, report))


def main() -> int:
    """Exercise the currently unqualified archive through an isolated installed candidate.

    Returns:
        Three when expected source refusal and all non-admission assertions pass.
        This is deliberately not a successful frozen-baseline acceptance exit.

    Raises:
        AssertionError: Source scope or installed behavior differs from the refusal scenario.
        ValueError: An input, publication or saved result violates its existing contract.
        OSError: A required source or evidence artifact is unavailable.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("manifest", "raw", "spec", "control", "output"):
        parser.add_argument(f"--{option}", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, required=True)
    parser.add_argument("--reopen", type=Path)
    args = parser.parse_args(namespace=_Arguments())
    assert "site-packages" in Path(simulation.__file__).parts
    evidence = _Evidence(args.output)
    codec = evidence.codec
    spec = codec.decode_json(args.spec.read_bytes(), BacktestSpec)
    control = codec.decode_json(args.control.read_bytes(), BacktestSpec)
    assert control.rule == "no-trade-v1"
    assert replace(control, instance=spec.instance, rule=spec.rule) == spec
    manifest = codec.decode_json(args.manifest.read_bytes(), AcquisitionManifest)
    raw = RawStore(args.raw)
    saved = AcquisitionManifest.read(args.manifest, run=manifest.run, store=raw)
    (request,) = SourceRequest.partition(saved.run)
    assert saved.pending is None and len(saved.completed) == 1
    assert (
        request.instrument.source,
        saved.run.job.stream,
        request.instrument.instrument_id,
    ) == spec.binding
    assert (saved.run.job.start, saved.run.job.end) == (spec.start, spec.end)
    assert saved.run.catalog.recorded_at > spec.end
    history = EligibilityAssertions(catalog=saved.run.catalog, assertions=())
    evidence.retain("acquisition", saved)
    evidence.retain("specification", spec)
    evidence.retain("control-specification", control)
    evidence.retain("eligibility", history)
    evidence.retain(
        "installation",
        {
            "implementation": ImplementationIdentity.sha256(),
            "environment": ExperimentSpec.installed_environment(),
            "consumer": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "seed": 0,
            "split": None,
            "fit": "inapplicable; frozen engineering sample",
        },
    )
    publisher = DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256())
    # Exhaust the reader: a valid prefix cannot establish full-day CSV/CRC validity.
    count = 0
    first_position: int | None = None
    last_position: int | None = None
    for row in publisher.occurrences(saved, raw, max_bytes=args.max_bytes):
        assert isinstance(row.event, ArchiveTrade)
        assert row.event.ts_source_received is None
        count += 1
        if first_position is None:
            first_position = row.position
        last_position = row.position
    assert count > 0
    evidence.retain(
        "saved-source",
        {
            "selected_rows": count,
            "first_position": first_position,
            "last_position": last_position,
            "raw_sha256": saved.completed[0].sha256,
            "raw_size_bytes": saved.completed[0].size_bytes,
            "receipt_clocks": "absent",
            "revision_availability": "unresolved",
        },
    )
    policy = QualityPolicy(
        use="causal", known_at=spec.start, max_gap=timedelta(seconds=spec.max_age_seconds)
    )
    causal = args.output / "causal-snapshots"
    causal.mkdir()
    try:
        publisher.publish(
            (saved,),
            raw,
            causal,
            max_bytes=args.max_bytes,
            policy=policy,
            eligibility=history,
            corrections={},
            report=evidence.quality,
        )
    except ValueError as error:
        assert "partition publication refused" in str(error)
        assert "original trade availability unknown" in str(error)
        assert "recorder coverage unknown" in str(error)
        assert "unknown" in str(error) and "eligibility" in str(error)
    else:
        raise AssertionError("unevidenced actual source unexpectedly passed causal publication")
    assert not tuple(causal.iterdir())
    snapshots = args.output / "exploratory-snapshots"
    snapshots.mkdir()
    identity = publisher.publish(
        (saved,),
        raw,
        snapshots,
        max_bytes=args.max_bytes,
        policy=replace(policy, use="exploratory"),
        eligibility=history,
        corrections={},
    )
    evidence.retain("exploratory-snapshot", identity)
    if args.reopen is not None:
        previous = codec.decode_json((args.reopen / "exploratory-snapshot.json").read_bytes(), str)
        assert previous == identity
        snapshots = args.reopen / "exploratory-snapshots"
    reader = QueryReader.read(
        snapshots,
        raw,
        readers=SourceAdapters(),
        identity=identity,
        precedence=(spec.binding,),
        max_bytes=args.max_bytes,
    )
    for selected in (spec, control):
        result = run_backtest(reader, selected)
        assert isinstance(result, EconomicResult)
        assert not result.checkpoint.state.ledger.fills
        assert all(item.point is None for item in result.checkpoint.state.observations.completed)
        assert result.terminal.nav == selected.initial_cash
        assert result.terminal.net.value == 0
        evidence.retain(selected.instance, result)
    checkpoint = run_backtest(reader, spec, stop_at=spec.start + (spec.end - spec.start) / 2)
    assert isinstance(checkpoint, EconomicCheckpoint)
    evidence.retain("checkpoint", checkpoint)
    if args.reopen is not None:
        checkpoint = codec.decode_json(
            (args.reopen / "checkpoint.json").read_bytes(), EconomicCheckpoint
        )
        resumed = run_backtest(reader, spec, checkpoint=checkpoint, batch_size=1)
        assert codec.encode_json(resumed) == (args.output / f"{spec.instance}.json").read_bytes()
        for name, digest in evidence.digests.items():
            assert hashlib.sha256((args.reopen / f"{name}.json").read_bytes()).hexdigest() == digest
    evidence.retain(
        "outcome",
        {
            "acceptance": "open",
            "causal_publication": "refused",
            "economic_interpretation": (
                "No eligible observations; unchanged cash is not a measured strategy return."
            ),
            "fresh_process_reproduction": args.reopen is not None,
            "remaining": (
                "historical eligibility",
                "historical trade/revision availability",
                "recorder coverage",
                "source-qualified economics and durable costed reports",
            ),
        },
    )
    ResultManifest.export(args.output / "inventory.json", codec.encode_json(evidence.digests))
    print("Saved-source checks passed; frozen baseline acceptance remains OPEN (exit 3).")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
