"""Resolve each provisioned paper service instance's candidate for its native source."""

from __future__ import annotations

# standard library imports
import hashlib
from pathlib import Path
from uuid import UUID

# project library imports
from configuration import (
    CandidateDeployment,
    PackagedCandidate,
    PaperServiceConfiguration,
    PaperServiceInstance,
    PaperServiceSource,
    UniverseSelection,
)
from execution import PortfolioContext
from reference_data.instruments import InstrumentId
from research.experiments import CandidateBundle
from research.features import FeatureStoreDefinition, VersionedFeatureStore
from research.observations import InputRequirement, NumericField
from runtime import (
    CandidateLoader,
    InstalledExtensions,
    LoadedCandidate,
    PaperCapabilities,
    PaperInputs,
    ReferenceCandidates,
    SharedStrategyBinding,
)
from serialization import DomainCodec


class PaperServiceCandidates:
    """Load installed reference formulas and signed packaged candidates without fallback.

    A packaged candidate is read from the release's signed candidates by its
    definition identity, with components only from its named installed extension;
    both resolve against this environment's paper capabilities. All candidates on
    one source share its projected book fields and, when it records trades, its
    trade fields, so their inputs of one feed must agree on the requirement name,
    clock and age. A packaged candidate with a ``feature_version`` reads that
    version's feature-store stream instead and adds no source fields.
    """

    def __init__(
        self,
        configuration: PaperServiceConfiguration,
        candidates: Path | None,
        extensions: InstalledExtensions | None = None,
    ) -> None:
        """Bind the selection, its signed candidates directory and installed extensions."""
        configuration.__post_init__()
        if candidates is not None and not candidates.is_absolute():
            raise ValueError("paper service candidates require an absolute directory")
        self.config, self.candidates = configuration, candidates
        self.extensions = InstalledExtensions() if extensions is None else extensions
        self.codec = DomainCodec()
        self._loaded: dict[str, LoadedCandidate] = {}

    def source(self, instance: PaperServiceInstance) -> PaperServiceSource:
        """Return the instance's configured native source."""
        return next(item for item in self.config.sources if item.name == instance.source)

    def capabilities(
        self, source: PaperServiceSource, features: FeatureStoreDefinition | None = None
    ) -> PaperCapabilities:
        """Describe this environment for one native book, optional trades and store."""
        return PaperCapabilities(
            venue=source.capture.venue,
            freshness_us=source.freshness_us,
            clocks=("receipt",),
            trades=source.trades,
            features=features,
        )

    def inputs(self, instance: PaperServiceInstance) -> tuple[InputRequirement, ...]:
        """Return the instance's declared source inputs without constructing components.

        A feature-served candidate reads its stream, so it declares no source inputs.
        """
        source = self.source(instance)
        if isinstance(instance.candidate, PackagedCandidate):
            if instance.candidate.feature_version is not None:
                return ()
            return self._bundle(instance.candidate).definition().inputs
        return self._references(source).inputs

    def published_inputs(self, instance: PaperServiceInstance) -> tuple[InputRequirement, ...]:
        """Return the source inputs the feature publisher reads for a served candidate.

        Only a feature-served packaged candidate under a configured publisher has
        any: the publisher computes its stream from these live fields.
        """
        features = self.config.features
        if (
            features is None
            or features.publisher is None
            or not isinstance(instance.candidate, PackagedCandidate)
            or instance.candidate.feature_version is None
        ):
            return ()
        return self._bundle(instance.candidate).definition().inputs

    def requirements(self, source: PaperServiceSource) -> tuple[InputRequirement, ...]:
        """Return the ordered union of fields the source's candidates and publisher read."""
        fields: tuple[InputRequirement, ...] = ()
        for instance in self.config.instances:
            if instance.source == source.name:
                read = (*self.inputs(instance), *self.published_inputs(instance))
                fields += tuple(item for item in read if item not in fields)
        return fields

    def feeds(self, source: PaperServiceSource) -> PaperInputs:
        """Partition the source's fields by feed, refusing any it does not provision."""
        return PaperInputs(self.requirements(source), has_trades=source.trades is not None)

    def book_requirements(self, source: PaperServiceSource) -> tuple[InputRequirement, ...]:
        """Return the book fields, or the touch imbalance the market needs when none is read."""
        book = self.feeds(source).book
        return book or (
            InputRequirement(
                name=f"{source.name}-book",
                family="book",
                clock="receipt",
                field=NumericField(name="imbalance", units="dimensionless"),
                max_age_us=source.freshness_us,
            ),
        )

    def source_identity(self, source: PaperServiceSource) -> str:
        """Identify a source's feeds and projected fields independently of recordings."""
        feeds: tuple[object, ...] = (source.capture, self.requirements(source))
        if source.trades is not None:
            feeds += (source.trades,)
        return hashlib.sha256(self.codec.encode_json(feeds)).hexdigest()

    def candidate(self, instance: PaperServiceInstance) -> LoadedCandidate:
        """Load the instance's explicitly selected candidate once."""
        loaded = self._loaded.get(instance.instance_id)
        if loaded is not None:
            return loaded
        source = self.source(instance)
        if isinstance(instance.candidate, PackagedCandidate):
            loaded = self._packaged(instance, instance.candidate, source)
        else:
            loaded = self._references(source).load(
                instance.candidate,
                instance=instance.instance_id,
                entity=str(source.scenario.instrument_id),
                quantity=instance.quantity,
                lot=instance.lot,
                currency=source.scenario.adverse.currency,
                tick=self.config.instance_limits(instance).tick,
                source_identity=self.source_identity(source),
            )
        self._loaded[instance.instance_id] = loaded
        return loaded

    def binding(self, instance: PaperServiceInstance) -> SharedStrategyBinding:
        """Bind one candidate's continuation to its economic instance and venue.

        Each instance is its own portfolio, so its physical orders are never netted
        with another candidate's: a decision replaces only its own working orders, and
        each candidate's fills stay its own, as research simulates them. The
        supervisor and any replay of its delivery logs bind through this one method.
        """
        source = self.source(instance)
        account = next(
            item for item in self.config.accounts if item.account_id == instance.account_id
        )
        loaded = self.candidate(instance)
        return SharedStrategyBinding(
            instance_id=instance.instance_id,
            account_id=instance.account_id,
            entity=str(source.scenario.instrument_id),
            candidate=loaded,
            context=PortfolioContext(
                portfolio_id=instance.instance_id,
                strategy_id=instance.instance_id,
                model_revision=self.model_identity(loaded),
                config_revision="paper-services",
                horizon="capture",
                reason="engineering-reference",
                venue=source.capture.venue,
                settlement="spot",
                risk_bucket="cash",
                authority_scope=account.configuration.mode,
            ),
            maximum_fee=instance.maximum_fee,
        )

    def report(self) -> dict[str, object]:
        """Return each instance's identities for authoring and checking signed deployments."""
        for source in self.config.sources:
            self.feeds(source)
        instances: dict[str, object] = {}
        for instance in self.config.instances:
            loaded = self.candidate(instance)
            instances[instance.instance_id] = {
                "candidate_identity": loaded.definition.identity,
                "policy_identity": loaded.policy.identity,
                "feature_identity": loaded.feature.schema.identity,
                "model_identity": self.model_identity(loaded),
                "cadence_us": loaded.definition.cadence_us,
                "output": loaded.definition.output,
                "feature_stream": (
                    None
                    if loaded.deployment.input_mode == "source"
                    else loaded.deployment.source_identity
                ),
            }
        return {
            "schema_version": "paper-service-candidates",
            "selection": self.config.identity,
            "sources": {
                source.name: self.source_identity(source) for source in self.config.sources
            },
            "instances": instances,
        }

    @staticmethod
    def model_identity(loaded: LoadedCandidate) -> str:
        """Name the candidate's fitted model, or the explicit rule-only selection."""
        return (
            "rule-only" if loaded.estimator_version is None else loaded.estimator_version.identity
        )

    def _references(self, source: PaperServiceSource) -> ReferenceCandidates:
        """Bind the installed reference formulas to one source and this environment."""
        return ReferenceCandidates(
            venue=source.capture.venue,
            freshness_us=source.freshness_us,
            clock="receipt",
            capabilities=self.capabilities(source),
        )

    def _bundle(self, selection: PackagedCandidate) -> CandidateBundle:
        """Open one signed candidate bundle by its definition identity."""
        if self.candidates is None:
            raise ValueError("packaged candidates require the release's signed candidates")
        return CandidateBundle(self.candidates / selection.definition_sha256)

    def _packaged(
        self,
        instance: PaperServiceInstance,
        selection: PackagedCandidate,
        source: PaperServiceSource,
    ) -> LoadedCandidate:
        """Load a provenance-verified bundle with components from its named extension."""
        bundle = self._bundle(selection)
        definition = bundle.definition()
        if definition.identity != selection.definition_sha256:
            raise ValueError("signed candidate bundle differs from its selected definition")
        if definition.cadence_us > min(
            source.freshness_us, source.capture.idle_seconds * 1_000_000
        ):
            raise ValueError("packaged candidate cadence exceeds source freshness or idle time")
        version = selection.feature_version
        store: FeatureStoreDefinition | None = None
        if version is not None:
            if definition.feature_store is None:
                raise ValueError("feature-served candidate bundle has no feature-store definition")
            store = self.codec.decode_json(
                bundle.artifact(definition.feature_store), FeatureStoreDefinition
            )
        capabilities = self.capabilities(source, store)
        instrument = InstrumentId(UUID(str(source.scenario.instrument_id)))
        deployment = CandidateDeployment(
            name=f"{definition.name}-{instance.instance_id}",
            candidate_identity=definition.identity,
            instance=instance.instance_id,
            entity=str(source.scenario.instrument_id),
            mode="runtime",
            input_mode="source" if store is None else "online_features",
            source_identity=(
                self.source_identity(source)
                if store is None or version is None
                else VersionedFeatureStore.stream_identity(store, version)
            ),
            starts_at=selection.starts_at,
            selections=capabilities.selections(
                definition.requirements,
                frozenset() if store is None else frozenset(i.name for i in definition.inputs),
            ),
            universes=UniverseSelection(
                collection=(instrument,),
                research=(),
                strategy=(instrument,),
                authorized_trading=(),
            ),
            feature_version=version,
        )
        return CandidateLoader(
            self.extensions.components(selection.extension), capabilities.registry()
        ).load(bundle, deployment)
