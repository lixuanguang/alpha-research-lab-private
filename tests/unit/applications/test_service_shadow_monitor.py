"""Keep shadow instance economics and authority visible during pending operation."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

# third party library imports
import msgspec

# project library imports
from accounting import AccountPosting, AccountState, PaperAccountReport, PaperScopeReport
from applications.execute.service_monitor import PaperServiceMonitor
from configuration import (
    AccountConfiguration,
    CaptureConfig,
    OpeningAccount,
    PaperAuthorization,
    PaperDeployment,
    PaperExecutionScenario,
    PaperServiceSource,
    PaperStrategyIdentity,
)
from execution import (
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountView,
    OrderState,
    PaperActivation,
    PaperOwner,
    PortfolioResidual,
    SocketPaperAccount,
    TaggedOrder,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent


class _SnapshotAccount(SocketPaperAccount):
    """Count account inspection without opening a service socket."""

    def __init__(
        self, config: AccountConfiguration, owner: PaperOwner, state: AccountExecutionResult
    ) -> None:
        """Expose exactly one pre-inspected state."""
        self.config = config
        self.paper_owner = owner
        self.state = state
        self.seen_requests: list[AccountExecutionRequest] = []

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Record every monitor transport request."""
        self.seen_requests.append(request)
        return self.state


class _InstanceSnapshot(msgspec.Struct):
    """Decode each retained instance scope without generic JSON values."""

    instance_id: str
    scope: PaperScopeReport
    orders: tuple[TaggedOrder, ...]
    reservations: tuple[TaggedOrder, ...]
    residuals: tuple[PortfolioResidual, ...]
    stopped: bool


class _RetainedSnapshot(msgspec.Struct):
    """Decode the complete typed diagnostic artifact."""

    observed_at: datetime
    account: AccountExecutionResult
    account_view: AccountView
    activation: PaperActivation | None
    report: PaperAccountReport
    instances: tuple[_InstanceSnapshot, ...]
    heartbeat_is_freshness: bool


