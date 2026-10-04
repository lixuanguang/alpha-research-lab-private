"""Compose trusted operating builds, local installation and compatible rollback."""

from __future__ import annotations

# standard library imports
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

# project library imports
from alpha_research_governance.artifact_supply_chain.builds import ReleaseBuild, ReleaseBuilder
from alpha_research_governance.artifact_supply_chain.bundles import ReleaseRegistry
from alpha_research_governance.artifact_supply_chain.installation import LocalInstallation
from alpha_research_governance.artifact_supply_chain.provenance import ReleaseProvenance
from alpha_research_governance.artifact_supply_chain.records import InstallationPolicy
from alpha_research_governance.dependency_admission import DependencyRepository
from alpha_research_governance.dependency_admission.wheelhouse import SelectedWheelhouse


class ArtifactArguments:
    """Parse only explicit administrative commands and named input paths."""

    @staticmethod
    def options(tokens: Sequence[str], required: set[str], optional: set[str]) -> dict[str, Path]:
        """Reject duplicate, absent and unknown arguments without implicit defaults."""
        if len(tokens) % 2:
            raise ValueError("artifact options require --name PATH pairs")
        values: dict[str, Path] = {}
        for index in range(0, len(tokens), 2):
            key = tokens[index]
            value = tokens[index + 1]
            if (
                key not in required | optional
                or key in values
                or not value
                or value.startswith("--")
            ):
                raise ValueError("unknown or duplicate artifact option")
            values[key] = Path(value).absolute()
        if not required.issubset(values):
            raise ValueError("missing required artifact option")
        return values


def main(arguments: Sequence[str] | None = None) -> int:
    """Build, verify, install or roll back a signed local operating release.

    The full research graph's ``release-check`` is refused while any wheel-only
    allowance is active. Named operating builds prove their own complete closure.
    Installation does not start services or grant production submission authority.
    """
    tokens = list(sys.argv[1:] if arguments is None else arguments)
    usage = (
        "usage: alpha-governance-artifacts release-check | "
        "fetch --repository PATH --request PATH --policy PATH --dependencies PATH | "
        "build --repository PATH --request PATH --policy PATH --configuration PATH "
        "--dependencies PATH --audit PATH --key PATH --registry PATH [--state PATH] "
        "[--candidates PATH] [--extensions PATH] | "
        "verify --release PATH --policy PATH | "
        "install|rollback --release PATH --policy PATH --target PATH | "
        "run --target PATH --policy PATH -- APPLICATION_ARGUMENTS"
    )
    if not tokens or tokens[0] not in {
        "release-check",
        "fetch",
        "build",
        "verify",
        "install",
        "rollback",
        "run",
    }:
        print(usage, file=sys.stderr)
        return 2
    command = tokens[0]
    try:
        if command == "release-check":
            if len(tokens) != 1:
                print(usage, file=sys.stderr)
                return 2
            DependencyRepository.require_release(Path.cwd())
            print(
                "artifact release blocked: select an admitted operating build profile",
                file=sys.stderr,
            )
            return 1
        application_arguments: tuple[str, ...] = ()
        if command == "run":
            if "--" not in tokens:
                raise ValueError("run requires an explicit application argument separator")
            index = tokens.index("--")
            application_arguments = tuple(tokens[index + 1 :])
            tokens = tokens[:index]
        required = {"--policy"}
        optional: set[str] = set()
        if command == "fetch":
            required |= {"--repository", "--request", "--dependencies"}
        elif command == "build":
            required |= {
                "--repository",
                "--request",
                "--configuration",
                "--dependencies",
                "--audit",
                "--key",
                "--registry",
            }
            optional = {"--state", "--candidates", "--extensions"}
        elif command == "verify":
            required.add("--release")
        elif command in {"install", "rollback"}:
            required |= {"--release", "--target"}
        else:
            required.add("--target")
        paths = ArtifactArguments.options(tokens[1:], required, optional)
        policy = InstallationPolicy.model_validate_json(
            ReleaseRegistry.read_regular(paths["--policy"], 1_048_576)
        )
        now = datetime.now(UTC)
        if command == "fetch":
            request = ReleaseBuild.model_validate_json(paths["--request"].read_bytes())
            LocalInstallation(paths["--dependencies"], policy)._require_tools(request.runtime)
            wheels = SelectedWheelhouse.fetch(
                paths["--repository"],
                request.runtime.application,
                paths["--dependencies"],
                Path(policy.uv_executable),
            )
            print(f"Retained {len(wheels)} verified external wheels at {paths['--dependencies']}")
        elif command == "build":
            request = ReleaseBuild.model_validate_json(paths["--request"].read_bytes())
            result = ReleaseBuilder(paths["--repository"], policy).build(
                request,
                configuration=paths["--configuration"],
                dependency_wheels=paths["--dependencies"],
                audit_report=paths["--audit"],
                private_key=paths["--key"],
                registry=paths["--registry"],
                now=now,
                state=paths.get("--state"),
                candidates=paths.get("--candidates"),
                extensions=paths.get("--extensions"),
            )
            print(result)
        elif command == "verify":
            verified = ReleaseRegistry.verify(paths["--release"], policy, now=now)
            facts = ReleaseProvenance.verify(verified, now=now)
            print(f"Verified {verified.identity}: {facts.root_name}, {len(facts.wheels)} wheels")
        elif command in {"install", "rollback"}:
            receipt = LocalInstallation(paths["--target"], policy).install(
                paths["--release"], now=now
            )
            print(
                f"{command}: {receipt.release}; slot={receipt.slot}; "
                f"state={receipt.runtime.state_schema}"
            )
        else:
            output = LocalInstallation(paths["--target"], policy).run(
                application_arguments, now=now
            )
            print(output.decode(), end="")
        return 0
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1


__all__ = [
    "InstallationPolicy",
    "LocalInstallation",
    "ReleaseBuild",
    "ReleaseBuilder",
    "ReleaseProvenance",
    "ReleaseRegistry",
    "main",
]
