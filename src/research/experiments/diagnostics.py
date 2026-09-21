"""Run bounded Alphalens diagnostics over a verified MR3 result payload.

The adapter consumes the existing ``feature-study-result-v1`` wire contract.
It never calculates a label from prices and never treats a pending label as an
observation.  Alphalens Reloaded and pandas are pinned core dependencies; they
are imported only when a report is run to keep experiment identity and
retained-result imports lightweight.
"""

from __future__ import annotations

# standard library imports
import html
import importlib
import math
from collections.abc import Mapping
from datetime import datetime, timedelta
from fractions import Fraction
from numbers import Real
from typing import TYPE_CHECKING, Literal, Protocol, cast

# project library imports
from financial_units import ExactRatio
from research.experiments.splits import SampleInterval
from research.features import FeatureValue, PriceWindow, TrailingReturn
from research.labels import ForwardReturn, LabelValue
from serialization import DomainCodec, WireRecord

if TYPE_CHECKING:
    # third party library imports
    import pandas as pd


type FactorDirection = Literal["ascending", "descending"]
type QuantileRule = Literal["equal-frequency-qcut-v1"]
type PriceConvention = Literal["forward-last-over-frozen-base-v1"]

_PRICE_CONVENTION: PriceConvention = "forward-last-over-frozen-base-v1"


