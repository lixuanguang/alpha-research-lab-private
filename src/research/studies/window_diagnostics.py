"""Compare retained numeric windows without fitting, selection or operational actions."""

from __future__ import annotations

# standard library imports
import hashlib
import html
import importlib
import math
import re
import warnings
from datetime import datetime, timedelta
from fractions import Fraction
from importlib.metadata import version
from typing import Literal, Protocol, cast

# project library imports
from financial_units import ExactRatio
from research.experiments import ExperimentSpec, Fingerprint, TemporalSplit, TimeWindow
from research.studies.diagnostics import FeatureLabelPayload
from research.studies.evaluation import EvaluationRecord
from serialization import DomainCodec, WireRecord


class DiagnosticSource(WireRecord, frozen=True, kw_only=True):
    """Pin an upstream attempt and its exact feature result or evaluation artifact."""

    attempt_id: str
    sha256: str

    def __post_init__(self) -> None:
        """Reject path-like attempt IDs and mutable content references."""
        if (
            type(self.attempt_id) is not str
            or re.fullmatch(r"[a-f0-9]{32}", self.attempt_id) is None
        ):
            raise ValueError("diagnostic source requires a retained attempt ID")
        Fingerprint(name="diagnostic source", sha256=self.sha256)


class WindowDiagnosticStudy(WireRecord, frozen=True, kw_only=True):
    """Freeze diagnostic windows, source identities and thresholds before computation.

    Windows are half-open UTC decision intervals inside validation. KS is a
    descriptive two-sided exact test on finite dimensionless float projections,
    per instrument; dependent time samples do not establish inferential significance.
    MSE remains exact rational arithmetic. No threshold selects a candidate.
    """

    family: str
    features: tuple[DiagnosticSource, ...]
    predictions: tuple[DiagnosticSource, ...]
    split: TemporalSplit
    reference: TimeWindow
    current: TimeWindow
    evaluated_as_of: datetime
    min_observations: int
    ks_statistic_threshold: float
    ks_pvalue_threshold: float
    predictive_metric: Literal["mse", "inapplicable"]
    predictive_reason: str
    max_mse: ExactRatio | None
    threshold_reason: str
    schema_version: Literal["window-diagnostic-study-v1"] = "window-diagnostic-study-v1"

    def __post_init__(self) -> None:
        """Validate declared availability, applicability and frozen numerical policy."""
        if self.schema_version != "window-diagnostic-study-v1":
            raise ValueError("unsupported window diagnostic study")
        for text in (self.family, self.predictive_reason, self.threshold_reason):
            if type(text) is not str or not text.strip():
                raise ValueError("diagnostics require authored family and policy reasons")
        for sources in (self.features, self.predictions):
            if type(sources) is not tuple or len(sources) > 16:
                raise ValueError("diagnostics require at most 16 immutable sources per role")
            for source in sources:
                if type(source) is not DiagnosticSource:
                    raise TypeError("diagnostics require DiagnosticSource records")
                source.__post_init__()
            if len({source.attempt_id for source in sources}) != len(sources):
                raise ValueError("duplicate diagnostic source")
        if not self.features:
            raise ValueError("diagnostics require retained features")
        self.split.__post_init__()
        self.reference.__post_init__()
        self.current.__post_init__()
        self._require_utc(self.evaluated_as_of, field_name="evaluated_as_of")
        if not (
            self.split.validation.start
            <= self.reference.start
            < self.reference.end
            <= self.current.start
            < self.current.end
            <= self.split.validation.end
            and self.current.end <= self.evaluated_as_of < self.split.holdout.start
        ):
            raise ValueError("diagnostic windows and cutoff must precede the untouched holdout")
        if type(self.min_observations) is not int or not 2 <= self.min_observations <= 1024:
            raise ValueError("minimum diagnostic observations must be 2 to 1024")
        for value in (self.ks_statistic_threshold, self.ks_pvalue_threshold):
            if type(value) is not float or not math.isfinite(value) or not 0 < value < 1:
                raise ValueError(
                    "KS thresholds must be finite floats strictly between zero and one"
                )
        if self.predictive_metric == "mse":
            if not self.predictions or type(self.max_mse) is not ExactRatio:
                raise ValueError("MSE requires retained predictions and an exact frozen threshold")
            self.max_mse.__post_init__()
            if int(self.max_mse.numerator) < 0:
                raise ValueError("MSE threshold must be nonnegative")
        elif self.predictive_metric != "inapplicable" or self.max_mse is not None:
            raise ValueError("inapplicable predictive metrics must not have an MSE threshold")

    def specification(self, *, implementation: str, environment: str) -> ExperimentSpec:
        """Bind the declared diagnostic contract to actual installed code and dependencies.

        Args:
            implementation: Installed owned-code SHA-256.
            environment: Actual installed dependency/interpreter SHA-256.

        Returns:
            Semantic specification preserving the declared source temporal split.
        """
        self.__post_init__()
        return ExperimentSpec(
            family=self.family,
            inputs=(
                Fingerprint(
                    name="window-study",
                    sha256=hashlib.sha256(DomainCodec().encode_json(self)).hexdigest(),
                ),
            ),
            components=(Fingerprint(name="implementation", sha256=implementation),),
            parameters=(("scope", "offline window diagnostics; no automatic action"),),
            seeds=(),
            environment_sha256=environment,
            split=self.split,
        )


