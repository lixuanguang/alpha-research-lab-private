"""Select the installed source adapters for saved and fixture inputs."""

from __future__ import annotations

# standard library imports
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Final

# project library imports
from alpha_research.configuration import ResolvedManifest
from alpha_research.data.inputs import FixtureReader, OccurrenceVerifier, SavedPartitionReader
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.providers.admission import SourceOccurrenceVerifier
from alpha_research.data.providers.binance.occurrences import BinanceArchiveOccurrences
from alpha_research.data.providers.tardis.inspection import TardisTradeFixture
from alpha_research.data.requests import SourceRequest

type SavedFactory = Callable[[AcquisitionManifest], tuple[SavedPartitionReader, ...]]
type FixtureFactory = Callable[[ResolvedManifest], FixtureReader]
type VerifierFactory = Callable[[SourceRequest], OccurrenceVerifier]
type SourceCapability = tuple[str, str, str]


_SAVED_FACTORIES: Final[Mapping[SourceCapability, SavedFactory]] = MappingProxyType(
    {("binance-archive", "binance", "trade"): BinanceArchiveOccurrences.from_manifest}
)
_FIXTURE_FACTORIES: Final[Mapping[SourceCapability, FixtureFactory]] = MappingProxyType(
    {("tardis", "binance", "trade"): TardisTradeFixture}
)
_VERIFIER_FACTORIES: Final[Mapping[SourceCapability, VerifierFactory]] = MappingProxyType(
    {
        ("tardis", "binance", "trade"): SourceOccurrenceVerifier,
        ("binance-archive", "binance", "trade"): SourceOccurrenceVerifier,
    }
)


class SourceAdapters:
    """Select the small declarative set of source capabilities installed here."""

    @staticmethod
    def saved(manifest: AcquisitionManifest) -> tuple[SavedPartitionReader, ...]:
        """Select readers for one validated saved acquisition manifest.

        Args:
            manifest: Complete or resumable acquisition state to bind to readers.

        Returns:
            Readers in the manifest's deterministic source-partition order.

        Raises:
            TypeError: The supplied value is not an acquisition manifest.
            ValueError: The manifest is invalid or its saved source is unsupported.
        """
        if type(manifest) is not AcquisitionManifest:
            raise TypeError("saved adapters require an AcquisitionManifest")
        manifest.__post_init__()
        capability = (manifest.run.job.provider, manifest.run.job.venue, manifest.run.job.stream)
        factory = _SAVED_FACTORIES.get(capability)
        if factory is None:
            raise ValueError(
                "unsupported saved source: "
                f"{manifest.run.job.provider}; only Binance daily archive is installed"
            )
        return factory(manifest)

    @staticmethod
    def fixture(manifest: ResolvedManifest) -> FixtureReader:
        """Select the installed fixture adapter for one resolved manifest.

        Args:
            manifest: Resolved fixture selection, including its provider and venue.

        Returns:
            A reusable reader bound to the selected fixture capability.

        Raises:
            TypeError: The supplied value is not a resolved manifest.
            ValueError: The manifest is invalid or its fixture source is unsupported.
        """
        if type(manifest) is not ResolvedManifest:
            raise TypeError("fixture adapters require a ResolvedManifest")
        manifest.__post_init__()
        capability = (
            manifest.job.provider,
            manifest.job.venue,
            manifest.job.stream,
        )
        factory = _FIXTURE_FACTORIES.get(capability)
        if factory is None:
            raise ValueError(
                f"unsupported fixture source: {capability[0]}/{capability[1]}/{capability[2]}"
            )
        return factory(manifest)

    @staticmethod
    def verifier(request: SourceRequest) -> OccurrenceVerifier:
        """Select the installed verifier for one source request.

        Args:
            request: Validated request whose retained occurrence will be checked.

        Returns:
            A reusable source-specific occurrence verifier bound to the request.

        Raises:
            TypeError: The supplied value is not a source request.
            ValueError: The request is invalid or its source capability is unsupported.
        """
        if type(request) is not SourceRequest:
            raise TypeError("occurrence verifiers require a SourceRequest")
        request.__post_init__()
        capability = (
            request.manifest.job.provider,
            request.manifest.job.venue,
            request.manifest.job.stream,
        )
        factory = _VERIFIER_FACTORIES.get(capability)
        if factory is None:
            raise ValueError(
                f"unsupported occurrence source: {capability[0]}/{capability[1]}/{capability[2]}"
            )
        return factory(request)


__all__ = ["SourceAdapters"]
