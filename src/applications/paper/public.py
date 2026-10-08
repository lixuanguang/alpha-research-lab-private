"""Compose bounded native public feeds with the shared paper decision and account owners."""

from __future__ import annotations

# standard library imports
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

# project library imports
from accounting import (
    AccountLedger,
    AttributedPaperFill,
    PaperAccountReport,
    PaperAccountReporter,
    PaperCostEvidence,
    PaperGasPolicy,
    PaperPositionMark,
)
from applications.paper.monitoring import PaperMonitoringResult, retain_public_paper_monitoring
from applications.paper.shared import SharedPaperResult
from configuration import (
    AccountConfiguration,
    BookRegistryConfiguration,
    BookSelection,
    PaperExecutionScenario,
)
from execution import AccountControl, AccountJournal, AccountObservation, PaperAccount, PaperMarket
from market_data.adapters.sources import BookAdapters
from market_data.adapters.transport import VenueSubscriptions, VenueTransport
from market_data.books import BookRegistry
from market_data.collection import CaptureRunner, CaptureRunResult, CaptureTransport
from market_data.contracts import CaptureRequest
from research.observations import InputRequirement, LiveBookDecisionSource
from runtime import (
    SharedDecisionRuntime,
    SharedPaperCaptureObserver,
    SharedStrategyBinding,
)
from serialization import DomainCodec


@dataclass(frozen=True)
class SharedPublicPaperResult:
    """Separate observed native capture from modeled account and decision outcomes."""

    capture: CaptureRunResult
    paper: SharedPaperResult
    book_registry: BookRegistryConfiguration
    last_market: PaperMarket | None
    report: PaperAccountReport
    monitoring: PaperMonitoringResult