class DiagnosticObservation(WireRecord, frozen=True, kw_only=True):
    """Retain one exact input, its window and separate feature/prediction/label exclusions."""

    row_id: str
    entity: str
    decision_at: datetime
    window: Literal["reference", "current", "excluded"]
    feature: ExactRatio | None
    prediction: ExactRatio | None
    label: ExactRatio | None
    model_version: str | None
    label_available_at: datetime | None
    feature_reason: str | None
    prediction_reason: str | None
    label_reason: str | None

    def __post_init__(self) -> None:
        """Require exact inputs, explicit missingness and original UTC clocks."""
        if (
            not self.row_id
            or not self.entity
            or self.window not in ("reference", "current", "excluded")
        ):
            raise ValueError("invalid diagnostic observation identity")
        self._require_utc(self.decision_at, field_name="decision_at")
        if self.label_available_at is not None:
            self._require_utc(self.label_available_at, field_name="label_available_at")
        for value, reason in (
            (self.feature, self.feature_reason),
            (self.prediction, self.prediction_reason),
            (self.label, self.label_reason),
        ):
            if value is not None:
                if type(value) is not ExactRatio:
                    raise TypeError("diagnostic observations require exact ratios")
                value.__post_init__()
            elif reason is None:
                raise ValueError("missing diagnostic values require a reason")
            if reason is not None and (type(reason) is not str or not reason.strip()):
                raise ValueError("diagnostic exclusion reasons must be nonempty")
        if (self.prediction is None) != (self.model_version is None):
            raise ValueError("a retained prediction requires its model version")
        if self.model_version is not None:
            Fingerprint(name="prediction model", sha256=self.model_version)


class DistributionDiagnostic(WireRecord, frozen=True, kw_only=True):
    """Record per-instrument sample sizes, KS results and descriptive threshold outcome."""

    entity: str
    field: Literal["feature", "prediction"]
    reference_count: int
    current_count: int
    statistic: float | None
    pvalue: float | None
    drift: bool | None
    inapplicable_reason: str | None

    def __post_init__(self) -> None:
        """Reject nonfinite results and invented inapplicable values."""
        if not self.entity or self.field not in ("feature", "prediction"):
            raise ValueError("invalid distribution diagnostic identity")
        if any(
            type(count) is not int or not 0 <= count <= 1024
            for count in (self.reference_count, self.current_count)
        ):
            raise ValueError("invalid distribution diagnostic counts")
        if self.inapplicable_reason is not None:
            if not self.inapplicable_reason.strip() or any(
                value is not None for value in (self.statistic, self.pvalue, self.drift)
            ):
                raise ValueError("inapplicable distributions must not invent numerical results")
        elif type(self.drift) is not bool or any(
            type(value) is not float or not math.isfinite(value) or not 0 <= value <= 1
            for value in (self.statistic, self.pvalue)
        ):
            raise ValueError("applicable distributions require finite KS results")


