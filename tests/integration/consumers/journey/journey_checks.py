"""Check MR17 journey evidence independently through the installed supported API.

The journey driver runs this file with the installed research interpreter (``-I``)
after a step's commands. It reads the step's retained outputs, never QR claims, and
prints its criteria as one JSON list of ``{"name", "passed", "observed"}`` rows.
"""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import importlib.metadata
import sys
from pathlib import Path

# third party library imports
import msgspec

# project library imports
import research
from research.experiments import AttemptHistory, AttemptStore, CandidateBundle, Fingerprint
from runtime import InstalledExtensions
from serialization import DomainCodec


class Criterion(msgspec.Struct, frozen=True):
    """Retain one named criterion, its outcome and the facts it read."""

    name: str
    passed: bool
    observed: object


class EnvironmentCheck:
    """Record the installed research and extension identities, and that neither is editable."""

    def __init__(self, checkout: Path, extension: str) -> None:
        """Bind the frozen checkout and the QR extension's distribution name."""
        self.checkout = checkout
        self.extension = extension

    def criteria(self) -> tuple[Criterion, ...]:
        """Identify the installation and refuse source files read from the checkout."""
        location = Path(research.__file__).resolve()
        # The distribution that installed ``research``, not an assumed project name.
        owners = importlib.metadata.packages_distributions().get("research", [])
        record = (
            importlib.metadata.distribution(owners[0]).read_text("RECORD") or ""
            if len(owners) == 1
            else ""
        )
        extensions = InstalledExtensions()
        distributions = sorted(
            f"{item.metadata['Name']}=={item.version}"
            for item in importlib.metadata.distributions()
        )
        return (
            Criterion(
                "research_installed_not_editable",
                not location.is_relative_to(self.checkout.resolve()) and bool(record),
                {
                    "research": str(location),
                    "record_sha256": hashlib.sha256(record.encode()).hexdigest(),
                },
            ),
            Criterion(
                "extension_installed",
                True,
                {
                    "extension": self.extension,
                    "identity": extensions.identity(self.extension),
                },
            ),
            Criterion("distributions", True, distributions),
        )


class ResearchCheck:
    """Require completed studies that pinned the installed extension, and one holdout use."""

    def __init__(self, attempts: Path, extension: str, holdouts: int) -> None:
        """Bind the journey's attempt store, extension and declared holdout consumptions."""
        self.attempts = attempts
        self.extension = extension
        self.holdouts = holdouts

    def criteria(self) -> tuple[Criterion, ...]:
        """Read every retained history and assess identity, completion and holdout use."""
        identity = InstalledExtensions().identity(self.extension)
        pinned = Fingerprint(name=f"extension:{self.extension}", sha256=identity)
        with AttemptStore(self.attempts) as store:
            histories = store.histories()
        completed = tuple(h for h in histories if h.status == "completed")
        unpinned = tuple(
            h.start.attempt_id for h in completed if pinned not in h.start.spec.components
        )
        consumed = tuple(
            h.start.attempt_id
            for h in histories
            for event in h.events
            if event.status == "holdout_consumed"
        )
        statuses = {h.start.attempt_id: h.status for h in histories}
        return (
            Criterion("studies_completed", bool(completed), statuses),
            Criterion("studies_pin_installed_extension", not unpinned, {"unpinned": unpinned}),
            Criterion("holdout_consumed_as_declared", len(consumed) == self.holdouts, consumed),
        )


class CandidateCheck:
    """Reopen every bundle and tie it to a completed attempt and the installed extension."""

    def __init__(self, candidates: Path, attempts: Path, extension: str) -> None:
        """Bind the bundle directory, the attempt store and the extension name."""
        self.candidates = candidates
        self.attempts = attempts
        self.extension = extension

    def criteria(self) -> tuple[Criterion, ...]:
        """Verify bundles, their component identities and their research provenance."""
        identity = InstalledExtensions().identity(self.extension)
        codec = DomainCodec()
        observed: dict[str, object] = {}
        failures: list[str] = []
        roots = sorted(path for path in self.candidates.iterdir() if path.is_dir())
        with AttemptStore(self.attempts) as store:
            for root in roots:
                bundle = CandidateBundle(root)
                manifest = bundle.read()
                history = codec.decode_json(bundle.artifact(manifest.attempt), AttemptHistory)
                retained = store.read(history.start.attempt_id)
                foreign = tuple(
                    item.factory_key
                    for item in manifest.definition.components
                    if item.implementation_sha256 != identity
                )
                if foreign or retained != history or retained.status != "completed":
                    failures.append(root.name)
                observed[root.name] = {
                    "definition": manifest.definition.name,
                    "attempt": history.start.attempt_id,
                    "foreign_components": foreign,
                }
        return (
            Criterion("bundles_present", bool(roots), [root.name for root in roots]),
            Criterion("bundles_verified_against_study_and_extension", not failures, observed),
        )


class _Arguments(argparse.Namespace):
    """Carry one check invocation's inputs."""

    check: str
    checkout: Path | None
    attempts: Path | None
    candidates: Path | None
    extension: str
    holdouts: int


def main() -> None:
    """Run one named check and print its criteria as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=("environment", "research", "candidates"))
    parser.add_argument("--extension", required=True)
    for option in ("--checkout", "--attempts", "--candidates"):
        parser.add_argument(option, type=Path, default=None)
    parser.add_argument("--holdouts", type=int, default=1)
    args = parser.parse_args(namespace=_Arguments())
    criteria: tuple[Criterion, ...]
    if args.check == "environment" and args.checkout is not None:
        criteria = EnvironmentCheck(args.checkout, args.extension).criteria()
    elif args.check == "research" and args.attempts is not None:
        criteria = ResearchCheck(args.attempts, args.extension, args.holdouts).criteria()
    elif args.check == "candidates" and args.candidates is not None and args.attempts is not None:
        criteria = CandidateCheck(args.candidates, args.attempts, args.extension).criteria()
    else:
        parser.error(f"check {args.check} is missing a required path")
    sys.stdout.write(msgspec.json.encode(criteria).decode() + "\n")


if __name__ == "__main__":
    main()
