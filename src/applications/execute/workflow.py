"""Inspect configuration and evaluate suppressed limit intents without submission."""

from __future__ import annotations

# standard library imports
import argparse
import sys
from pathlib import Path

# project library imports
from configuration import ExecutionConfiguration, ExecutionRequest
from risk import SubmissionAdmission
from serialization import DomainCodec


class ExecuteArguments(argparse.Namespace):
    """Hold typed installed command arguments."""

    action: str
    config: Path
    request: Path | None


def main() -> None:
    """Run an installed configuration check or one suppressed admission request."""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    inspect_parser = actions.add_parser("inspect")
    inspect_parser.add_argument("--config", type=Path, required=True)
    admit_parser = actions.add_parser("admit")
    admit_parser.add_argument("--config", type=Path, required=True)
    admit_parser.add_argument("--request", type=Path, required=True)
    arguments = parser.parse_args(namespace=ExecuteArguments())
    try:
        config = ExecutionConfiguration.read(arguments.config)
        if arguments.action == "inspect":
            result: object = config.inspect()
        else:
            if arguments.request is None:
                raise ValueError("admission requires a request")
            result = SubmissionAdmission().evaluate(
                config, ExecutionRequest.read(arguments.request)
            )
        print(DomainCodec().encode_json(result).decode(), flush=True)
    except (OSError, TypeError, ValueError) as error:
        print(f"execution admission rejected: {error}", file=sys.stderr, flush=True)
        raise SystemExit(2) from error