class _PerformanceAPI(Protocol):
    """Describe the Alphalens performance calls used by the adapter."""

    def factor_information_coefficient(
        self, factor_data: pd.DataFrame, group_adjust: bool = ..., by_group: bool = ...
    ) -> pd.DataFrame:
        """Calculate date-level rank information coefficients."""
        ...

    def mean_return_by_quantile(
        self,
        factor_data: pd.DataFrame,
        by_date: bool = ...,
        by_group: bool = ...,
        demeaned: bool = ...,
        group_adjust: bool = ...,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Calculate mean forward returns by factor quantile."""
        ...

    def quantile_turnover(
        self, quantile_factor: pd.Series, quantile: int, period: int = ...
    ) -> pd.Series:
        """Calculate the proportion of names entering one quantile."""
        ...


class _UtilityAPI(Protocol):
    """Describe Alphalens' quantile assignment operation."""

    def quantize_factor(
        self,
        factor_data: pd.DataFrame,
        quantiles: int,
        bins: None = ...,
        by_group: bool = ...,
        no_raise: bool = ...,
        zero_aware: bool = ...,
    ) -> pd.Series:
        """Assign cross-sectional quantiles without deriving a return."""
        ...


class _AlphalensModule(Protocol):
    """Describe the lazy Alphalens module boundary."""

    performance: _PerformanceAPI
    utils: _UtilityAPI


class _DataFrameLike(Protocol):
    """Expose the native frame projection used for typed metric rows."""

    @property
    def empty(self) -> bool:
        """Whether the frame has no rows."""
        ...

    def to_dict(self, orient: str = ...) -> object:
        """Return a native frame mapping."""
        ...


class _SeriesLike(Protocol):
    """Expose the native series projection used for typed metric rows."""

    def to_dict(self) -> object:
        """Return a native series mapping."""
        ...


class _PandasModule(Protocol):
    """Describe the small pandas construction boundary used by Alphalens."""

    DataFrame: type[pd.DataFrame]
    MultiIndex: type[pd.MultiIndex]


class DiagnosticDrop(WireRecord, frozen=True, kw_only=True):
    """Retain one excluded row and the causal reason for excluding it."""

    row_id: str
    decision_at: datetime
    reason: str
    available_at: datetime | None = None

    def __post_init__(self) -> None:
        """Require a stable row identity, UTC decision clock and authored reason."""
        if type(self.row_id) is not str or not self.row_id.strip():
            raise ValueError("diagnostic drop requires a row identity")
        if type(self.reason) is not str or not self.reason.strip():
            raise ValueError("diagnostic drop requires a reason")
        self._require_utc(self.decision_at, field_name="decision_at")
        if self.available_at is not None:
            self._require_utc(self.available_at, field_name="available_at")


class DiagnosticMetric(WireRecord, frozen=True, kw_only=True):
    """Retain one projected Alphalens metric with its key and sample count."""

    name: str
    period: str
    group: str | None
    value: float | None
    sample_count: int

    def __post_init__(self) -> None:
        """Reject ambiguous metric names, nonfinite values and invalid counts."""
        if (
            type(self.name) is not str
            or not self.name.strip()
            or type(self.period) is not str
            or not self.period.strip()
            or (self.group is not None and (type(self.group) is not str or not self.group.strip()))
            or type(self.sample_count) is not int
            or self.sample_count < 0
        ):
            raise ValueError("invalid diagnostic metric identity or sample count")
        if self.value is not None and (
            type(self.value) is not float or not math.isfinite(self.value)
        ):
            raise ValueError("diagnostic metric value must be finite")


class FeatureLabelPayload(WireRecord, frozen=True, kw_only=True):
    """Decode and verify the retained MR3 feature/label result contract.

    This local wire type intentionally mirrors the producer's closed result
    schema.  Importing the model package here would re-enter ``experiments``
    while that package is being initialized, so the consumer keeps the wire
    records and their validation in this module.
    """

    schema_version: Literal["feature-study-result-v1"]
    selection_identity: str
    feature_definition: TrailingReturn
    label_definition: ForwardReturn | None
    features: tuple[tuple[str, FeatureValue], ...]
    labels: tuple[tuple[str, LabelValue], ...]
    samples: tuple[SampleInterval, ...]
    split_identity: str
    fitting: str
    scope: Literal["exploratory_degraded"]

    def __post_init__(self) -> None:
        """Verify definitions, clocks and aligned row identities before dataframe use."""
        if (
            self.schema_version != "feature-study-result-v1"
            or self.scope != "exploratory_degraded"
            or type(self.fitting) is not str
            or not self.fitting.strip()
            or not self._fingerprint(self.selection_identity)
            or not self._fingerprint(self.split_identity)
        ):
            raise ValueError("unsupported or malformed feature-study result payload")
        self.feature_definition.__post_init__()
        if self.label_definition is not None:
            self.label_definition.__post_init__()
        feature_ids = self._validate_features()
        label_ids = self._validate_labels()
        sample_ids = self._validate_samples()
        if not 1 <= len(feature_ids) <= 1024:
            raise ValueError("feature-study result must contain 1 to 1024 rows")
        if set(label_ids) - set(feature_ids) or set(sample_ids) != set(feature_ids):
            raise ValueError("feature, label and sample row identities are not aligned")
        if self.label_definition is None and label_ids:
            raise ValueError("labels require a forward-return definition")
        if self.label_definition is not None and set(label_ids) != set(feature_ids):
            raise ValueError("forward-return payload must retain one label per feature row")
        labels = dict(self.labels)
        samples = {sample.row_id: sample for sample in self.samples}
        for row_id, feature in self.features:
            if feature.definition_identity != self.feature_definition.identity:
                raise ValueError("feature row uses a different feature definition")
            sample = samples[row_id]
            if sample.decision_at != feature.decision_at:
                raise ValueError("sample and feature decision clocks differ")
            if sample.features_available_at != feature.available_at:
                raise ValueError("sample and feature availability clocks differ")
            label = labels.get(row_id)
            if label is None:
                if sample.label_available_at is not None:
                    raise ValueError("unlabeled sample cannot declare label availability")
                continue
            if (
                self.label_definition is None
                or label.definition_identity != self.label_definition.identity
            ):
                raise ValueError("label row uses a different forward-return definition")
            if label.decision_at != feature.decision_at:
                raise ValueError("feature and label decision clocks differ")
            if sample.label_available_at != label.available_at:
                raise ValueError("sample and label availability clocks differ")
            if (
                sample.information_start != label.information_start
                or sample.information_end != label.information_end
            ):
                raise ValueError("sample and label information intervals differ")

    @classmethod
    def decode(cls, payload: bytes) -> FeatureLabelPayload:
        """Decode one retained result through the repository's strict JSON codec.

        Args:
            payload: Complete UTF-8 ``feature-study-result-v1`` bytes.

        Returns:
            A verified immutable feature/label payload.

        Raises:
            ValueError: The bytes are malformed, unknown-fielded or misaligned.
        """
        if type(payload) is not bytes or not payload:
            raise ValueError("feature-label payload requires nonempty bytes")
        return DomainCodec().decode_json(payload, cls)

    @property
    def universe(self) -> tuple[str, ...]:
        """Return stable instrument identities represented by the feature rows.

        Returns:
            Sorted instrument identities retained in the feature rows.
        """
        assets = {self._asset_name(feature.window.binding) for _, feature in self.features}
        return tuple(sorted(assets))

    def aligned_rows(
        self,
    ) -> tuple[tuple[str, FeatureValue, LabelValue | None, SampleInterval], ...]:
        """Join retained feature, optional label and sample records by row identity.

        Returns:
            Ordered rows with the feature, optional label and verified sample interval.
        """
        self.__post_init__()
        labels = dict(self.labels)
        samples = {sample.row_id: sample for sample in self.samples}
        return tuple(
            (row_id, feature, labels.get(row_id), samples[row_id])
            for row_id, feature in self.features
        )

    @staticmethod
    def _fingerprint(value: str) -> bool:
        """Check a repository SHA-256 identity without normalizing authored text."""
        return (
            type(value) is str
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    @staticmethod
    def _asset_name(binding: tuple[object, object, object]) -> str:
        """Project one source binding to the stable instrument identity."""
        if type(binding) is not tuple or len(binding) != 3:
            raise ValueError("feature binding must contain source, stream and instrument")
        asset = str(binding[2])
        if not asset.strip():
            raise ValueError("feature binding instrument must be nonempty")
        return asset

    def _validate_features(self) -> tuple[str, ...]:
        """Validate feature rows and return their ordered identities."""
        if type(self.features) is not tuple:
            raise TypeError("features must be an immutable tuple")
        identities: list[str] = []
        for row_id, feature in self.features:
            if type(row_id) is not str or not row_id.strip() or type(feature) is not FeatureValue:
                raise TypeError("features require row identities and FeatureValue records")
            if type(feature.window) is not PriceWindow:
                raise TypeError("feature rows require PriceWindow records")
            if feature.value is not None:
                if type(feature.value) is not ExactRatio:
                    raise TypeError("feature values must be ExactRatio or None")
                feature.value.__post_init__()
            self._require_utc(feature.decision_at, field_name="feature.decision_at")
            self._require_utc(feature.available_at, field_name="feature.available_at")
            if feature.decision_at != feature.available_at:
                raise ValueError("feature availability must equal its decision clock")
            identities.append(row_id)
        if len(set(identities)) != len(identities):
            raise ValueError("feature row identities must be unique")
        return tuple(identities)

    def _validate_labels(self) -> tuple[str, ...]:
        """Validate labels and return their ordered identities."""
        if type(self.labels) is not tuple:
            raise TypeError("labels must be an immutable tuple")
        identities: list[str] = []
        for row_id, label in self.labels:
            if type(row_id) is not str or not row_id.strip() or type(label) is not LabelValue:
                raise TypeError("labels require row identities and LabelValue records")
            self._require_utc(label.decision_at, field_name="label.decision_at")
            self._require_utc(label.outcome_at, field_name="label.outcome_at")
            self._require_utc(label.information_start, field_name="label.information_start")
            self._require_utc(label.information_end, field_name="label.information_end")
            if label.available_at is not None:
                self._require_utc(label.available_at, field_name="label.available_at")
            if label.window is not None and type(label.window) is not PriceWindow:
                raise TypeError("label rows require PriceWindow or None")
            if label.value is not None:
                if type(label.value) is not ExactRatio:
                    raise TypeError("label values must be ExactRatio or None")
                label.value.__post_init__()
            identities.append(row_id)
        if len(set(identities)) != len(identities):
            raise ValueError("label row identities must be unique")
        return tuple(identities)

    def _validate_samples(self) -> tuple[str, ...]:
        """Validate sample intervals and return their ordered identities."""
        if type(self.samples) is not tuple:
            raise TypeError("samples must be an immutable tuple")
        identities: list[str] = []
        for sample in self.samples:
            if type(sample) is not SampleInterval:
                raise TypeError("samples require SampleInterval records")
            sample.__post_init__()
            identities.append(sample.row_id)
        if len(set(identities)) != len(identities):
            raise ValueError("sample row identities must be unique")
        return tuple(identities)


# This alias makes the producer's result terminology available to callers
# without inventing a second wire schema or importing the model package.
FeatureStudyResult = FeatureLabelPayload


class AlphalensStudy(WireRecord, frozen=True, kw_only=True):
    """Declare one bounded cross-sectional Alphalens comparison."""

    schema_version: Literal["alphalens-study-v1"] = "alphalens-study-v1"
    selection_identity: str
    universe: tuple[str, ...] = ()
    factor_direction: FactorDirection = "ascending"
    horizon_us: int = 0
    price_convention: PriceConvention = _PRICE_CONVENTION
    groups: tuple[tuple[str, str], ...] = ()
    quantiles: int = 5
    quantile_rule: QuantileRule = "equal-frequency-qcut-v1"
    demeaned: bool = True
    group_adjust: bool = False
    known_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate source, universe, factor, horizon and quantile choices."""
        if (
            self.schema_version != "alphalens-study-v1"
            or not FeatureLabelPayload._fingerprint(self.selection_identity)
            or self.factor_direction not in ("ascending", "descending")
            or type(self.horizon_us) is not int
            or not 0 <= self.horizon_us <= 31_536_000_000_000
            or self.price_convention != _PRICE_CONVENTION
            or type(self.quantiles) is not int
            or not 2 <= self.quantiles <= 20
            or self.quantile_rule != "equal-frequency-qcut-v1"
            or type(self.demeaned) is not bool
            or type(self.group_adjust) is not bool
        ):
            raise ValueError("invalid Alphalens factor study configuration")
        self._validate_names(self.universe, "universe")
        if type(self.groups) is not tuple:
            raise TypeError("groups must be an immutable tuple")
        seen_groups: set[str] = set()
        for asset, group in self.groups:
            if (
                type(asset) is not str
                or not asset.strip()
                or type(group) is not str
                or not group.strip()
            ):
                raise ValueError("groups require nonempty asset and group names")
            if asset in seen_groups:
                raise ValueError("groups must contain one mapping per asset")
            seen_groups.add(asset)
        if self.known_at is not None:
            self._require_utc(self.known_at, field_name="known_at")

    @staticmethod
    def _validate_names(names: tuple[str, ...], field_name: str) -> None:
        """Validate an immutable unique-name collection."""
        if type(names) is not tuple or any(
            type(value) is not str or not value.strip() for value in names
        ):
            raise TypeError(f"{field_name} must contain nonempty strings")
        if len(set(names)) != len(names):
            raise ValueError(f"{field_name} must contain unique names")


class AlphalensReport(WireRecord, frozen=True, kw_only=True):
    """Retain Alphalens metrics, exclusions and ClearML-ready report bytes."""

    schema_version: Literal["alphalens-report-v1"] = "alphalens-report-v1"
    selection_identity: str
    universe: tuple[str, ...]
    factor_direction: FactorDirection
    horizon_us: int
    price_convention: PriceConvention
    groups: tuple[tuple[str, str], ...]
    quantiles: int
    quantile_rule: QuantileRule
    demeaned: bool
    group_adjust: bool
    known_at: datetime | None
    eligible_rows: tuple[str, ...]
    dropped_rows: tuple[DiagnosticDrop, ...]
    late_labels: tuple[DiagnosticDrop, ...]
    information_coefficients: tuple[DiagnosticMetric, ...]
    quantile_returns: tuple[DiagnosticMetric, ...]
    turnover: tuple[DiagnosticMetric, ...]
    inapplicable_reason: str | None
    report_json: bytes
    report_html: bytes

    def __post_init__(self) -> None:
        """Validate immutable metadata, metrics and nonempty report artifacts."""
        if (
            self.schema_version != "alphalens-report-v1"
            or not FeatureLabelPayload._fingerprint(self.selection_identity)
            or type(self.report_json) is not bytes
            or not self.report_json
            or type(self.report_html) is not bytes
            or not self.report_html
            or type(self.horizon_us) is not int
            or self.horizon_us < 0
            or type(self.quantiles) is not int
            or self.quantiles < 2
            or self.quantile_rule != "equal-frequency-qcut-v1"
            or type(self.demeaned) is not bool
            or type(self.group_adjust) is not bool
            or self.price_convention != _PRICE_CONVENTION
            or type(self.quantile_rule) is not str
            or not self.quantile_rule.strip()
        ):
            raise ValueError("invalid Alphalens report")
        for metric in (*self.information_coefficients, *self.quantile_returns, *self.turnover):
            metric.__post_init__()
        for drop in (*self.dropped_rows, *self.late_labels):
            drop.__post_init__()
        if self.known_at is not None:
            self._require_utc(self.known_at, field_name="known_at")
        if self.inapplicable_reason is not None and not self.inapplicable_reason.strip():
            raise ValueError("inapplicable report reason cannot be empty")

    @property
    def json_bytes(self) -> bytes:
        """Expose JSON bytes under the artifact-oriented retention name.

        Returns:
            UTF-8 report JSON bytes for retention.
        """
        return self.report_json

    @property
    def html_bytes(self) -> bytes:
        """Expose HTML bytes under the artifact-oriented retention name.

        Returns:
            UTF-8 report HTML bytes for retention.
        """
        return self.report_html

    @property
    def dropped(self) -> tuple[DiagnosticDrop, ...]:
        """Return ordinary exclusions; late labels remain separately attributable.

        Returns:
            Dropped rows that were not classified as late labels.
        """
        return self.dropped_rows


class AlphalensDiagnostics:
    """Adapt explicit MR3 factor/label values to real Alphalens calculations."""

    _MAX_ROWS = 1024

    def evaluate(
        self, study: AlphalensStudy, payload: FeatureLabelPayload | bytes
    ) -> AlphalensReport:
        """Run IC, quantile-return and turnover calculations for one declared study.

        Args:
            study: Explicit factor direction, universe, horizon, groups and quantiles.
            payload: Verified ``FeatureLabelPayload`` or retained JSON bytes.

        Returns:
            A typed report retaining exclusions and JSON/HTML artifact bytes.

        Raises:
            RuntimeError: The pinned Alphalens dependency is unavailable.
            ValueError: Payload definitions or source selection conflict with the study.
        """
        study.__post_init__()
        source = FeatureLabelPayload.decode(payload) if isinstance(payload, bytes) else payload
        if type(source) is not FeatureLabelPayload:
            raise TypeError("Alphalens requires a FeatureLabelPayload")
        source.__post_init__()
        self._check_source(study, source)
        horizon = self._effective_horizon(study, source)
        observations, dropped, late = self._observations(study, source)
        universe = study.universe or source.universe
        if source.label_definition is None:
            return self._report(
                study,
                universe,
                horizon,
                (),
                dropped,
                late,
                (),
                (),
                (),
                "an explicit forward-return label definition is required",
            )
        if not observations:
            return self._report(
                study,
                universe,
                horizon,
                (),
                dropped,
                late,
                (),
                (),
                (),
                "no complete factor/label observations are available",
            )
        by_date = self._date_counts(observations)
        if not any(count >= 2 for count in by_date.values()):
            return self._report(
                study,
                universe,
                horizon,
                (),
                dropped,
                late,
                (),
                (),
                (),
                "cross-sectional statistics require at least two assets at one decision",
            )
        try:
            pandas = cast(_PandasModule, importlib.import_module("pandas"))
            alphalens = self._load_alphalens()
            frame, _ = self._frame(pandas, study, observations, horizon)
            quantile = alphalens.utils.quantize_factor(
                frame,
                quantiles=study.quantiles,
                by_group=bool(study.groups),
                no_raise=True,
                zero_aware=False,
            )
            frame["factor_quantile"] = quantile
            quantile_values = self._series_values(quantile)
            quantile_rows = tuple(
                item.row_id
                for item in observations
                if self._is_missing(quantile_values.get((item.decision_at, item.asset)))
            )
            if quantile_rows:
                dropped = (*dropped, *self._quantile_drops(quantile_rows, observations))
            frame = frame.dropna(subset=["factor_quantile"])
            eligible = tuple(item for item in observations if item.row_id not in set(quantile_rows))
            if frame.empty or not eligible:
                return self._report(
                    study,
                    universe,
                    horizon,
                    (),
                    dropped,
                    late,
                    (),
                    (),
                    (),
                    "the selected quantile rule produced no eligible rows",
                )
            grouped = bool(study.groups)
            ic_native = alphalens.performance.factor_information_coefficient(
                frame, group_adjust=study.group_adjust, by_group=grouped
            )
            mean_native, _ = alphalens.performance.mean_return_by_quantile(
                frame,
                by_date=False,
                by_group=grouped,
                demeaned=study.demeaned,
                group_adjust=study.group_adjust,
            )
            ic = self._frame_metrics(
                "information_coefficient", ic_native, self._index_counts(frame)
            )
            quantile_returns = self._frame_metrics(
                "quantile_return", mean_native, self._quantile_counts(frame)
            )
            turnover = self._turnover_metrics(
                alphalens.performance, frame["factor_quantile"], study.quantiles
            )
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "alphalens-reloaded==0.4.3 is required for factor diagnostics"
            ) from error
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
            raise ValueError(
                f"Alphalens could not evaluate the declared factor sample: {error}"
            ) from error
        return self._report(
            study,
            universe,
            horizon,
            tuple(item.row_id for item in eligible),
            dropped,
            late,
            ic,
            quantile_returns,
            turnover,
            None,
        )

    @staticmethod
    def _load_alphalens() -> _AlphalensModule:
        """Load and type the pinned Alphalens modules only at evaluation time."""
        return cast(_AlphalensModule, importlib.import_module("alphalens"))

    @staticmethod
    def _effective_horizon(study: AlphalensStudy, payload: FeatureLabelPayload) -> int:
        """Resolve the report horizon from the retained label definition."""
        if payload.label_definition is None:
            return study.horizon_us
        horizon = payload.label_definition.horizon_us
        if study.horizon_us not in (0, horizon):
            raise ValueError("Alphalens horizon differs from the retained label definition")
        return horizon

    @staticmethod
    def _check_source(study: AlphalensStudy, payload: FeatureLabelPayload) -> None:
        """Reject source-selection, universe and group mappings absent from the payload."""
        if study.price_convention != _PRICE_CONVENTION:
            raise ValueError("unsupported Alphalens price convention")
        if study.selection_identity != payload.selection_identity:
            raise ValueError("Alphalens selection identity differs from the feature payload")
        source_universe = set(payload.universe)
        if study.universe and not set(study.universe) <= source_universe:
            raise ValueError("Alphalens universe includes an asset absent from the feature payload")
        if any(asset not in source_universe for asset, _ in study.groups):
            raise ValueError("Alphalens group mapping includes an asset absent from the payload")

    def _observations(
        self, study: AlphalensStudy, payload: FeatureLabelPayload
    ) -> tuple[tuple[_Observation, ...], tuple[DiagnosticDrop, ...], tuple[DiagnosticDrop, ...]]:
        """Admit only complete factor/label rows whose labels were then available."""
        labels = dict(payload.labels)
        observations: list[_Observation] = []
        dropped: list[DiagnosticDrop] = []
        late: list[DiagnosticDrop] = []
        groups = dict(study.groups)
        for row_id, feature, label, sample in payload.aligned_rows():
            asset = FeatureLabelPayload._asset_name(feature.window.binding)
            if study.universe and asset not in study.universe:
                dropped.append(
                    DiagnosticDrop(
                        row_id=row_id,
                        decision_at=sample.decision_at,
                        reason="outside declared universe",
                    )
                )
                continue
            if feature.value is None:
                dropped.append(
                    DiagnosticDrop(
                        row_id=row_id,
                        decision_at=sample.decision_at,
                        reason="missing factor value",
                    )
                )
                continue
            if study.groups and asset not in groups:
                dropped.append(
                    DiagnosticDrop(
                        row_id=row_id,
                        decision_at=sample.decision_at,
                        reason="asset has no declared group",
                    )
                )
                continue
            retained = label if row_id in labels else None
            if retained is None or retained.value is None:
                expected = self._expected_label_availability(payload, retained)
                reason = (
                    "missing forward label"
                    if retained is None
                    else (retained.missing or "missing forward label")
                )
                if reason == "outcome not yet available" or (
                    expected is not None and (study.known_at is None or expected > study.known_at)
                ):
                    late.append(
                        DiagnosticDrop(
                            row_id=row_id,
                            decision_at=sample.decision_at,
                            reason=reason,
                            available_at=expected,
                        )
                    )
                else:
                    dropped.append(
                        DiagnosticDrop(
                            row_id=row_id,
                            decision_at=sample.decision_at,
                            reason=reason,
                            available_at=expected,
                        )
                    )
                continue
            available = retained.available_at
            if available is None:
                dropped.append(
                    DiagnosticDrop(
                        row_id=row_id,
                        decision_at=sample.decision_at,
                        reason="label availability is unknown",
                    )
                )
                continue
            if study.known_at is not None and available > study.known_at:
                late.append(
                    DiagnosticDrop(
                        row_id=row_id,
                        decision_at=sample.decision_at,
                        reason="label unavailable at evaluation cutoff",
                        available_at=available,
                    )
                )
                continue
            factor = self._fraction(feature.value)
            outcome = self._fraction(retained.value)
            if study.factor_direction == "descending":
                factor = -factor
            observations.append(
                _Observation(
                    row_id,
                    asset,
                    groups.get(asset),
                    sample.decision_at,
                    factor,
                    outcome,
                )
            )
        return tuple(observations), tuple(dropped), tuple(late)

    @staticmethod
    def _expected_label_availability(
        payload: FeatureLabelPayload, label: LabelValue | None
    ) -> datetime | None:
        """Infer only the declared publication clock for a pending retained label."""
        if label is None or payload.label_definition is None:
            return None
        return label.outcome_at + timedelta(
            microseconds=payload.label_definition.availability_delay_us
        )

    @staticmethod
    def _fraction(value: ExactRatio) -> Fraction:
        """Convert a canonical exact ratio only at the third-party float boundary."""
        value.__post_init__()
        return Fraction(int(value.numerator), int(value.denominator))

    def _frame(
        self,
        pandas: _PandasModule,
        study: AlphalensStudy,
        observations: tuple[_Observation, ...],
        horizon: int,
    ) -> tuple[pd.DataFrame, str]:
        """Build Alphalens' expected factor/forward-return MultiIndex frame."""
        period = self._period_name(horizon)
        index = pandas.MultiIndex.from_tuples(
            [(item.decision_at, item.asset) for item in observations], names=("date", "asset")
        )
        values: dict[str, list[float] | list[str | None]] = {
            "factor": [self._finite_float(item.factor) for item in observations],
            period: [self._finite_float(item.label) for item in observations],
        }
        if any(item.group is not None for item in observations):
            values["group"] = [item.group for item in observations]
        return pandas.DataFrame(values, index=index), period

    @staticmethod
    def _period_name(horizon_us: int) -> str:
        """Encode an exact horizon using Alphalens' accepted timedelta column syntax."""
        if horizon_us % 86_400_000_000 == 0:
            return f"{horizon_us // 86_400_000_000}D"
        if horizon_us % 3_600_000_000 == 0:
            return f"{horizon_us // 3_600_000_000}h"
        if horizon_us % 60_000_000 == 0:
            return f"{horizon_us // 60_000_000}m"
        if horizon_us % 1_000_000 == 0:
            return f"{horizon_us // 1_000_000}s"
        if horizon_us % 1_000 == 0:
            return f"{horizon_us // 1_000}ms"
        return f"{horizon_us}us"

    @staticmethod
    def _finite_float(value: Fraction) -> float:
        """Project one exact rational to a finite third-party float."""
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("diagnostic ratio cannot be represented as a finite float")
        return result

    @staticmethod
    def _date_counts(observations: tuple[_Observation, ...]) -> dict[datetime, int]:
        """Count complete cross-sectional rows per decision."""
        counts: dict[datetime, int] = {}
        for item in observations:
            counts[item.decision_at] = counts.get(item.decision_at, 0) + 1
        return counts

    @staticmethod
    def _series_values(series: pd.Series) -> dict[object, object]:
        """Read a native quantile series without importing pandas types eagerly."""
        raw = cast(_SeriesLike, series).to_dict()
        return AlphalensDiagnostics._mapping(raw) or {}

    @staticmethod
    def _mapping(value: object) -> dict[object, object] | None:
        """Narrow a native mapping without allowing an untyped dict through mypy."""
        if type(value) is not dict:
            return None
        return cast(dict[object, object], value)

    @staticmethod
    def _object_list(value: object) -> list[object] | None:
        """Narrow a native list without allowing an untyped list through mypy."""
        if type(value) is not list:
            return None
        return cast(list[object], value)

    @classmethod
    def _index_counts(cls, frame: pd.DataFrame) -> dict[str, int]:
        """Count source rows by the exact index key returned by Alphalens."""
        raw = cast(_DataFrameLike, frame).to_dict(orient="split")
        counts: dict[str, int] = {}
        mapping = cls._mapping(raw)
        if mapping is None:
            return counts
        indexes = cls._object_list(mapping.get("index"))
        rows = cls._object_list(mapping.get("data"))
        columns = cls._object_list(mapping.get("columns"))
        if indexes is None or rows is None or columns is None:
            return counts
        group_column = columns.index("group") if "group" in columns else -1
        for index, values in zip(indexes, rows, strict=False):
            key = cls._key_text(index)
            counts[key] = counts.get(key, 0) + 1
            row_values = cls._object_list(values)
            if group_column >= 0 and row_values is not None and group_column < len(row_values):
                group = row_values[group_column]
                if group is not None:
                    date = index[0] if isinstance(index, tuple) and index else index
                    grouped_key = f"{cls._scalar_text(date)}|{group}"
                    counts[grouped_key] = counts.get(grouped_key, 0) + 1
        return counts

    @classmethod
    def _quantile_counts(cls, frame: pd.DataFrame) -> dict[str, int]:
        """Count source rows by the factor quantile index used in mean returns."""
        counts: dict[str, int] = {}
        raw = cast(_DataFrameLike, frame).to_dict(orient="split")
        mapping = cls._mapping(raw)
        if mapping is None:
            return counts
        columns = cls._object_list(mapping.get("columns"))
        rows = cls._object_list(mapping.get("data"))
        if columns is None or rows is None:
            return counts
        quantile_column = columns.index("factor_quantile") if "factor_quantile" in columns else -1
        group_column = columns.index("group") if "group" in columns else -1
        for row in rows:
            values = cls._object_list(row)
            if values is None or quantile_column < 0 or quantile_column >= len(values):
                continue
            value = values[quantile_column]
            if cls._is_missing(value):
                continue
            key = cls._key_text(value)
            counts[key] = counts.get(key, 0) + 1
            if (
                group_column >= 0
                and group_column < len(values)
                and values[group_column] is not None
            ):
                grouped_key = f"{key}|{values[group_column]}"
                counts[grouped_key] = counts.get(grouped_key, 0) + 1
        return counts

    @classmethod
    def _frame_metrics(
        cls, name: str, result: pd.DataFrame, counts: Mapping[str, int]
    ) -> tuple[DiagnosticMetric, ...]:
        """Project one Alphalens DataFrame result into typed metric rows."""
        raw = cast(_DataFrameLike, result).to_dict(orient="split")
        mapping = cls._mapping(raw)
        if mapping is None:
            return ()
        columns = cls._object_list(mapping.get("columns"))
        indexes = cls._object_list(mapping.get("index"))
        rows = cls._object_list(mapping.get("data"))
        if columns is None or indexes is None or rows is None:
            return ()
        output: list[DiagnosticMetric] = []
        for index, row in zip(indexes, rows, strict=False):
            values = cls._object_list(row)
            if values is None:
                continue
            index_key = cls._key_text(index)
            sample_count = counts.get(index_key, 0)
            group = cls._group_from_index(index)
            for column, value in zip(columns, values, strict=False):
                if type(column) is not str:
                    continue
                output.append(
                    DiagnosticMetric(
                        name=name,
                        period=cls._metric_period(index, column),
                        group=group,
                        value=cls._optional_float(value),
                        sample_count=sample_count,
                    )
                )
        return tuple(output)

    @classmethod
    def _turnover_metrics(
        cls, performance: _PerformanceAPI, quantile_factor: pd.Series, quantiles: int
    ) -> tuple[DiagnosticMetric, ...]:
        """Calculate turnover for every configured quantile with real Alphalens code."""
        output: list[DiagnosticMetric] = []
        for quantile in range(1, quantiles + 1):
            series = performance.quantile_turnover(quantile_factor, quantile, period=1)
            raw = cast(_SeriesLike, series).to_dict()
            mapping = cls._mapping(raw)
            if mapping is None:
                continue
            for index, value in mapping.items():
                output.append(
                    DiagnosticMetric(
                        name="turnover",
                        period=f"q{quantile}:{cls._scalar_text(index)}",
                        group=str(quantile),
                        value=cls._optional_float(value),
                        sample_count=0 if cls._optional_float(value) is None else 1,
                    )
                )
        return tuple(output)

    @staticmethod
    def _optional_float(value: object) -> float | None:
        """Translate native scalar output while retaining undefined statistics."""
        if not isinstance(value, Real):
            return None
        projected = float(value)
        return projected if math.isfinite(projected) else None

    @staticmethod
    def _is_missing(value: object) -> bool:
        """Recognize native NaN/None quantile assignments without pandas imports."""
        if value is None:
            return True
        if isinstance(value, Real):
            return not math.isfinite(float(value))
        return False

    @staticmethod
    def _scalar_text(value: object) -> str:
        """Encode a native index scalar deterministically for a wire metric key."""
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    @classmethod
    def _key_text(cls, value: object) -> str:
        """Encode scalar or MultiIndex keys without relying on pandas internals."""
        if isinstance(value, tuple):
            return "|".join(cls._scalar_text(item) for item in value)
        return cls._scalar_text(value)

    @classmethod
    def _metric_period(cls, index: object, column: str) -> str:
        """Retain both native period and returned index in one stable metric key."""
        return f"{cls._key_text(index)}:{column}"

    @staticmethod
    def _group_from_index(index: object) -> str | None:
        """Project a grouped MultiIndex level when Alphalens returned one."""
        if isinstance(index, tuple) and len(index) > 1:
            return str(index[-1])
        return None

    @staticmethod
    def _quantile_drops(
        row_ids: tuple[str, ...], observations: tuple[_Observation, ...]
    ) -> tuple[DiagnosticDrop, ...]:
        """Retain rows Alphalens could not assign under the declared quantile rule."""
        by_id = {item.row_id: item for item in observations}
        return tuple(
            DiagnosticDrop(
                row_id=row_id,
                decision_at=by_id[row_id].decision_at,
                reason="quantile unavailable",
            )
            for row_id in row_ids
            if row_id in by_id
        )

    def _report(
        self,
        study: AlphalensStudy,
        universe: tuple[str, ...],
        horizon: int,
        eligible_rows: tuple[str, ...],
        dropped: tuple[DiagnosticDrop, ...],
        late: tuple[DiagnosticDrop, ...],
        ic: tuple[DiagnosticMetric, ...],
        quantile_returns: tuple[DiagnosticMetric, ...],
        turnover: tuple[DiagnosticMetric, ...],
        reason: str | None,
    ) -> AlphalensReport:
        """Materialize a typed summary and deterministic ClearML-ready artifacts."""
        summary = {
            "schema_version": "alphalens-report-v1",
            "selection_identity": study.selection_identity,
            "universe": universe,
            "factor_direction": study.factor_direction,
            "horizon_us": horizon,
            "price_convention": study.price_convention,
            "groups": study.groups,
            "quantiles": study.quantiles,
            "quantile_rule": study.quantile_rule,
            "demeaned": study.demeaned,
            "group_adjust": study.group_adjust,
            "known_at": study.known_at,
            "eligible_rows": eligible_rows,
            "dropped_rows": dropped,
            "late_labels": late,
            "information_coefficients": ic,
            "quantile_returns": quantile_returns,
            "turnover": turnover,
            "inapplicable_reason": reason,
        }
        payload = DomainCodec().encode_json(summary)
        page = self._html("Alphalens factor diagnostics", payload)
        return AlphalensReport(
            selection_identity=study.selection_identity,
            universe=universe,
            factor_direction=study.factor_direction,
            horizon_us=horizon,
            price_convention=study.price_convention,
            groups=study.groups,
            quantiles=study.quantiles,
            quantile_rule=study.quantile_rule,
            demeaned=study.demeaned,
            group_adjust=study.group_adjust,
            known_at=study.known_at,
            eligible_rows=eligible_rows,
            dropped_rows=dropped,
            late_labels=late,
            information_coefficients=ic,
            quantile_returns=quantile_returns,
            turnover=turnover,
            inapplicable_reason=reason,
            report_json=payload,
            report_html=page,
        )

    @staticmethod
    def _html(title: str, payload: bytes) -> bytes:
        """Create a self-contained HTML artifact from retained JSON bytes."""
        body = html.escape(payload.decode("utf-8"))
        return (
            '<!doctype html><html><head><meta charset="utf-8"><title>'
            + html.escape(title)
            + "</title></head><body><h1>"
            + html.escape(title)
            + "</h1><pre>"
            + body
            + "</pre></body></html>"
        ).encode("utf-8")


class _Observation:
    """Internal immutable aligned row at the exact-to-float adapter boundary."""

    __slots__ = ("asset", "decision_at", "factor", "group", "label", "row_id")

    def __init__(
        self,
        row_id: str,
        asset: str,
        group: str | None,
        decision_at: datetime,
        factor: Fraction,
        label: Fraction,
    ) -> None:
        """Bind one verified MR3 row without retaining mutable dataframe state."""
        self.row_id = row_id
        self.asset = asset
        self.group = group
        self.decision_at = decision_at
        self.factor = factor
        self.label = label
