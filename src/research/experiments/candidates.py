"""Retain verified candidate bytes and research lineage without granting runtime authority.

The bundle is a local, content-addressed research handoff. It contains no code
loader, account selection, credential, release signature or order permission.
Runtime consumers resolve its registered component keys through their own
installed factories and capability admission before starting work.
"""

from __future__ import annotations

# standard library imports
import hashlib
import os
import re
from collections.abc import Mapping
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal, Protocol

# third party library imports
import msgspec

# project library imports
from configuration import CapabilityRequirement
from financial_units import ExactRatio
from research.experiments.identity import ExperimentSpec, Fingerprint
from research.experiments.store import AttemptHistory
from research.observations import InputRequirement
from serialization import DomainCodec, WireRecord

_NAME = re.compile(r"[a-z][a-z0-9-]{0,127}\Z")
_KEY = re.compile(r"[a-z][a-z0-9_.-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024


class CandidateArtifact(WireRecord, frozen=True):
    """Name one immutable bundle object using its exact SHA-256 bytes."""

    name: str
    sha256: str

    def __post_init__(self) -> None:
        """Keep names within one safe, portable path component."""
        if (
            type(self.name) is not str
            or _NAME.fullmatch(self.name) is None
            or type(self.sha256) is not str
            or _SHA256.fullmatch(self.sha256) is None
        ):
            raise ValueError("invalid candidate artifact name or SHA-256")


class CandidateComponent(WireRecord, frozen=True, kw_only=True):
    """Select reviewed installed code by registry key, expected identity and JSON parameters."""

    role: Literal["feature", "transform", "estimator", "policy", "metric", "chart"]
    factory_key: str
    identity: str
    implementation_sha256: str
    parameters: CandidateArtifact

    def __post_init__(self) -> None:
        """Refuse implicit module imports and incomplete implementation identities."""
        if self.role not in ("feature", "transform", "estimator", "policy", "metric", "chart"):
            raise ValueError("unknown candidate component role")
        if (
            type(self.factory_key) is not str
            or _KEY.fullmatch(self.factory_key) is None
            or type(self.identity) is not str
            or not self.identity.strip()
            or self.identity != self.identity.strip()
            or type(self.implementation_sha256) is not str
            or _SHA256.fullmatch(self.implementation_sha256) is None
        ):
            raise ValueError("component requires a registered key and pinned implementation")
        if type(self.parameters) is not CandidateArtifact:
            raise TypeError("component parameters require an artifact reference")
        self.parameters.__post_init__()


class CandidateStateContract(WireRecord, frozen=True, kw_only=True):
    """Describe warm-up, gap and restart behavior for isolated candidate instances.

    After a missed decision instant, ``pause`` stops deciding, ``reset`` restarts
    feature and policy state, and ``continue`` keeps both and decides normally.
    """

    feature_mode: Literal["batch", "incremental"]
    warmup_observations: int
    checkpoint_schema: str | None
    on_gap: Literal["pause", "reset", "continue"]
    on_restart: Literal["reset", "restore"]
    policy_state_schema: str
    schema_version: Literal["candidate-state"] = "candidate-state"

    def __post_init__(self) -> None:
        """Require an explicit portable state version for replay/runtime parity."""
        if (
            self.schema_version != "candidate-state"
            or self.feature_mode not in ("batch", "incremental")
            or type(self.warmup_observations) is not int
            or not 0 <= self.warmup_observations <= 1_000_000
            or self.on_gap not in ("pause", "reset", "continue")
            or self.on_restart not in ("reset", "restore")
            or type(self.policy_state_schema) is not str
            or not self.policy_state_schema.strip()
        ):
            raise ValueError("invalid candidate state contract")
        if self.checkpoint_schema is not None and (
            type(self.checkpoint_schema) is not str or not self.checkpoint_schema.strip()
        ):
            raise ValueError("invalid candidate checkpoint schema")
        if self.on_restart == "restore" and self.checkpoint_schema is None:
            raise ValueError("restart restoration requires a checkpoint schema")


class CandidateMetricContract(WireRecord, frozen=True, kw_only=True):
    """Bind a selected metric or view to applicability, units and diagnostic thresholds."""

    name: str
    kind: Literal["metric", "chart"]
    component_key: str
    version: str
    units: str
    applies_to: tuple[Literal["research", "runtime"], ...]
    warning_below: ExactRatio | None = None
    warning_above: ExactRatio | None = None
    schema_version: Literal["candidate-metric"] = "candidate-metric"

    def __post_init__(self) -> None:
        """Reject unnamed, dimensionless, ambiguous or inverted diagnostics."""
        if (
            self.schema_version != "candidate-metric"
            or self.kind not in ("metric", "chart")
            or type(self.name) is not str
            or not self.name.strip()
            or type(self.component_key) is not str
            or _KEY.fullmatch(self.component_key) is None
            or type(self.version) is not str
            or not self.version.strip()
            or type(self.units) is not str
            or not self.units.strip()
            or type(self.applies_to) is not tuple
            or not self.applies_to
            or len(set(self.applies_to)) != len(self.applies_to)
            or any(item not in ("research", "runtime") for item in self.applies_to)
        ):
            raise ValueError("invalid candidate diagnostic contract")
        for threshold in (self.warning_below, self.warning_above):
            if threshold is not None:
                if type(threshold) is not ExactRatio:
                    raise TypeError("diagnostic thresholds require exact ratios")
                threshold.__post_init__()
        if self.kind == "chart" and (
            self.warning_below is not None or self.warning_above is not None
        ):
            raise ValueError("chart definitions cannot carry metric warning thresholds")
        if (
            self.warning_below is not None
            and self.warning_above is not None
            and Fraction(int(self.warning_below.numerator), int(self.warning_below.denominator))
            >= Fraction(int(self.warning_above.numerator), int(self.warning_above.denominator))
        ):
            raise ValueError("diagnostic warning bounds must increase")


class CandidateAssessment(WireRecord, frozen=True, kw_only=True):
    """Retain an authored research decision separately from engineering qualification."""

    report_sha256: str
    decision: Literal["accepted", "rejected"]
    rationale: str
    limitations: tuple[str, ...]
    schema_version: Literal["candidate-assessment"] = "candidate-assessment"

    def __post_init__(self) -> None:
        """Require a specific assessed report without conferring operating authority."""
        if (
            self.schema_version != "candidate-assessment"
            or type(self.report_sha256) is not str
            or _SHA256.fullmatch(self.report_sha256) is None
            or self.decision not in ("accepted", "rejected")
            or type(self.rationale) is not str
            or not self.rationale.strip()
            or type(self.limitations) is not tuple
            or any(type(item) is not str or not item.strip() for item in self.limitations)
        ):
            raise ValueError("invalid candidate assessment")


class CandidateDefinition(WireRecord, frozen=True, kw_only=True):
    """Pin everything replay and runtime execute, independently of research provenance.

    A definition names reviewed installed components, their parameter and fitted
    state objects, typed inputs and capability requirements, the decision schedule,
    the intent family and the state contract. ``artifacts`` inventories exactly
    the objects these references name. Research provenance is carried separately
    by ``CandidateManifest``.
    """

    name: str
    version: str
    code_sha256: str
    environment_sha256: str
    feature_schema: CandidateArtifact
    feature_store: CandidateArtifact | None
    transform: CandidateArtifact | None
    estimator: CandidateArtifact | None
    components: tuple[CandidateComponent, ...]
    inputs: tuple[InputRequirement, ...]
    requirements: tuple[CapabilityRequirement, ...]
    product: str
    calendar: str
    entities: tuple[str, ...]
    cadence_us: int
    available_at: datetime
    output: Literal["target", "exposure", "order", "quote"]
    state: CandidateStateContract
    metrics: tuple[CandidateMetricContract, ...]
    artifacts: tuple[CandidateArtifact, ...]
    schema_version: Literal["candidate-definition"] = "candidate-definition"

    def __post_init__(self) -> None:
        """Validate direct construction and all cross-references before artifact I/O."""
        if (
            self.schema_version != "candidate-definition"
            or type(self.name) is not str
            or _NAME.fullmatch(self.name) is None
            or type(self.version) is not str
            or not self.version.strip()
            or type(self.code_sha256) is not str
            or _SHA256.fullmatch(self.code_sha256) is None
            or type(self.environment_sha256) is not str
            or _SHA256.fullmatch(self.environment_sha256) is None
            or self.output not in ("target", "exposure", "order", "quote")
        ):
            raise ValueError("invalid candidate identity or output")
        for value in (self.product, self.calendar):
            if type(value) is not str or not value.strip() or value != value.strip():
                raise ValueError("candidate requires product and calendar")
        if (
            type(self.entities) is not tuple
            or not self.entities
            or len(set(self.entities)) != len(self.entities)
            or any(type(item) is not str or not item.strip() for item in self.entities)
            or type(self.cadence_us) is not int
            or not 0 < self.cadence_us <= 31_536_000_000_000
        ):
            raise ValueError("invalid candidate entities or cadence")
        self._require_utc(self.available_at, field_name="candidate availability")
        if type(self.state) is not CandidateStateContract:
            raise TypeError("candidate requires a state contract")
        self.state.__post_init__()
        self._validate_components()
        self._validate_artifacts()
        self._validate_inputs()
        self._validate_metrics()

    @property
    def identity(self) -> str:
        """Identify the executable candidate independently of storage and provenance."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    def _validate_artifacts(self) -> None:
        """Require exactly one inventory entry for every executable reference."""
        by_name = _Inventory.index(self.artifacts)
        references = tuple(
            reference
            for reference in (
                self.feature_schema,
                self.feature_store,
                self.transform,
                self.estimator,
            )
            if reference is not None
        )
        named = references + tuple(component.parameters for component in self.components)
        for reference in named:
            if type(reference) is not CandidateArtifact:
                raise TypeError("candidate requires typed semantic artifact references")
            reference.__post_init__()
            if by_name.get(reference.name) != reference:
                raise ValueError(f"candidate artifact is absent or differs: {reference.name}")
        if len({reference.name for reference in references}) != len(references):
            raise ValueError("candidate semantic artifact roles must have distinct names")
        if {reference.name for reference in named} != set(by_name):
            raise ValueError("candidate definition inventory names unreferenced objects")

    def _validate_components(self) -> None:
        """Require selected feature/policy and paired learned artifact roles."""
        if type(self.components) is not tuple or not self.components:
            raise ValueError("candidate requires selected components")
        selected: set[tuple[str, str]] = set()
        by_role: dict[str, int] = {}
        for component in self.components:
            if type(component) is not CandidateComponent:
                raise TypeError("candidate requires typed component selections")
            component.__post_init__()
            key = component.role, component.factory_key
            if key in selected:
                raise ValueError("duplicate candidate component selection")
            selected.add(key)
            by_role[component.role] = by_role.get(component.role, 0) + 1
        if any(by_role.get(role) != 1 for role in ("feature", "policy")):
            raise ValueError("candidate requires exactly one feature and policy")
        if any(by_role.get(role, 0) > 1 for role in ("transform", "estimator")):
            raise ValueError("candidate cannot select multiple transform or estimator versions")
        if (self.transform is None) != (by_role.get("transform", 0) == 0):
            raise ValueError("transform artifact and selected adapter must be paired")
        if (self.estimator is None) != (by_role.get("estimator", 0) == 0):
            raise ValueError("estimator artifact and selected adapter must be paired")

    def _validate_inputs(self) -> None:
        """Map every named source field to a typed data capability requirement."""
        if type(self.inputs) is not tuple or not self.inputs:
            raise ValueError("candidate requires named input requirements")
        input_keys: set[tuple[str, str]] = set()
        for item in self.inputs:
            if type(item) is not InputRequirement:
                raise TypeError("candidate inputs require InputRequirement")
            item.__post_init__()
            key = item.name, item.field.name
            if key in input_keys:
                raise ValueError("duplicate candidate input field")
            input_keys.add(key)
        if type(self.requirements) is not tuple or not self.requirements:
            raise ValueError("candidate requires typed capability requirements")
        requirements: dict[str, CapabilityRequirement] = {}
        kinds: set[str] = set()
        for requirement in self.requirements:
            if type(requirement) is not CapabilityRequirement:
                raise TypeError("candidate requires CapabilityRequirement")
            requirement.__post_init__()
            if requirement.name in requirements:
                raise ValueError("duplicate candidate capability requirement")
            if requirement.product != self.product or requirement.calendar != self.calendar:
                raise ValueError("candidate capability product/calendar differs")
            requirements[requirement.name] = requirement
            kinds.add(requirement.kind)
        if kinds != {
            "market_data",
            "reference_data",
            "calendar",
            "valuation",
            "account",
            "execution",
        }:
            raise ValueError("candidate requires all six distinct capability families")
        if any(
            item.name not in requirements
            or requirements[item.name].kind not in ("market_data", "reference_data")
            for item in self.inputs
        ):
            raise ValueError("candidate input has no source capability requirement")

    def _validate_metrics(self) -> None:
        """Bind every selected diagnostic to exactly one contract and selected component."""
        if type(self.metrics) is not tuple:
            raise ValueError("candidate diagnostics require an immutable tuple")
        selected = {(item.role, item.factory_key) for item in self.components}
        seen: set[tuple[str, str]] = set()
        for item in self.metrics:
            if type(item) is not CandidateMetricContract:
                raise TypeError("candidate diagnostics require metric contracts")
            item.__post_init__()
            key = item.kind, item.component_key
            if key in seen or key not in selected:
                raise ValueError("candidate diagnostic is duplicate or lacks selected code")
            seen.add(key)
        if any(
            (item.role, item.factory_key) not in seen
            for item in self.components
            if item.role in ("metric", "chart")
        ):
            raise ValueError("candidate metric and chart selections must match contracts")


class CandidateManifest(WireRecord, frozen=True, kw_only=True):
    """Pin one executable definition to its completed research provenance.

    ``artifacts`` holds the provenance objects the roles name, plus any retained
    research bytes such as extension source; definition objects are listed separately.

    ``dataset`` is the exact resolved input-selection record fingerprinted by
    the experiment. It can name multiple underlying datasets and sources; the
    retained request and report carry their original validity and availability
    semantics. It is not evidence that a venue history is complete.
    """

    definition: CandidateDefinition
    qualification: Literal["engineering", "empirical"]
    dataset: CandidateArtifact
    experiment: CandidateArtifact
    attempt: CandidateArtifact
    report: CandidateArtifact
    assessment: CandidateArtifact | None
    artifacts: tuple[CandidateArtifact, ...]
    limitations: tuple[str, ...] = ()
    schema_version: Literal["candidate-manifest"] = "candidate-manifest"

    def __post_init__(self) -> None:
        """Validate the definition, provenance inventory and research diagnostics."""
        if self.schema_version != "candidate-manifest" or self.qualification not in (
            "engineering",
            "empirical",
        ):
            raise ValueError("invalid candidate manifest or qualification")
        if type(self.definition) is not CandidateDefinition:
            raise TypeError("candidate manifest requires a candidate definition")
        self.definition.__post_init__()
        by_name = _Inventory.index(self.artifacts)
        references = tuple(
            reference
            for reference in (
                self.dataset,
                self.experiment,
                self.attempt,
                self.report,
                self.assessment,
            )
            if reference is not None
        )
        for reference in references:
            if type(reference) is not CandidateArtifact:
                raise TypeError("candidate requires typed provenance artifact references")
            reference.__post_init__()
            if by_name.get(reference.name) != reference:
                raise ValueError(f"candidate artifact is absent or differs: {reference.name}")
        if len({reference.name for reference in references}) != len(references):
            raise ValueError("candidate provenance roles must have distinct names")
        if set(by_name) & {item.name for item in self.definition.artifacts}:
            raise ValueError("candidate provenance and definition object names overlap")
        if self.qualification == "empirical" and self.assessment is None:
            raise ValueError("empirical candidate requires a retained acceptance assessment")
        if {item.kind for item in self.definition.metrics} != {"metric", "chart"}:
            raise ValueError("research candidate requires selected metrics and views")
        if type(self.limitations) is not tuple or any(
            type(item) is not str or not item.strip() for item in self.limitations
        ):
            raise ValueError("candidate limitations must be immutable nonempty statements")

    @property
    def identity(self) -> str:
        """Identify the full immutable candidate handoff independently of its storage path."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    @property
    def objects(self) -> tuple[CandidateArtifact, ...]:
        """Return the complete stored inventory: definition objects, then provenance."""
        return (*self.definition.artifacts, *self.artifacts)


class _Inventory:
    """Index an immutable artifact inventory by unique name."""

    @staticmethod
    def index(artifacts: tuple[CandidateArtifact, ...]) -> dict[str, CandidateArtifact]:
        """Reject untyped or duplicate entries and return references by name."""
        if type(artifacts) is not tuple or not artifacts:
            raise ValueError("candidate requires an artifact inventory")
        by_name: dict[str, CandidateArtifact] = {}
        for artifact in artifacts:
            if type(artifact) is not CandidateArtifact:
                raise TypeError("candidate inventory requires artifact references")
            artifact.__post_init__()
            if artifact.name in by_name:
                raise ValueError("duplicate candidate artifact name")
            by_name[artifact.name] = artifact
        return by_name


class CandidateSource(Protocol):
    """Supply one verified executable definition and its exact objects."""

    def definition(self) -> CandidateDefinition:
        """Return the verified executable definition."""
        ...

    def artifact(self, reference: CandidateArtifact) -> bytes:
        """Return the verified bytes of one object the definition names."""
        ...


class CandidateObjects:
    """Hold a definition and its exact objects in memory, without research provenance.

    Applications use this for installed built-in candidates and authored fixtures.
    Whether a definition without provenance may run is the consuming application's
    admission decision; this class only verifies integrity.
    """

    def __init__(self, definition: CandidateDefinition, artifacts: Mapping[str, bytes]) -> None:
        """Verify the exact inventory and every payload digest before use."""
        definition.__post_init__()
        if set(artifacts) != {item.name for item in definition.artifacts}:
            raise ValueError("candidate artifact bytes differ from the exact inventory")
        for item in definition.artifacts:
            CandidateBundle.verify_payload(item, artifacts[item.name])
        for component in definition.components:
            CandidateBundle.require_json_parameters(artifacts[component.parameters.name])
        self._definition = definition
        self._artifacts = dict(artifacts)

    def definition(self) -> CandidateDefinition:
        """Return the verified executable definition."""
        return self._definition

    def artifact(self, reference: CandidateArtifact) -> bytes:
        """Return one verified definition object."""
        if reference not in self._definition.artifacts:
            raise ValueError("artifact is not part of the selected candidate")
        return self._artifacts[reference.name]


class _ResultInventory(WireRecord, frozen=True):
    """Read only the lightweight successful-result inventory owned by study reports."""

    artifacts: tuple[Fingerprint, ...]
    schema_version: Literal["research-result"] = "research-result"

    def __post_init__(self) -> None:
        """Reject unsupported, empty or duplicate completed-result references."""
        if self.schema_version != "research-result" or not self.artifacts:
            raise ValueError("candidate requires a completed research result inventory")
        names: set[str] = set()
        for artifact in self.artifacts:
            if type(artifact) is not Fingerprint:
                raise TypeError("completed result requires fingerprint references")
            artifact.__post_init__()
            if artifact.name in names:
                raise ValueError("duplicate completed result artifact")
            names.add(artifact.name)


class CandidateBundle:
    """Publish and reopen immutable candidate manifests and content-addressed objects."""

    def __init__(self, root: Path) -> None:
        """Bind an explicit local root without performing I/O."""
        self._root = root
        self._codec = DomainCodec()

    def publish(self, manifest: CandidateManifest, artifacts: Mapping[str, bytes]) -> str:
        """Verify all bytes and research links, then atomically expose one manifest.

        An identical retry is idempotent. A changed manifest requires a new root;
        failed staging never exposes a candidate. Content digests establish local
        integrity, not trusted build provenance or deployment admission.
        """
        manifest.__post_init__()
        if set(artifacts) != {item.name for item in manifest.objects}:
            raise ValueError("candidate artifact bytes differ from the exact inventory")
        for item in manifest.objects:
            self.verify_payload(item, artifacts[item.name])
        self._verify_content(manifest, artifacts)
        payload = self._codec.encode_json(manifest)
        if len(payload) > _MAX_MANIFEST_BYTES:
            raise ValueError("candidate manifest exceeds four MiB")
        self._prepare_root()
        published = self._manifest_path()
        if published.is_symlink():
            raise ValueError("candidate publication cannot replace a symlink")
        if published.exists() and published.read_bytes() != payload:
            raise ValueError("candidate root already contains a different manifest")
        for item in manifest.objects:
            self._publish_bytes(self._object_path(item), artifacts[item.name])
        self._publish_bytes(published, payload)
        return manifest.identity

    def read(self) -> CandidateManifest:
        """Reopen a candidate only after every object and provenance link verifies."""
        if self._root.is_symlink() or (self._root / "objects").is_symlink():
            raise ValueError("candidate bundle cannot be read through a symlink")
        path = self._manifest_path()
        if path.is_symlink():
            raise ValueError("candidate manifest cannot be a symlink")
        with path.open("rb") as source:
            payload = source.read(_MAX_MANIFEST_BYTES + 1)
        if len(payload) > _MAX_MANIFEST_BYTES:
            raise ValueError("candidate manifest exceeds four MiB")
        manifest = self._codec.decode_json(payload, CandidateManifest)
        manifest.__post_init__()
        if self._codec.encode_json(manifest) != payload:
            raise ValueError("candidate manifest is not canonical JSON")
        artifacts = {item.name: self._read_object(item) for item in manifest.objects}
        self._verify_content(manifest, artifacts)
        return manifest

    def definition(self) -> CandidateDefinition:
        """Return the executable definition only after its provenance verifies."""
        return self.read().definition

    def artifact(self, reference: CandidateArtifact) -> bytes:
        """Return one verified member only after the complete bundle is admitted."""
        manifest = self.read()
        if reference not in manifest.objects:
            raise ValueError("artifact is not part of the selected candidate")
        return self._read_object(reference)

    def _verify_content(self, manifest: CandidateManifest, artifacts: Mapping[str, bytes]) -> None:
        """Bind exact selected inputs, completed attempt and retained report bytes."""
        definition = manifest.definition
        specification = self._codec.decode_json(artifacts[manifest.experiment.name], ExperimentSpec)
        history = self._codec.decode_json(artifacts[manifest.attempt.name], AttemptHistory)
        specification.__post_init__()
        history.__post_init__()
        if history.status != "completed" or history.events[-1].result is None:
            raise ValueError("candidate requires a completed experiment attempt")
        if (
            history.start.spec != specification
            or history.start.run_identity != specification.identity
        ):
            raise ValueError("candidate experiment and attempt differ")
        if manifest.dataset.sha256 not in {item.sha256 for item in specification.inputs}:
            raise ValueError("candidate dataset selection is absent from experiment inputs")
        if (
            Fingerprint(name="resolved-configuration", sha256=manifest.dataset.sha256)
            not in specification.inputs
            or artifacts[manifest.dataset.name] != history.start.request
        ):
            raise ValueError("candidate dataset selection differs from retained study request")
        if definition.code_sha256 not in {item.sha256 for item in specification.components}:
            raise ValueError("candidate code identity is absent from experiment components")
        if definition.environment_sha256 != specification.environment_sha256:
            raise ValueError("candidate environment differs from completed experiment")
        result = self._codec.decode_json(history.events[-1].result, _ResultInventory)
        result.__post_init__()
        if (
            Fingerprint(name=manifest.report.name, sha256=manifest.report.sha256)
            not in result.artifacts
        ):
            raise ValueError("candidate report is absent from the completed result")
        retained = {item.sha256 for item in result.artifacts}
        for selected in (definition.feature_schema, definition.transform, definition.estimator):
            if selected is not None and selected.sha256 not in retained:
                raise ValueError(f"candidate selected state is absent from result: {selected.name}")
        source_implementations = {item.sha256 for item in specification.components} | retained
        if any(
            component.implementation_sha256 not in source_implementations
            for component in definition.components
        ):
            raise ValueError("candidate component implementation lacks experiment provenance")
        self._verify_study_selection(manifest, artifacts, specification)
        if manifest.qualification == "engineering":
            if manifest.assessment is not None:
                raise ValueError("engineering candidate cannot carry empirical acceptance")
        else:
            if specification.schema_version != "experiment-spec" or manifest.assessment is None:
                raise ValueError(
                    "empirical candidate requires a temporal evaluation and assessment"
                )
            assessment = self._codec.decode_json(
                artifacts[manifest.assessment.name], CandidateAssessment
            )
            assessment.__post_init__()
            if (
                assessment.report_sha256 != manifest.report.sha256
                or assessment.decision != "accepted"
            ):
                raise ValueError("candidate assessment does not accept this exact report")
        for component in definition.components:
            self.require_json_parameters(artifacts[component.parameters.name])

    def _verify_study_selection(
        self,
        manifest: CandidateManifest,
        artifacts: Mapping[str, bytes],
        specification: ExperimentSpec,
    ) -> None:
        """Bind selected code and inputs to one saved generalized decision study."""
        definition = manifest.definition
        selection = self._json_object(artifacts[manifest.dataset.name], name="study selection")
        report = self._json_object(artifacts[manifest.report.name], name="study report")
        schema = self._json_object(artifacts[definition.feature_schema.name], name="feature schema")
        if (
            selection.get("schema_version") != "decision-study"
            or report.get("schema_version") != "study-report"
            or schema.get("schema_version") != "feature-schema"
        ):
            raise ValueError("candidate requires supported completed decision-study records")
        economics = self._object_field(selection, "economics")
        self._text_field(selection, "source_identity")
        self._text_field(economics, "source_identity")
        if (
            economics.get("schema_version") != "offline-intent-simulation"
            or definition.product != "spot"
            or definition.entities != (self._text_field(economics, "entity"),)
            or self._text_field(selection, "family") != specification.family
            or self._text_field(selection, "calendar") != definition.calendar
            or self._text_field(selection, "output") != definition.output
            or self._text_field(report, "study_identity") != specification.identity
        ):
            raise ValueError("candidate scope differs from the completed decision study")
        selections = {
            item.role: item
            for item in definition.components
            if item.role not in ("metric", "chart")
        }
        if (
            self._text_field(selection, "feature_identity") != selections["feature"].identity
            or self._text_field(selection, "policy_identity") != selections["policy"].identity
            or definition.feature_schema.sha256 != selections["feature"].identity
            or self._text_field(schema, "mode") != definition.state.feature_mode
            or self._optional_text_field(selection, "transform_identity")
            != (selections["transform"].identity if "transform" in selections else None)
            or self._optional_text_field(selection, "model_identity")
            != (selections["estimator"].identity if "estimator" in selections else None)
        ):
            raise ValueError("candidate components differ from completed study selections")
        inputs = msgspec.convert(
            schema.get("inputs"), type=tuple[InputRequirement, ...], strict=True
        )
        if inputs != definition.inputs:
            raise ValueError("candidate named inputs differ from retained feature schema")
        if definition.transform is not None:
            transform = self._json_object(
                artifacts[definition.transform.name], name="transform version"
            )
            if self._text_field(transform, "implementation") != selections["transform"].identity:
                raise ValueError("candidate transform state differs from selected implementation")
        if definition.estimator is not None:
            estimator = self._json_object(
                artifacts[definition.estimator.name], name="estimator version"
            )
            if self._text_field(estimator, "implementation") != selections["estimator"].identity:
                raise ValueError("candidate estimator state differs from selected implementation")
        for kind, selected_field in (("metric", "metrics"), ("chart", "charts")):
            expected_sha256 = tuple(
                next(
                    component.identity
                    for component in definition.components
                    if component.role == kind and component.factory_key == item.component_key
                )
                for item in definition.metrics
                if item.kind == kind
            )
            selected = self._fingerprints(selection.get(selected_field))
            reported = self._fingerprints(report.get(f"selected_{selected_field}"))
            if (
                tuple(item.sha256 for item in selected) != expected_sha256
                or selected != reported
                or len(set(expected_sha256)) != len(expected_sha256)
            ):
                raise ValueError(f"candidate {kind} selections differ from completed study report")

    @staticmethod
    def _json_object(payload: bytes, *, name: str) -> dict[str, object]:
        """Decode only the narrow selection fields needed without importing studies."""
        try:
            return msgspec.json.decode(payload, type=dict[str, object], strict=True)
        except (msgspec.DecodeError, msgspec.ValidationError) as error:
            raise ValueError(f"candidate {name} must be a JSON object") from error

    @staticmethod
    def _object_field(record: dict[str, object], field: str) -> dict[str, object]:
        """Require one nested object at a known versioned study field."""
        try:
            return msgspec.convert(record.get(field), type=dict[str, object], strict=True)
        except msgspec.ValidationError as error:
            raise ValueError(f"candidate study field is not an object: {field}") from error

    @staticmethod
    def _text_field(record: dict[str, object], field: str) -> str:
        """Read one nonempty exact study identity with no coercion."""
        value = record.get(field)
        if type(value) is not str or not value:
            raise ValueError(f"candidate study field is absent or invalid: {field}")
        return value

    @classmethod
    def _optional_text_field(cls, record: dict[str, object], field: str) -> str | None:
        """Distinguish an inapplicable learned component from an invalid identity."""
        return None if record.get(field) is None else cls._text_field(record, field)

    @staticmethod
    def _fingerprints(value: object) -> tuple[Fingerprint, ...]:
        """Read exact selected report identities through the existing lightweight record."""
        try:
            rows = msgspec.convert(value, type=tuple[Fingerprint, ...], strict=True)
        except msgspec.ValidationError as error:
            raise ValueError("candidate report lacks selected metric/chart identities") from error
        for row in rows:
            row.__post_init__()
        return rows

    @staticmethod
    def require_json_parameters(payload: bytes) -> None:
        """Admit declarative JSON parameters; factories later decode their exact schema."""
        try:
            parameters = msgspec.json.decode(payload, type=dict[str, object], strict=True)
        except (msgspec.DecodeError, msgspec.ValidationError) as error:
            raise ValueError("candidate component parameters must be a JSON object") from error
        if DomainCodec().encode_json(parameters) != payload:
            raise ValueError("candidate component parameters must use canonical JSON")

    @staticmethod
    def verify_payload(reference: CandidateArtifact, payload: bytes) -> None:
        """Reject empty, oversized or changed content before publication or use."""
        if (
            type(payload) is not bytes
            or not payload
            or len(payload) > _MAX_ARTIFACT_BYTES
            or hashlib.sha256(payload).hexdigest() != reference.sha256
        ):
            raise ValueError(f"candidate artifact bytes differ: {reference.name}")

    def _prepare_root(self) -> None:
        """Create only the fixed bundle directories and reject local symlink substitution."""
        if self._root.is_symlink():
            raise ValueError("candidate root cannot be a symlink")
        self._root.mkdir(parents=True, exist_ok=True)
        objects = self._root / "objects"
        if objects.is_symlink():
            raise ValueError("candidate object store cannot be a symlink")
        objects.mkdir(exist_ok=True)

    def _object_path(self, reference: CandidateArtifact) -> Path:
        """Map a validated digest to one safe content-addressed path."""
        reference.__post_init__()
        return self._root / "objects" / reference.sha256

    def _manifest_path(self) -> Path:
        """Return the sole published candidate manifest path."""
        return self._root / "manifest.json"

    def _read_object(self, reference: CandidateArtifact) -> bytes:
        """Read bounded bytes and verify their digest on every access."""
        path = self._object_path(reference)
        if path.is_symlink():
            raise ValueError("candidate object cannot be a symlink")
        with path.open("rb") as source:
            payload = source.read(_MAX_ARTIFACT_BYTES + 1)
        self.verify_payload(reference, payload)
        return payload

    @staticmethod
    def _publish_bytes(path: Path, payload: bytes) -> None:
        """Link a flushed temporary file into place without replacing prior bytes."""
        if path.is_symlink():
            raise ValueError("candidate publication cannot replace a symlink")
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError(
                    f"candidate publication conflicts with existing bytes: {path.name}"
                )
            return
        with NamedTemporaryFile(dir=path.parent, prefix=".candidate-", delete=False) as staged:
            temporary = Path(staged.name)
            try:
                staged.write(payload)
                staged.flush()
                os.fsync(staged.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != payload:
                    raise ValueError(
                        f"candidate publication conflicts with existing bytes: {path.name}"
                    )
            path.chmod(path.stat().st_mode & ~0o222)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
