"""Inspect or apply suppressed execution admission and durable paper requests."""

from __future__ import annotations

# standard library imports
import argparse
import sqlite3
import sys
from pathlib import Path

# project library imports
from applications.execute.paper import PaperExecutionApplication
from configuration import ExecutionConfiguration, ExecutionRequest
from risk import SubmissionAdmission
from serialization import DomainCodec


class ExecuteArguments(argparse.Namespace):
    """Hold typed installed command arguments."""

    action: str
    config: Path
    request: Path | None
    journal: Path
    instance: str


def main() -> None:
    """Run one installed no-submission admission or dedicated paper operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    inspect_parser = actions.add_parser("inspect")
    inspect_parser.add_argument("--config", type=Path, required=True)
    admit_parser = actions.add_parser("admit")
    admit_parser.add_argument("--config", type=Path, required=True)
    admit_parser.add_argument("--request", type=Path, required=True)
    paper_parser = actions.add_parser("paper")
    paper_parser.add_argument("--config", type=Path, required=True)
    paper_parser.add_argument("--journal", type=Path, required=True)
    paper_parser.add_argument("--instance", required=True)
    paper_parser.add_argument("--request", type=Path)
    arguments = parser.parse_args(namespace=ExecuteArguments())
    try:
        if arguments.action == "paper":
            result: object = PaperExecutionApplication().run(
                config_path=arguments.config,
                journal_path=arguments.journal,
                instance=arguments.instance,
                request_path=arguments.request,
            )
        else:
            config = ExecutionConfiguration.read(arguments.config)
            if arguments.action == "inspect":
                result = config.inspect()
            else:
                if arguments.request is None:
                    raise ValueError("admission requires a request")
                result = SubmissionAdmission().evaluate(
                    config, ExecutionRequest.read(arguments.request)
                )
        print(DomainCodec().encode_json(result).decode(), flush=True)
    except (OSError, sqlite3.Error, TypeError, ValueError) as error:
        print(f"execution admission rejected: {error}", file=sys.stderr, flush=True)
        raise SystemExit(2) from error
