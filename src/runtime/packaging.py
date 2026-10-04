"""Package a completed decision study's selected components as a candidate bundle."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from research.experiments import (
    AttemptStore,
    CandidateArtifact,
    CandidateBundle,
    CandidateComponent,
    CandidateDefinition,
    CandidateManifest,
    CandidateMetricContract,
    CandidateStateContract,
    Fingerprint,
)
from research.features import FeatureSchema, FeatureStoreDefinition, TransformVersion
from research.models import EstimatorVersion
from research.studies import DecisionStudy, StudyResult
from runtime.extensions import InstalledExtensions
from runtime.identity import ImplementationIdentity
from runtime.requirements import CandidateRequirements
from serialization import DomainCodec, WireRecord

ComponentRole = Literal["feature", "transform", "estimator", "policy", "metric", "chart"]


class ComponentSelection(WireRecord, frozen=True):
    """Select one registered factory and its JSON parameters for a study component."""

    role: ComponentRole
    factory_key: str
    parameters: bytes

    def __post_init__(self) -> None:
        """Require a named factory and a JSON object of parameters."""
        if self.role not in ("feature", "transform", "estimator", "policy", "metric", "chart"):
            raise ValueError("unsupported component role")
        if type(self.factory_key) is not str or not self.factory_key.strip():
            raise ValueError("component selection requires a factory key")
        CandidateBundle.require_json_parameters(self.parameters)


class CandidatePackager:
    """Publish a completed study's exact components as a provenance-verified bundle.

    The packaged components come from one installed extension. Each selection is
    built through that extension's registered factories with the identity the study
    recorded, so a bundle cannot carry code other than what was studied; the study
    must also have retained the extension's installed identity (see
    ``InstalledExtensions.artifact``). Requirements are derived from the study's
    inputs and output exactly as for authored candidates. Provenance (dataset,
    experiment, attempt, report and fitted state) is copied from the attempt store,
    and the bundle is read back through ``CandidateBundle`` before it is returned.
    """

    def __init__(self, extensions: InstalledExtensions | None = None) -> None:
        """Bind the installed extensions that provide packaged components."""
        self._extensions = InstalledExtensions() if extensions is None else extensions
        self._codec = DomainCodec()

    def feature_store(
        self,
        store: AttemptStore,
        attempt_id: str,
        *,
        name: str,
        entity_type: str = "instrument",
        instance: str | None = None,
    ) -> FeatureStoreDefinition:
        """Build the stored-feature definition a served candidate of this study needs.

        It carries the study's feature schema and, for a fitted study, the last
        fold's transform identity and output fields, so stored vectors are the
        transformed vectors the candidate consumes. Pass the same definition to
        ``FeatureMaterializer.materialize`` (with that transform) and to ``publish``. An
        incremental schema needs a named ``instance``.
        """
        history = store.read(attempt_id)
        if history.status != "completed":
            raise ValueError("a served definition requires a completed study attempt")
        result = StudyResult.read(store, attempt_id)
        schema = self._codec.decode_json(
            store.artifact(attempt_id, "feature-schema"), FeatureSchema
        )
        study = self._codec.decode_json(history.start.request, DecisionStudy)
        transform = (
            store.artifact(attempt_id, f"transform-{len(result.folds) - 1:04d}")
            if study.transform_identity is not None
            else None
        )
        return replace(self._serving(schema, transform, name, entity_type), instance=instance)

    def _serving(
        self, schema: FeatureSchema, transform: bytes | None, name: str, entity_type: str
    ) -> FeatureStoreDefinition:
        """Derive the served definition from a schema and optional retained transform."""
        if transform is None:
            return FeatureStoreDefinition(name=name, entity_type=entity_type, schema=schema)
        version = self._codec.decode_json(transform, TransformVersion)
        return FeatureStoreDefinition(
            name=name,
            entity_type=entity_type,
            schema=schema,
            transform_identity=version.identity,
            output_fields=version.output_fields,
        )

    def publish(
        self,
        root: Path,
        *,
        store: AttemptStore,
        attempt_id: str,
        extension: str,
        selections: tuple[ComponentSelection, ...],
        name: str,
        version: str,
        venue: str,
        cadence_us: int,
        state: CandidateStateContract,
        metrics: tuple[CandidateMetricContract, ...],
        limitations: tuple[str, ...],
        order_types: tuple[str, ...] = ("gtc", "ioc"),
        feature_store: FeatureStoreDefinition | None = None,
    ) -> CandidateManifest:
        """Publish the bundle at ``root`` and return its verified manifest.

        Raises:
            ValueError: The attempt is incomplete, a selection is missing or differs
                from the study, or the study did not retain the extension identity.
        """
        history = store.read(attempt_id)
        if history.status != "completed":
            raise ValueError("candidate packaging requires a completed study attempt")
        study = self._codec.decode_json(history.start.request, DecisionStudy)
        result = StudyResult.read(store, attempt_id)
        implementation = self._extensions.identity(extension)
        if Fingerprint(name=f"extension:{extension}", sha256=implementation) not in (
            history.start.spec.components
        ):
            raise ValueError("study did not retain the installed extension identity")
        payloads: dict[str, bytes] = {
            "dataset": history.start.request,
            "experiment": self._codec.encode_json(history.start.spec),
            "attempt": self._codec.encode_json(history),
            "study-report": store.artifact(attempt_id, "study-report"),
            "feature-schema": store.artifact(attempt_id, "feature-schema"),
        }
        schema = self._codec.decode_json(payloads["feature-schema"], FeatureSchema)
        last = len(result.folds) - 1
        fold = result.folds[-1]
        if study.transform_identity is not None:
            payloads["transform"] = store.artifact(attempt_id, f"transform-{last:04d}")
        if study.model_identity is not None:
            payloads["estimator"] = store.artifact(attempt_id, f"model-{last:04d}")
        if feature_store is not None:
            expected = self._serving(
                schema, payloads.get("transform"), feature_store.name, feature_store.entity_type
            )
            if replace(feature_store, instance=None) != replace(expected, instance=None) or (
                schema.mode == "batch" and feature_store.instance is not None
            ):
                raise ValueError(
                    "feature-store definition differs from the study's schema, transform "
                    "or output fields; build it with CandidatePackager.feature_store"
                )
            payloads["feature-store"] = self._codec.encode_json(feature_store)
        components = self._components(
            study, schema, selections, extension, implementation, payloads
        )
        references = {
            item: CandidateArtifact(name=item, sha256=hashlib.sha256(payload).hexdigest())
            for item, payload in payloads.items()
        }
        provenance = ("dataset", "experiment", "attempt", "study-report")
        definition = CandidateDefinition(
            name=name,
            version=version,
            code_sha256=ImplementationIdentity.sha256(),
            environment_sha256=history.start.spec.environment_sha256,
            feature_schema=references["feature-schema"],
            feature_store=references.get("feature-store"),
            transform=references.get("transform"),
            estimator=references.get("estimator"),
            components=components,
            inputs=schema.inputs,
            requirements=CandidateRequirements(venue=venue, calendar=study.calendar).derive(
                schema.inputs, study.output, order_types
            ),
            product="spot",
            calendar=study.calendar,
            entities=(study.economics.entity,),
            cadence_us=cadence_us,
            available_at=self._available(study, fold.model),
            output=study.output,
            state=state,
            metrics=metrics,
            artifacts=tuple(ref for item, ref in references.items() if item not in provenance),
        )
        manifest = CandidateManifest(
            definition=definition,
            qualification="engineering",
            dataset=references["dataset"],
            experiment=references["experiment"],
            attempt=references["attempt"],
            report=references["study-report"],
            assessment=None,
            artifacts=tuple(references[item] for item in provenance),
            limitations=limitations,
        )
        bundle = CandidateBundle(root)
        bundle.publish(manifest, payloads)
        if bundle.read() != manifest:
            raise ValueError("published candidate bundle differs from its manifest")
        return manifest

    def _components(
        self,
        study: DecisionStudy,
        schema: FeatureSchema,
        selections: tuple[ComponentSelection, ...],
        extension: str,
        implementation: str,
        payloads: dict[str, bytes],
    ) -> tuple[CandidateComponent, ...]:
        """Build every selection with the study's identity, refusing any difference."""
        expected: dict[ComponentRole, tuple[str, ...]] = {
            "feature": (study.feature_identity,),
            "policy": (study.policy_identity,),
            "transform": () if study.transform_identity is None else (study.transform_identity,),
            "estimator": () if study.model_identity is None else (study.model_identity,),
            "metric": tuple(item.sha256 for item in study.metrics),
            "chart": tuple(item.sha256 for item in study.charts),
        }
        factories = self._extensions.components(extension)
        components: list[CandidateComponent] = []
        for role, identities in expected.items():
            chosen = tuple(item for item in selections if item.role == role)
            if len(chosen) != len(identities):
                raise ValueError(f"candidate packaging needs one selection per study {role}")
            for index, (selection, identity) in enumerate(zip(chosen, identities, strict=True)):
                selection.__post_init__()
                key = f"{role}-parameters" if len(identities) == 1 else f"{role}-{index}-parameters"
                payloads[key] = selection.parameters
                component = CandidateComponent(
                    role=role,
                    factory_key=selection.factory_key,
                    identity=identity,
                    implementation_sha256=implementation,
                    parameters=CandidateArtifact(
                        name=key, sha256=hashlib.sha256(selection.parameters).hexdigest()
                    ),
                )
                if role == "feature":
                    factories.feature(component, schema, selection.parameters)
                elif role == "policy":
                    factories.policy(component, selection.parameters)
                elif role == "transform":
                    factories.transform(component, selection.parameters)
                elif role == "estimator":
                    factories.estimator(component, selection.parameters)
                elif role == "metric":
                    factories.metric(component, selection.parameters)
                else:
                    factories.chart(component, selection.parameters)
                components.append(component)
        if len(components) != len(selections):
            raise ValueError("candidate packaging received a selection for no study component")
        return tuple(components)

    @staticmethod
    def _available(study: DecisionStudy, model: EstimatorVersion | None) -> datetime:
        """Return when the packaged state became available: the fitted model, else the study."""
        return study.folds[0].decisions[0] if model is None else model.available_at