def test_shadow_monitor_retains_pending_instance_zero_economics_once(tmp_path: Path) -> None:
    """Pending reservations do not invent fills, costs, or P&L for a shadow policy."""
    capture = CaptureConfig.read(Path("configs/live/okx-btc-usdt.json"))
    now = datetime.now(UTC)
    currency = Currency.from_code("USDT")
    dimension = Dimension(instrument_id=capture.instrument_id, kind=QuantityKind.BASE_UNIT)
    cash = Money(value=Decimal("1000"), currency=currency)
    quantity = Quantity(value=Decimal("1"), dimension=dimension)
    price = Price(value=Decimal("10"), currency=currency, per=dimension)
    config = AccountConfiguration(
        mode="shadow",
        opening_at=now - timedelta(minutes=1),
        accounts=(OpeningAccount(account_id="shared", cash=(cash,)),),
        instruments=(SpotLimits(maximum=quantity, lot=quantity, tick=price, product="spot"),),
        budgets=BudgetPolicy(
            valuation_currency=currency,
            firm_maximum=cash,
            accounts=(AccountLimit(account_id="shared", maximum=cash),),
            instances=tuple(
                InstanceLimit(
                    instance_id=name,
                    account_id="shared",
                    maximum=cash,
                    instruments=(capture.instrument_id,),
                )
                for name in ("first", "second")
            ),
            max_quote_age_us=30_000_000,
            max_state_age_us=30_000_000,
            max_price_deviation_bps=100,
            max_order_notional=cash,
        ),
    )
    scenario = PaperExecutionScenario(
        venue="okx",
        instrument_id=capture.instrument_id,
        entry_delay_us=1000,
        cancel_delay_us=2000,
        adverse=Price(value=Decimal("0.01"), currency=currency, per=dimension),
        fee_rate=Decimal("0.001"),
        take_fraction=Decimal("0.5"),
        gas_inapplicable_reason="Off-chain spot without transfers.",
    )
    source = PaperServiceSource(
        name="book", capture=capture, scenario=scenario, freshness_us=30_000_000
    )
    deployment = PaperDeployment(
        account_id="shared",
        configuration_sha256=hashlib.sha256(DomainCodec().encode_json(config)).hexdigest(),
        releases=("b" * 64,),
        strategies=tuple(
            PaperStrategyIdentity(
                instance_id=name,
                policy_identity="fixed-clip",
                candidate_identity="candidate",
                model_identity="none",
                feature_identity="book",
            )
            for name in ("first", "second")
        ),
        input_identity="book",
        scenario=scenario,
        state_identity="paper-account-state-v1",
        submission_authority="shadow",
    )
    authorization = PaperAuthorization(
        identity="bounded",
        deployment_sha256=deployment.identity,
        valid_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=1),
        quantities=(quantity,),
        maximum_order_notional=cash,
        maximum_orders=2,
        submission_authority="shadow",
    )
    owner = PaperOwner(
        account_id="shared",
        deployment_sha256=deployment.identity,
        authorization_id=authorization.identity,
        release_identity="b" * 64,
        owner_id="worker",
        generation=1,
    )
    activation = PaperActivation(
        deployment=deployment,
        changed_at=now,
        authorization=authorization,
        owner=owner,
        generation=1,
    )
    order = TaggedOrder(
        account_id="shared",
        instance_id="first",
        order=OrderState(
            identity="pending-first",
            decision_identity="decision-first",
            decision_at=now,
            intent=OrderIntent(side="buy", quantity=quantity, limit=price, time_in_force="gtc"),
            status="intent",
            filled=Quantity(value=Decimal("0"), dimension=dimension),
            paid_fee=Money(value=Decimal("0"), currency=currency),
            maximum_fee=Money(value=Decimal("1"), currency=currency),
        ),
    )
    opening = AccountPosting(
        identity="opening",
        account_id="shared",
        event_at=config.opening_at,
        known_at=config.opening_at,
        kind="transfer",
        cash=cash,
    )
    view = AccountView(
        ledger=AccountState(account_id="shared", currencies=(currency,), postings=(opening,)),
        reconciled_at=config.opening_at,
    )
    state = AccountExecutionResult(
        accounts=(view,),
        orders=(order,),
        stopped_instances=("second",),
        paper_activations=(activation,),
    )
    account = _SnapshotAccount(config, owner, state)
    retained_root = tmp_path / "monitor"
    result = PaperServiceMonitor(retained_root).sample(account, (source,), ())

    assert result["status"] == "retained"
    assert result["account"] == view
    assert result["activation"] == activation
    assert len(account.seen_requests) == 1
    assert account.seen_requests[0].action == "inspect"
    assert account.seen_requests[0].account_id == "shared"
    status_instances = cast(tuple[dict[str, object], ...], result["instances"])
    assert tuple(item["instance_id"] for item in status_instances) == ("first", "second")
    assert status_instances[0]["orders"] == (order,)
    assert status_instances[0]["reservations"] == (order,)
    assert status_instances[1]["stopped"] is True

    retained = DomainCodec().decode_json(
        (retained_root / "shared.json").read_bytes(), _RetainedSnapshot
    )
    assert retained.account == state
    assert retained.account_view == view
    assert retained.activation == activation
    assert retained.report.instances == ()
    assert retained.report.account.currencies[0].nav == cash
    assert retained.heartbeat_is_freshness is False
    assert tuple(item.instance_id for item in retained.instances) == ("first", "second")
    first, second = retained.instances
    assert first.orders == first.reservations == (order,)
    assert first.stopped is False
    assert second.orders == second.reservations == ()
    assert second.stopped is True
    for item in retained.instances:
        scope = item.scope
        assert scope.snapshot.instance_id == item.instance_id
        assert scope.snapshot.fill_ids == ()
        assert scope.snapshot.posting_ids == ()
        assert scope.snapshot.positions == ()
        assert scope.snapshot.fees[0].value == 0
        assert scope.snapshot.rebates[0].value == 0
        assert scope.currencies[0].net_pnl.value == 0
        assert scope.currencies[0].slippage.value == 0
