"""Package supplied or installed components as provenance-free executable candidates."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

# project library imports
from configuration import (
    CandidateDeployment,
    CapabilityField,
    CapabilityKind,
    CapabilityProfile,
    CapabilityRegistry,
    CapabilityRequirement,
    CapabilitySelection,
    ReferenceCandidate,
    UniverseSelection,
)
from financial_units import Currency, Price, Quantity
from reference_data.instruments import InstrumentId
from research.experiments import (
    CandidateArtifact,
    CandidateComponent,
    CandidateDefinition,
    CandidateObjects,
    CandidateStateContract,
    ExperimentSpec,
)
from research.features import FeatureKernel, FeatureSchema, ProjectionFeature
from research.observations import InputRequirement, NumericField
from runtime.candidates import CandidateLoader, LoadedCandidate
from runtime.components import CandidateComponents, FeatureFactory, PolicyFactory
from runtime.identity import ImplementationIdentity
from runtime.paper_capabilities import PaperCapabilities
from serialization import DomainCodec
from strategies import DecisionPolicy, ReferencePolicies

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SERVICES: tuple[tuple[str, CapabilityKind], ...] = (
    ("calendar", "calendar"),
    ("valuation", "valuation"),
    ("account", "account"),
    ("execution", "execution"),
)


class _Supplied:
    """Return one already constructed component from a registered factory."""

    def __init__(self, feature: FeatureKernel, policy: DecisionPolicy) -> None:
        """Bind the supplied feature kernel and policy."""
        self.feature, self.policy = feature, policy

    def create_feature(self, schema: FeatureSchema, parameters: bytes) -> FeatureKernel:
        """Return the supplied kernel for its own parameter-free schema."""
        if parameters != b"{}" or schema != self.feature.schema:
            raise ValueError("authored feature takes its own schema and no parameters")
        return self.feature

    def create_policy(self, parameters: bytes) -> DecisionPolicy:
        """Return the supplied policy; its identity pins every parameter."""
        if parameters != b"{}":
            raise ValueError("authored policy takes no parameters")
        return self.policy


class AuthoredCandidates:
    """Load a supplied feature kernel and policy as a candidate with no research provenance.

    The candidate's inputs are the feature schema's inputs, served by one venue's
    native sources. Its definition binds the installed implementation and
    environment and the supplied components' own identities. It is an engineering
    or authored workload: admitting a provenance-free candidate is the calling
    application's decision, and nothing here grants trading authority.
    """

    def __init__(
        self,
        *,
        venue: str,
        product: str = "spot",
        calendar: str = "continuous-utc",
        capabilities: PaperCapabilities | None = None,
    ) -> None:
        """Bind the venue, product and calendar every requirement declares.

        With ``capabilities``, requirements resolve against that installed
        environment; without it, against self-declared fixture profiles.
        """
        self.venue, self.product, self.calendar = venue, product, calendar
        self.capabilities = capabilities
        self._codec = DomainCodec()
        self._implementation = ImplementationIdentity.sha256()

    def load(
        self,
        *,
        name: str,
        feature: FeatureKernel,
        policy: DecisionPolicy,
        instance: str,
        entity: str,
        cadence_us: int,
        starts_at: datetime,
        source_identity: str,
        state: CandidateStateContract,
        order_types: tuple[str, ...] = ("gtc", "ioc"),
    ) -> LoadedCandidate:
        """Package and load the supplied components for one runtime placement."""
        schema = feature.schema
        policy.admit(schema.outputs, None)
        requirements = self._requirements(schema.inputs, policy.output, order_types)
        payloads = {
            "feature-schema": self._codec.encode_json(schema),
            "feature-parameters": b"{}",
            "policy-parameters": b"{}",
        }
        artifacts = {
            item: CandidateArtifact(name=item, sha256=hashlib.sha256(payload).hexdigest())
            for item, payload in payloads.items()
        }
        definition = CandidateDefinition(
            name=name,
            version="1",
            code_sha256=self._implementation,
            environment_sha256=ExperimentSpec.installed_environment(),
            feature_schema=artifacts["feature-schema"],
            feature_store=None,
            transform=None,
            estimator=None,
            components=(
                CandidateComponent(
                    role="feature",
                    factory_key="authored-feature",
                    identity=schema.identity,
                    implementation_sha256=self._implementation,
                    parameters=artifacts["feature-parameters"],
                ),
                CandidateComponent(
                    role="policy",
                    factory_key="authored-policy",
                    identity=policy.identity,
                    implementation_sha256=self._implementation,
                    parameters=artifacts["policy-parameters"],
                ),
            ),
            inputs=schema.inputs,
            requirements=requirements,
            product=self.product,
            calendar=self.calendar,
            entities=(entity,),
            cadence_us=cadence_us,
            available_at=_EPOCH,
            output=policy.output,
            state=state,
            metrics=(),
            artifacts=tuple(artifacts.values()),
        )
        instrument = InstrumentId(UUID(entity))
        deployment = CandidateDeployment(
            name=name,
            candidate_identity=definition.identity,
            instance=instance,
            entity=entity,
            mode="runtime",
            input_mode="source",
            source_identity=source_identity,
            starts_at=starts_at,
            selections=self._selections(requirements),
            universes=UniverseSelection(
                collection=(instrument,),
                research=(),
                strategy=(instrument,),
                authorized_trading=(),
            ),
        )
        supplied = _Supplied(feature, policy)
        components = CandidateComponents(
            features={
                "authored-feature": FeatureFactory(
                    implementation_sha256=self._implementation, create=supplied.create_feature
                )
            },
            policies={
                "authored-policy": PolicyFactory(
                    implementation_sha256=self._implementation, create=supplied.create_policy
                )
            },
        )
        registry = (
            self._registry(requirements)
            if self.capabilities is None
            else self.capabilities.registry()
        )
        return CandidateLoader(components, registry).load(
            CandidateObjects(definition, payloads), deployment
        )

    def _selections(
        self, requirements: tuple[CapabilityRequirement, ...]
    ) -> tuple[CapabilitySelection, ...]:
        """Select the environment's profiles, or this candidate's own fixture profiles."""
        if self.capabilities is not None:
            return self.capabilities.selections(requirements)
        return tuple(
            CapabilitySelection(name=item.name, profile=f"authored-{item.name}")
            for item in requirements
        )

    def _requirements(
        self,
        inputs: tuple[InputRequirement, ...],
        output: str,
        order_types: tuple[str, ...],
    ) -> tuple[CapabilityRequirement, ...]:
        """Declare one source requirement per named input, then the four service families."""
        sources: dict[str, tuple[InputRequirement, ...]] = {}
        for item in inputs:
            sources[item.name] = (*sources.get(item.name, ()), item)
        declared = [
            CapabilityRequirement(
                name=named,
                kind="reference_data" if rows[0].family == "reference" else "market_data",
                product=self.product,
                venue=self.venue,
                calendar=self.calendar,
                channel=rows[0].family,
                clock=rows[0].clock,
                max_freshness_us=min(row.max_age_us for row in rows),
                fields=tuple(
                    CapabilityField(name=row.field.name, units=row.field.units) for row in rows
                ),
            )
            for named, rows in sources.items()
        ]
        if not any(item.kind == "reference_data" for item in declared):
            declared.append(
                CapabilityRequirement(
                    name="reference",
                    kind="reference_data",
                    product=self.product,
                    venue=self.venue,
                    calendar=self.calendar,
                )
            )
        declared.extend(
            CapabilityRequirement(
                name=named,
                kind=kind,
                product=self.product,
                venue=self.venue,
                calendar=self.calendar,
                operations=(f"intent:{output}",) if kind == "execution" else (),
                order_types=order_types if kind == "execution" else (),
            )
            for named, kind in _SERVICES
        )
        return tuple(declared)

    def _registry(self, requirements: tuple[CapabilityRequirement, ...]) -> CapabilityRegistry:
        """Bind installed native inputs and non-executable paper service profiles."""
        return CapabilityRegistry(
            tuple(
                CapabilityProfile(
                    name=f"authored-{item.name}",
                    kind=item.kind,
                    implementation_identity=f"installed-{item.kind}",
                    version="1",
                    products=(self.product,),
                    venues=(self.venue,),
                    calendars=(self.calendar,),
                    modes=("runtime",),
                    channels=() if item.channel is None else (item.channel,),
                    clocks=() if item.clock is None else (item.clock,),
                    max_freshness_us=item.max_freshness_us,
                    fields=item.fields,
                    operations=item.operations,
                    order_types=item.order_types,
                    qualification="read_only" if item.kind == "market_data" else "fixture",
                )
                for item in requirements
            )
        )


class ReferenceCandidates:
    """Load the installed reference formulas over the native touch as candidates.

    A reference candidate projects the native touch (ask, bid, ask size) into the
    named formula. It carries no research provenance or profitability claim.
    """

    fields = (
        NumericField(name="ask", units="quote/base"),
        NumericField(name="bid", units="quote/base"),
        NumericField(name="ask_size", units="base"),
    )

    def __init__(
        self,
        *,
        venue: str,
        freshness_us: int,
        clock: Literal["event", "receipt"],
        capabilities: PaperCapabilities | None = None,
    ) -> None:
        """Bind the native venue, source freshness, source clock and optional environment."""
        if type(freshness_us) is not int or freshness_us <= 0 or clock not in ("event", "receipt"):
            raise ValueError("reference candidates require positive freshness and a source clock")
        self.freshness_us, self.clock = freshness_us, clock
        self._authored = AuthoredCandidates(venue=venue, capabilities=capabilities)
        self._implementation = ImplementationIdentity.sha256()

    @property
    def inputs(self) -> tuple[InputRequirement, ...]:
        """Return the native touch fields every reference candidate reads."""
        return tuple(
            InputRequirement(
                name="book",
                family="book",
                clock=self.clock,
                field=field,
                max_age_us=self.freshness_us,
            )
            for field in self.fields
        )

    def load(
        self,
        selection: ReferenceCandidate,
        *,
        instance: str,
        entity: str,
        quantity: Quantity,
        lot: Quantity,
        currency: Currency,
        tick: Price,
        source_identity: str,
    ) -> LoadedCandidate:
        """Package and load one selected formula for one runtime placement."""
        selection.__post_init__()
        return self._authored.load(
            name=f"reference-{selection.formula.replace('_', '-')}",
            feature=ProjectionFeature(
                FeatureSchema(
                    implementation="named-projection",
                    inputs=self.inputs,
                    outputs=self.fields,
                    parameters=(),
                    mode="batch",
                    ttl_us=self.freshness_us,
                )
            ),
            policy=ReferencePolicies.create(
                selection.formula,
                quantity,
                currency,
                lot,
                tick=tick,
                implementation=self._implementation,
            ),
            instance=instance,
            entity=entity,
            cadence_us=selection.cadence_us,
            starts_at=selection.starts_at,
            source_identity=source_identity,
            state=CandidateStateContract(
                feature_mode="batch",
                warmup_observations=0,
                checkpoint_schema="candidate-checkpoint",
                on_gap="continue",
                on_restart="restore",
                policy_state_schema="reference-clip-counter",
            ),
        )