class PredictiveDiagnostic(WireRecord, frozen=True, kw_only=True):
    """Retain exact dimensionless-squared error or an explicit applicability reason."""

    entity: str
    window: Literal["reference", "current"]
    count: int
    mean_squared_error: ExactRatio | None
    threshold_exceeded: bool | None
    inapplicable_reason: str | None

    def __post_init__(self) -> None:
        """Require exact error or an explicit applicability reason."""
        if (
            not self.entity
            or self.window not in ("reference", "current")
            or type(self.count) is not int
            or not 0 <= self.count <= 1024
        ):
            raise ValueError("invalid predictive diagnostic identity or count")
        if self.inapplicable_reason is not None:
            if (
                not self.inapplicable_reason.strip()
                or self.mean_squared_error is not None
                or self.threshold_exceeded is not None
            ):
                raise ValueError("inapplicable predictive metrics must not invent error values")
        else:
            if (
                type(self.mean_squared_error) is not ExactRatio
                or type(self.threshold_exceeded) is not bool
                or self.count == 0
            ):
                raise ValueError("predictive metrics require exact error and applicable samples")
            self.mean_squared_error.__post_init__()
            if int(self.mean_squared_error.numerator) < 0:
                raise ValueError("squared errors cannot be negative")


class WindowDiagnosticReport(WireRecord, frozen=True, kw_only=True):
    """Carry reproducible report inputs and numerical outputs with honest tool identities."""

    study: WindowDiagnosticStudy
    versions: tuple[tuple[str, str], ...]
    observations: tuple[DiagnosticObservation, ...]
    distributions: tuple[DistributionDiagnostic, ...]
    predictive: tuple[PredictiveDiagnostic, ...]
    schema_version: Literal["window-diagnostic-report-v1"] = "window-diagnostic-report-v1"
    units: str = (
        "feature/prediction/label: dimensionless; MSE: dimensionless-squared; KS: dimensionless"
    )
    availability_policy: str = (
        "features at decision; labels only when available_at <= evaluated_as_of; no imputation"
    )
    test_definition: str = (
        "scipy.stats.ks_2samp(alternative=two-sided, method=exact); per instrument; "
        "drift iff D >= frozen D and p <= frozen p"
    )
    metric_definition: str = (
        "mean((prediction-forward_return)**2), exact rational; threshold exceeded iff MSE > max_mse"
    )
    limitations: str = (
        "Descriptive diagnostics on dependent temporal observations; unadjusted p-values, "
        "no inferential or empirical acceptance; "
        "no retraining, promotion, deployment or trading action"
    )

    def __post_init__(self) -> None:
        """Validate immutable report rows when saved bytes are reopened."""
        if self.schema_version != "window-diagnostic-report-v1":
            raise ValueError("unsupported window diagnostic report")
        self.study.__post_init__()
        for collection in (self.observations, self.distributions, self.predictive):
            if type(collection) is not tuple:
                raise TypeError("diagnostic report collections must be immutable")
            for item in collection:
                item.__post_init__()
        if len({row.row_id for row in self.observations}) != len(self.observations):
            raise ValueError("duplicate diagnostic report observations")
        if (
            type(self.versions) is not tuple
            or not self.versions
            or any(not name or not value for name, value in self.versions)
        ):
            raise ValueError("diagnostic reports require actual computation versions")

    def html_bytes(self) -> bytes:
        """Render a self-contained readable report with the complete reproducible JSON.

        Returns:
            UTF-8 HTML generated by this repository, never represented as Evidently output.
        """
        payload = DomainCodec().encode_json(self).decode()
        rows = "".join(
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(value))}</td>"
                for value in (
                    item.entity,
                    item.field,
                    item.reference_count,
                    item.current_count,
                    item.statistic,
                    item.pvalue,
                    item.drift,
                    item.inapplicable_reason,
                )
            )
            + "</tr>"
            for item in self.distributions
        )
        return (
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            "<title>Offline window diagnostics</title><style>body{font:16px system-ui;"
            "margin:2rem;max-width:1100px}td,th{padding:.5rem;border:1px solid #aaa}"
            "table{border-collapse:collapse}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>"
            "<h1>Offline window diagnostics</h1><p>Repository report computed with SciPy. "
            "Drift is diagnostic only.</p><p>" + html.escape(self.limitations) + "</p>"
            "<table><tr><th>Entity</th><th>Field</th><th>Reference n</th><th>Current n</th>"
            "<th>KS D</th><th>p-value</th><th>Drift</th><th>Inapplicability</th></tr>"
            + rows
            + "</table><h2>Policy, inputs, exclusions and exact predictive results</h2><pre>"
            + html.escape(payload)
            + "</pre></html>"
        ).encode()


