"""Validate selected economic research definitions before application effects."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import timedelta
from pathlib import Path

# project library imports
from research.experiments import ExperimentSpec, Fingerprint, TemporalSplit, TimeWindow
from research.features import TrailingReturn
from research.studies.reports import ReportPolicy
from serialization import DomainCodec, WireRecord
from simulation import BacktestSpec


class BacktestRun(WireRecord, frozen=True):
    """Select one independent instance and pinned inputs for a no-fit validation study."""

    family: str
    snapshot_id: str
    economics: BacktestSpec
    report: ReportPolicy
    split: TemporalSplit | None
    engineering_sample: TimeWindow | None = None
    feature: TrailingReturn | None = None
    versioned_inputs_sha256: str | None = None
    schema_version: str = "configured-backtest-v1"

    def __post_init__(self) -> None:
        """Reject unsupported selections and access to reserved final holdout observations."""
        Fingerprint(name=self.family, sha256=self.snapshot_id)
        if self.versioned_inputs_sha256 is not None:
            Fingerprint(name="versioned-inputs", sha256=self.versioned_inputs_sha256)
        if (
            self.schema_version
            not in ("configured-backtest-v1", "configured-engineering-sample-v1")
            or type(self.economics) is not BacktestSpec
            or type(self.report) is not ReportPolicy
        ):
            raise ValueError("unsupported configured economic research schema")
        self.economics.__post_init__()
        self.report.__post_init__()
        if self.schema_version == "configured-engineering-sample-v1":
            if self.split is not None or type(self.engineering_sample) is not TimeWindow:
                raise ValueError("engineering sample requires its interval and no temporal split")
            self.engineering_sample.__post_init__()
            if (self.engineering_sample.start, self.engineering_sample.end) != (
                self.economics.start,
                self.economics.end,
            ):
                raise ValueError("engineering sample must exactly match economic interval")
        else:
            if type(self.split) is not TemporalSplit or self.engineering_sample is not None:
                raise ValueError("validation study requires its temporal split")
            self.split.__post_init__()
        if self.feature is not None:
            if type(self.feature) is not TrailingReturn:
                raise TypeError("configured diagnostic requires TrailingReturn")
            self.feature.__post_init__()
        if self.split is not None and (
            self.split.fit_mode != "none"
            or self.split.samples
            or not self.split.validation.start
            <= self.economics.start
            < self.economics.end
            <= self.split.validation.end
        ):
            raise ValueError("configured economics requires a no-fit validation window")
        if self.report.cadence_seconds != self.economics.cadence_seconds:
            raise ValueError("report cadence differs from economic cadence")
        cadence = timedelta(seconds=self.economics.cadence_seconds)
        duration = self.economics.end - self.economics.start
        ends = tuple(self.economics.start + cadence * i for i in range(1, duration // cadence + 1))
        if duration % cadence or tuple(item.end for item in self.report.benchmark) != ends:
            raise ValueError("benchmark must exactly align with configured economic periods")

    @classmethod
    def read(cls, path: Path) -> BacktestRun:
        """Read a bounded strict JSON configuration without starting any workflow.

        Args:
            path: Explicit non-secret configuration, at most one MiB.

        Returns:
            Validated resolved study retaining actual benchmark and strategy parameters.

        Raises:
            ValueError: Configuration is too large, malformed or unsupported.
        """
        with path.open("rb") as source:
            payload = source.read(1_048_577)
        if len(payload) > 1_048_576:
            raise ValueError("backtest configuration exceeds one MiB")
        return DomainCodec().decode_json(payload, cls)

    @property
    def identity(self) -> str:
        """Fingerprint all resolved choices, independent of execution/output paths.

        Returns:
            SHA-256 of the complete strict configuration record.
        """
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    def specification(self, *, implementation: str, environment: str) -> ExperimentSpec:
        """Bind the selected inputs to actual installed code and environment identities.

        Args:
            implementation: Digest of the installed owned code and resources.
            environment: Digest of the installed interpreter and distribution versions.

        Returns:
            Existing attempt-core specification, with fitting explicitly inapplicable.
        """
        return ExperimentSpec(
            schema_version=(
                "experiment-spec-v1"
                if self.split is not None
                else "experiment-engineering-sample-v1"
            ),
            family=self.family,
            inputs=(
                Fingerprint(name="snapshot", sha256=self.snapshot_id),
                Fingerprint(name="resolved-configuration", sha256=self.identity),
            ),
            components=(Fingerprint(name="implementation", sha256=implementation),),
            parameters=(
                (
                    "scope",
                    "offline cash-funded spot validation"
                    if self.split is not None
                    else "unfitted engineering sample; no strategy selection",
                ),
            ),
            seeds=() if self.split is not None else (("deterministic-rule", 0),),
            environment_sha256=environment,
            split=self.split,
            engineering_sample=self.engineering_sample,
        )
