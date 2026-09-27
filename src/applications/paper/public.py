"""Compose bounded native public feeds with the shared paper decision and account owners."""

from __future__ import annotations

# standard library imports
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
from applications.paper.shared import SharedPaperResult
from configuration import (
    AccountConfiguration,
    BookRegistryConfiguration,
    BookSelection,
    PaperExecutionScenario,
)
from execution import AccountJournal, AccountObservation, PaperMarket
from market_data.adapters.sources import BookAdapters
from market_data.adapters.transport import VenueSubscriptions, VenueTransport
from market_data.books import BookRegistry
from market_data.collection import CaptureRunner, CaptureRunResult, CaptureTransport
from market_data.contracts import CaptureRequest
from research.observations import InputRequirement, LiveBookDecisionSource
from runtime import (
    SharedBookInputs,
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


async def run_live_shared_paper(
    config: AccountConfiguration,
    *,
    account_id: str,
    bindings: tuple[SharedStrategyBinding, ...],
    scenario: PaperExecutionScenario,
    requirement: InputRequirement,
    inputs: SharedBookInputs,
    request: CaptureRequest,
    journal_path: Path,
    output: Path,
    observations: tuple[AccountObservation, ...] = (),
    history_capacity: int = 1000,
    transport: CaptureTransport | None = None,
) -> SharedPublicPaperResult:
    """Run selected policies over a finite native feed without private access.

    One selected account/instrument may have one or several strategy instances.
    Every eligible book first matches older admitted orders, then evaluates a
    policy cohort through independent portfolio/risk checks. Complete independent
    opening/recovery observations must be supplied when readiness requires them;
    this workflow never derives reconciliation facts from its own ledger.

    The absent output directory receives an immutable resolved manifest, bounded
    native capture, fsynced delivery/decision envelopes and final account result.
    On failure the retained account is blocked without releasing open exposure.
    Completion releases no reservations and performs no liquidation. Reopening
    uses a fresh recording and waits for synchronized fresh public input.
    """
    config.__post_init__()
    scenario.__post_init__()
    request.__post_init__()
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
    source = LiveBookDecisionSource(request, requirement, history_capacity=history_capacity)
    books = BookRegistry(
        BookRegistryConfiguration(
            selections=(
                BookSelection.from_capture(
                    request.config,
                    source_id=request.identity,
                    capability=BookAdapters.capability(request.config),
                    max_age_ns=min(
                        requirement.max_age_us * 1000, request.config.idle_seconds * 1_000_000_000
                    ),
                    allow_degraded=True,
                ),
            ),
            equivalences=(),
            history_capacity=history_capacity,
        )
    )
    journal = AccountJournal(journal_path, config)
    runtime = SharedDecisionRuntime(journal, bindings)
    observer = SharedPaperCaptureObserver(
        source=source,
        books=books,
        journal=journal,
        runtime=runtime,
        account_id=account_id,
        scenario=scenario,
        inputs=inputs,
        delivery_path=output / "deliveries.jsonl",
    )
    codec = DomainCodec()
    try:
        output.mkdir(parents=True, exist_ok=False)
        manifest = {
            "schema_version": "public-paper-run-v1",
            "account_configuration": config,
            "account_id": account_id,
            "execution_scenario": scenario,
            "capture_request": request,
            "book_registry": books.config,
            "requirement": requirement,
            "input_binding": inputs.identity,
            "paper_mark_policy": "last_eligible_bid_v1",
            "strategies": tuple(
                (binding.instance_id, binding.policy.identity, binding.context, binding.maximum_fee)
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
            observer=observer,
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
            max_mark_age=timedelta(microseconds=requirement.max_age_us),
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
        (output / "execution-traces.json").write_bytes(
            codec.encode_json(journal.paper_traces(account_id))
        )
        (output / "cost-report.json").write_bytes(codec.encode_json(report))
        paper = SharedPaperResult(
            accounts=journal.accounts(),
            children=journal.orders(),
            net_orders=journal.net_orders(),
            decisions=tuple(observer.decisions),
            residuals=journal.portfolio_residuals(account_id),
        )
        (output / "paper-result.json").write_bytes(codec.encode_json(paper))
        return SharedPublicPaperResult(
            capture=capture,
            paper=paper,
            book_registry=books.config,
            last_market=observer.last_market,
            report=report,
        )
    except BaseException as error:
        try:
            account = next(
                (item for item in journal.accounts() if item.ledger.account_id == account_id), None
            )
            if account is None or account.operator_block is None:
                journal.block(account_id, "public_paper_failure")
        except BaseException as block_error:
            error.add_note(f"paper account block also failed: {type(block_error).__name__}")
        raise