async def run_live_shared_paper(
    config: AccountConfiguration,
    *,
    account_id: str,
    bindings: tuple[SharedStrategyBinding, ...],
    scenario: PaperExecutionScenario,
    request: CaptureRequest,
    journal_path: Path,
    output: Path,
    observations: tuple[AccountObservation, ...] = (),
    history_capacity: int = 1000,
    transport: CaptureTransport | None = None,
    alert_socket: str | None = None,
    paper_account: PaperAccount | None = None,
) -> SharedPublicPaperResult:
    """Run selected candidates over a finite native feed without private access.

    One selected account/instrument may have one or several candidate instances.
    The source projects every field the candidates read. Each candidate decides at
    its grid instants through independent portfolio/risk checks, and the book that
    crosses an instant then matches admitted orders. Complete independent
    opening/recovery observations must be supplied when readiness requires them;
    this workflow never derives reconciliation facts from its own ledger.

    The absent output directory receives an immutable resolved manifest, bounded
    native capture, fsynced delivery/decision envelopes and final account result. A
    relative ``output`` is resolved against the working directory before any effect,
    so a signed account runner, which has its own, writes the trace export there too.
    On failure the retained account is blocked without releasing open exposure.
    Completion releases no reservations and performs no liquidation. Reopening
    uses a fresh recording and waits for synchronized fresh public input.
    """
    config.__post_init__()
    scenario.__post_init__()
    request.__post_init__()
    output = output.absolute()
    if (
        config.mode != "paper"
        or not bindings
        or any(
            binding.account_id != account_id
            or binding.entity != str(request.config.instrument_id)
            or binding.context.venue != request.config.venue
            for binding in bindings
        )
    ):
        raise ValueError("public paper requires selected paper account and native venue bindings")
    requirements: tuple[InputRequirement, ...] = ()
    for binding in bindings:
        requirements += tuple(
            item for item in binding.candidate.definition.inputs if item not in requirements
        )
    source = LiveBookDecisionSource(request, requirements, history_capacity=history_capacity)
    max_age_us = requirements[0].max_age_us
    books = BookRegistry(
        BookRegistryConfiguration(
            selections=(
                BookSelection.from_capture(
                    request.config,
                    source_id=request.identity,
                    capability=BookAdapters.capability(request.config),
                    max_age_ns=min(max_age_us * 1000, request.config.idle_seconds * 1_000_000_000),
                    allow_degraded=True,
                ),
            ),
            equivalences=(),
            history_capacity=history_capacity,
        )
    )
    journal: PaperAccount = (
        AccountJournal(journal_path, config) if paper_account is None else paper_account
    )
    if paper_account is not None:
        if journal.config != config or journal.paper_owner is None:
            raise ValueError("public paper requires a configured claimed owner")
        activation = next(
            (
                item
                for item in journal.paper_activations()
                if item.deployment.account_id == account_id
            ),
            None,
        )
        if activation is None or activation.owner != journal.paper_owner:
            raise ValueError("public paper owner is absent or stale")
        activation.require_authority(datetime.now(UTC))
        deployment = activation.deployment
        if (
            deployment.scenario != scenario
            or deployment.input_identity
            != hashlib.sha256(DomainCodec().encode_json((request.config, requirements))).hexdigest()
            or {
                (
                    item.instance_id,
                    item.candidate_identity,
                    item.policy_identity,
                    item.model_identity,
                    item.feature_identity,
                )
                for item in deployment.strategies
            }
            != {
                (
                    item.instance_id,
                    item.candidate.definition.identity,
                    item.candidate.policy.identity,
                    item.context.model_revision,
                    item.candidate.feature.schema.identity,
                )
                for item in bindings
            }
            or any(item.context.authority_scope != "paper" for item in bindings)
        ):
            raise ValueError("public paper deployment workload bindings differ")
    # Every account's traces share one history; this run's follow its current length.
    initial_traces = journal.paper_trace_history().count
    runtime = SharedDecisionRuntime(journal, bindings)
    observer = SharedPaperCaptureObserver(
        source=source,
        books=books,
        journal=journal,
        runtime=runtime,
        account_id=account_id,
        scenario=scenario,
        delivery_path=output / "deliveries.jsonl",
    )
    codec = DomainCodec()
    owns_output = False
    try:
        output.mkdir(parents=True, exist_ok=False)
        owns_output = True
        manifest = {
            "schema_version": "public-paper-run",
            "account_configuration": config,
            "account_id": account_id,
            "execution_scenario": scenario,
            "capture_request": request,
            "book_registry": books.config,
            "requirements": requirements,
            "paper_mark_policy": "last_eligible_bid",
            "strategies": tuple(
                (
                    binding.instance_id,
                    binding.candidate.definition.identity,
                    binding.candidate.deployment.identity,
                    binding.context,
                    binding.maximum_fee,
                )
                for binding in bindings
            ),
            "opening_observations": observations,
        }
        (output / "manifest.json").write_bytes(codec.encode_json(manifest))
        for observation in observations:
            if observation.snapshot.account_id != account_id or not journal.reconcile(observation):
                raise ValueError("public paper opening or recovery reconciliation failed")
        runner = CaptureRunner(
            book_factory=BookAdapters.create,
            transport=VenueTransport(request.config) if transport is None else transport,
            subscriptions=VenueSubscriptions(),
            observer=observer.projected_rows(),
        )
        capture = await runner.run(request, output / "capture")
        if capture.summary.get("stop_reason") not in ("duration_limit", "message_limit") or (
            capture.summary.get("synchronized") is not True
        ):
            raise ValueError("public paper capture ended without a healthy synchronized book")
        account = next(
            (item for item in journal.accounts() if item.ledger.account_id == account_id), None
        )
        if account is None:
            raise ValueError("public paper account disappeared before reporting")
        matched_fills, matched_costs = journal.paper_report_facts(account_id)
        marks = (
            (
                PaperPositionMark(
                    identity=observer.last_market.identity,
                    available_at=observer.last_market.at,
                    price=observer.last_market.bid,
                ),
            )
            if AccountLedger(account.ledger).snapshot().positions
            and observer.last_market is not None
            else ()
        )
        report = PaperAccountReporter().build(
            account.ledger,
            cutoff=datetime.now(UTC),
            max_mark_age=timedelta(microseconds=max_age_us),
            marks=marks,
            fills=tuple(
                AttributedPaperFill(
                    instance_id=item.instance_id, order_id=item.order_id, fill=item.fill
                )
                for item in matched_fills
            ),
            costs=tuple(
                PaperCostEvidence(
                    source_fill_id=item.source_fill_id,
                    posting_id=item.posting_id,
                    amount=item.amount,
                )
                for item in matched_costs
            ),
            gas_policy=PaperGasPolicy(
                scenario_id=scenario.identity,
                applicable=False,
                reason=scenario.gas_inapplicable_reason,
            ),
        )
        journal.export_paper_traces(output / "execution-traces.json", account_id)
        (output / "cost-report.json").write_bytes(codec.encode_json(report))
        paper = SharedPaperResult(
            accounts=journal.accounts(),
            children=journal.orders(),
            net_orders=journal.net_orders(),
            decisions=tuple(observer.decisions),
            residuals=journal.portfolio_residuals(account_id),
        )
        (output / "paper-result.json").write_bytes(codec.encode_json(paper))
    except BaseException as error:
        try:
            account = next(
                (item for item in journal.accounts() if item.ledger.account_id == account_id), None
            )
            if account is None or account.operator_block is None:
                if paper_account is None:
                    journal.block(account_id, "public_paper_failure")
                else:
                    journal.control(
                        AccountControl(
                            identity=f"public-paper-fault:{request.identity}",
                            account_id=account_id,
                            kind="fault",
                            at=datetime.now(UTC),
                            reason="public_paper_failure",
                        )
                    )
        except BaseException as block_error:
            error.add_note(f"paper account block also failed: {type(block_error).__name__}")
        if owns_output:
            monitoring = retain_public_paper_monitoring(
                journal,
                account_id=account_id,
                request=request,
                root=output,
                observed_at=datetime.now(UTC),
                report=None,
                decisions=tuple(observer.decisions),
                prior_traces=initial_traces,
                summary={},
                processing_ns=observer.processing_ns,
                delivered_count=observer.delivered_count,
                alert_socket=alert_socket,
                faulted=True,
            )
            if monitoring.errors:
                error.add_note(f"monitoring errors: {monitoring.errors}")
        raise
    if paper_account is not None:
        stopped = journal.control(
            AccountControl(
                identity=f"public-paper-stop:{request.identity}",
                account_id=account_id,
                kind="stop",
                at=datetime.now(UTC),
                reason="finite_public_paper_completed",
            )
        )
        if stopped.status != "applied":
            raise ValueError("public paper completion stop was rejected")
    monitoring = retain_public_paper_monitoring(
        journal,
        account_id=account_id,
        request=request,
        root=output,
        observed_at=datetime.now(UTC),
        report=report,
        decisions=tuple(observer.decisions),
        prior_traces=initial_traces,
        summary=capture.summary,
        processing_ns=observer.processing_ns,
        delivered_count=observer.delivered_count,
        alert_socket=alert_socket,
    )
    return SharedPublicPaperResult(
        capture=capture,
        paper=paper,
        book_registry=books.config,
        last_market=observer.last_market,
        report=report,
        monitoring=monitoring,
    )
