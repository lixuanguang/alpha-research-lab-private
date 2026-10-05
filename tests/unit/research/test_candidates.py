"""Exercise candidate integrity, completed-attempt linkage and qualification boundaries."""

from __future__ import annotations

# standard library imports
import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from configuration import CapabilityRequirement
from research.experiments import (
    AttemptStore,
    ExperimentSpec,
    Fingerprint,
    TemporalSplit,
    TimeWindow,
)
from research.experiments.candidates import (
    CandidateArtifact,
    CandidateAssessment,
    CandidateBundle,
    CandidateComponent,
    CandidateDefinition,
    CandidateManifest,
    CandidateMetricContract,
    CandidateStateContract,
)
from research.observations import InputRequirement, NumericField
from research.studies import ResultManifest
from serialization import DomainCodec

_START = datetime(2024, 6, 1, tzinfo=UTC)
_CODE_SHA256 = "b" * 64
_ENVIRONMENT_SHA256 = "c" * 64
_METRIC_SHA256 = "d" * 64
_CHART_SHA256 = "e" * 64


class TestCandidateBundles:
    """Use a real attempt store and independently corrupted bundle bytes."""

    @staticmethod
    def _artifact(name: str, payload: bytes) -> CandidateArtifact:
        """Identify known test bytes without relying on the bundle writer."""
        return CandidateArtifact(name=name, sha256=hashlib.sha256(payload).hexdigest())

    @staticmethod
    def _requirements() -> tuple[CapabilityRequirement, ...]:
        """Declare six independently resolved service families for one spot scope."""
        return (
            CapabilityRequirement(
                name="market",
                kind="market_data",
                product="spot",
                venue="okx",
                calendar="always-open",
            ),
            CapabilityRequirement(
                name="reference",
                kind="reference_data",
                product="spot",
                venue="okx",
                calendar="always-open",
            ),
            CapabilityRequirement(
                name="calendar",
                kind="calendar",
                product="spot",
                venue="okx",
                calendar="always-open",
            ),
            CapabilityRequirement(
                name="valuation",
                kind="valuation",
                product="spot",
                venue="okx",
                calendar="always-open",
            ),
            CapabilityRequirement(
                name="account",
                kind="account",
                product="spot",
                venue="okx",
                calendar="always-open",
            ),
            CapabilityRequirement(
                name="execution",
                kind="execution",
                product="spot",
                venue="okx",
                calendar="always-open",
            ),
        )

    @classmethod
    def _bundle_inputs(
        cls, root: Path, *, empirical: bool = False, learned: bool = False
    ) -> tuple[CandidateManifest, dict[str, bytes]]:
        """Retain actual completed attempt and selected report through their owners."""
        codec = DomainCodec()
        market_input = InputRequirement(
            name="market",
            family="book",
            clock="receipt",
            field=NumericField(name="mid", units="USD/base"),
            max_age_us=1_000_000,
        )
        selected_metric = Fingerprint(name="net-return", sha256=_METRIC_SHA256)
        selected_chart = Fingerprint(name="ledger-curve", sha256=_CHART_SHA256)
        feature_schema = codec.encode_json(
            {
                "schema_version": "feature-schema",
                "implementation": "feature-algorithm",
                "mode": "batch",
                "inputs": (market_input,),
            }
        )
        feature_identity = hashlib.sha256(feature_schema).hexdigest()
        payloads: dict[str, bytes] = {
            "dataset-selection": codec.encode_json(
                {
                    "schema_version": "decision-study",
                    "family": "candidate-reference",
                    "source_identity": "saved-okx-decision-source",
                    "feature_identity": feature_identity,
                    "policy_identity": "policy",
                    "model_identity": "nearest-example" if learned else None,
                    "transform_identity": "fitted-center" if learned else None,
                    "output": "target",
                    "calendar": "always-open",
                    "economics": {
                        "schema_version": "offline-intent-simulation",
                        "entity": "ETH-USDT",
                        "source_identity": "saved-okx-execution-market",
                    },
                    "metrics": (selected_metric,),
                    "charts": (selected_chart,),
                }
            ),
            "feature-schema": feature_schema,
            "feature-parameters": b'{"window":"2"}',
            "policy-parameters": b'{"threshold":"1/2"}',
            "metric-parameters": b"{}",
            "chart-parameters": b"{}",
        }
        if learned:
            payloads.update(
                {
                    "transform-version": b'{"implementation":"fitted-center"}',
                    "estimator-version": b'{"implementation":"nearest-example"}',
                    "transform-parameters": b'{"kind":"center"}',
                    "estimator-parameters": b'{"k":"1"}',
                }
            )
        split = (
            TemporalSplit(
                training=None,
                validation=TimeWindow(start=_START, end=_START + timedelta(hours=2)),
                holdout=TimeWindow(
                    start=_START + timedelta(hours=3), end=_START + timedelta(hours=5)
                ),
                samples=(),
                fit_mode="none",
                fit_cutoff=None,
                embargo_us=0,
                rationale="An authored no-fit validation interval and untouched final interval.",
            )
            if empirical
            else None
        )
        spec = ExperimentSpec(
            schema_version=("experiment-spec" if empirical else "experiment-engineering-sample"),
            family="candidate-reference",
            inputs=(
                Fingerprint(
                    name="resolved-configuration",
                    sha256=hashlib.sha256(payloads["dataset-selection"]).hexdigest(),
                ),
            ),
            components=(Fingerprint(name="implementation", sha256=_CODE_SHA256),),
            parameters=(),
            seeds=(),
            environment_sha256=_ENVIRONMENT_SHA256,
            split=split,
            engineering_sample=(
                TimeWindow(start=_START, end=_START + timedelta(hours=5)) if split is None else None
            ),
        )
        payloads["study-report"] = codec.encode_json(
            {
                "schema_version": "study-report",
                "study_identity": spec.identity,
                "selected_metrics": (selected_metric,),
                "selected_charts": (selected_chart,),
            }
        )
        if empirical:
            payloads["assessment"] = codec.encode_json(
                CandidateAssessment(
                    report_sha256=hashlib.sha256(payloads["study-report"]).hexdigest(),
                    decision="accepted",
                    rationale="Independent research acceptance of this exact report.",
                    limitations=("Future market outcomes remain unknown.",),
                )
            )
        retained = {
            "study-report": payloads["study-report"],
            "feature-schema": payloads["feature-schema"],
        }
        if learned:
            retained["transform-version"] = payloads["transform-version"]
            retained["estimator-version"] = payloads["estimator-version"]
        with AttemptStore(root / "attempts") as store:
            started = store.start(
                spec,
                at=_START + timedelta(hours=6),
                invocation="tests.unit.research.candidate_reference",
                request=payloads["dataset-selection"],
            )
            result = ResultManifest.retain(store, started.attempt_id, retained)
            history = store.finish(
                started.attempt_id,
                status="completed",
                at=_START + timedelta(hours=7),
                reason="Retained reference candidate research result.",
                result=codec.encode_json(result),
            )
        payloads["experiment"] = codec.encode_json(spec)
        payloads["attempt"] = codec.encode_json(history)
        artifacts = {name: cls._artifact(name, payload) for name, payload in payloads.items()}
        components = [
            CandidateComponent(
                role="feature",
                factory_key="feature-reference",
                identity=feature_identity,
                implementation_sha256=_CODE_SHA256,
                parameters=artifacts["feature-parameters"],
            ),
            CandidateComponent(
                role="policy",
                factory_key="policy-reference",
                identity="policy",
                implementation_sha256=_CODE_SHA256,
                parameters=artifacts["policy-parameters"],
            ),
            CandidateComponent(
                role="metric",
                factory_key="net-return",
                identity=_METRIC_SHA256,
                implementation_sha256=_CODE_SHA256,
                parameters=artifacts["metric-parameters"],
            ),
            CandidateComponent(
                role="chart",
                factory_key="ledger-curve",
                identity=_CHART_SHA256,
                implementation_sha256=_CODE_SHA256,
                parameters=artifacts["chart-parameters"],
            ),
        ]
        if learned:
            components.extend(
                (
                    CandidateComponent(
                        role="transform",
                        factory_key="fitted-center",
                        identity="fitted-center",
                        implementation_sha256=_CODE_SHA256,
                        parameters=artifacts["transform-parameters"],
                    ),
                    CandidateComponent(
                        role="estimator",
                        factory_key="nearest-example",
                        identity="nearest-example",
                        implementation_sha256=_CODE_SHA256,
                        parameters=artifacts["estimator-parameters"],
                    ),
                )
            )
        provenance = ("assessment", "attempt", "dataset-selection", "experiment", "study-report")
        definition = CandidateDefinition(
            name="candidate-reference",
            version="reference",
            code_sha256=_CODE_SHA256,
            environment_sha256=_ENVIRONMENT_SHA256,
            runtime_code_sha256=_CODE_SHA256,
            runtime_environment_sha256=_ENVIRONMENT_SHA256,
            feature_schema=artifacts["feature-schema"],
            feature_store=None,
            transform=artifacts["transform-version"] if learned else None,
            estimator=artifacts["estimator-version"] if learned else None,
            components=tuple(components),
            inputs=(market_input,),
            requirements=cls._requirements(),
            product="spot",
            calendar="always-open",
            entities=("ETH-USDT",),
            cadence_us=1_000_000,
            available_at=_START + timedelta(hours=7),
            output="target",
            state=CandidateStateContract(
                feature_mode="batch",
                warmup_observations=0,
                checkpoint_schema=None,
                on_gap="pause",
                on_restart="reset",
                policy_state_schema="policy-state",
            ),
            metrics=(
                CandidateMetricContract(
                    name="net-return",
                    kind="metric",
                    component_key="net-return",
                    version="v1",
                    units="ratio",
                    applies_to=("research", "runtime"),
                ),
                CandidateMetricContract(
                    name="ledger-curve",
                    kind="chart",
                    component_key="ledger-curve",
                    version="v1",
                    units="USD",
                    applies_to=("research", "runtime"),
                ),
            ),
            artifacts=tuple(
                artifacts[name] for name in sorted(artifacts) if name not in provenance
            ),
        )
        manifest = CandidateManifest(
            definition=definition,
            qualification="empirical" if empirical else "engineering",
            dataset=artifacts["dataset-selection"],
            experiment=artifacts["experiment"],
            attempt=artifacts["attempt"],
            report=artifacts["study-report"],
            assessment=artifacts["assessment"] if empirical else None,
            artifacts=tuple(artifacts[name] for name in sorted(artifacts) if name in provenance),
            limitations=("Synthetic software reference; no exchange execution evidence.",),
        )
        return manifest, payloads

    @staticmethod
    def _defined(manifest: CandidateManifest, **changes: object) -> CandidateManifest:
        """Replace definition fields while keeping the manifest's provenance."""
        return replace(manifest, definition=replace(manifest.definition, **changes))

    def test_reopen_exact_rule_bundle_and_reject_changed_bytes(self, tmp_path: Path) -> None:
        """A completed attempt reopens; mutating even a report object fails at read."""
        manifest, payloads = self._bundle_inputs(tmp_path)
        bundle = CandidateBundle(tmp_path / "candidate")
        assert bundle.publish(manifest, payloads) == manifest.identity
        assert bundle.publish(manifest, payloads) == manifest.identity
        assert bundle.read() == manifest
        assert bundle.artifact(manifest.report) == payloads["study-report"]
        report_path = tmp_path / "candidate" / "objects" / manifest.report.sha256
        os.chmod(report_path, 0o600)
        report_path.write_bytes(b'{"result":"changed"}')
        with pytest.raises(ValueError, match="report"):
            bundle.read()

    def test_learned_state_is_paired_and_retrievable(self, tmp_path: Path) -> None:
        """A learned reference retains distinct transform and model state artifacts."""
        manifest, payloads = self._bundle_inputs(tmp_path, learned=True)
        bundle = CandidateBundle(tmp_path / "candidate")
        bundle.publish(manifest, payloads)
        definition = manifest.definition
        assert definition.estimator is not None
        assert definition.transform is not None
        assert bundle.artifact(definition.estimator) == payloads["estimator-version"]
        assert bundle.artifact(definition.transform) == payloads["transform-version"]
        assert bundle.definition() == definition
        with pytest.raises(ValueError, match="estimator artifact"):
            self._defined(manifest, estimator=None).__post_init__()

    def test_substituted_schema_and_learned_state_have_no_report_provenance(
        self, tmp_path: Path
    ) -> None:
        """Changing candidate content cannot borrow the completed attempt's old report."""
        manifest, payloads = self._bundle_inputs(tmp_path, learned=True)
        for name, expected in (
            ("feature-schema", "selected state"),
            ("transform-version", "selected state"),
            ("estimator-version", "selected state"),
        ):
            altered = payloads[name] + b" "
            reference = self._artifact(name, altered)
            inventory = tuple(
                reference if item.name == name else item for item in manifest.definition.artifacts
            )
            if name == "feature-schema":
                changed = self._defined(manifest, feature_schema=reference, artifacts=inventory)
            elif name == "transform-version":
                changed = self._defined(manifest, transform=reference, artifacts=inventory)
            else:
                changed = self._defined(manifest, estimator=reference, artifacts=inventory)
            with pytest.raises(ValueError, match=expected):
                CandidateBundle(tmp_path / f"changed-{name}").publish(
                    changed, {**payloads, name: altered}
                )

    def test_substituted_policy_and_metric_identity_differ_from_study(self, tmp_path: Path) -> None:
        """Valid JSON parameters cannot rewrite selected decision or report definitions."""
        manifest, payloads = self._bundle_inputs(tmp_path)
        policy_components = tuple(
            replace(component, identity="unselected-policy")
            if component.role == "policy"
            else component
            for component in manifest.definition.components
        )
        changed_policy = self._defined(manifest, components=policy_components)
        with pytest.raises(ValueError, match="components differ"):
            CandidateBundle(tmp_path / "changed-policy").publish(changed_policy, payloads)
        metric_components = tuple(
            replace(component, identity="f" * 64) if component.role == "metric" else component
            for component in manifest.definition.components
        )
        changed_metric = self._defined(manifest, components=metric_components)
        with pytest.raises(ValueError, match="metric selections differ"):
            CandidateBundle(tmp_path / "changed-metric").publish(changed_metric, payloads)

    def test_forged_source_and_incomplete_attempt_cannot_promote(self, tmp_path: Path) -> None:
        """An arbitrary source label or unfinished study cannot become candidate evidence."""
        manifest, payloads = self._bundle_inputs(tmp_path)
        foreign = b'{"source_identity":"unrelated-history"}'
        changed_inventory = tuple(
            self._artifact("dataset-selection", foreign)
            if item.name == "dataset-selection"
            else item
            for item in manifest.artifacts
        )
        candidate = replace(
            manifest,
            dataset=self._artifact("dataset-selection", foreign),
            artifacts=changed_inventory,
        )
        with pytest.raises(ValueError, match="dataset selection"):
            CandidateBundle(tmp_path / "foreign").publish(
                candidate, {**payloads, "dataset-selection": foreign}
            )
        with AttemptStore(tmp_path / "unfinished") as store:
            spec = DomainCodec().decode_json(payloads["experiment"], ExperimentSpec)
            started = store.start(
                spec,
                at=_START + timedelta(hours=6),
                invocation="unfinished reference",
                request=payloads["dataset-selection"],
            )
            history = store.read(started.attempt_id)
        incomplete = DomainCodec().encode_json(history)
        reference = self._artifact("attempt", incomplete)
        changed_inventory = tuple(
            reference if item.name == "attempt" else item for item in manifest.artifacts
        )
        invalid = replace(
            manifest,
            attempt=reference,
            artifacts=changed_inventory,
        )
        with pytest.raises(ValueError, match="completed experiment"):
            CandidateBundle(tmp_path / "incomplete").publish(
                invalid, {**payloads, "attempt": incomplete}
            )

    def test_empirical_label_requires_matching_accepted_report(self, tmp_path: Path) -> None:
        """An engineering sample cannot claim acceptance; an actual temporal attempt can."""
        engineering, _ = self._bundle_inputs(tmp_path / "engineering")
        with pytest.raises(ValueError, match="assessment"):
            replace(engineering, qualification="empirical").__post_init__()
        empirical, empirical_bytes = self._bundle_inputs(tmp_path / "empirical", empirical=True)
        bundle = CandidateBundle(tmp_path / "accepted")
        bundle.publish(empirical, empirical_bytes)
        assert bundle.read().qualification == "empirical"
        rejected = DomainCodec().encode_json(
            CandidateAssessment(
                report_sha256=empirical.report.sha256,
                decision="rejected",
                rationale="Independent evidence failed the predefined threshold.",
                limitations=(),
            )
        )
        reference = self._artifact("assessment", rejected)
        changed_inventory = tuple(
            reference if item.name == "assessment" else item for item in empirical.artifacts
        )
        invalid = replace(
            empirical,
            assessment=reference,
            artifacts=changed_inventory,
        )
        with pytest.raises(ValueError, match="does not accept"):
            CandidateBundle(tmp_path / "rejected").publish(
                invalid, {**empirical_bytes, "assessment": rejected}
            )

    def test_unsafe_names_and_non_json_parameters_fail_before_publication(
        self, tmp_path: Path
    ) -> None:
        """A bundle never interprets a path component or serialized executable state."""
        with pytest.raises(ValueError, match="artifact name"):
            CandidateArtifact(name="../escape", sha256="a" * 64)
        manifest, payloads = self._bundle_inputs(tmp_path)
        binary = b"\x80\x04pickle"
        reference = self._artifact("feature-parameters", binary)
        changed_components = tuple(
            replace(component, parameters=reference) if component.role == "feature" else component
            for component in manifest.definition.components
        )
        changed_inventory = tuple(
            reference if item.name == "feature-parameters" else item
            for item in manifest.definition.artifacts
        )
        changed = self._defined(
            manifest, components=changed_components, artifacts=changed_inventory
        )
        with pytest.raises(ValueError, match="JSON object"):
            CandidateBundle(tmp_path / "binary").publish(
                changed, {**payloads, "feature-parameters": binary}
            )
        assert not (tmp_path / "binary" / "manifest.json").exists()
