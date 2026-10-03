"""Exercise one real Feast offline view through the installed worker bridge."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import textwrap
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from unittest.mock import patch

# third party library imports
import msgspec

# project library imports
import applications.explore as explore_application
from applications.explore import compare_offline_features
from research.experiments import AttemptHistory, AttemptStore
from research.exploration import VerifiedFeatureRows
from research.features import (
    FeastOfflineWorker,
    FeatureEntity,
    FeatureObservation,
    OfflineFeatureAccess,
    OfflineFeatureBridge,
    OfflineFeatureDefinition,
    OfflineFeatureRequest,
)
from research.studies import ClearMLDestination, ClearMLPublication, ResultManifest
from serialization import DomainCodec

_SDK_VERSION = "0.66.0"
_TTL_US = 1_000_000
_LATE_DELAY = timedelta(microseconds=250_000)
_CORRECTION_DELAY = timedelta(microseconds=500_000)
_EXPIRY_DELAY = timedelta(seconds=2)
_DEFAULT_WORKER = Path("configs/development/research-worker/.venv/bin/python")
_CODEC = DomainCodec()


_WORKER_FIXTURE_SOURCE = textwrap.dedent(
    """
    from __future__ import annotations

    import json
    import sys
    from datetime import timedelta
    from pathlib import Path

    import pandas as pd
    from feast import Entity, FeatureStore, FeatureView, Field, FileSource
    from feast.types import String, ZonedTimestamp
    from feast.value_type import ValueType


    def main() -> None:
        repo = Path(sys.argv[1]).resolve()
        rows_path = Path(sys.argv[2]).resolve()
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "data").mkdir(parents=True, exist_ok=True)
        (repo / "feature_store.yaml").write_text(
            "project: research_offline_acceptance\\n"
            "provider: local\\n"
            "registry: data/registry.db\\n"
            "online_store:\\n"
            "  type: sqlite\\n"
            "  path: data/online.db\\n",
            encoding="utf-8",
        )
        rows = json.loads(rows_path.read_text(encoding="utf-8"))
        frame = pd.DataFrame(rows)
        for name in ("feature_event_timestamp", "created_timestamp"):
            frame[name] = pd.to_datetime(frame[name], utc=True, format="mixed")
        source_path = repo / "data" / "features.parquet"
        frame.to_parquet(source_path, index=False)
        entity = Entity(
            name="instrument",
            join_keys=["instrument"],
            value_type=ValueType.STRING,
        )
        source = FileSource(
            name="mr3_feature_source",
            path=str(source_path),
            event_timestamp_column="feature_event_timestamp",
            created_timestamp_column="created_timestamp",
            timestamp_field="feature_event_timestamp",
        )
        view = FeatureView(
            name="trailing_return",
            entities=[entity],
            ttl=timedelta(seconds=1),
            schema=[
                Field(name="trailing_return", dtype=String),
                Field(name="feature_event_timestamp", dtype=ZonedTimestamp),
                Field(name="created_timestamp", dtype=ZonedTimestamp),
            ],
            source=source,
            online=False,
            offline=True,
        )
        store = FeatureStore(repo_path=str(repo))
        store.apply([entity, source, view])
        if not (repo / "data" / "registry.db").is_file():
            raise RuntimeError("Feast did not write the pinned local registry")


    if __name__ == "__main__":
        main()
    """
).strip()


class OfflineFeatureAcceptance:
    """Author, compare and accept offline feature fixtures and their worker handoff."""

    @staticmethod
    def sha256(path: Path) -> str:
        """Return the SHA-256 digest of one retained fixture file."""
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def source_history(attempts: Path, payload: bytes) -> AttemptHistory:
        """Select a completed MR3 attempt whose terminal bytes equal the saved payload."""
        candidates = [
            history
            for history in AttemptStore(attempts).histories()
            if history.status == "completed"
            and not any(event.status == "holdout_consumed" for event in history.events)
            and history.events[-1].result == payload
        ]
        if not candidates:
            raise AssertionError("MR3 attempts contain no completed matching source payload")
        selected = candidates[0]
        for history in candidates[1:]:
            if history.start.attempt_id < selected.start.attempt_id:
                selected = history
        return selected

    @staticmethod
    def formal_comparison(
        request: OfflineFeatureRequest,
        access: OfflineFeatureAccess,
        source: AttemptHistory,
        payload: bytes,
        attempts: Path,
        destination: ClearMLDestination,
    ) -> tuple[AttemptHistory, ResultManifest]:
        """Run the retained offline comparison with explicitly unavailable publication.

        Args:
            request: Bounded entity/decision grid sent through the worker.
            access: Worker bridge that performs the real Feast retrieval.
            source: Completed MR3 attempt supplying the causal reference.
            payload: Exact source result bytes retained by ``source``.
            attempts: Shared attempt store receiving the comparison attempt.
            destination: ClearML destination retained for the source acceptance.

        Returns:
            The completed comparison history and verified local result manifest.

        Raises:
            AssertionError: The formal attempt or manifest is invalid, or failed publication
                is hidden.
        """
        assert source.start.spec.split is not None
        before = {history.start.attempt_id for history in AttemptStore(attempts).histories()}
        with patch.object(
            ClearMLPublication,
            "publish",
            side_effect=ConnectionError("offline feature comparison transport"),
        ):
            try:
                compare_offline_features(
                    request,
                    access,
                    family=source.start.spec.family,
                    source_attempt=source.start.attempt_id,
                    source_sha256=hashlib.sha256(payload).hexdigest(),
                    split=source.start.spec.split,
                    attempts=attempts,
                    tracking=destination,
                )
            except ConnectionError:
                pass
            else:
                raise AssertionError("unavailable comparison publication must be visible")
        histories = [
            history
            for history in AttemptStore(attempts).histories()
            if history.start.attempt_id not in before
        ]
        if len(histories) != 1 or histories[0].status != "completed":
            raise AssertionError("formal offline comparison did not retain one completed attempt")
        history = histories[0]
        with AttemptStore(attempts) as store:
            manifest = ResultManifest.read(store, history.start.attempt_id)
            if "clearml-receipt" in store.artifacts(history.start.attempt_id):
                raise AssertionError("offline comparison unexpectedly retained a ClearML receipt")
        return history, manifest

    @staticmethod
    def run_fixture_author(
        worker_python: Path, paths: _FixturePaths, rows: Sequence[dict[str, str]]
    ) -> None:
        """Create the real Feast source and registry in the separate worker environment.

        Args:
            worker_python: Python executable from the pinned Feast worker environment.
            paths: Fresh acceptance paths receiving the source and registry.
            rows: Exact string-valued MR3 observations plus the correction fixture.

        Raises:
            AssertionError: The worker fixture authoring process fails or omits a file.
        """
        paths.rows_json.write_bytes(
            msgspec.json.encode(list(rows))  # type: ignore[misc]  # [owner=research; rationale=msgspec JSON encode accepts an untyped object boundary; expires=2026-12-01]
        )
        paths.worker_fixture.write_text(_WORKER_FIXTURE_SOURCE + "\n", encoding="utf-8")
        completed = subprocess.run(
            [
                str(worker_python),
                "-I",
                str(paths.worker_fixture),
                str(paths.repository),
                str(paths.rows_json),
            ],
            cwd=paths.root,
            capture_output=True,
            check=False,
            timeout=60,
        )
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace")
            raise AssertionError(f"Feast fixture author failed: {detail}")
        assert paths.source.is_file()
        assert paths.registry.is_file()
        assert paths.definition.is_file()

    @staticmethod
    def worker_handoff(paths: _FixturePaths, command_path: Path) -> Path:
        """Write the minimal fresh-process runpy handoff to the installed command."""
        source = textwrap.dedent(
            f"""
        import runpy

        module = runpy.run_path({str(command_path)!r})
        raise SystemExit(module["main"](["feast-worker"]))
        """
        ).strip()
        paths.handoff.write_text(source + "\n", encoding="utf-8")
        return paths.handoff

    @staticmethod
    def fixture_rows(verified: VerifiedFeatureRows) -> tuple[dict[str, str], ...]:
        """Build exact Feast source rows from the completed MR3 result values."""
        if len(verified.rows) != 2:
            raise AssertionError("the MR3 acceptance source must contain two feature rows")
        decisions = {row.decision_at for row in verified.rows}
        if len(decisions) != 1:
            raise AssertionError("MR3 acceptance rows must share one cross-sectional decision")
        decision = next(iter(decisions))
        rows: list[dict[str, str]] = []
        for row in verified.rows:
            if row.value is None or row.event_at is None or row.available_at is None:
                raise AssertionError("MR3 acceptance source must contain non-null feature values")
            rows.append(
                {
                    "instrument": row.entity_key,
                    "feature_event_timestamp": row.event_at.isoformat(),
                    "created_timestamp": row.available_at.isoformat(),
                    "trailing_return": row.value,
                }
            )
        first = verified.rows[0]
        assert first.value is not None and first.event_at is not None
        rows.append(
            {
                "instrument": first.entity_key,
                "feature_event_timestamp": first.event_at.isoformat(),
                "created_timestamp": (decision + _LATE_DELAY).isoformat(),
                "trailing_return": "9/10",
            }
        )
        return tuple(rows)

    @staticmethod
    def definition(paths: _FixturePaths) -> OfflineFeatureDefinition:
        """Bind Feast bytes and source identity into the core offline contract."""
        return OfflineFeatureDefinition(
            feature_name="trailing_return",
            feature_ref="trailing_return:trailing_return",
            entity_type="instrument",
            units="dimensionless",
            ttl_us=_TTL_US,
            sdk_version=_SDK_VERSION,
            definition_version="trailing-return",
            definition_bytes=paths.definition.read_bytes(),
            registry_bytes=paths.registry.read_bytes(),
            source_version="mr3-feature-study-result",
            source_sha256=OfflineFeatureAcceptance.sha256(paths.source),
            join_key="instrument",
            repository_path=str(paths.repository),
        )

    @staticmethod
    def reference(
        definition: OfflineFeatureDefinition,
        verified: VerifiedFeatureRows,
        missing_key: str,
    ) -> tuple[FeatureObservation, ...]:
        """Rebind native MR3 values to the retained Feast definition identity."""
        rows: list[FeatureObservation] = []
        for source_row in verified.rows:
            rows.append(
                FeatureObservation(
                    definition_identity=definition.identity,
                    source_version=definition.source_version,
                    source_sha256=definition.source_sha256,
                    feature_name=definition.feature_name,
                    entity_type=definition.entity_type,
                    entity_key=source_row.entity_key,
                    decision_at=source_row.decision_at,
                    event_at=source_row.event_at,
                    available_at=source_row.available_at,
                    ttl_us=definition.ttl_us,
                    units=definition.units,
                    value=source_row.value,
                    revision_identity=source_row.revision_identity,
                )
            )
        decision = verified.rows[0].decision_at
        rows.append(
            FeatureObservation(
                definition_identity=definition.identity,
                source_version=definition.source_version,
                source_sha256=definition.source_sha256,
                feature_name=definition.feature_name,
                entity_type=definition.entity_type,
                entity_key=missing_key,
                decision_at=decision,
                event_at=None,
                available_at=None,
                ttl_us=definition.ttl_us,
                units=definition.units,
                value=None,
                missing_reason="missing entity or no eligible source row",
            )
        )
        return tuple(rows)

    @staticmethod
    def request(
        definition: OfflineFeatureDefinition,
        entities: Sequence[str],
        decisions: Sequence[datetime],
    ) -> OfflineFeatureRequest:
        """Build one bounded Feast request with explicit entity keys and UTC clocks."""
        return OfflineFeatureRequest(
            definition=definition,
            entities=tuple(
                FeatureEntity(entity_type=definition.entity_type, entity_key=entity)
                for entity in entities
            ),
            decisions=tuple(decisions),
        )

    @staticmethod
    def run_acceptance(source: Path, output: Path, worker_python: Path) -> None:
        """Run native parity, late correction, missing entity and TTL assertions."""
        if not source.is_dir():
            raise AssertionError(f"MR3 source directory is unavailable: {source}")
        source_attempts = source / "attempts"
        tracking_path = source / "tracking.json"
        if not source_attempts.is_dir() or not tracking_path.is_file():
            raise AssertionError("MR3 source is missing retained attempts or tracking metadata")
        output.mkdir(parents=True, exist_ok=False)
        attempts = output / "attempts"
        shutil.copytree(source_attempts, attempts)
        if not worker_python.is_file():
            raise AssertionError(f"pinned Feast worker Python is unavailable: {worker_python}")
        installed_command = Path(explore_application.__file__).with_name("command.py").resolve()
        assert "site-packages" in installed_command.parts
        payload_path = source / "result.json"
        payload = payload_path.read_bytes()
        verified = VerifiedFeatureRows.from_result(
            payload,
            hashlib.sha256(payload).hexdigest(),
            ttl_us=_TTL_US,
        )
        paths = _FixturePaths(output)
        OfflineFeatureAcceptance.run_fixture_author(
            worker_python, paths, OfflineFeatureAcceptance.fixture_rows(verified)
        )
        definition = OfflineFeatureAcceptance.definition(paths)
        handoff = OfflineFeatureAcceptance.worker_handoff(paths, installed_command)
        worker = FeastOfflineWorker(
            (str(worker_python), "-I", str(handoff)),
            cwd=paths.repository,
            timeout_seconds=60,
        )
        access = OfflineFeatureAccess(OfflineFeatureBridge(worker))
        entity_keys = tuple(row.entity_key for row in verified.rows)
        missing_key = "missing-entity"
        decision = verified.rows[0].decision_at
        baseline_request = OfflineFeatureAcceptance.request(
            definition, (*entity_keys, missing_key), (decision,)
        )
        comparison = access.compare(
            baseline_request, OfflineFeatureAcceptance.reference(definition, verified, missing_key)
        )
        assert not comparison.mismatches
        assert len(comparison.matches) == 3
        assert comparison.rows[-1].retrieved_value is None
        source_history = OfflineFeatureAcceptance.source_history(attempts, payload)
        destination = _CODEC.decode_json(tracking_path.read_bytes(), ClearMLDestination)
        formal_history, manifest = OfflineFeatureAcceptance.formal_comparison(
            baseline_request,
            access,
            source_history,
            payload,
            attempts,
            destination,
        )
        correction_request = OfflineFeatureAcceptance.request(
            definition,
            (entity_keys[0],),
            (decision + _CORRECTION_DELAY,),
        )
        corrected = access.retrieve(correction_request).rows[0]
        assert corrected.value == "9/10"
        assert corrected.available_at == decision + _LATE_DELAY
        expiry_request = OfflineFeatureAcceptance.request(
            definition, (entity_keys[0],), (decision + _EXPIRY_DELAY,)
        )
        expired = access.retrieve(expiry_request).rows[0]
        assert expired.value is None
        assert expired.missing_reason == "missing entity or no eligible source row"
        report = {
            "source_payload_sha256": hashlib.sha256(payload).hexdigest(),
            "source_sha256": definition.source_sha256,
            "registry_sha256": definition.registry_sha256,
            "worker_sdk_version": definition.sdk_version,
            "installed_command": str(installed_command),
            "source_attempt_id": source_history.start.attempt_id,
            "formal_attempt_id": formal_history.start.attempt_id,
            "formal_manifest": [
                {"name": artifact.name, "sha256": artifact.sha256}
                for artifact in manifest.artifacts
            ],
            "baseline_matches": len(comparison.matches),
            "missing_entity": missing_key,
            "late_correction_value": corrected.value,
            "late_correction_available_at": corrected.available_at.isoformat()
            if corrected.available_at is not None
            else None,
            "ttl_expired_value": expired.value,
        }
        (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print("Installed Feast 0.66 offline retrieval, source pinning and native parity verified.")
        print("Late correction, explicit missing entity and TTL expiry behavior verified.")


class _FixturePaths:
    """Retain the worker-authored source, repository and registry paths."""

    def __init__(self, root: Path) -> None:
        """Bind the paths under one fresh acceptance output directory."""
        self.root = root
        self.repository = root / "feast-repo"
        self.rows_json = root / "fixture-rows.json"
        self.worker_fixture = root / "author-feast-fixture.py"
        self.source = self.repository / "data" / "features.parquet"
        self.registry = self.repository / "data" / "registry.db"
        self.definition = self.repository / "feature_store.yaml"
        self.handoff = root / "run-installed-feast-worker.py"


class _Arguments(argparse.Namespace):
    """Type the source, output, action and worker interpreter CLI arguments."""

    source: Path
    output: Path
    action: Literal["run", "author-fixture"]
    worker_python: Path


def main() -> None:
    """Run the installed Feast acceptance consumer or author only its worker fixture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "action",
        choices=("run", "author-fixture"),
        nargs="?",
        default="run",
    )
    parser.add_argument(
        "--worker-python",
        type=Path,
        default=Path(os.environ.get("ALPHA_RESEARCH_WORKER_PYTHON", _DEFAULT_WORKER)),
    )
    arguments = parser.parse_args(namespace=_Arguments())
    source = arguments.source.resolve()
    output = arguments.output.resolve()
    worker_python = arguments.worker_python
    if not worker_python.is_absolute():
        worker_python = Path.cwd() / worker_python
    worker_python = worker_python.absolute()
    if arguments.action == "author-fixture":
        payload = (source / "result.json").read_bytes()
        verified = VerifiedFeatureRows.from_result(
            payload,
            hashlib.sha256(payload).hexdigest(),
            ttl_us=_TTL_US,
        )
        output.mkdir(parents=True, exist_ok=False)
        paths = _FixturePaths(output)
        OfflineFeatureAcceptance.run_fixture_author(
            worker_python, paths, OfflineFeatureAcceptance.fixture_rows(verified)
        )
        print(paths.repository)
        return
    OfflineFeatureAcceptance.run_acceptance(source, output, worker_python)


if __name__ == "__main__":
    main()
