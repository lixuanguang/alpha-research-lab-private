"""Canonical artifact supply-chain API and command for roadmap package B08."""

from __future__ import annotations

# standard library imports
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Protocol

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
    """Print the supported artifact lifecycle command syntax to standard error."""
    print(
        "usage: alpha-governance-artifacts "
        "[create ARTIFACT_PATH ARTIFACT_KIND BUILD_COMMAND SOURCE_COMMIT_SHA "
        "TEST_EVIDENCE_PATH OUTPUT_BUNDLE_PATH | "
        "sign BUNDLE_PATH SIGNING_CONTEXT | "
        "publish BUNDLE_PATH SHA256_DIGEST REGISTRY_ROOT | "
        "verify BUNDLE_PATH SHA256_DIGEST]",
        file=sys.stderr,
    )


class _JsonDumpModel(Protocol):
    """Expose the JSON-mode model dump consumed by the CLI."""

    def model_dump(self, *, mode: Literal["json"]) -> object:
        """Return the model's JSON-compatible representation."""


def _serialize_bundle_summary(bundle: ArtifactBundle) -> str:
    """Serialize a bundle summary with the command's stable JSON settings."""
    serializer: _JsonDumpModel = bundle
    return json.dumps(serializer.model_dump(mode="json"), sort_keys=True)


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate artifact policy or execute one selected lifecycle operation.

    The command uses ``Path.cwd()`` as the repository root and uses the policy, uv lock,
    project manifest, integration and evidence files as validation inputs. With no command it
    prints the policy status. ``create`` runs the configured Syft process and writes an
    unsigned candidate directory, printing its bundle summary as sorted JSON; ``sign``
    runs Cosign and writes the candidate's signature bundle before verifying it;
    ``publish`` verifies a staged copy and writes one content-addressed directory below
    ``registry_root/sha256/<artifact_digest>``; and ``verify`` runs Cosign verification
    and prints the verified bundle summary as sorted JSON. Expected
    ``ArtifactSupplyChainError``, ``OSError`` and ``ValueError`` failures inside the
    validation and lifecycle block, including its result output, are
    caught and translated to status ``1``.

    Args:
        arguments: Optional command-line tokens. ``None`` consumes ``sys.argv[1:]``;
            otherwise the sequence may contain no command or one of ``create``, ``sign``,
            ``publish`` or ``verify`` with the operands shown by the usage text.

    Returns:
        ``0`` after validating the repository or completing a lifecycle operation, ``1``
        after printing a caught artifact, filesystem or value failure to standard error,
        or ``2`` after printing usage for an unsupported command or operand count. The
        initial repository validation runs before command dispatch, so a usage status of
        ``2`` is reached only when that validation succeeds.

    Raises:
        OSError: If resolving the default working directory or writing usage output
            fails outside the guarded validation and lifecycle block.
    """
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    repository_root = Path.cwd()
    try:
        artifact_supply_chain_policy = validate_repository(repository_root)
        if not cli_arguments:
            print("Artifact supply-chain policy passed.")
            return 0
        lifecycle_command = cli_arguments.pop(0)
        if lifecycle_command == "create" and len(cli_arguments) == 6:
            created_bundle = create_bundle(
                Path(cli_arguments[0]),
                artifact_kind=cli_arguments[1],
                build_command=cli_arguments[2],
                source_commit=cli_arguments[3],
                test_evidence_paths=(Path(cli_arguments[4]),),
                output_path=Path(cli_arguments[5]),
                repository_root=repository_root,
                policy=artifact_supply_chain_policy,
            )
            print(_serialize_bundle_summary(created_bundle))
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
            print(_serialize_bundle_summary(verified_bundle))
            return 0
    except (ArtifactSupplyChainError, OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    _print_usage()
    return 2
