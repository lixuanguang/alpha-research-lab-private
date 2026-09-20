"""Describe the first retained, unfitted research consumer over a pinned saved-data selection."""

from __future__ import annotations

# standard library imports
from typing import Literal

# project library imports
from research.experiments import ExperimentSpec, Fingerprint, TemporalSplit
from research.exploration.selection import ResearchSelection
from serialization import WireRecord


class ExplorationStudy(WireRecord, frozen=True, kw_only=True):
    """Select a validation or final-holdout inspection without inventing a model fit."""

    schema_version: Literal["exploration-study-v1"] = "exploration-study-v1"
    family: str
    question: str
    selection: ResearchSelection
    split: TemporalSplit
    partition: Literal["validation", "holdout"]

    def __post_init__(self) -> None:
        """Require explicit no-fit scope and exact selected decision-window boundaries."""
        if self.schema_version != "exploration-study-v1":
            raise ValueError("unsupported exploration study schema")
        for text in (self.family, self.question):
            if type(text) is not str or not text.strip():
                raise ValueError("study requires a family and research question")
        if type(self.selection) is not ResearchSelection or type(self.split) is not TemporalSplit:
            raise TypeError("study requires a pinned selection and temporal split")
        self.selection.__post_init__()
        self.split.__post_init__()
        if self.partition not in ("validation", "holdout") or self.split.fit_mode != "none":
            raise ValueError("exploration supports validation/holdout inspection with no fitting")
        window = self.split.validation if self.partition == "validation" else self.split.holdout
        if any(
            item.query.start != window.start or item.query.end != window.end
            for item in self.selection.inputs
        ):
            raise ValueError("study input windows must match the selected split partition")

    def specification(self, *, implementation: str, environment: str) -> ExperimentSpec:
        """Bind the resolved inspection to actual installed code and environment identities.

        Args:
            implementation: SHA-256 of installed runtime implementation and resources.
            environment: SHA-256 of the interpreter/platform and installed dependencies.

        Returns:
            Semantic study inputs, excluding paths, batch sizes, byte caps and attempt clocks.
        """
        self.__post_init__()
        return ExperimentSpec(
            family=self.family,
            inputs=(Fingerprint(name="research-selection", sha256=self.selection.identity),),
            components=(Fingerprint(name="installed-implementation", sha256=implementation),),
            parameters=(("partition", self.partition), ("question", self.question)),
            seeds=(),
            environment_sha256=environment,
            split=self.split,
        )
