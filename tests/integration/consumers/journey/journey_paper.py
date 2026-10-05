"""J6 operator steps the journey driver delegates to the installed platform.

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
import hashlib
import shutil
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
    AccountExecutionRequest,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    InstalledPaperAccount,
    PaperMarket,
    PaperOwner,
    SocketPaperAccount,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from market_data.adapters.sources import BookAdapters
from market_data.books import BookRegistry
from market_data.storage import CaptureRecording
from reference_data.instruments import InstrumentId
from research.experiments import CandidateBundle
from research.features import FeastOfflineWorker, FeastServingBridge, VersionedFeatureStore
from research.observations import LiveBookDecisionSource, LiveTradeDecisionSource
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from runtime import (
    LiveBookDelivery,
    ServedFeatures,
    SharedBookDelivery,
    SharedDecisionRuntime,
    SharedPaperCaptureObserver,
)
from serialization import DomainCodec

Mode = Literal["paper", "shadow"]


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
                (f"rule-{market.name}", f"mr17-rule-{market.name}", origin, None),
                # Five seconds after the rule, so the pair decide in separate batches and
                # the learned target contends for the limit the rule's bid reserved.
                (
                    f"learned-{market.name}",
                    f"mr17-learned-{market.name}",
                    origin + timedelta(seconds=5),
                    "live",
                ),
            ]
            if self.mode == "paper" and account_id == "okx-shared":
                selected.append(
                    (
                        f"rule-{market.name}-late",
                        f"mr17-rule-{market.name}",
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
                            extension="mr17-extensions",
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
            self.codec.decode_json(line, SharedBookDelivery)
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
        """Pass when one contender met the shared limit because the other held, and it held.

        Which contender acts first depends on the market, so either ordering is the race;
        a refusal while the other contender is flat is a contender's own limit, not the
        race. Groups are read in order until the race is seen.
        """
        fills = self.installed.execute(
            AccountExecutionRequest(action="inspect", account_id=account_id, projection="facts")
        ).paper_fills
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
                outcomes.append(
                    {"at": group.at, "instances": instances, "status": status, "reason": reason}
                )
                if status != "rejected" or reason != "holding_limit":
                    continue
                for refused in instances:
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
                        if other != refused and held != 0 and race is None:
                            race = {
                                "at": group.at,
                                "refused": refused,
                                "held_by": other,
                                "held": held,
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

    metric = "mr17.net-per-turnover"

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
            received = self.alerts.read_bytes().count(b"\n") if self.alerts.is_file() else 0
            gates.append(PhaseGate("alert_received", received > 0, {"datagrams": received}))
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
                observed = PaperObservation(installed, account_id).observe(
                    self.accepted_market(account_id)
                )
                matched = installed.reconcile(observed)
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
        for command in ("claim", "reclaim"):
            for name in ("launcher", "targets", "policy"):
                named[command].add_argument(f"--{name}", type=Path, required=True)
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
    }[arguments.step]()


if __name__ == "__main__":
    main()
