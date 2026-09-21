"""Prove identity, temporal leakage boundaries and interrupted-attempt retention."""

from __future__ import annotations

# standard library imports
import hashlib
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock, patch

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from research.experiments import (
    AttemptEvent,
    AttemptStart,
    AttemptStore,
    ClearMLDestination,
    ClearMLPublication,
    ExperimentSpec,
    Fingerprint,
    SampleInterval,
    TemporalSplit,
    TimeWindow,
)
from serialization import DomainCodec

_START = datetime(2024, 6, 1, tzinfo=UTC)
_CODEC = DomainCodec()


class TestExperiments:
    """Use hand-authored clocks and values independent of the split implementation."""

    @staticmethod
    def _time(hour: int) -> datetime:
        """Return a synthetic UTC instant without relying on the wall clock."""
        return _START + timedelta(hours=hour)

    @classmethod
    def _row(cls, name: str, decision: int, end: int, label: int | None) -> SampleInterval:
        """Create an independently identified sample with an explicit outcome clock."""
        return SampleInterval(
            row_id=name,
            input_sha256=hashlib.sha256(name.encode()).hexdigest(),
            decision_at=cls._time(decision),
            information_start=cls._time(decision),
            information_end=cls._time(end),
            features_available_at=cls._time(decision),
            label_available_at=cls._time(label) if label is not None else None,
        )

    @classmethod
    def _split(cls) -> TemporalSplit:
        """Specify one known fitting pair and distinct independently excluded samples."""
        return TemporalSplit(
            training=TimeWindow(start=cls._time(0), end=cls._time(10)),
            validation=TimeWindow(start=cls._time(10), end=cls._time(12)),
            holdout=TimeWindow(start=cls._time(20), end=cls._time(22)),
            samples=(
                cls._row("a", 1, 2, 3),
                cls._row("b", 3, 4, 10),
                cls._row("embargo", 8, 9, 9),
                cls._row("overlap", 8, 10, 10),
                cls._row("late", 4, 5, 11),
                cls._row("unknown", 4, 5, None),
                replace(cls._row("future_feature", 4, 5, 6), features_available_at=cls._time(5)),
                cls._row("validation", 10, 11, 11),
                cls._row("holdout", 20, 21, 22),
                cls._row("future", 30, 31, 32),
            ),
            fit_mode="labels",
            fit_cutoff=cls._time(10),
            embargo_us=3_600_000_000,
            rationale="Earlier-only fold; closed information intervals plus a one-hour gap.",
        )

    @classmethod
    def _spec(cls) -> ExperimentSpec:
        """Bind explicit immutable inputs, configuration and seeds to the temporal fold."""
        return ExperimentSpec(
            family="diagnostic-comparison",
            inputs=(Fingerprint(name="dataset", sha256="a" * 64),),
            components=(Fingerprint(name="diagnostic-v1", sha256="b" * 64),),
            parameters=(("window", "2"), ("missing", "reject")),
            seeds=(("diagnostic", 23),),
            environment_sha256="c" * 64,
            split=cls._split(),
        )

    def test_custom_search_parameter_remains_publishable(self, tmp_path: Path) -> None:
        """Do not interpret an existing free-form search parameter as an Optuna trial."""
        destination = ClearMLDestination(
            project="custom-experiment",
            api_uri="http://127.0.0.1:18008",
            files_uri="http://127.0.0.1:18081",
        )
        task = MagicMock(
            **{"id": "synthetic-task", "status": "in_progress", "flush.return_value": True}
        )
        with (
            AttemptStore(tmp_path / "attempts") as store,
            patch.object(ClearMLPublication, "_task", return_value=task),
            patch.object(ClearMLPublication, "_upload"),
            patch(
                "research.experiments.tracking.Session.get_api_server_host",
                return_value=destination.api_uri,
            ),
        ):
            spec = replace(self._spec(), parameters=(("search", "manual-screen"),))
            start = store.start(spec, at=self._time(12), invocation="custom diagnostic")
            store.finish(
                start.attempt_id,
                status="completed",
                at=self._time(13),
                reason="Independent custom experiment",
                result=b"retained-result",
            )
            receipt = ClearMLPublication(store, destination).publish(start.attempt_id)
            assert receipt.task_id == "synthetic-task"
            assert store.read(start.attempt_id).start.spec.parameters == spec.parameters

    def test_hand_fitting_set_and_future_perturbation(self) -> None:
        """Admit exactly two earlier rows; no unavailable outcome or held-out value enters fit."""
        split = self._split()
        assert tuple(row.row_id for row in split.fitting_rows()) == ("a", "b")
        reasons = dict(split.exclusions())
        assert reasons == {
            "embargo": "embargoed shared information",
            "overlap": "purged overlapping information",
            "late": "label unavailable at fitting cutoff",
            "unknown": "label unavailable at fitting cutoff",
            "future_feature": "features unavailable at decision",
            "validation": "outside training partition",
            "holdout": "outside training partition",
            "future": "outside training partition",
        }
        # A consumer selects its actual values only after validating their IDs.
        values = {"a": 2, "b": 4, "holdout": 1000, "future": 2000, "late": 9000}
        ids = tuple(row.row_id for row in split.fitting_rows())
        split.require_fit_rows(ids)
        assert sum(values[row] for row in ids) == 6
        values.update(holdout=-90000, future=99000, late=-12345)
        assert sum(values[row] for row in ids) == 6
        for attempted in (("a", "holdout"), ("late",), ("future",), ("a", "a"), ()):
            with pytest.raises(ValueError, match="admitted training"):
                split.require_fit_rows(attempted)
        unsupervised = replace(split, fit_mode="features")
        assert {row.row_id for row in unsupervised.fitting_rows()} == {"a", "b", "late", "unknown"}
        no_fit = replace(split, training=None, fit_cutoff=None, fit_mode="none")
        assert no_fit.fitting_rows() == ()
        with pytest.raises(ValueError, match="admitted training"):
            no_fit.require_fit_rows(("a",))

    def test_information_overlap_and_exact_gap_boundaries(self) -> None:
        """Purge evaluation lookbacks, inclusive horizon ties and cutoff overruns."""
        split = self._split()
        validation = replace(self._row("eval", 10, 11, 12), information_start=self._time(4))
        combined: tuple[SampleInterval, ...] = (*split.samples, validation)
        with_lookback = replace(split, samples=combined)
        assert tuple(row.row_id for row in with_lookback.fitting_rows()) == ("a",)
        beyond = self._row("beyond", 9, 11, 11)
        assert dict(replace(split, samples=(beyond,)).exclusions())["beyond"] == (
            "information extends beyond fitting cutoff"
        )
        adjacent = self._row("adjacent", 9, 9, 9)
        assert replace(split, samples=(adjacent,), embargo_us=0).fitting_rows() == (adjacent,)
        assert replace(split, samples=(adjacent,)).fitting_rows() == ()
        window = split.validation
        assert window.contains(self._time(10)) and not window.contains(self._time(12))

    def test_semantic_identity_reload_and_changed_inputs(self) -> None:
        """Reorder mappings without changing identity; any influencing choice changes the run."""
        spec = self._spec()
        reloaded = _CODEC.decode_json(_CODEC.encode_json(spec), ExperimentSpec)
        assert reloaded == spec and reloaded.identity == spec.identity
        assert reloaded.split.fitting_rows() == spec.split.fitting_rows()
        reversed_parameters = tuple(reversed(spec.parameters))
        reversed_samples = tuple(reversed(spec.split.samples))
        reordered = replace(
            spec,
            parameters=reversed_parameters,
            split=replace(spec.split, samples=reversed_samples),
        )
        assert reordered.identity == spec.identity
        variants = (
            replace(spec, inputs=(Fingerprint(name="dataset", sha256="d" * 64),)),
            replace(spec, components=(Fingerprint(name="diagnostic-v2", sha256="b" * 64),)),
            replace(spec, parameters=(("window", "3"),)),
            replace(spec, seeds=(("diagnostic", 24),)),
            replace(spec, environment_sha256="d" * 64),
            replace(spec, split=replace(spec.split, embargo_us=0)),
            replace(
                spec,
                split=replace(
                    spec.split, samples=(replace(spec.split.samples[0], input_sha256="d" * 64),)
                ),
            ),
        )
        assert len({spec.identity, *(value.identity for value in variants)}) == len(variants) + 1

    def test_invalid_and_unsafe_copied_records(self) -> None:
        """Refuse malformed clocks, schema, duplicate IDs and unsafe constructor bypasses."""
        split = self._split()
        with pytest.raises(ValueError, match="unique"):
            replace(split, samples=(split.samples[0], split.samples[0]))
        with pytest.raises(ValueError, match="precede"):
            replace(split, fit_cutoff=self._time(11))
        with pytest.raises(ValueError, match="UTC"):
            TimeWindow(start=datetime.fromisoformat("2024-01-01T00:00:00+01:00"), end=self._time(1))
        with pytest.raises(TypeError, match="aware"):
            replace(split.samples[0], decision_at=datetime(2024, 6, 1))
        with pytest.raises(ValueError, match="label"):
            replace(split.samples[0], label_available_at=self._time(1))
        with pytest.raises(ValueError, match="inapplicable"):
            replace(split, fit_mode="none")
        with pytest.raises(ValueError, match="embargo"):
            replace(split, embargo_us=True)
        spec = self._spec()
        force_setattr(spec.split.samples[0], "input_sha256", "not-a-digest")
        with pytest.raises(ValueError, match="SHA-256"):
            _ = spec.identity
        with pytest.raises(ValueError):
            _CODEC.decode_json(
                _CODEC.encode_json(self._spec()).replace(
                    b'"experiment-spec-v1"', b'"future-version"'
                ),
                ExperimentSpec,
            )

    def test_attempt_identity_outcomes_and_reader_writer_boundary(self, tmp_path: Path) -> None:
        """Keep distinct executions and every terminal outcome without rewriting history."""
        spec = self._spec()
        with AttemptStore(tmp_path) as store:
            first = store.start(spec, at=self._time(30), invocation="location/one", request=b"one")
            with pytest.raises(BlockingIOError):
                with AttemptStore(tmp_path):
                    pytest.fail("a second writer was admitted")
            assert AttemptStore(tmp_path).read(first.attempt_id).status == "incomplete"
            second = store.start(spec, at=self._time(31), invocation="location/two", request=b"two")
            assert (
                first.run_identity == second.run_identity and first.attempt_id != second.attempt_id
            )
            outcomes: tuple[tuple[AttemptStart, Literal["failed", "rejected"]], ...] = (
                (first, "failed"),
                (second, "rejected"),
            )
            for attempt, status in outcomes:
                store.finish(
                    attempt.attempt_id, status=status, at=self._time(32), reason="retained"
                )
            third = store.start(spec, at=self._time(32), invocation="third")
            store.finish(third.attempt_id, status="abandoned", at=self._time(33), reason="stopped")
            fourth = store.start(spec, at=self._time(32), invocation="fourth")
            complete = store.finish(
                fourth.attempt_id,
                status="completed",
                at=self._time(33),
                reason="software result",
                result=b'{"value":6}',
            )
            assert complete.events[-1].result == b'{"value":6}'
            with pytest.raises(ValueError, match="terminal"):
                store.finish(
                    first.attempt_id,
                    status="completed",
                    at=self._time(33),
                    reason="cannot erase failure",
                    result=b"result",
                )
        assert {history.status for history in store.histories()} == {
            "failed",
            "rejected",
            "abandoned",
            "completed",
        }
        with pytest.raises(RuntimeError, match="writer"):
            store.start(spec, at=self._time(34), invocation="closed")
        with pytest.raises(ValueError, match="identity"):
            store.read("../escape")
        with pytest.raises(ValueError, match="completion"):
            AttemptEvent(status="completed", recorded_at=self._time(32), reason="partial")

    def test_consumed_holdout_survives_failure_and_only_same_run_reproduces(
        self, tmp_path: Path
    ) -> None:
        """Retain failed holdout reads and refuse using them to evaluate a tuned variant."""
        spec = self._spec()
        with AttemptStore(tmp_path) as store:
            first = store.start(spec, at=self._time(30), invocation="evaluate")
            store.consume_holdout(first.attempt_id, at=self._time(30), reason="final evaluation")
            store.finish(
                first.attempt_id, status="failed", at=self._time(31), reason="input missing"
            )
            repeat = store.start(spec, at=self._time(32), invocation="reproduce")
            store.consume_holdout(
                repeat.attempt_id, at=self._time(32), reason="unchanged reproduction"
            )
            other = store.start(
                replace(spec, seeds=(("diagnostic", 24),)),
                at=self._time(33),
                invocation="changed attempt",
            )
            with pytest.raises(ValueError, match="already consumed"):
                store.consume_holdout(other.attempt_id, at=self._time(33), reason="retuned")
            store.finish(other.attempt_id, status="rejected", at=self._time(34), reason="consumed")
            with pytest.raises(ValueError, match="frozen"):
                store.start(
                    replace(
                        spec,
                        split=replace(
                            spec.split, holdout=TimeWindow(start=self._time(22), end=self._time(24))
                        ),
                    ),
                    at=self._time(34),
                    invocation="relabel holdout",
                )
        assert store.read(first.attempt_id).events[0].status == "holdout_consumed"
        assert sum(history.status == "rejected" for history in store.histories()) == 2

    def test_interrupted_rejected_start_cannot_complete(self, tmp_path: Path) -> None:
        """Keep the frozen boundary even if the process stops before rejection publication."""
        spec = self._spec()
        changed = replace(
            spec,
            split=replace(spec.split, holdout=TimeWindow(start=self._time(22), end=self._time(24))),
        )
        with AttemptStore(tmp_path) as store:
            original = store.start(spec, at=self._time(30), invocation="original")
            with patch.object(store, "finish", side_effect=KeyboardInterrupt):
                with pytest.raises(KeyboardInterrupt):
                    store.start(changed, at=self._time(31), invocation="changed holdout")
            interrupted = next(
                history
                for history in store.histories()
                if history.start.attempt_id != original.attempt_id
            )
            assert interrupted.status == "incomplete"
            with pytest.raises(ValueError, match="frozen"):
                store.finish(
                    interrupted.start.attempt_id,
                    status="completed",
                    at=self._time(32),
                    reason="cannot bypass the frozen boundary",
                    result=b"result",
                )
            with pytest.raises(ValueError, match="frozen"):
                store.consume_holdout(
                    interrupted.start.attempt_id,
                    at=self._time(32),
                    reason="cannot consume rejected holdout",
                )
            store.finish(
                interrupted.start.attempt_id,
                status="rejected",
                at=self._time(32),
                reason="changed frozen holdout",
            )

    @pytest.mark.integration
    def test_process_death_before_commit_retains_holdout_and_releases_writer(
        self, tmp_path: Path
    ) -> None:
        """Kill after result bytes flush but before rename, then inspect and abandon the attempt."""
        script = Path(__file__).parents[2] / "support/subprocesses/interrupt_attempt.py"
        shutil.copyfile(script, tmp_path / script.name)
        (tmp_path / "spec.json").write_bytes(_CODEC.encode_json(self._spec()))
        result = subprocess.run(
            [sys.executable, "-I", str(tmp_path / script.name), str(tmp_path)],
            cwd=tmp_path,
            capture_output=True,
            check=False,
            timeout=20,
        )
        assert result.returncode == 76, result.stderr
        with AttemptStore(tmp_path / "attempts") as store:
            histories = store.histories()
            assert len(histories) == 1 and histories[0].status == "incomplete"
            history = histories[0]
            assert history.events[0].status == "holdout_consumed"
            assert list((tmp_path / "attempts" / history.start.attempt_id).glob(".pending-*"))
            store.finish(
                history.start.attempt_id,
                status="abandoned",
                at=self._time(40),
                reason="process interrupted before atomic completion",
            )
        assert store.read(history.start.attempt_id).status == "abandoned"
