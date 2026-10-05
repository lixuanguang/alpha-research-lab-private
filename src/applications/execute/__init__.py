"""Expose the installed execution admission application."""

# standard library imports
from typing import TYPE_CHECKING

# project library imports
from applications.execute.accounts import (
    AccountExecutionApplication,
    AccountExecutionRequest,
    AccountExecutionResult,
)
from applications.execute.monitoring import MonitoringApplication, MonitoringConfiguration
from applications.execute.paper import (
    PaperExecutionApplication,
    PaperExecutionRequest,
    PaperExecutionResult,
)
from applications.execute.venue import VenueApplicationResult, VenueExecutionApplication
from applications.execute.workflow import main

if TYPE_CHECKING:
    # project library imports
    from applications.execute.feature_publisher import FeaturePublisher
    from applications.execute.service_candidates import PaperServiceCandidates
    from applications.execute.services import (
        PaperServiceControl,
        PaperServiceOwners,
        run_paper_services,
    )
    from applications.execute.source_service import DecodedBookObservation


def __getattr__(name: str) -> object:
    """Resolve paper-service composition only when a consumer asks for it.

    The independently installed execution application does not ship every input
    those services compose, so they are not imported with the package.
    """
    if name in {"PaperServiceControl", "PaperServiceOwners", "run_paper_services"}:
        # project library imports
        from applications.execute import services

        exports: dict[str, object] = {
            "PaperServiceControl": services.PaperServiceControl,
            "PaperServiceOwners": services.PaperServiceOwners,
            "run_paper_services": services.run_paper_services,
        }
        return exports[name]
    if name in {"FeaturePublisher"}:
        # project library imports
        from applications.execute import feature_publisher

        exports = {"FeaturePublisher": feature_publisher.FeaturePublisher}
        return exports[name]
    if name in {"PaperServiceCandidates"}:
        # project library imports
        from applications.execute import service_candidates

        exports = {"PaperServiceCandidates": service_candidates.PaperServiceCandidates}
        return exports[name]
    if name in {"DecodedBookObservation"}:
        # project library imports
        from applications.execute import source_service

        exports = {"DecodedBookObservation": source_service.DecodedBookObservation}
        return exports[name]
    raise AttributeError(name)


__all__ = [
    "AccountExecutionApplication",
    "AccountExecutionRequest",
    "AccountExecutionResult",
    "DecodedBookObservation",
    "FeaturePublisher",
    "MonitoringApplication",
    "MonitoringConfiguration",
    "PaperExecutionApplication",
    "PaperExecutionRequest",
    "PaperExecutionResult",
    "PaperServiceCandidates",
    "PaperServiceControl",
    "PaperServiceOwners",
    "VenueApplicationResult",
    "VenueExecutionApplication",
    "main",
    "run_paper_services",
]
