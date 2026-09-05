"""Canonical artifact supply-chain API and command for roadmap package B08."""

from __future__ import annotations

# standard library imports
import json
import sys
from collections.abc import Sequence
from pathlib import Path

# project library imports
from alpha_research_governance.artifact_supply_chain.bundle import (
    create_bundle,
    publish_bundle,
    sign_bundle,
    verify_bundle,
)
from alpha_research_governance.artifact_supply_chain.models import (
    ArtifactBundle,
    ArtifactSupplyChainError,
    ArtifactSupplyChainPolicy,
    ArtifactTool,
    LockIdentity,
)
from alpha_research_governance.artifact_supply_chain.policy import (
    load_policy,
    validate_repository,
)

__all__ = [
    "ArtifactBundle",
    "ArtifactSupplyChainError",
    "ArtifactSupplyChainPolicy",
    "ArtifactTool",
    "LockIdentity",
    "create_bundle",
    "load_policy",
    "main",
    "publish_bundle",
    "sign_bundle",
    "validate_repository",
    "verify_bundle",
]


def _print_usage() -> None:
    print(
        "usage: alpha-governance-artifacts "
        "[create ARTIFACT_PATH ARTIFACT_KIND BUILD_TARGET SOURCE_COMMIT_SHA "
        "TEST_EVIDENCE_PATH OUTPUT_BUNDLE_PATH | "
        "sign BUNDLE_PATH SIGNING_CONTEXT | "
        "publish BUNDLE_PATH SHA256_DIGEST REGISTRY_ROOT | "
        "verify BUNDLE_PATH SHA256_DIGEST]",
        file=sys.stderr,
    )


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate policy or execute an explicitly selected artifact lifecycle operation."""
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    repository_root = Path.cwd()
    try:
        artifact_supply_chain_policy = validate_repository(repository_root)
        if not cli_arguments:
            print(
                "Artifact supply-chain policy passed; package status is "
                f"{artifact_supply_chain_policy.package_status}."
            )
            return 0
        lifecycle_command = cli_arguments.pop(0)
        if lifecycle_command == "create" and len(cli_arguments) == 6:
            created_bundle = create_bundle(
                Path(cli_arguments[0]),
                artifact_kind=cli_arguments[1],
                build_target=cli_arguments[2],
                source_commit=cli_arguments[3],
                test_evidence_paths=(Path(cli_arguments[4]),),
                output_path=Path(cli_arguments[5]),
                repository_root=repository_root,
                policy=artifact_supply_chain_policy,
            )
            print(json.dumps(created_bundle.model_dump(mode="json"), sort_keys=True))
            return 0
        if lifecycle_command == "sign" and len(cli_arguments) == 2:
            sign_bundle(
                Path(cli_arguments[0]),
                signing_context=cli_arguments[1],
                policy=artifact_supply_chain_policy,
                repository_root=repository_root,
            )
            print("Artifact attestation signed in the protected context.")
            return 0
        if lifecycle_command == "publish" and len(cli_arguments) == 3:
            published_bundle_path = publish_bundle(
                Path(cli_arguments[0]),
                expected_artifact_digest=cli_arguments[1],
                registry_root=Path(cli_arguments[2]),
                repository_root=repository_root,
                policy=artifact_supply_chain_policy,
            )
            print(published_bundle_path)
            return 0
        if lifecycle_command == "verify" and len(cli_arguments) == 2:
            verified_bundle = verify_bundle(
                Path(cli_arguments[0]),
                expected_artifact_digest=cli_arguments[1],
                repository_root=repository_root,
                policy=artifact_supply_chain_policy,
            )
            print(json.dumps(verified_bundle.model_dump(mode="json"), sort_keys=True))
            return 0
    except (ArtifactSupplyChainError, OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    _print_usage()
    return 2
