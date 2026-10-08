"""J6 and J7 operator steps the journey driver delegates to the installed platform.

The driver imports no platform code. It runs this consumer with the research
interpreter to author the signed services and account definitions from the QR's
packaged candidates, to install and claim each account through its signed
launcher, to author restart observations, and to reconcile every account on a
fixed cadence. Every effect still goes through a signed launcher; this file only
writes typed request bytes and reads typed results.
"""

from __future__ import annotations

# standard library imports
import argparse
import fcntl
import hashlib
import shutil
import subprocess  # nosec B404  # [owner=runtime; rationale=standalone account inspection of a restored copy; expires=2027-03-01]
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.util import find_spec
from pathlib import Path
from typing import ClassVar, Literal
from uuid import uuid4

# third party library imports
import msgspec

# project library imports
from accounting import AccountLedger, AccountSnapshot
from applications.execute import PaperServiceCandidates, PaperServiceOwners
from configuration import (
    AccountConfiguration,
    BookRegistryConfiguration,
    BookSelection,
    CaptureConfig,
    InstrumentFeeRate,
    OpeningAccount,
    PackagedCandidate,
    PaperAuthorization,
    PaperDeployment,
    PaperExecutionScenario,
    PaperFeaturePublisher,
    PaperFeatureServing,
    PaperServiceAccount,
    PaperServiceConfiguration,
    PaperServiceInstance,
    PaperServiceSource,
    PaperSourceChain,
    PaperStrategyIdentity,
    ReferenceCandidate,
)
from execution import (
    AccountControl,
    AccountControlResult,
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountJournal,
    AccountObservation,
    AccountPaperCost,
    AccountPaperFill,
    AccountQuote,
    AccountView,
    InstalledPaperAccount,
    NetOrder,
    PaperMarket,
    PaperOwner,
    SocketPaperAccount,
    TaggedOrder,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from market_data.adapters.sources import BookAdapters
from market_data.books import BookRegistry
from market_data.storage import CaptureRecording
from reference_data.instruments import InstrumentId
from research.experiments import AttemptStore, CandidateBundle
from research.features import FeastOfflineWorker, FeastServingBridge, VersionedFeatureStore
from research.observations import LiveBookDecisionSource, LiveTradeDecisionSource
from research.studies import DecisionStudy, StudyResult
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from runtime import (
    AccountRecoveryReceipt,
    LiveBookDelivery,
    ServedFeatures,
    SharedBookDelivery,
    SharedDecisionRuntime,
    SharedPaperCaptureObserver,
    WorkspaceBackup,
)
from serialization import DomainCodec

Mode = Literal["paper", "shadow"]
# The paper services' workspace components J7 backs up: the release's candidates, the
# served feature store and J6's two paper service roots.
PAPER_COMPONENTS = ("candidates", "features", "service-p-a", "service-p-b")
# The account rules paper may refuse for and research does not model: budgets,
# holdings, funding, and self-trade protection between the account's working orders.
PAPER_ONLY_REASONS = frozenset(
    {
        "self_trade_conflict",
        "holding_limit",
        "instance_limit",
        "account_limit",
        "firm_limit",
        "insufficient_cash",
        "insufficient_owned_inventory",
        "order_notional_limit",
    }
)


@dataclass(frozen=True, slots=True)
class Market:
    """One declared instrument: its venue, asset and the J6 numbers that size it."""

    venue: Literal["okx", "bitfinex"]
    asset: Literal["btc", "eth"]
    quote: str
    position_limit: str
    size: str

    @property
    def name(self) -> str:
        """Name the source and the candidates' family suffix."""
        return f"{self.venue}-{self.asset}"

    @property
    def feed(self) -> str:
        """Name the QR's captured feed files."""
        return f"{self.venue}-{self.asset}-{self.quote.lower()}"


# Names the QR workspace chose for its extension package, study families and metric.
QR_EXTENSION = "mr17-extensions"
QR_PREFIX = "mr17"


class PaperPlan:
    """Author the services and account definitions with the approved J6 numbers.

    Paper deploys `okx-shared`, `okx-isolated`, `bitfinex-shared` and
    `bitfinex-isolated`, each with the rule and learned candidates on one
    instrument, plus an inactive second-origin rule on `okx-shared` for J7.
    Shadow deploys `okx-shadow` and `bitfinex-shadow` with both BTC candidates.
    """

    markets: ClassVar[dict[str, Market]] = {
        "okx-btc": Market("okx", "btc", "USDT", "0.01", "0.006"),
        "okx-eth": Market("okx", "eth", "USDT", "0.5", "0.1"),
        "bitfinex-btc": Market("bitfinex", "btc", "USD", "0.01", "0.006"),
        "bitfinex-eth": Market("bitfinex", "eth", "USD", "0.5", "0.1"),
    }
    accounts: ClassVar[dict[Mode, tuple[tuple[str, str], ...]]] = {
        "paper": (
            ("okx-shared", "okx-btc"),
            ("okx-isolated", "okx-eth"),
            ("bitfinex-shared", "bitfinex-btc"),
            ("bitfinex-isolated", "bitfinex-eth"),
        ),
        "shadow": (("okx-shadow", "okx-btc"), ("bitfinex-shadow", "bitfinex-btc")),
    }
    lot = Decimal("0.00001")
    tick = Decimal("0.01")
    service_life_seconds = 3000

    def __init__(self, qr: Path, candidates: Path, *, mode: Mode, opening: datetime) -> None:
        """Bind the QR workspace, its packaged candidates and the opening clock."""
        self.qr, self.candidates, self.mode, self.opening = qr, candidates, mode, opening
        self.codec = DomainCodec()

    @staticmethod
    def dimension(capture: CaptureConfig) -> Dimension:
        """Return the instrument's base-unit dimension."""
        return Dimension(instrument_id=capture.instrument_id, kind=QuantityKind.BASE_UNIT)

    def capture(self, market: Market, channel: Literal["books", "trades"]) -> CaptureConfig:
        """Read one of the QR's declared capture configurations."""
        path = self.qr / "data/feeds" / f"{market.feed}-{channel}.json"
        return self.codec.decode_json(path.read_bytes(), CaptureConfig)

    def bundles(self, output: Path) -> dict[str, str]:
        """Copy each packaged family into the release layout, named by definition identity."""
        identities: dict[str, str] = {}
        for root in sorted(path for path in self.candidates.iterdir() if path.is_dir()):
            identity = CandidateBundle(root).definition().identity
            shutil.copytree(root, output / identity)
            identities[root.name] = identity
        return identities

    def account(
        self, account_id: str, market: Market, instances: tuple[str, ...]
    ) -> AccountConfiguration:
        """Size one account with the approved budgets, limits and fees."""
        books = self.capture(market, "books")
        dimension = self.dimension(books)
        currency = Currency.from_code(market.quote)
        money = Money(value=Decimal("100000"), currency=currency)
        bound = Money(value=Decimal("10000"), currency=currency)
        return AccountConfiguration(
            mode=self.mode,
            opening_at=self.opening,
            accounts=(OpeningAccount(account_id=account_id, cash=(money,)),),
            instruments=(
                SpotLimits(
                    maximum=Quantity(value=Decimal(market.position_limit), dimension=dimension),
                    lot=Quantity(value=self.lot, dimension=dimension),
                    tick=Price(value=self.tick, currency=currency, per=dimension),
                    product="spot",
                ),
            ),
            fee_rates=(
                InstrumentFeeRate(instrument_id=books.instrument_id, rate=Decimal("0.001")),
            ),
            budgets=BudgetPolicy(
                valuation_currency=currency,
                firm_maximum=bound,
                accounts=(AccountLimit(account_id=account_id, maximum=bound),),
                instances=tuple(
                    InstanceLimit(
                        instance_id=name,
                        account_id=account_id,
                        maximum=Money(value=Decimal("5000"), currency=currency),
                        instruments=(books.instrument_id,),
                    )
                    for name in instances
                ),
                max_quote_age_us=30_000_000,
                max_state_age_us=120_000_000,
                max_residual_age_us=86_400_000_000,
                max_price_deviation_bps=500,
                max_order_notional=Money(value=Decimal("1000"), currency=currency),
            ),
            service_life_seconds=self.service_life_seconds,
        )

    def source(self, market: Market) -> PaperServiceSource:
        """Bind the instrument's books and trades feeds and its paper scenario."""
        books, trades = self.capture(market, "books"), self.capture(market, "trades")
        currency = Currency.from_code(market.quote)
        return PaperServiceSource(
            name=market.name,
            capture=books,
            trades=trades,
            freshness_us=15_000_000,
            chain=PaperSourceChain(max_messages=10_000_000, max_bytes=8 * 1024**3, max_segments=64),
            scenario=PaperExecutionScenario(
                venue=market.venue,
                instrument_id=books.instrument_id,
                # The QR's simulator: a 1 ms entry delay, no cancel delay, full take.
                entry_delay_us=1_000,
                cancel_delay_us=0,
                adverse=Price(value=Decimal("0.5"), currency=currency, per=self.dimension(books)),
                fee_rate=Decimal("0.001"),
                take_fraction=Decimal(1),
                gas_inapplicable_reason="Off-chain spot without blockchain transfers.",
            ),
        )

    def configuration(
        self,
        identities: dict[str, str],
        *,
        sockets: Path,
        store: Path,
        serving_root: Path,
        worker: Path,
        alert_socket: Path,
        duration_seconds: int,
        origin: datetime,
    ) -> PaperServiceConfiguration:
        """Select every account, source and instance of this mode's phase."""
        accounts: list[PaperServiceAccount] = []
        sources: list[PaperServiceSource] = []
        instances: list[PaperServiceInstance] = []
        inactive: list[str] = []
        for account_id, market_name in self.accounts[self.mode]:
            market = self.markets[market_name]
            source = self.source(market)
            dimension = self.dimension(source.capture)
            currency = Currency.from_code(market.quote)
            selected: list[tuple[str, str, datetime, str | None]] = [
                (f"rule-{market.name}", f"{QR_PREFIX}-rule-{market.name}", origin, None),
                # Five seconds after the rule, so the pair decide in separate batches and
                # the learned target contends for the limit the rule's bid reserved.
                (
                    f"learned-{market.name}",
                    f"{QR_PREFIX}-learned-{market.name}",
                    origin + timedelta(seconds=5),
                    "live",
                ),
            ]
            if self.mode == "paper" and account_id == "okx-shared":
                selected.append(
                    (
                        f"rule-{market.name}-late",
                        f"{QR_PREFIX}-rule-{market.name}",
                        origin + timedelta(seconds=7, microseconds=500_000),
                        None,
                    )
                )
                inactive.append(f"rule-{market.name}-late")
            for name, family, starts_at, version in selected:
                instances.append(
                    PaperServiceInstance(
                        instance_id=name,
                        account_id=account_id,
                        source=source.name,
                        candidate=PackagedCandidate(
                            definition_sha256=identities[family],
                            extension=QR_EXTENSION,
                            starts_at=starts_at,
                            feature_version=version,
                        ),
                        quantity=Quantity(value=Decimal(market.size), dimension=dimension),
                        lot=Quantity(value=self.lot, dimension=dimension),
                        maximum_fee=Money(value=Decimal("2"), currency=currency),
                    )
                )
            names = [name for name, _, _, _ in selected]
            if self.mode == "paper" and account_id == "okx-shared":
                # A platform reference holds the BTC size from its first decision, so a
                # QR candidate's long bid meets the shared limit because of its holding.
                names.append(f"reference-{market.name}")
                instances.append(
                    PaperServiceInstance(
                        instance_id=f"reference-{market.name}",
                        account_id=account_id,
                        source=source.name,
                        candidate=ReferenceCandidate(
                            formula="fixed_clip",
                            cadence_us=15_000_000,
                            starts_at=origin + timedelta(seconds=2, microseconds=500_000),
                        ),
                        quantity=Quantity(value=Decimal(market.size), dimension=dimension),
                        lot=Quantity(value=self.lot, dimension=dimension),
                        maximum_fee=Money(value=Decimal("2"), currency=currency),
                    )
                )
            accounts.append(
                PaperServiceAccount(
                    account_id=account_id,
                    configuration=self.account(
                        account_id,
                        market,
                        tuple(names),
                    ),
                    socket_path=str(sockets / f"{account_id}.sock"),
                )
            )
            sources.append(source)
        spec = find_spec("applications.explore.command")
        if spec is None or spec.origin is None:
            raise ValueError("the research environment lacks the Feast serving worker command")
        return PaperServiceConfiguration(
            accounts=tuple(accounts),
            sources=tuple(sources),
            instances=tuple(instances),
            active=tuple(
                item.instance_id for item in instances if item.instance_id not in inactive
            ),
            revision=1,
            duration_seconds=duration_seconds,
            alert_socket=str(alert_socket),
            features=PaperFeatureServing(
                store_path=str(store),
                serving_root=str(serving_root),
                worker=(
                    str(worker),
                    "-I",
                    "-c",
                    "from runpy import run_path; raise SystemExit("
                    f"run_path({spec.origin!r})['main'](['feast-serving-worker']))",
                ),
                worker_timeout_seconds=60,
                publisher=PaperFeaturePublisher(max_lag_seconds=30),
            ),
        )


class CheckedInstance(msgspec.Struct, frozen=True):
    """Read one instance's identities as the installed release's deployment check reports."""

    candidate_identity: str
    policy_identity: str
    feature_identity: str
    model_identity: str
    cadence_us: int


class DeploymentCheck(msgspec.Struct, frozen=True):
    """Read the installed release's deployment check: source and instance identities."""

    sources: dict[str, str]
    instances: dict[str, CheckedInstance]


class PaperAuthority:
    """Author each account's disabled deployment and finite grant.

    Identities come from the installed release's deployment check, never from this
    environment: a reference candidate's identity names the code and environment that
    load it, and only the release's are the supervisor's.
    """

    def __init__(self, configuration: PaperServiceConfiguration, check: DeploymentCheck) -> None:
        """Bind the services configuration and the release's checked identities."""
        self.configuration, self.check = configuration, check
        self.codec = DomainCodec()

    def deployment(
        self, account: PaperServiceAccount, releases: tuple[str, ...]
    ) -> PaperDeployment:
        """Sign every provisioned instance of one account, as the supervisor's preflight checks."""
        definitions = tuple(
            item for item in self.configuration.instances if item.account_id == account.account_id
        )
        source = next(
            item for item in self.configuration.sources if item.name == definitions[0].source
        )
        strategies = tuple(
            PaperStrategyIdentity(
                instance_id=item.instance_id,
                policy_identity=checked.policy_identity,
                candidate_identity=checked.candidate_identity,
                model_identity=checked.model_identity,
                feature_identity=checked.feature_identity,
            )
            for item in definitions
            for checked in (self.check.instances[item.instance_id],)
        )
        return PaperDeployment(
            account_id=account.account_id,
            configuration_sha256=hashlib.sha256(
                self.codec.encode_json(account.configuration)
            ).hexdigest(),
            releases=releases,
            strategies=strategies,
            input_identity=self.check.sources[source.name],
            scenario=source.scenario,
            state_identity="paper-account-state",
            submission_authority="paper" if account.configuration.mode == "paper" else "shadow",
        )

    def authorization(self, deployment: PaperDeployment, at: datetime) -> PaperAuthorization:
        """Grant one hour of the account's deployed decisions.

        Each decision replaces its instance's working orders, so an instance can place
        both legs of a quote at every cadence step. The order count is the binding cap:
        each instrument's quantity admits that many orders of its market's size, and
        exposure stays bounded by the position limits, budgets and order notional.
        """
        scenario = deployment.scenario
        instances = {item.instance_id: item for item in self.configuration.instances}
        decisions = sum(
            3_600_000_000 // self.check.instances[item.instance_id].cadence_us
            for item in deployment.strategies
        )
        maximum_orders = 2 * decisions
        market = PaperPlan.markets[instances[deployment.strategies[0].instance_id].source]
        return PaperAuthorization(
            identity=f"{deployment.account_id}-grant-{uuid4().hex[:8]}",
            deployment_sha256=deployment.identity,
            valid_from=at - timedelta(minutes=1),
            expires_at=at + timedelta(hours=1),
            quantities=(
                Quantity(
                    value=Decimal(market.size) * maximum_orders, dimension=scenario.adverse.per
                ),
            ),
            maximum_order_notional=Money(value=Decimal("1000"), currency=scenario.adverse.currency),
            maximum_orders=maximum_orders,
            submission_authority=deployment.submission_authority,
        )


class PaperClaim:
    """Install, authorize, observe, reconcile and claim one signed account."""

    def __init__(self, installed: InstalledPaperAccount, account: PaperServiceAccount) -> None:
        """Bind the signed account client and its configuration."""
        self.installed, self.account = installed, account

    def opening(self, at: datetime) -> AccountObservation:
        """Observe the account flat with its declared opening cash."""
        return self.opening_of(self.account, at)

    @staticmethod
    def opening_of(account: PaperServiceAccount, at: datetime) -> AccountObservation:
        """Observe an account flat with its declared opening cash."""
        cash = account.configuration.accounts[0].cash[0]
        return AccountObservation(
            identity=f"{account.account_id}-opening-{uuid4().hex[:8]}",
            at=at,
            snapshot=AccountSnapshot(
                account_id=account.account_id,
                instance_id=None,
                cash=(cash,),
                positions=(),
                fees=(cash - cash,),
                rebates=(cash - cash,),
                transfers=(cash,),
                fill_ids=(),
                posting_ids=(f"opening:{cash.currency.code}",),
            ),
            open_orders=(),
        )

    def refuse_research_grant(
        self, grant: PaperAuthorization, research: tuple[str, ...]
    ) -> dict[str, object]:
        """Ask for a grant over the research selection; it must be refused unchanged."""
        before = self.installed.execute(AccountExecutionRequest(action="inspect"))
        quantities = tuple(
            Quantity(
                value=Decimal("1"),
                dimension=Dimension(
                    instrument_id=InstrumentId.from_canonical_text(instrument),
                    kind=QuantityKind.BASE_UNIT,
                ),
            )
            for instrument in research
        )
        refused, error = False, ""
        reasons = set(self.installed.requests.glob("*.stderr"))
        try:
            self.installed.execute(
                AccountExecutionRequest(
                    action="authorize_paper",
                    authorization=msgspec.structs.replace(grant, quantities=quantities),
                )
            )
        except RuntimeError:
            # The signed runner refuses with a non-zero exit and retains its reason.
            (retained,) = set(self.installed.requests.glob("*.stderr")) - reasons
            refused = True
            error = retained.read_text(encoding="utf-8").strip().splitlines()[-1]
        after = self.installed.execute(AccountExecutionRequest(action="inspect"))
        return {
            "refused": refused,
            "error": error,
            "unchanged": before.paper_activations == after.paper_activations,
        }

    def claim(
        self, deployment: PaperDeployment, authorization: PaperAuthorization, quote: Price
    ) -> PaperOwner:
        """Install the disabled deployment, authorize it and claim its owner."""
        deployment.require_configuration(self.account.configuration)
        deployment.require_authorization(authorization)
        retained = self.installed.execute(
            AccountExecutionRequest(action="install_paper", deployment=deployment)
        )
        if [item.deployment for item in retained.paper_activations] != [deployment]:
            raise ValueError("signed account did not retain the disabled deployment")
        self.installed.execute(
            AccountExecutionRequest(action="authorize_paper", authorization=authorization)
        )
        stopped = self.installed.accounts()[0]
        if stopped.phase != "stopped" or stopped.active_control_identity is None:
            raise ValueError("signed account did not retain its disabled stop")
        self.installed.observe(AccountQuote(price=quote, at=datetime.now(UTC)))
        if not self.installed.reconcile(self.opening(datetime.now(UTC))):
            raise ValueError("signed account opening reconciliation differed")
        claimed = self.installed.execute(
            AccountExecutionRequest(
                action="claim_paper",
                account_id=self.account.account_id,
                owner_id=f"{self.account.account_id}-owner-{uuid4().hex[:8]}",
                control=AccountControl(
                    identity=f"{self.account.account_id}-start-{uuid4().hex[:8]}",
                    account_id=self.account.account_id,
                    kind="restart",
                    at=datetime.now(UTC),
                    expected_control_identity=stopped.active_control_identity,
                ),
            )
        )
        if claimed.claimed_owner is None:
            raise ValueError("signed account did not claim an owner")
        return claimed.claimed_owner


class PaperObservation:
    """Observe an account independently from its settled ledger and open orders.

    Paper facts are the account's own settled ledger and open physical orders, read
    with the account's knowledge clock from one snapshot through the
    ``reconciliation`` projection. The observation is stamped at the later of that
    clock and the caller's instant (an accepted market, or a stopped account's
    present): the account already refuses any market before its own clock, so that
    clock never refuses a market still in flight.
    """

    def __init__(self, served: SocketPaperAccount | InstalledPaperAccount, account_id: str) -> None:
        """Bind the served account's owner-bound socket client."""
        self.installed, self.account_id = served, account_id

    def observe(self, at: datetime | None = None) -> AccountObservation:
        """Return a complete observation of the account at its knowledge clock or ``at``."""
        facts = self.installed.execute(
            AccountExecutionRequest(
                action="inspect", account_id=self.account_id, projection="reconciliation"
            )
        )
        if facts.known_at is None:
            raise ValueError("reconciliation projection omitted the account's knowledge clock")
        (account,) = facts.accounts
        return AccountObservation(
            identity=f"{self.account_id}-observed-{uuid4().hex}",
            at=facts.known_at if at is None else max(at, facts.known_at),
            snapshot=AccountLedger(account.ledger).snapshot(),
            open_orders=(
                *(item.order for item in facts.orders),
                *(item.order for item in facts.net_orders),
            ),
        )


class SourceMarkets(msgspec.Struct, frozen=True):
    """Read one source's per-account last applied markets from the supervisor status."""

    markets: tuple[PaperMarket | None, ...]


class SupervisorStatus(msgspec.Struct, frozen=True):
    """Read the supervisor status fields the recovery and checks need."""

    sources: dict[str, SourceMarkets]


class PhaseGate(msgspec.Struct, frozen=True):
    """One criterion, in the driver's gate shape."""

    name: str
    passed: bool
    observed: object


class PaperRecovery:
    """Settle and replace one account's owner after a phase, as the runbook's step 5.

    Under the retained owner it stops the account if still running and cancels its
    working orders, settles them against the source's last real market re-observed
    now, reconciles independently, then claims a fresh owner.
    """

    def __init__(self, installed: InstalledPaperAccount, account: PaperServiceAccount) -> None:
        """Bind the signed launcher client and the account."""
        self.installed, self.account = installed, account

    def recover(self, market: PaperMarket | None) -> tuple[PaperOwner, dict[str, object]]:
        """Return the fresh owner and what recovery observed and did."""
        account_id = self.account.account_id
        state = self.installed.execute(AccountExecutionRequest(action="inspect"))
        if len(state.paper_activations) != 1 or state.paper_activations[0].owner is None:
            raise ValueError("recovery requires one retained activation and its owner")
        activation = state.paper_activations[0]
        self.installed.paper_owner = activation.owner
        observed: dict[str, object] = {"account": account_id}
        if self.installed.accounts()[0].phase == "running":
            stop = self.installed.control(
                AccountControl(
                    identity=f"{account_id}-recovery-stop-{uuid4().hex[:8]}",
                    account_id=account_id,
                    kind="stop",
                    at=datetime.now(UTC),
                    reason="journey phase recovery",
                )
            )
            observed["stop"] = stop.status
        cancel = self.installed.control(
            AccountControl(
                identity=f"{account_id}-recovery-cancel-{uuid4().hex[:8]}",
                account_id=account_id,
                kind="cancel",
                at=datetime.now(UTC),
                reason="settle local paper obligations",
            )
        )
        observed["cancel"] = cancel.status
        if market is not None:
            settled = self.installed.match_public_market(
                account_id,
                msgspec.structs.replace(market, identity=uuid4().hex, at=datetime.now(UTC)),
                activation.deployment.scenario,
            )
            observed["settled"] = settled.status
        observation = PaperObservation(self.installed, account_id).observe(datetime.now(UTC))
        observed["reconciled"] = self.installed.reconcile(observation)
        observed["open_orders"] = len(observation.open_orders)
        if observed["reconciled"] is not True:
            raise ValueError(f"recovery reconciliation differed for {account_id}")
        if market is None:
            raise ValueError(f"recovery of {account_id} requires its source's last market")
        # A restart requires a quote after the stop's cutoff, as the first claim does.
        self.installed.observe(AccountQuote(price=market.ask, at=datetime.now(UTC)))
        stopped = self.installed.accounts()[0]
        claimed = self.installed.execute(
            AccountExecutionRequest(
                action="claim_paper",
                account_id=account_id,
                owner_id=f"{account_id}-owner-{uuid4().hex[:8]}",
                control=AccountControl(
                    identity=f"{account_id}-restart-{uuid4().hex[:8]}",
                    account_id=account_id,
                    kind="restart",
                    at=datetime.now(UTC),
                    expected_control_identity=stopped.active_control_identity,
                ),
            )
        )
        if claimed.claimed_owner is None:
            raise ValueError(f"recovery claimed no owner for {account_id}")
        return claimed.claimed_owner, observed


class DeliveryLogs:
    """Locate one account's retained delivery logs and the recordings they came from."""

    def __init__(
        self, root: Path, configuration: PaperServiceConfiguration, account_id: str
    ) -> None:
        """Bind the phase's single supervisor run and the account's source feeds."""
        runs = sorted(path for path in (root / "runs").iterdir() if path.is_dir())
        if len(runs) != 1:
            raise ValueError("a phase retains exactly one supervisor run")
        self.source = next(
            item
            for item in configuration.sources
            if any(
                instance.source == item.name and instance.account_id == account_id
                for instance in configuration.instances
            )
        )
        (book,) = CaptureRecording.discover(runs[0] / self.source.name)
        trades_root = runs[0] / f"{self.source.name}.trades"
        found = CaptureRecording.discover(trades_root) if trades_root.is_dir() else ()
        self.book, self.trades = book, (found[0] if found else None)
        self.book_log = runs[0] / self.source.name / f"{book.key}-{account_id}.jsonl"
        self.trades_log = self.book_log.with_name(self.book_log.stem + ".trades.jsonl")
        self.codec = DomainCodec()

    def books(self) -> tuple[SharedBookDelivery, ...]:
        """Decode the account's retained book deliveries in order."""
        return tuple(
            SharedBookDelivery.decode(line, self.codec)
            for line in self.book_log.read_bytes().splitlines()
        )

    def trades_deliveries(self) -> tuple[LiveBookDelivery, ...]:
        """Decode the account's retained trades deliveries in order."""
        if not self.trades_log.is_file():
            return ()
        return tuple(
            self.codec.decode_json(line, LiveBookDelivery)
            for line in self.trades_log.read_bytes().splitlines()
        )


class DeliveryReplay:
    """Replay one account's retained deliveries through a fresh observer, exactly.

    The observer is built as the supervisor builds it, with the same candidate
    bindings, and both logs are applied in delivery-time order (a trades boundary
    before a book delivered at the same instant). Replay recomputes every grid
    instant, decided input, served snapshot and coordination clock, and refuses any
    difference. Account effects go to a scratch journal.
    """

    def __init__(
        self, configuration: PaperServiceConfiguration, candidates: Path, scratch: Path
    ) -> None:
        """Bind the phase configuration, its signed candidates and a scratch directory."""
        self.configuration, self.scratch = configuration, scratch
        self.resolved = PaperServiceCandidates(configuration, candidates)
        serving = configuration.features
        self.features = (
            None
            if serving is None
            else ServedFeatures(
                VersionedFeatureStore(Path(serving.store_path)),
                bridge=FeastServingBridge(
                    FeastOfflineWorker(
                        serving.worker, timeout_seconds=serving.worker_timeout_seconds
                    )
                ),
                serving_root=Path(serving.serving_root),
            )
        )

    def replay(self, account: PaperServiceAccount, logs: DeliveryLogs) -> dict[str, object]:
        """Return how many deliveries replayed exactly, or where replay first differed."""
        source = logs.source
        journal = AccountJournal(
            self.scratch / f"{account.account_id}.sqlite3", account.configuration
        )
        journal.reconcile(PaperClaim.opening_of(account, account.configuration.opening_at))
        bindings = tuple(
            self.resolved.binding(item)
            for item in self.configuration.instances
            if item.account_id == account.account_id
        )
        trade_fields = self.resolved.feeds(source).trades
        observer = SharedPaperCaptureObserver(
            source=LiveBookDecisionSource(
                logs.book.request, self.resolved.book_requirements(source), history_capacity=1000
            ),
            books=BookRegistry(
                BookRegistryConfiguration(
                    selections=(
                        BookSelection.from_capture(
                            source.capture,
                            source_id=logs.book.request.identity,
                            capability=BookAdapters.capability(source.capture),
                            max_age_ns=source.freshness_us * 1000,
                            allow_degraded=True,
                        ),
                    ),
                    equivalences=(),
                    history_capacity=1000,
                )
            ),
            journal=journal,
            runtime=SharedDecisionRuntime(journal, bindings),
            account_id=account.account_id,
            scenario=source.scenario,
            delivery_path=None,
            trades=(
                None
                if logs.trades is None or not trade_fields
                else LiveTradeDecisionSource(
                    logs.trades.request,
                    trade_fields,
                    tapes=BookAdapters.trades,
                    history_capacity=1000,
                )
            ),
            features=self.features,
        )
        ordered = sorted(
            [
                (item.available_at, 0, index, item)
                for index, item in enumerate(logs.trades_deliveries())
            ]
            + [
                (item.source.available_at, 1, index, item)
                for index, item in enumerate(logs.books())
            ],
            key=self._order,
        )
        replayed, decided = 0, 0
        for _, kind, index, item in ordered:
            try:
                if isinstance(item, SharedBookDelivery):
                    observer.deliver(item)
                    decided += len(item.decisions)
                else:
                    observer.deliver_trades(item)
            except ValueError as error:
                return {
                    "replayed": replayed,
                    "decided_groups": decided,
                    "first_difference": {
                        "kind": "book" if kind else "trades",
                        "index": index,
                        "error": str(error),
                    },
                }
            replayed += 1
        return {"replayed": replayed, "decided_groups": decided, "first_difference": None}

    @staticmethod
    def _order(item: tuple[datetime, int, int, object]) -> tuple[datetime, int, int]:
        """Order deliveries by delivery clock, trades before books, then log order."""
        return item[0], item[1], item[2]


class RaceCheck:
    """Read the shared-budget race's batch outcomes from the account journal.

    Each decided group's batch identity is recomputed from the retained delivery as
    the observer computes it, and its outcome read through the signed launcher.
    """

    limit = Decimal("0.01")

    def __init__(self, installed: InstalledPaperAccount, logs: DeliveryLogs) -> None:
        """Bind the signed account client and its delivery logs."""
        self.installed, self.logs = installed, logs
        self.codec = DomainCodec()

    def assess(self, account_id: str, *, contenders: tuple[str, ...]) -> PhaseGate:
        """Pass when one contender met the shared limit because another held, and it held.

        Which contender acts first depends on the market, so either ordering is the race.
        A batch lists each contender its own admission refused at the limit in
        ``refused``; a batch-wide refusal at the limit counts every contender in it.
        Another contender holds when it has fills, or when its latest admitted decision
        reserved a working order: a resting order counts against the shared limit until
        it fills or its cancel completes. A refusal while every other contender is flat
        and unreserved is a contender's own limit, not the race. Groups are read in
        order until the race is seen.
        """
        fills = self.installed.execute(
            AccountExecutionRequest(action="inspect", account_id=account_id, projection="facts")
        ).paper_fills
        decided = self.installed.execute(
            AccountExecutionRequest(action="inspect", account_id=account_id, projection="decisions")
        ).decision_outcomes
        outcomes: list[dict[str, object]] = []
        race: dict[str, object] | None = None
        for delivery in self.logs.books():
            for group in delivery.decisions:
                if race is not None:
                    break
                identity = hashlib.sha256(
                    self.codec.encode_json((delivery.source, group))
                ).hexdigest()
                result = self.installed.execute(
                    AccountExecutionRequest(
                        action="inspect",
                        account_id=account_id,
                        projection="saved_batch",
                        query_batch=identity,
                    )
                ).portfolio
                instances = [item.instance_id for item in group.inputs]
                status = None if result is None else result.status
                reason = None if result is None else result.reason
                refusals = (
                    []
                    if result is None
                    else [
                        item.instance_id
                        for item in result.refused
                        if item.reason == "holding_limit"
                    ]
                    # A batch-wide refusal at the limit names no decision.
                    or (instances if (status, reason) == ("rejected", "holding_limit") else [])
                )
                outcomes.append(
                    {
                        "at": group.at,
                        "instances": instances,
                        "status": status,
                        "reason": reason,
                        "refused": refusals,
                    }
                )
                for refused in refusals:
                    if refused not in contenders:
                        continue
                    for other in contenders:
                        held = sum(
                            (
                                item.fill.quantity.value
                                for item in fills
                                if item.instance_id == other and item.fill.filled_at < group.at
                            ),
                            Decimal(0),
                        )
                        admitted = [
                            item
                            for item in decided
                            if item.instance_id == other
                            and item.status == "committed"
                            and item.decided_at < group.at
                        ]
                        reserved = bool(admitted) and admitted[-1].reason == "reserved"
                        if other != refused and (held != 0 or reserved) and race is None:
                            race = {
                                "at": group.at,
                                "refused": refused,
                                "held_by": other,
                                "held": held,
                                "reserved": reserved,
                            }
        ledger = AccountLedger(self.installed.accounts()[0].ledger).snapshot()
        positions = [abs(item.value) for item in ledger.positions]
        within = all(value <= self.limit for value in positions)
        return PhaseGate(
            "race_admitted_once_and_refused_once",
            race is not None and within,
            {
                "race": race,
                "positions": [str(value) for value in positions],
                "outcomes": outcomes[-8:],
            },
        )


class PhaseVerification:
    """Assess one phase from its retained monitoring, reconciliation and receiver evidence."""

    metric = f"{QR_PREFIX}.net-per-turnover"

    def __init__(
        self,
        configuration: PaperServiceConfiguration,
        plan: Path,
        root: Path,
        alerts: Path,
        *,
        race: InstalledPaperAccount | None = None,
    ) -> None:
        """Bind the phase's configuration, evidence locations and optional race account."""
        self.configuration, self.plan, self.root, self.alerts = configuration, plan, root, alerts
        self.race = race

    def gates(self) -> tuple[PhaseGate, ...]:
        """Return every criterion of the phase, in order."""
        accounts = tuple(item.account_id for item in self.configuration.accounts)
        rows = (
            tuple(
                msgspec.json.decode(line, type=dict[str, object])
                for line in (self.plan / "reconciliation.jsonl").read_bytes().splitlines()
            )
            if (self.plan / "reconciliation.jsonl").is_file()
            else ()
        )
        rounds = {name: sum(1 for row in rows if row["account"] == name) for name in accounts}
        gates = [
            PhaseGate(
                "reconciled_every_round",
                bool(rows)
                and all(row["matched"] is True for row in rows)
                and all(count >= 1 for count in rounds.values()),
                {
                    "rounds": rounds,
                    "mismatched": [row for row in rows if row["matched"] is not True],
                },
            )
        ]
        reports = {name: (self.root / "monitoring" / f"{name}.json").is_file() for name in accounts}
        gates.append(PhaseGate("reports_retained", all(reports.values()), reports))
        dashboards = {name: self.dashboard_shows_metric(name) for name in accounts}
        gates.append(
            PhaseGate("candidate_metric_on_dashboards", all(dashboards.values()), dashboards)
        )
        mode = self.configuration.accounts[0].configuration.mode
        if mode == "paper":
            # Whether one phase alerts depends on its market, so the count is observed
            # here and the driver requires an alert across the step's phases.
            received = self.alerts.read_bytes().count(b"\n") if self.alerts.is_file() else 0
            gates.append(PhaseGate("alerts_observed", True, {"datagrams": received}))
        else:
            fills = {name: self.fills(name) for name in accounts}
            gates.append(PhaseGate("shadow_zero_fills", all(n == 0 for n in fills.values()), fills))
        replay = DeliveryReplay(self.configuration, self.plan / "candidates", self.plan / "replay")
        (self.plan / "replay").mkdir(exist_ok=True)
        replayed = {
            item.account_id: replay.replay(
                item, DeliveryLogs(self.root, self.configuration, item.account_id)
            )
            for item in self.configuration.accounts
        }
        gates.append(
            PhaseGate(
                "delivery_logs_replay_exactly",
                all(value["first_difference"] is None for value in replayed.values()),
                replayed,
            )
        )
        if self.race is not None:
            gates.append(
                RaceCheck(
                    self.race, DeliveryLogs(self.root, self.configuration, "okx-shared")
                ).assess(
                    "okx-shared",
                    contenders=("rule-okx-btc", "learned-okx-btc", "reference-okx-btc"),
                )
            )
        return tuple(gates)

    def dashboard_shows_metric(self, account_id: str) -> bool:
        """Report whether any rendered page of the account carries the candidate metric."""
        pages = self.root / "monitoring" / "dashboards" / account_id
        return pages.is_dir() and any(
            self.metric.encode() in path.read_bytes() for path in pages.glob("*/snapshot.json")
        )

    def fills(self, account_id: str) -> int:
        """Count the account's retained paper fills."""
        snapshot = msgspec.json.decode(
            (self.root / "monitoring" / f"{account_id}.json").read_bytes(), type=dict[str, object]
        )
        account = snapshot.get("account")
        fills = account.get("paper_fills", ()) if isinstance(account, dict) else ()
        return len(fills) if isinstance(fills, list) else 0


class StandaloneAccount:
    """Inspect a restored account copy through the research environment's ``account`` command.

    A restored copy is not selected by any installed target, so the runbook's
    standalone interface reads it, with the account's signed configuration.
    """

    def __init__(self, configuration: Path, journal: Path, requests: Path) -> None:
        """Bind the account configuration, the restored journal and retained requests."""
        self.configuration, self.journal, self.requests = configuration, journal, requests
        self.codec = DomainCodec()

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Run one read request and return its typed result."""
        payload = self.codec.encode_json(request)
        self.requests.mkdir(parents=True, exist_ok=True)
        path = self.requests / f"{hashlib.sha256(payload).hexdigest()}.json"
        path.write_bytes(payload)
        completed = subprocess.run(  # nosec B603  # [owner=runtime; rationale=fixed standalone account command; expires=2027-03-01]
            (
                str(Path(sys.executable).parent / "alpha-execute"),
                "account",
                "--config",
                str(self.configuration),
                "--journal",
                str(self.journal),
                "--request",
                str(path),
            ),
            capture_output=True,
            check=False,
            timeout=60,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.decode(errors="replace").strip()[-400:])
        return self.codec.decode_json(completed.stdout, AccountExecutionResult)


class RetainedFacts(msgspec.Struct, frozen=True):
    """One journal's retained facts, with each instance's latest checkpoint digest."""

    accounts: tuple[AccountView, ...]
    orders: tuple[TaggedOrder, ...]
    net_orders: tuple[NetOrder, ...]
    controls: tuple[AccountControlResult, ...]
    stopped_instances: tuple[str, ...]
    fills: tuple[AccountPaperFill, ...]
    costs: tuple[AccountPaperCost, ...]
    checkpoints: dict[str, str | None]
    quarantined: bool

    def differing(self, other: RetainedFacts) -> tuple[str, ...]:
        """Name the facts that differ from ``other``, ignoring the quarantine mark."""
        pairs: tuple[tuple[str, object, object], ...] = (
            ("accounts", self.accounts, other.accounts),
            ("orders", self.orders, other.orders),
            ("net_orders", self.net_orders, other.net_orders),
            ("controls", self.controls, other.controls),
            ("stopped_instances", self.stopped_instances, other.stopped_instances),
            ("fills", self.fills, other.fills),
            ("costs", self.costs, other.costs),
            ("checkpoints", self.checkpoints, other.checkpoints),
        )
        return tuple(name for name, mine, theirs in pairs if mine != theirs)

    def appended(self, later: RetainedFacts) -> tuple[str, ...]:
        """Name the append-only histories ``later`` does not extend unchanged."""
        pairs: tuple[tuple[str, tuple[object, ...], tuple[object, ...]], ...] = (
            ("fills", self.fills, later.fills),
            ("costs", self.costs, later.costs),
            ("controls", self.controls, later.controls),
        )
        return tuple(name for name, mine, theirs in pairs if theirs[: len(mine)] != mine)


class ControlWindow(msgspec.Struct, frozen=True):
    """One supervisor control the journey sent during a phase, and when it ran."""

    label: str
    started_at: datetime
    ended_at: datetime


class ControlWindows(msgspec.Struct, frozen=True):
    """Every supervisor control the journey sent during its paper phases."""

    controls: tuple[ControlWindow, ...]


class RetainedJournals(msgspec.Struct, frozen=True):
    """Every paper journal's retained facts, by account."""

    accounts: dict[str, RetainedFacts]


class AccountFacts:
    """Read one journal's retained facts: views, orders, controls, fills and checkpoints."""

    def __init__(
        self, reader: InstalledPaperAccount | StandaloneAccount, account: PaperServiceAccount
    ) -> None:
        """Bind a reader of one account and its planned configuration."""
        self.reader, self.account = reader, account

    def read(self, instances: tuple[str, ...]) -> RetainedFacts:
        """Return the account's facts read through its reader."""
        full = self.reader.execute(AccountExecutionRequest(action="inspect"))
        facts = self.reader.execute(
            AccountExecutionRequest(
                action="inspect", account_id=self.account.account_id, projection="facts"
            )
        )
        checkpoints: dict[str, str | None] = {}
        for instance in instances:
            saved = self.reader.execute(
                AccountExecutionRequest(
                    action="inspect", projection="checkpoint", query_instance=instance
                )
            ).checkpoint
            checkpoints[instance] = None if saved is None else hashlib.sha256(saved).hexdigest()
        return RetainedFacts(
            accounts=full.accounts,
            orders=full.orders,
            net_orders=full.net_orders,
            controls=full.controls,
            stopped_instances=full.stopped_instances,
            fills=facts.paper_fills,
            costs=facts.paper_costs,
            checkpoints=checkpoints,
            quarantined=full.paper_restore_quarantined,
        )


class BackupRecord(msgspec.Struct, frozen=True):
    """Read the paper backup's manifest digest and each account's recovery receipt."""

    paper: str
    accounts: dict[str, AccountRecoveryReceipt]


class Quiescence:
    """Check that no supervisor, publisher, scheduler or account owner holds its fence."""

    @staticmethod
    def held(path: Path) -> bool:
        """Report whether another process holds the advisory lock at ``path``."""
        if not path.exists():
            return False
        with path.open("a+b") as fence:
            try:
                fcntl.flock(fence.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(fence.fileno(), fcntl.LOCK_UN)
        return False

    @classmethod
    def fences(
        cls, configuration: PaperServiceConfiguration, plan: Path, targets: Path
    ) -> tuple[Path, ...]:
        """Return every fence a running J6 or J7 process would hold."""
        paths = [*sorted(plan.glob("service-*/supervisor.lock"))]
        if configuration.features is not None:
            paths.append(Path(configuration.features.serving_root) / "publisher.lock")
        for account in configuration.accounts:
            socket = Path(account.socket_path)
            paths.append(socket.with_suffix(".scheduler.lock"))
            paths.append(socket.parent / "supervisor.endpoint.lock")
            paths.append(targets / account.account_id / "state/accounts.sqlite3.service.lock")
        return tuple(sorted(set(paths)))


class EntryDelays:
    """Compare every paper decision delay with its study's modelled entry delay.

    A decision's delay is its coordination clock less its grid instant, as the
    delivery logs retain both. A study's modelled delay is read from its retained
    orders (placement less decision), so it is the delay research actually applied.
    """

    def __init__(self, configuration: PaperServiceConfiguration, plan: Path) -> None:
        """Bind the configuration and the packaged families' identities."""
        self.configuration = configuration
        identities = msgspec.json.decode(
            (plan / "candidates.json").read_bytes(), type=dict[str, str]
        )
        self.families = {identity: family for family, identity in identities.items()}
        self.codec = DomainCodec()

    def family(self, instance: PaperServiceInstance) -> str | None:
        """Name the QR family an instance runs, or None for a platform reference."""
        if not isinstance(instance.candidate, PackagedCandidate):
            return None
        return self.families[instance.candidate.definition_sha256]

    def modelled(self, attempts: Path) -> dict[str, list[int]]:
        """Return each family's distinct modelled entry delays, in microseconds."""
        delays: dict[str, set[int]] = {}
        with AttemptStore(attempts) as store:
            for history in store.histories():
                if history.status != "completed":
                    continue
                family = self.codec.decode_json(history.start.request, DecisionStudy).family
                attempt = history.start.attempt_id
                if "study-result" not in store.artifacts(attempt):
                    continue
                result = StudyResult.read(store, attempt)
                retained = msgspec.json.decode(self.codec.encode_json(result), type=object)
                for order in self.orders(retained):
                    placed = datetime.fromisoformat(order["placed_at"])
                    decided = datetime.fromisoformat(order["decision_at"])
                    delays.setdefault(family, set()).add(
                        (placed - decided) // timedelta(microseconds=1)
                    )
        return {family: sorted(values) for family, values in delays.items()}

    @classmethod
    def orders(cls, value: object) -> list[dict[str, str]]:
        """Collect every retained simulated order, wherever the result nests it."""
        if isinstance(value, dict):
            placed, decided = value.get("placed_at"), value.get("decision_at")
            if isinstance(placed, str) and isinstance(decided, str):
                return [{"placed_at": placed, "decision_at": decided}]
            return [item for child in value.values() for item in cls.orders(child)]
        if isinstance(value, list):
            return [item for child in value for item in cls.orders(child)]
        return []

    def observed(self, roots: tuple[Path, ...]) -> dict[str, list[int]]:
        """Return every decided input's delay per instance over the given phase roots."""
        delays: dict[str, list[int]] = {}
        for root in roots:
            for account in self.configuration.accounts:
                logs = DeliveryLogs(root, self.configuration, account.account_id)
                for delivery in logs.books():
                    for group in delivery.decisions:
                        delay = (group.coordinated_at - group.at) // timedelta(microseconds=1)
                        for item in group.inputs:
                            delays.setdefault(item.instance_id, []).append(delay)
        return delays

    def gates(self, attempts: Path, roots: tuple[Path, ...]) -> tuple[PhaseGate, dict[str, object]]:
        """Pass when each candidate's every delay is at most its study's single modelled delay."""
        modelled = self.modelled(attempts)
        observed = self.observed(roots)
        table: dict[str, object] = {}
        failed: list[str] = []
        for instance in self.configuration.instances:
            values = sorted(observed.get(instance.instance_id, ()))
            family = self.family(instance)
            bound = modelled.get(family, []) if family is not None else []
            row: dict[str, object] = {
                "family": family,
                "modelled_us": bound,
                "decisions": len(values),
            }
            if values:
                row.update(
                    p50_us=values[len(values) // 2],
                    p90_us=values[int(len(values) * 0.9)],
                    p99_us=values[min(len(values) - 1, int(len(values) * 0.99))],
                    max_us=values[-1],
                )
            table[instance.instance_id] = row
            if family is not None and (len(bound) != 1 or (values and values[-1] > bound[0])):
                failed.append(instance.instance_id)
        return (
            PhaseGate("decision_delay_within_modelled_entry_delay", not failed, {"failed": failed}),
            table,
        )


class JourneyPaper:
    """Dispatch one operator step and write its typed outputs."""

    def __init__(self, arguments: JourneyPaperArguments) -> None:
        """Bind the parsed arguments."""
        self.arguments = arguments
        self.codec = DomainCodec()

    def write(self, path: Path, value: object) -> None:
        """Write one typed value as canonical JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.codec.encode_json(value))

    def configuration(self) -> PaperServiceConfiguration:
        """Read the planned services configuration."""
        return self.codec.decode_json(
            (self.arguments.plan / "services.json").read_bytes(), PaperServiceConfiguration
        )

    def installed(self, account: PaperServiceAccount) -> InstalledPaperAccount:
        """Bind one account's signed launcher client."""
        return InstalledPaperAccount(
            config=account.configuration,
            launcher=self.arguments.launcher,
            target=self.arguments.targets / account.account_id,
            policy=self.arguments.policy,
            requests=self.arguments.plan / "requests" / account.account_id,
        )

    def served(self, account: PaperServiceAccount) -> SocketPaperAccount:
        """Bind a served account's socket client under its claimed owner.

        While an account is served its owner holds the installation fence, so
        operations go through its socket, not the launcher.
        """
        return SocketPaperAccount(
            config=account.configuration,
            socket_path=Path(account.socket_path),
            requests=self.arguments.plan / "requests" / f"{account.account_id}-served",
            paper_owner=self.codec.decode_json(
                (self.arguments.plan / f"owner-{account.account_id}.json").read_bytes(), PaperOwner
            ),
        )

    def account(self, account_id: str) -> PaperServiceAccount:
        """Return one planned account."""
        return next(item for item in self.configuration().accounts if item.account_id == account_id)

    def plan(self) -> None:
        """Author the services configuration, account configurations and release candidates."""
        arguments = self.arguments
        plan = PaperPlan(
            arguments.qr,
            arguments.candidates,
            mode=arguments.mode,
            opening=datetime.now(UTC) - timedelta(minutes=1),
        )
        identities = plan.bundles(arguments.plan / "candidates")
        origin = datetime.now(UTC).replace(second=0, microsecond=0)
        configuration = plan.configuration(
            identities,
            sockets=arguments.sockets,
            store=arguments.store,
            serving_root=arguments.serving_root,
            worker=arguments.worker,
            alert_socket=arguments.alert_socket,
            duration_seconds=arguments.duration,
            origin=origin,
        )
        self.write(arguments.plan / "services.json", configuration)
        for account in configuration.accounts:
            self.write(arguments.plan / f"account-{account.account_id}.json", account.configuration)
        self.write(arguments.plan / "candidates.json", identities)

    def claim(self) -> None:
        """Author an account's deployment and grant, install them and claim its owner."""
        arguments = self.arguments
        account = self.account(arguments.account)
        receipt = msgspec.json.decode(
            (arguments.targets / account.account_id / "current.json").read_bytes(),
            type=dict[str, object],
        )
        release = receipt["release"]
        if not isinstance(release, str):
            raise ValueError("installed account target names no release")
        authority = PaperAuthority(
            self.configuration(),
            self.codec.decode_json(
                (arguments.plan / "deployment-check.json").read_bytes(), DeploymentCheck
            ),
        )
        deployment = authority.deployment(account, (release,))
        authorization = authority.authorization(deployment, datetime.now(UTC))
        self.write(arguments.plan / f"deployment-{account.account_id}.json", deployment)
        self.write(arguments.plan / f"authorization-{account.account_id}.json", authorization)
        claim = PaperClaim(self.installed(account), account)
        result: dict[str, object] = {"account": account.account_id}
        if arguments.research:
            result["research_grant"] = claim.refuse_research_grant(
                authorization, tuple(arguments.research.split(","))
            )
        quote = Price(
            value=Decimal(arguments.quote),
            currency=deployment.scenario.adverse.currency,
            per=deployment.scenario.adverse.per,
        )
        owner = claim.claim(deployment, authorization, quote)
        self.write(arguments.plan / f"owner-{account.account_id}.json", owner)
        result["owner"] = owner.owner_id
        print(self.codec.encode_json(result).decode())

    def owners(self) -> None:
        """Collect the claimed owners into the supervisor's owners file."""
        configuration = self.configuration()
        owners = tuple(
            self.codec.decode_json(
                (self.arguments.plan / f"owner-{item.account_id}.json").read_bytes(), PaperOwner
            )
            for item in configuration.accounts
        )
        self.write(self.arguments.plan / "owners.json", PaperServiceOwners(owners=owners))

    def accepted_market(self, account_id: str) -> datetime | None:
        """Return the account's last accepted market instant from the supervisor status.

        Markets reach an account in order, so a stamp at it refuses no market still in
        flight; with the account's knowledge clock it keeps a quiet account fresh.
        """
        status_path = self.arguments.root / "status.json"
        if not status_path.is_file():
            return None
        source = next(
            item.source for item in self.configuration().instances if item.account_id == account_id
        )
        status = self.codec.decode_json(status_path.read_bytes(), SupervisorStatus)
        markets = status.sources.get(source, SourceMarkets(markets=())).markets
        known = tuple(item.at for item in markets if item is not None)
        return max(known) if known else None

    def observation(self) -> None:
        """Write a restart control carrying a fresh independent observation."""
        arguments = self.arguments
        account = self.account(arguments.account)
        observed = PaperObservation(self.served(account), account.account_id).observe(
            self.accepted_market(account.account_id)
        )
        self.write(
            arguments.output,
            {
                "action": "restart_instance",
                "identity": f"restart-{uuid4().hex[:12]}",
                "subject": arguments.instance,
                "observation": observed,
            },
        )

    def serve_requests(self) -> None:
        """Write each account's typed serve request under its claimed owner."""
        for account in self.configuration().accounts:
            owner = self.codec.decode_json(
                (self.arguments.plan / f"owner-{account.account_id}.json").read_bytes(), PaperOwner
            )
            self.write(
                self.arguments.plan / f"serve-{account.account_id}.json",
                AccountExecutionRequest(
                    action="serve_paper",
                    paper_owner=owner,
                    service_socket=account.socket_path,
                    service_seconds=self.arguments.seconds,
                ),
            )

    def reclaim(self) -> None:
        """Recover one account after a phase and write its fresh owner."""
        arguments = self.arguments
        account = self.account(arguments.account)
        configuration = self.configuration()
        market: PaperMarket | None = None
        status_path = arguments.root / "status.json"
        if status_path.is_file():
            source = next(
                item.source
                for item in configuration.instances
                if item.account_id == account.account_id
            )
            status = self.codec.decode_json(status_path.read_bytes(), SupervisorStatus)
            known = tuple(
                item
                for item in status.sources.get(source, SourceMarkets(markets=())).markets
                if item is not None
            )
            market = known[-1] if known else None
        owner, observed = PaperRecovery(self.installed(account), account).recover(market)
        self.write(arguments.plan / f"owner-{account.account_id}.json", owner)
        print(self.codec.encode_json(observed).decode())

    def verify(self) -> None:
        """Print the phase's gates."""
        arguments = self.arguments
        race = None
        if arguments.race:
            race = self.installed(self.account("okx-shared"))
        verification = PhaseVerification(
            self.configuration(), arguments.plan, arguments.root, arguments.alerts, race=race
        )
        print(self.codec.encode_json(verification.gates()).decode())

    def reconcile(self) -> None:
        """Reconcile every account each period until the stop file appears; stop at a mismatch."""
        arguments = self.arguments
        configuration = self.configuration()
        clients = {account.account_id: self.served(account) for account in configuration.accounts}
        log = arguments.plan / "reconciliation.jsonl"
        while not arguments.stop.exists():
            time.sleep(arguments.period)
            if arguments.stop.exists():
                break
            for account_id, installed in sorted(clients.items()):
                # A decision landing between the read and the reconcile makes the
                # observation stale; the account refuses it unrecorded, so re-observe.
                for attempt in range(3):
                    observed = PaperObservation(installed, account_id).observe(
                        self.accepted_market(account_id)
                    )
                    try:
                        matched = installed.reconcile(observed)
                        break
                    except RuntimeError as error:
                        if "observation_precedes_account_state" not in str(error) or attempt == 2:
                            raise
                with log.open("ab") as stream:
                    stream.write(
                        self.codec.encode_json(
                            {
                                "account": account_id,
                                "identity": observed.identity,
                                "at": observed.at,
                                "matched": matched,
                                "open_orders": len(observed.open_orders),
                            }
                        )
                        + b"\n"
                    )
                if not matched:
                    raise SystemExit(f"reconciliation mismatch on {account_id}")

    def print_gates(self, gates: list[PhaseGate]) -> None:
        """Print criteria in the driver's gate shape."""
        print(self.codec.encode_json(tuple(gates)).decode())

    def instances(self, account_id: str) -> tuple[str, ...]:
        """Return an account's planned instances."""
        return tuple(
            item.instance_id
            for item in self.configuration().instances
            if item.account_id == account_id
        )

    def quiesce(self) -> None:
        """J7: refuse while any fence is held, and stop every paper account still running."""
        arguments = self.arguments
        configuration = self.configuration()
        fences = Quiescence.fences(configuration, arguments.plan, arguments.targets)
        held = [str(path) for path in fences if Quiescence.held(path)]
        gates = [
            PhaseGate("nothing_running", not held, {"held": held, "fences": len(fences)}),
        ]
        phases: dict[str, dict[str, object]] = {}
        for account in configuration.accounts:
            installed = self.installed(account)
            before = installed.accounts()[0].phase
            observed: dict[str, object] = {"before": before}
            if before == "running":
                state = installed.execute(AccountExecutionRequest(action="inspect"))
                installed.paper_owner = state.paper_activations[0].owner
                stop = installed.control(
                    AccountControl(
                        identity=f"{account.account_id}-j7-stop-{uuid4().hex[:8]}",
                        account_id=account.account_id,
                        kind="stop",
                        at=datetime.now(UTC),
                        reason="J7 quiesced backup",
                    )
                )
                observed["stop"] = stop.status
            observed["phase"] = installed.accounts()[0].phase
            phases[account.account_id] = observed
        gates.append(
            PhaseGate(
                "paper_accounts_stopped",
                all(item["phase"] in ("stopped", "faulted") for item in phases.values()),
                phases,
            )
        )
        self.print_gates(gates)

    def backup(self) -> None:
        """J7: back up the paper services' components and every stopped paper account."""
        arguments = self.arguments
        backup = arguments.backup
        paper = WorkspaceBackup.create(
            arguments.plan, backup / "paper", components=PAPER_COMPONENTS
        )
        (backup / "accounts").mkdir()
        receipts: dict[str, AccountRecoveryReceipt] = {}
        for account in self.configuration().accounts:
            result = self.installed(account).execute(
                AccountExecutionRequest(
                    action="backup", backup_root=str(backup / "accounts" / account.account_id)
                )
            )
            if result.recovery is None:
                raise ValueError(f"account backup of {account.account_id} returned no receipt")
            receipts[account.account_id] = result.recovery
        self.write(arguments.record, {"paper": paper, "accounts": receipts})

    def restore(self) -> None:
        """J7: restore the paper components and accounts and check each restored copy."""
        arguments = self.arguments
        configuration = self.configuration()
        record = self.codec.decode_json(arguments.record.read_bytes(), BackupRecord)
        restored = arguments.restored / "paper"
        manifest = WorkspaceBackup.restore(arguments.backup / "paper", restored)
        digest = hashlib.sha256((arguments.backup / "paper/manifest.json").read_bytes()).hexdigest()
        gates = [
            PhaseGate(
                "paper_manifest_equal",
                manifest == WorkspaceBackup.verify(arguments.backup / "paper")
                and digest == record.paper,
                {"manifest_sha256": digest, "files": len(manifest.files)},
            )
        ]
        # The restored store must serve every J6 snapshot exactly: replay J6's
        # retained deliveries from the restored roots against it.
        if configuration.features is None:
            raise ValueError("paper services serve no features")
        features = msgspec.structs.replace(
            configuration.features,
            store_path=str(restored / "features/store.sqlite3"),
            serving_root=str(restored / "features/feast"),
        )
        reopened = msgspec.structs.replace(configuration, features=features)
        replayed: dict[str, dict[str, object]] = {}
        for root in (name for name in PAPER_COMPONENTS if name.startswith("service-")):
            # Each phase replays into its own scratch journals.
            scratch = arguments.restored / "replay" / root
            scratch.mkdir(parents=True)
            replay = DeliveryReplay(reopened, restored / "candidates", scratch)
            for item in reopened.accounts:
                replayed[f"{root}/{item.account_id}"] = replay.replay(
                    item, DeliveryLogs(restored / root, reopened, item.account_id)
                )
        gates.append(
            PhaseGate(
                "restored_store_serves_equal_values",
                all(value["first_difference"] is None for value in replayed.values()),
                replayed,
            )
        )
        (arguments.restored / "accounts").mkdir()
        accounts: dict[str, object] = {}
        for account in configuration.accounts:
            installed = self.installed(account)
            backed = record.accounts[account.account_id]
            target = arguments.restored / "accounts" / account.account_id
            result = installed.execute(
                AccountExecutionRequest(
                    action="restore",
                    backup_root=str(arguments.backup / "accounts" / account.account_id),
                    restore_root=str(target),
                    manifest_sha256=backed.manifest_sha256,
                )
            )
            if result.journal_path is None:
                raise ValueError(f"account restore of {account.account_id} named no journal")
            copy = StandaloneAccount(
                arguments.plan / f"account-{account.account_id}.json",
                Path(result.journal_path),
                arguments.plan / "requests" / f"{account.account_id}-restored",
            )
            instances = self.instances(account.account_id)
            retained = AccountFacts(installed, account).read(instances)
            reopened_facts = AccountFacts(copy, account).read(instances)
            accounts[account.account_id] = {
                "receipt_equal": result.recovery == backed,
                "differing": reopened_facts.differing(retained),
                "quarantined": reopened_facts.quarantined,
                "retained_quarantined": retained.quarantined,
            }
        gates.append(
            PhaseGate(
                "restored_accounts_equal_and_quarantined",
                all(
                    item["receipt_equal"] is True
                    and not item["differing"]
                    and item["quarantined"] is True
                    and item["retained_quarantined"] is False
                    for item in accounts.values()
                    if isinstance(item, dict)
                ),
                accounts,
            )
        )
        self.print_gates(gates)

    def upgrade(self) -> None:
        """J7: author services v2, revision 2 with the inactive instance active."""
        configuration = self.configuration()
        if self.arguments.instance in configuration.active:
            raise ValueError("the upgrade instance is already active")
        active: tuple[str, ...] = (*configuration.active, self.arguments.instance)
        self.write(
            self.arguments.output,
            msgspec.structs.replace(
                configuration,
                revision=configuration.revision + 1,
                previous_sha256=configuration.identity,
                active=active,
            ),
        )

    def facts(self) -> None:
        """J7: retain every paper journal's facts."""
        self.write(
            self.arguments.output,
            RetainedJournals(
                accounts={
                    account.account_id: AccountFacts(self.installed(account), account).read(
                        self.instances(account.account_id)
                    )
                    for account in self.configuration().accounts
                }
            ),
        )

    def late(self) -> None:
        """J7: the activated instance decided during phase U."""
        arguments = self.arguments
        account = next(
            item.account_id
            for item in self.configuration().instances
            if item.instance_id == arguments.instance
        )
        upgraded = self.codec.decode_json(
            arguments.services.read_bytes(), PaperServiceConfiguration
        )
        decided = sum(
            any(item.instance_id == arguments.instance for item in group.inputs)
            for delivery in DeliveryLogs(arguments.root, upgraded, account).books()
            for group in delivery.decisions
        )
        fills = [
            item
            for item in self.installed(self.account(account))
            .execute(
                AccountExecutionRequest(action="inspect", account_id=account, projection="facts")
            )
            .paper_fills
            if item.instance_id == arguments.instance
        ]
        # Whether it also trades depends on the market and on the shared limit the race
        # exhausts, so its fills are retained, not required.
        self.print_gates(
            [
                PhaseGate(
                    "late_instance_decided", decided > 0, {"groups": decided, "fills": len(fills)}
                )
            ]
        )

    def rollback_check(self) -> None:
        """J7: after the rollback, journals keep their facts and the store its v2 snapshots."""
        arguments = self.arguments
        before, after = (
            self.codec.decode_json(path.read_bytes(), RetainedJournals).accounts
            for path in (arguments.before, arguments.after)
        )
        lost: dict[str, list[str]] = {}
        for account_id, earlier in before.items():
            later = after[account_id]
            lost[account_id] = list(earlier.appended(later))
            current = {item.order.identity: item for item in later.orders}
            if any(
                current.get(item.order.identity) != item
                for item in earlier.orders
                if item.order.is_terminal
            ):
                lost[account_id].append("terminal_orders")
        gates = [PhaseGate("rollback_keeps_retained_facts", not any(lost.values()), lost)]
        late = arguments.instance
        account = next(
            item.account_id for item in self.configuration().instances if item.instance_id == late
        )
        orders = [
            sorted(
                item.order.identity for item in facts[account].orders if item.instance_id == late
            )
            for facts in (before, after)
        ]
        fills = [
            sum(1 for item in facts[account].fills if item.instance_id == late)
            for facts in (before, after)
        ]
        held = before[account].checkpoints[late] == after[account].checkpoints[late]
        gates.append(
            PhaseGate(
                "late_instance_held_and_placed_nothing",
                held and orders[0] == orders[1] and fills[0] == fills[1],
                {
                    "checkpoint_unchanged": held,
                    "orders": [len(item) for item in orders],
                    "fills": fills,
                },
            )
        )
        # The store still serves every snapshot published under v2: U replays exactly.
        upgraded = self.codec.decode_json(
            arguments.services.read_bytes(), PaperServiceConfiguration
        )
        scratch = arguments.plan / "replay-u"
        scratch.mkdir(exist_ok=True)
        replay = DeliveryReplay(upgraded, arguments.plan / "candidates", scratch)
        replayed = {
            item.account_id: replay.replay(
                item, DeliveryLogs(arguments.root, upgraded, item.account_id)
            )
            for item in upgraded.accounts
        }
        gates.append(
            PhaseGate(
                "store_keeps_upgraded_snapshots",
                all(value["first_difference"] is None for value in replayed.values()),
                replayed,
            )
        )
        self.print_gates(gates)

    def refusals(self) -> None:
        """J7: every paper refusal and dropped leg carries a declared paper-only reason.

        Paper enforces budgets research does not model, so a budget-bound
        decision research admits may be refused here, but for no other reason.
        """
        # An operator control stamps the account's clock while it runs, so a decision
        # whose instant falls inside one is refused as stale: attributed, not unexplained.
        windows = tuple(
            (item.started_at, item.ended_at)
            for item in self.codec.decode_json(
                self.arguments.controls.read_bytes(), ControlWindows
            ).controls
        )
        counts: dict[str, dict[str, int]] = {}
        other: list[dict[str, object]] = []
        for account in self.configuration().accounts:
            outcomes = (
                self.installed(account)
                .execute(
                    AccountExecutionRequest(
                        action="inspect", account_id=account.account_id, projection="decisions"
                    )
                )
                .decision_outcomes
            )
            for outcome in outcomes:
                reasons = ((outcome.reason,) if outcome.status == "rejected" else ()) + tuple(
                    leg.reason for leg in outcome.dropped
                )
                for reason in reasons:
                    tally = counts.setdefault(outcome.instance_id, {})
                    tally[reason] = tally.get(reason, 0) + 1
                    attributed = reason == "decision_precedes_account_state" and any(
                        start <= outcome.decided_at <= end for start, end in windows
                    )
                    if reason not in PAPER_ONLY_REASONS and not attributed:
                        other.append(
                            {
                                "instance": outcome.instance_id,
                                "at": outcome.decided_at,
                                "reason": reason,
                            }
                        )
        self.write(self.arguments.output, counts)
        self.print_gates(
            [
                PhaseGate(
                    "refusals_carry_paper_only_reasons",
                    not other,
                    {"other": other[:20], "counts": counts},
                )
            ]
        )

    def delays(self) -> None:
        """J7: every paper decision delay is within its study's modelled entry delay."""
        arguments = self.arguments
        gate, table = EntryDelays(self.configuration(), arguments.plan).gates(
            arguments.attempts, tuple(Path(item) for item in arguments.roots.split(","))
        )
        self.write(arguments.output, table)
        self.print_gates([gate])


class JourneyPaperArguments(argparse.Namespace):
    """Carry one operator step's typed arguments."""

    step: str
    plan: Path
    mode: Mode
    qr: Path
    candidates: Path
    sockets: Path
    store: Path
    serving_root: Path
    worker: Path
    alert_socket: Path
    duration: int
    launcher: Path
    targets: Path
    policy: Path
    account: str
    quote: str
    research: str
    instance: str
    output: Path
    period: float
    stop: Path
    seconds: int
    root: Path
    alerts: Path
    race: bool
    backup: Path
    record: Path
    restored: Path
    services: Path
    before: Path
    after: Path
    attempts: Path
    roots: str
    controls: Path


class JourneyPaperParser:
    """Parse an operator step's command line into typed arguments."""

    steps: ClassVar[tuple[str, ...]] = (
        "plan",
        "claim",
        "owners",
        "observation",
        "reconcile",
        "serve-requests",
        "reclaim",
        "verify",
        "quiesce",
        "backup",
        "restore",
        "upgrade",
        "facts",
        "late",
        "rollback-check",
        "delays",
        "refusals",
    )

    @classmethod
    def parse(cls, argv: list[str]) -> JourneyPaperArguments:
        """Return the parsed step and its paths."""
        parser = argparse.ArgumentParser(description=__doc__)
        steps = parser.add_subparsers(dest="step", required=True)
        named = {name: steps.add_parser(name) for name in cls.steps}
        for step in named.values():
            step.add_argument("--plan", type=Path, required=True)
            step.add_argument("--mode", choices=("paper", "shadow"), default="paper")
        for name in (
            "qr",
            "candidates",
            "sockets",
            "store",
            "serving-root",
            "worker",
            "alert-socket",
        ):
            named["plan"].add_argument(f"--{name}", type=Path, required=True)
        named["plan"].add_argument("--duration", type=int, required=True)
        for command in (
            "claim",
            "reclaim",
            "quiesce",
            "backup",
            "restore",
            "facts",
            "late",
            "refusals",
        ):
            for name in ("launcher", "targets", "policy"):
                named[command].add_argument(f"--{name}", type=Path, required=True)
        for command in ("backup", "restore"):
            for name in ("backup", "record"):
                named[command].add_argument(f"--{name}", type=Path, required=True)
        named["restore"].add_argument("--restored", type=Path, required=True)
        for command in ("upgrade", "late", "rollback-check"):
            named[command].add_argument("--instance", required=True)
        for command in ("upgrade", "facts", "delays", "refusals"):
            named[command].add_argument("--output", type=Path, required=True)
        for command in ("late", "rollback-check"):
            named[command].add_argument("--root", type=Path, required=True)
            named[command].add_argument("--services", type=Path, required=True)
        for name in ("before", "after"):
            named["rollback-check"].add_argument(f"--{name}", type=Path, required=True)
        named["delays"].add_argument("--attempts", type=Path, required=True)
        named["refusals"].add_argument("--controls", type=Path, required=True)
        named["delays"].add_argument("--roots", required=True)
        named["reclaim"].add_argument("--account", required=True)
        named["reclaim"].add_argument("--root", type=Path, required=True)
        named["serve-requests"].add_argument("--seconds", type=int, required=True)
        named["verify"].add_argument("--root", type=Path, required=True)
        named["verify"].add_argument("--alerts", type=Path, required=True)
        named["verify"].add_argument("--race", action="store_true")
        for name in ("launcher", "targets", "policy"):
            named["verify"].add_argument(f"--{name}", type=Path, required=True)
        named["claim"].add_argument("--account", required=True)
        named["claim"].add_argument("--quote", required=True)
        named["claim"].add_argument("--research", default="")
        named["observation"].add_argument("--account", required=True)
        named["observation"].add_argument("--root", type=Path, required=True)
        named["reconcile"].add_argument("--root", type=Path, required=True)
        named["observation"].add_argument("--instance", required=True)
        named["observation"].add_argument("--output", type=Path, required=True)
        named["reconcile"].add_argument("--period", type=float, default=60.0)
        named["reconcile"].add_argument("--stop", type=Path, required=True)
        return parser.parse_args(argv, namespace=JourneyPaperArguments())


def main() -> None:
    """Run one operator step."""
    arguments = JourneyPaperParser.parse(sys.argv[1:])
    journey = JourneyPaper(arguments)
    {
        "plan": journey.plan,
        "claim": journey.claim,
        "owners": journey.owners,
        "observation": journey.observation,
        "reconcile": journey.reconcile,
        "serve-requests": journey.serve_requests,
        "reclaim": journey.reclaim,
        "verify": journey.verify,
        "quiesce": journey.quiesce,
        "backup": journey.backup,
        "restore": journey.restore,
        "upgrade": journey.upgrade,
        "facts": journey.facts,
        "late": journey.late,
        "rollback-check": journey.rollback_check,
        "delays": journey.delays,
        "refusals": journey.refusals,
    }[arguments.step]()


if __name__ == "__main__":
    main()
