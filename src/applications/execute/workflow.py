"""Inspect or operate durable paper accounts and authorized test venues."""

from __future__ import annotations

# standard library imports
import argparse
import sqlite3
import sys
from pathlib import Path

# project library imports
from applications.execute.accounts import AccountExecutionApplication
from applications.execute.monitoring import MonitoringApplication
from applications.execute.paper import PaperExecutionApplication
from applications.execute.venue import VenueAction, VenueExecutionApplication
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
    venue_action: VenueAction
    authorization: Path | None
    order: str | None
    duration: float | None
    messages: int | None
    output: Path
    alerts: Path | None
    telemetry: Path | None
    release_identity: str | None
    owners: Path
    root: Path
    socket: Path


def main() -> None:
    """Run one installed admission, local account or test-venue operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    services_parser = actions.add_parser("deployment")
    services_parser.add_argument("--config", type=Path, required=True)
    services_parser.add_argument("--owners", type=Path, required=True)
    services_parser.add_argument("--root", type=Path, required=True)
    services_parser.add_argument("--socket", type=Path, required=True)
    service_control = actions.add_parser("deployment-control")
    service_control.add_argument("--socket", type=Path, required=True)
    service_control.add_argument("--request", type=Path, required=True)
    monitor_parser = actions.add_parser("monitor")
    monitor_parser.add_argument("--config", type=Path, required=True)
    monitor_parser.add_argument("--journal", type=Path, required=True)
    monitor_parser.add_argument("--output", type=Path, required=True)
    monitor_parser.add_argument("--alerts", type=Path)
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
    account_parser = actions.add_parser("account")
    account_parser.add_argument("--config", type=Path, required=True)
    account_parser.add_argument("--journal", type=Path, required=True)
    account_parser.add_argument("--request", type=Path)
    account_parser.add_argument("--telemetry", type=Path)
    account_parser.add_argument("--release-identity")
    venue_parser = actions.add_parser("venue")
    venue_parser.add_argument("--config", type=Path, required=True)
    venue_parser.add_argument("--journal", type=Path, required=True)
    venue_parser.add_argument(
        "--action",
        dest="venue_action",
        choices=(
            "inspect",
            "quote",
            "admit",
            "coordinate",
            "reconcile",
            "submit",
            "cancel",
            "cancel-stranded",
            "stream",
        ),
        default="inspect",
    )
    venue_parser.add_argument("--request", type=Path)
    venue_parser.add_argument("--authorization", type=Path)
    venue_parser.add_argument("--order")
    venue_parser.add_argument("--duration", type=float)
    venue_parser.add_argument("--messages", type=int)
    venue_parser.add_argument("--telemetry", type=Path)
    arguments = parser.parse_args(namespace=ExecuteArguments())
    try:
        result: object
        if arguments.action == "deployment":
            # project library imports
            from applications.execute.services import PaperServiceOwners, run_paper_services
            from configuration import PaperServiceConfiguration

            codec = DomainCodec()
            selected = codec.decode_json(arguments.config.read_bytes(), PaperServiceConfiguration)
            owners = codec.decode_json(arguments.owners.read_bytes(), PaperServiceOwners).owners
            result = run_paper_services(
                selected, owners, root=arguments.root, control_socket=arguments.socket
            )
        elif arguments.action == "deployment-control":
            # project library imports
            from applications.execute.services import control_paper_services

            if arguments.request is None:
                raise ValueError("deployment control requires a typed request")
            print(control_paper_services(arguments.socket, arguments.request).decode(), flush=True)
            return
        elif arguments.action == "monitor":
            snapshot = MonitoringApplication().run(
                config_path=arguments.config,
                journal_path=arguments.journal,
                output=arguments.output,
                alerts_path=arguments.alerts,
            )
            result = {"identity": snapshot.identity, "directory": str(arguments.output.absolute())}
        elif arguments.action == "venue":
            result = VenueExecutionApplication().run(
                config_path=arguments.config,
                journal_path=arguments.journal,
                action=arguments.venue_action,
                request_path=arguments.request,
                authorization_path=arguments.authorization,
                order_id=arguments.order,
                duration_seconds=arguments.duration,
                max_messages=arguments.messages,
                telemetry_path=arguments.telemetry,
            )
        elif arguments.action == "account":
            result = AccountExecutionApplication().run(
                config_path=arguments.config,
                journal_path=arguments.journal,
                request_path=arguments.request,
                telemetry_path=arguments.telemetry,
                release_identity=arguments.release_identity,
            )
        elif arguments.action == "paper":
            result = PaperExecutionApplication().run(
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
    except (OSError, sqlite3.Error, TypeError, ValueError, RuntimeError) as error:
        print(f"execution request failed: {error}", file=sys.stderr, flush=True)
        raise SystemExit(2) from error