class _KSResult(Protocol):
    """Describe the two finite numerical fields returned by SciPy."""

    statistic: float
    pvalue: float


class _ScipyStats(Protocol):
    """Type the exercised SciPy computation without importing an untyped surface eagerly."""

    def ks_2samp(
        self, data1: list[float], data2: list[float], *, alternative: str, method: str
    ) -> _KSResult:
        """Compute a two-sample empirical CDF distance and its exact null probability."""
        ...


class WindowDiagnostics:
    """Calculate deterministic per-instrument diagnostics from verified retained inputs."""

    def evaluate(
        self,
        study: WindowDiagnosticStudy,
        features: tuple[FeatureLabelPayload, ...],
        predictions: tuple[EvaluationRecord, ...],
    ) -> WindowDiagnosticReport:
        """Compare explicit windows without constructing features, predictions or labels.

        Args:
            study: Frozen diagnostic windows, cutoff, thresholds and applicability policy.
            features: Verified retained feature/label results with their original provenance.
            predictions: Verified retained evaluations; later labels are filtered again here.

        Returns:
            Reproducible exact inputs, numerical results, exclusions and computation versions.

        Raises:
            ValueError: Inputs duplicate rows, disagree on labels or exceed temporal boundaries.
        """
        study.__post_init__()
        if len(features) != len(study.features) or len(predictions) != len(study.predictions):
            raise ValueError("diagnostic source counts differ from the frozen declaration")
        rows = self._observations(study, features, predictions)
        entities = sorted({row.entity for row in rows})
        distributions = tuple(
            self._distribution(study, rows, entity, field)
            for entity in entities
            for field in ("feature", "prediction")
        )
        predictive = tuple(
            self._predictive(study, rows, entity, window)
            for entity in entities
            for window in ("reference", "current")
        )
        return WindowDiagnosticReport(
            study=study,
            versions=(
                ("repository-calculation", "window-diagnostics-v1"),
                ("scipy", version("scipy")),
                ("numpy", version("numpy")),
            ),
            observations=rows,
            distributions=distributions,
            predictive=predictive,
        )

    def _observations(
        self,
        study: WindowDiagnosticStudy,
        payloads: tuple[FeatureLabelPayload, ...],
        evaluations: tuple[EvaluationRecord, ...],
    ) -> tuple[DiagnosticObservation, ...]:
        """Join by immutable row identity and retain independent exclusion reasons."""
        prediction_rows: dict[str, tuple[str, ExactRatio, ExactRatio, datetime]] = {}
        prediction_exclusions: dict[str, str] = {}
        for evaluation in evaluations:
            evaluation.__post_init__()
            if evaluation.partition != "validation":
                raise ValueError("diagnostics cannot reuse holdout predictions")
            for row_id, model, prediction, outcome, available in evaluation.predictions:
                if row_id in prediction_rows or row_id in prediction_exclusions:
                    raise ValueError("duplicate diagnostic prediction row")
                prediction_rows[row_id] = (model, prediction, outcome, available)
            for row_id, reason in evaluation.excluded:
                if row_id in prediction_rows or row_id in prediction_exclusions:
                    raise ValueError("duplicate diagnostic prediction exclusion")
                prediction_exclusions[row_id] = reason
        rows: list[DiagnosticObservation] = []
        seen: set[str] = set()
        entity_clocks: set[tuple[str, datetime]] = set()
        definition: tuple[str, str | None] | None = None
        for payload in payloads:
            payload.__post_init__()
            current_definition = (
                payload.feature_definition.identity,
                None if payload.label_definition is None else payload.label_definition.identity,
            )
            if definition is not None and current_definition != definition:
                raise ValueError("diagnostic inputs mix feature or label definitions")
            definition = current_definition
            for row_id, feature, label, sample in payload.aligned_rows():
                if (
                    sample.input_sha256
                    != hashlib.sha256(DomainCodec().encode_json((feature, label))).hexdigest()
                ):
                    raise ValueError("diagnostic sample digest differs from feature/label bytes")
                if label is not None and label.available_at is not None:
                    if payload.label_definition is None:
                        raise ValueError("available labels require a retained definition")
                    earliest = label.outcome_at + timedelta(
                        microseconds=payload.label_definition.availability_delay_us
                    )
                    if label.available_at < earliest:
                        raise ValueError("label availability precedes the declared delay")
                if row_id in seen or len(seen) >= 1024:
                    raise ValueError("diagnostics require at most 1024 unique feature rows")
                seen.add(row_id)
                entity_clock = (str(feature.window.binding[2]), sample.decision_at)
                if entity_clock in entity_clocks:
                    raise ValueError("diagnostics cannot pool duplicate instrument/decision rows")
                entity_clocks.add(entity_clock)
                if (
                    not study.split.validation.contains(sample.decision_at)
                    or sample.information_end >= study.split.holdout.start
                ):
                    raise ValueError(
                        "diagnostic observations reach outside validation or into holdout"
                    )
                window: Literal["reference", "current", "excluded"] = "excluded"
                if study.reference.contains(sample.decision_at):
                    window = "reference"
                elif study.current.contains(sample.decision_at):
                    window = "current"
                outside = (
                    "outside declared reference/current windows" if window == "excluded" else None
                )
                label_reason = outside
                if label is None or label.value is None or label.available_at is None:
                    label_reason = (
                        label_reason
                        or (None if label is None else label.missing)
                        or "missing label or unknown availability; no imputation"
                    )
                elif label.available_at > study.evaluated_as_of:
                    label_reason = label_reason or "label unavailable at evaluation cutoff"
                prediction_row = prediction_rows.get(row_id)
                if prediction_row is not None and (
                    label is None
                    or prediction_row[2] != label.value
                    or prediction_row[3] != label.available_at
                ):
                    raise ValueError("prediction outcome differs from retained feature label")
                rows.append(
                    DiagnosticObservation(
                        row_id=row_id,
                        entity=str(feature.window.binding[2]),
                        decision_at=sample.decision_at,
                        window=window,
                        feature=feature.value,
                        prediction=None if prediction_row is None else prediction_row[1],
                        label=None if label is None else label.value,
                        model_version=None if prediction_row is None else prediction_row[0],
                        label_available_at=None if label is None else label.available_at,
                        feature_reason=outside
                        or (
                            (feature.window.missing or "missing feature; no imputation")
                            if feature.value is None
                            else None
                        ),
                        prediction_reason=outside
                        or (
                            None
                            if prediction_row is not None
                            else prediction_exclusions.get(row_id, "no retained prediction")
                        ),
                        label_reason=label_reason,
                    )
                )
        if set(prediction_rows) - seen or set(prediction_exclusions) - seen:
            raise ValueError("prediction rows are absent from declared feature sources")
        return tuple(rows)

    def _distribution(
        self,
        study: WindowDiagnosticStudy,
        rows: tuple[DiagnosticObservation, ...],
        entity: str,
        field: Literal["feature", "prediction"],
    ) -> DistributionDiagnostic:
        """Project exact dimensionless observations and call the actual SciPy KS test."""
        values: dict[str, list[float]] = {"reference": [], "current": []}
        for row in rows:
            value = row.feature if field == "feature" else row.prediction
            reason = row.feature_reason if field == "feature" else row.prediction_reason
            if (
                row.entity == entity
                and row.window in values
                and value is not None
                and reason is None
            ):
                projected = float(self._fraction(value))
                if not math.isfinite(projected):
                    raise ValueError("diagnostic input has no finite float projection")
                values[row.window].append(projected)
        reference, current = values["reference"], values["current"]
        statistic = pvalue = None
        drift = None
        reason = "insufficient observations for the frozen minimum"
        if min(len(reference), len(current)) >= study.min_observations:
            stats = cast(_ScipyStats, importlib.import_module("scipy.stats"))
            # SciPy warns and falls back to asymptotics if its exact calculation
            # fails. Preserve that as a computation failure, never a changed test.
            with warnings.catch_warnings():
                warnings.simplefilter("error", RuntimeWarning)
                result = stats.ks_2samp(reference, current, alternative="two-sided", method="exact")
            statistic, pvalue = float(result.statistic), float(result.pvalue)
            if not all(math.isfinite(value) and 0 <= value <= 1 for value in (statistic, pvalue)):
                raise ValueError("SciPy returned an invalid KS result")
            drift = (
                statistic >= study.ks_statistic_threshold and pvalue <= study.ks_pvalue_threshold
            )
            reason = None
        return DistributionDiagnostic(
            entity=entity,
            field=field,
            reference_count=len(reference),
            current_count=len(current),
            statistic=statistic,
            pvalue=pvalue,
            drift=drift,
            inapplicable_reason=reason,
        )

    def _predictive(
        self,
        study: WindowDiagnosticStudy,
        rows: tuple[DiagnosticObservation, ...],
        entity: str,
        window: Literal["reference", "current"],
    ) -> PredictiveDiagnostic:
        """Compute exact MSE only for complete predictions and then-available labels."""
        errors = [
            (self._fraction(row.prediction) - self._fraction(row.label)) ** 2
            for row in rows
            if row.entity == entity
            and row.window == window
            and row.prediction is not None
            and row.label is not None
            and row.prediction_reason is None
            and row.label_reason is None
        ]
        mse = exceeded = None
        reason: str | None = None
        if study.predictive_metric == "inapplicable":
            reason = study.predictive_reason
        elif not errors:
            reason = "no complete predictions with labels available at evaluation cutoff"
        else:
            exact = sum(errors, Fraction()) / len(errors)
            mse = ExactRatio.from_fraction(exact)
            if study.max_mse is None:
                raise ValueError("applicable predictive metrics require a frozen threshold")
            exceeded = exact > self._fraction(study.max_mse)
        return PredictiveDiagnostic(
            entity=entity,
            window=window,
            count=len(errors),
            mean_squared_error=mse,
            threshold_exceeded=exceeded,
            inapplicable_reason=reason,
        )

    @staticmethod
    def _fraction(value: ExactRatio) -> Fraction:
        """Recover the exact retained rational without decimal-context dependence."""
        value.__post_init__()
        return Fraction(int(value.numerator), int(value.denominator))
