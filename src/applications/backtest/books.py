"""Compose verified saved-book inspection, isolated IOC simulation and retained reports."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime
from pathlib import Path

# project library imports
from configuration import BookRun
from market_data.adapters.sources import SourceAdapters
from market_data.datasets import CaptureInput
from market_data.storage import RawStore
from research.experiments import AttemptStore, ExperimentSpec, Fingerprint, TimeWindow
from research.observations import BookFeatures
from research.studies import BookReport, ResultManifest
from runtime import ImplementationIdentity
from serialization import DomainCodec
from simulation import BookCheckpoint, BookSimulation
from strategies import BookRules


def run_books(
    config: Path,
    archive: Path,
    *,
    output: Path,
    resume: Path | None = None,
    stop_at: datetime | None = None,
) -> Path:
    """Run the saved L2 workflow through installed shared owners and retain failed attempts.

    Args:
        config: Versioned resolved BookRun JSON with instrument/date/window and assumptions.
        archive: Existing completed native archive directory; no acquisition or latest selection.
        output: Local attempt and export root; each invocation retains its own directory.
        resume: Optional exported directory containing every instance checkpoint from the same run.
        stop_at: Optional inclusive checkpoint clock; incomplete attempts do not produce a report.

    Returns:
        Unique export directory containing a report or complete per-instance checkpoints.

    Raises:
        ValueError: Configuration, archive provenance, recovery or financial reconciliation fails.
        Exception: Execution fails after preserving its original attempt and partial artifacts.
    """
    selected, codec, registry = BookRun.read(config), DomainCodec(), BookRules()
    rules = tuple(registry.resolve(instance.rule) for instance in selected.instances)
    source = CaptureInput.read(archive, max_records=selected.history.max_records)
    if source.archive is None or source.archive.config != selected.history:
        raise ValueError("saved archive binding differs from resolved history configuration")
    implementation = ImplementationIdentity.sha256()
    environment = ExperimentSpec.installed_environment()
    spec = ExperimentSpec(
        schema_version="experiment-engineering-sample",
        family=f"l2-book-{selected.history.instrument_id}-{selected.history.day}",
        inputs=(
            Fingerprint(name="native-archive", sha256=source.raw.sha256),
            Fingerprint(name="native-request", sha256=source.request.identity),
        ),
        components=(Fingerprint(name="installed-code", sha256=implementation),),
        parameters=(("configuration", selected.identity),),
        seeds=(),
        environment_sha256=environment,
        split=None,
        engineering_sample=TimeWindow(start=selected.start, end=selected.end),
    )
    output.mkdir(parents=True, exist_ok=True)
    configuration = codec.encode_json(selected)
    with AttemptStore(output / "attempts") as store:
        attempt = store.start(
            spec,
            at=datetime.now(UTC),
            invocation="alpha-backtest books",
            request=configuration,
        )
        destination = output / attempt.attempt_id
        destination.mkdir()
        try:
            artifacts = {
                "resolved-configuration": store.retain(
                    attempt.attempt_id, "resolved-configuration", configuration
                ),
                "source-evidence": store.retain(
                    attempt.attempt_id, "source-evidence", codec.encode_json(source)
                ),
            }
            store.export(
                attempt.attempt_id, "resolved-configuration", destination / "configuration.json"
            )
            features = tuple(
                BookFeatures.inspect(row, selected.instances[0].depth)
                for row in SourceAdapters.books(source, RawStore(archive))
            )
            if len(features) != selected.history.max_records:
                raise ValueError("saved archive shorter than configured message prefix")
            artifacts["eda"] = store.retain(attempt.attempt_id, "eda", codec.encode_json(features))
            store.export(attempt.attempt_id, "eda", destination / "eda.json")
            accounts: list[BookCheckpoint] = []
            for index, (instance, rule) in enumerate(zip(selected.instances, rules, strict=True)):
                identity = hashlib.sha256(
                    codec.encode_json((spec.identity, instance.instance))
                ).hexdigest()
                restored = (
                    None
                    if resume is None
                    else codec.decode_json(
                        (resume / f"checkpoint-{index}.json").read_bytes(), BookCheckpoint
                    )
                )
                account = BookSimulation(selected, instance, rule).execute(
                    SourceAdapters.books(source, RawStore(archive)),
                    identity=identity,
                    checkpoint=restored,
                    stop_at=stop_at,
                )
                accounts.append(account)
                name = f"checkpoint-{index}"
                artifacts[name] = store.retain(attempt.attempt_id, name, codec.encode_json(account))
                store.export(attempt.attempt_id, name, destination / f"{name}.json")
            if stop_at is not None and stop_at < selected.end:
                store.finish(
                    attempt.attempt_id,
                    status="abandoned",
                    at=datetime.now(UTC),
                    reason="Requested complete L2 checkpoints; resume creates a new attempt",
                )
            else:
                report = BookReport(
                    run_identity=spec.identity,
                    implementation=implementation,
                    environment=environment,
                    raw_sha256=source.raw.sha256,
                    request_identity=source.request.identity,
                    configuration=selected,
                    features=features,
                    accounts=tuple(accounts),
                )
                artifacts["report"] = store.retain(
                    attempt.attempt_id,
                    "report",
                    report.encode_references(
                        configuration_sha256=artifacts["resolved-configuration"],
                        features_sha256=artifacts["eda"],
                        accounts_sha256=tuple(
                            artifacts[f"checkpoint-{index}"] for index in range(len(accounts))
                        ),
                    ),
                )
                artifacts["report-html"] = store.retain(
                    attempt.attempt_id, "report-html", report.render()
                )
                manifest = ResultManifest(
                    artifacts=tuple(
                        Fingerprint(name=name, sha256=digest)
                        for name, digest in sorted(artifacts.items())
                    )
                )
                store.export(attempt.attempt_id, "report", destination / "report.json")
                store.export(attempt.attempt_id, "report-html", destination / "report.html")
                store.finish(
                    attempt.attempt_id,
                    status="completed",
                    at=datetime.now(UTC),
                    reason="Verified L2 source, EDA, exact IOC accounts and report committed",
                    result=codec.encode_json(manifest),
                )
            ResultManifest.export(
                destination / "attempt.json", codec.encode_json(store.read(attempt.attempt_id))
            )
        except (Exception, KeyboardInterrupt) as error:
            if store.read(attempt.attempt_id).status == "incomplete":
                store.finish(
                    attempt.attempt_id,
                    status="abandoned" if isinstance(error, KeyboardInterrupt) else "failed",
                    at=datetime.now(UTC),
                    reason=f"{type(error).__name__}: {error}",
                )
            ResultManifest.export(
                destination / "attempt.json", codec.encode_json(store.read(attempt.attempt_id))
            )
            raise
    return destination
