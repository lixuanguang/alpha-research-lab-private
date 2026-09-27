"""Validate the retained feature-study result wire contract."""

from __future__ import annotations

# standard library imports
from typing import Literal

# project library imports
from financial_units import ExactRatio
from research.experiments import SampleInterval
from research.features import FeatureValue, PriceWindow, TrailingReturn
from research.labels import ForwardReturn, LabelValue
from serialization import DomainCodec, WireRecord


class FeatureStudyResult(WireRecord, frozen=True, kw_only=True):
    """Decode and verify the retained feature/label result contract.

    The producer, model admission boundary and reporting adapters share this
    closed ``feature-study-result-v1`` schema.  Model-specific checks remain at
    the model boundary; this class only owns the common wire shape and
    feature/label/sample invariants. One to 16,384 aligned feature rows may be retained.
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
        """Verify definitions, clocks and aligned row identities before use."""
        if (
            self.schema_version != "feature-study-result-v1"
            or self.scope != "exploratory_degraded"
            or type(self.fitting) is not str
            or not self.fitting.strip()
            or not self.is_fingerprint(self.selection_identity)
            or not self.is_fingerprint(self.split_identity)
        ):
            raise ValueError("unsupported or malformed feature-study result payload")
        self.feature_definition.__post_init__()
        if self.label_definition is not None:
            self.label_definition.__post_init__()
        feature_ids = self._validate_features()
        label_ids = self._validate_labels()
        sample_ids = self._validate_samples()
        if not 1 <= len(feature_ids) <= 16_384:
            raise ValueError("feature-study result must contain 1 to 16384 rows")
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
    def decode(cls, payload: bytes) -> FeatureStudyResult:
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
        assets = {self.asset_name(feature.window.binding) for _, feature in self.features}
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
    def is_fingerprint(value: str) -> bool:
        """Check a repository SHA-256 identity without normalizing authored text.

        Args:
            value: Authored identity text.

        Returns:
            Whether the identity contains exactly 64 lowercase hexadecimal characters.
        """
        return (
            type(value) is str
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    @staticmethod
    def asset_name(binding: tuple[object, object, object]) -> str:
        """Project one source binding to the stable instrument identity.

        Args:
            binding: Source, stream and instrument identity retained with a feature.

        Returns:
            Nonempty instrument identity text.

        Raises:
            ValueError: The binding shape or instrument identity is invalid.
        """
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
