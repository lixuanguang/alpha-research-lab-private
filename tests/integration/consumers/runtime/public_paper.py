"""Exercise installed native public-feed paper matching with exact retained evidence."""

from __future__ import annotations

# standard library imports
import argparse
import asyncio
import hashlib
import socket
import tempfile
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal
from uuid import uuid4

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
from accounting import (
    AccountLedger,
    AccountSnapshot,
)
from applications.paper import (
    PaperMonitoringInput,
    PaperMonitoringResult,
    render_paper_monitoring,
    run_live_shared_paper,
)
from configuration import (
    AccountConfiguration,
    BookRegistryConfiguration,
    CaptureConfig,
    OpeningAccount,
    PaperExecutionScenario,
)
from execution import (
    AccountJournal,
    AccountObservation,
    AccountPaperTrace,
    AccountQuote,
    OrderState,
    PaperMarket,
    PortfolioCommit,
)
from financial_units import (
    Currency,
    DecimalGrid,
    Dimension,
    ExactRatio,
    Money,
    Price,
    Quantity,
    QuantityKind,
)
from market_data.books import BookRegistry
from market_data.contracts import CaptureRequest, FeedSocket
from portfolio import PortfolioContext
from research.features import FeatureVector
from research.observations import (
    DecisionInputs,
    InputRequirement,
    LiveBookDecisionSource,
    NumericField,
)
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from runtime import (
    ImplementationIdentity,
    SharedBookDelivery,
    SharedDecisionRuntime,
    SharedPaperCaptureObserver,
    SharedStrategyBinding,
    SharedStrategyInput,
)
from serialization import DomainCodec
from strategies import DecisionContext, DecisionTransition, OrderIntent
from telemetry import DashboardSnapshot, MonitoringQuery, TelemetryStore


class FixedOpeningClip:
    """Buy one configured opening clip, then quote below the book without more executions."""

    def __init__(
        self,
        quantity: Quantity,
        currency: Currency,
        lot: Quantity,
        *,
        no_trade: bool,
        implementation: str,
    ) -> None:
        """Pin the engineering clip and explicit no-trade control."""
        self.quantity, self.currency, self.lot, self.no_trade = quantity, currency, lot, no_trade
        self.implementation = implementation

    @property
    def identity(self) -> str:
        """Bind complete policy parameters to its installed reference implementation."""
        return hashlib.sha256(
            DomainCodec().encode_json(
                (
                    self.implementation,
                    type(self).__name__,
                    self.quantity,
                    self.currency,
                    self.lot,
                    self.no_trade,
                )
            )
        ).hexdigest()

    @property
    def output(self) -> Literal["order"]:
        """Declare portable order intents, independently admitted by the account."""
        return "order"

    def admit(self, fields: tuple[NumericField, ...], prediction: NumericField | None) -> None:
        """Require exact public-book features without learned predictions."""
        if fields != PublicPaperWorkload.fields or prediction is not None:
            raise ValueError("reference clip requires the named book signature")

    def initial_state(self) -> bytes:
        """Start the independently checkpointed clip count."""
        return b"0"

    def validate_state(self, state: bytes) -> None:
        """Reject foreign or noncanonical counters."""
        if not state.isdigit() or str(int(state)).encode() != state:
            raise ValueError("invalid reference clip state")

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Take the opening book once; retain subsequent nonmarketable GTC interests."""
        ask, bid = context.features.values[:2]
        if ask is None or bid is None:
            raise ValueError("reference clip requires an eligible two-sided book")
        active = state == b"0" and not self.no_trade
        raw = (
            Fraction(int(ask.numerator), int(ask.denominator)) + Fraction(2)
            if active
            else Fraction(int(bid.numerator), int(bid.denominator)) - Fraction(1)
        )
        price = Price(
            value=DecimalGrid.exact_decimal(raw),
            currency=self.currency,
            per=self.quantity.dimension,
        )
        return DecisionTransition(
            intent=OrderIntent(
                side="buy", quantity=self.quantity, limit=price, time_in_force="gtc"
            ),
            state=str(int(state) + 1).encode(),
        )


class LiquidityOpeningClip(FixedOpeningClip):
    """Scale the opening clip down when visible liquidity is smaller than the fixed clip."""

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Use visible touch size as a separate engineering policy formula."""
        transition = super().decide(context, state)
        size = context.features.values[2]
        if size is None or Fraction(int(size.numerator), int(size.denominator)) <= 0:
            raise ValueError("liquidity clip requires positive visible size")
        visible = Fraction(int(size.numerator), int(size.denominator))
        lots = max(1, (visible / 2) // Fraction(self.lot.value))
        quantity = Quantity(
            value=DecimalGrid.exact_decimal(
                min(Fraction(self.quantity.value), lots * Fraction(self.lot.value))
            ),
            dimension=self.quantity.dimension,
        )
        if not isinstance(transition.intent, OrderIntent):
            raise ValueError("liquidity clip requires order intent")
        return replace(transition, intent=replace(transition.intent, quantity=quantity))


class ScriptedPublicFeed:
    """Provide finite native frames through the real capture/reconstruction boundary."""

    def __init__(self, frames: tuple[bytes, ...]) -> None:
        """Bind a deterministic native source script."""
        self.frames = iter(frames)

    async def open(self, timeout: float) -> FeedSocket:
        """Open the read-only scripted connection."""
        return self

    async def send(self, message: str) -> None:
        """Accept only public subscription/configuration traffic."""
        if "auth" in message or "order" in message:
            raise ValueError("private request reached public fixture")

    async def recv(self) -> bytes:
        """Allow the prior durable callback to finish before the next native update."""
        await asyncio.sleep(0.015)
        frame = next(self.frames, None)
        if frame is None:
            raise OSError("public fixture exhausted")
        return frame

    async def close(self) -> None:
        """Release a connection without external side effects."""

    def snapshot(self) -> bytes:
        """Refuse unused REST snapshot behavior for the selected WebSocket books."""
        raise ValueError("fixture has no REST snapshot")


class PublicPaperWorkload:
    """Compose independently funded reference policies, native sources and numerical checks."""

    fields = (
        NumericField(name="ask", units="quote/base"),
        NumericField(name="bid", units="quote/base"),
        NumericField(name="ask_size", units="base"),
    )

    def __init__(
        self,
        config: CaptureConfig,
        *,
        live: bool,
        no_trade: bool,
        adverse: str,
        reference_source: bytes,
        dedicated: bool = False,
    ) -> None:
        """Bind one venue and explicitly authored execution assumptions."""
        self.capture = config
        self.reference_source = reference_source
        self.reference_identity = hashlib.sha256(reference_source).hexdigest()
        self.live, self.no_trade = live, no_trade
        self.names = ("fixed",) if dedicated else ("fixed", "liquidity")
        self.codec = DomainCodec()
        self.currency = Currency.from_code(config.quote_currency)
        self.dimension = Dimension(instrument_id=config.instrument_id, kind=QuantityKind.BASE_UNIT)
        self.opened_at = datetime.now(UTC) - timedelta(seconds=1)
        self.scenario = PaperExecutionScenario(
            venue="okx" if config.venue == "okx" else "bitfinex",
            instrument_id=config.instrument_id,
            entry_delay_us=1000,
            cancel_delay_us=2000,
            adverse=self.price(adverse),
            fee_rate=Decimal("0.001"),
            take_fraction=Decimal("0.5"),
            gas_inapplicable_reason=(
                "Off-chain spot paper matching; no blockchain activity or transfers."
            ),
        )
        self.requirement = InputRequirement(
            name="book",
            family="book",
            field=NumericField(name="imbalance", units="dimensionless"),
            clock="receipt",
            max_age_us=5_000_000,
        )

    @property
    def identity(self) -> str:
        """Pin this pure book-feature binding separately from the selected policies."""
        return hashlib.sha256(
            self.codec.encode_json(
                ("public-paper-features-v1", self.fields, self.reference_identity)
            )
        ).hexdigest()

    def money(self, value: str) -> Money:
        """Construct independent quote-currency amounts."""
        return Money(
            value=DecimalGrid.exact_decimal(Fraction(Decimal(value))), currency=self.currency
        )

    def quantity(self, value: str) -> Quantity:
        """Construct exact configured base units."""
        return Quantity(
            value=DecimalGrid.exact_decimal(Fraction(Decimal(value))), dimension=self.dimension
        )

    def price(self, value: str) -> Price:
        """Construct exact configured quote per base prices."""
        return Price(
            value=DecimalGrid.exact_decimal(Fraction(Decimal(value))),
            currency=self.currency,
            per=self.dimension,
        )

    def account_config(self) -> AccountConfiguration:
        """Keep shared firm/account/instance admission active for the reference consumers."""
        return AccountConfiguration(
            mode="paper",
            opening_at=self.opened_at,
            accounts=(OpeningAccount(account_id="paper", cash=(self.money("100000"),)),),
            instruments=(
                SpotLimits(
                    maximum=self.quantity("1000"),
                    lot=self.quantity("0.00000001" if self.live else "1"),
                    tick=self.price("0.01"),
                    product="spot",
                ),
            ),
            budgets=BudgetPolicy(
                valuation_currency=self.currency,
                firm_maximum=self.money("10000"),
                accounts=(AccountLimit(account_id="paper", maximum=self.money("10000")),),
                instances=tuple(
                    InstanceLimit(
                        instance_id=name,
                        account_id="paper",
                        maximum=self.money("9000"),
                        instruments=(self.dimension.instrument_id,),
                    )
                    for name in self.names
                ),
                max_quote_age_us=5_000_000,
                max_state_age_us=86_400_000_000,
                max_price_deviation_bps=500,
                max_order_notional=self.money("9000"),
            ),
        )

    def bindings(self) -> tuple[SharedStrategyBinding, ...]:
        """Select two distinct active formulas with independent durable policy state."""
        quantity = self.quantity("0.0001" if self.live else "2")
        return tuple(
            SharedStrategyBinding(
                instance_id=name,
                account_id="paper",
                entity=str(self.dimension.instrument_id),
                policy=policy,
                context=PortfolioContext(
                    portfolio_id="reference",
                    strategy_id=name,
                    model_revision="rule-only",
                    config_revision="public-paper-v1",
                    horizon="capture",
                    reason="engineering-reference",
                    venue=self.capture.venue,
                    settlement="spot",
                    risk_bucket="cash",
                    authority_scope="paper",
                ),
                maximum_fee=self.money("2"),
            )
            for name, policy in (
                (
                    "fixed",
                    FixedOpeningClip(
                        quantity,
                        self.currency,
                        self.quantity("0.00000001" if self.live else "1"),
                        no_trade=self.no_trade,
                        implementation=self.reference_identity,
                    ),
                ),
                (
                    "liquidity",
                    LiquidityOpeningClip(
                        quantity,
                        self.currency,
                        self.quantity("0.00000001" if self.live else "1"),
                        no_trade=self.no_trade,
                        implementation=self.reference_identity,
                    ),
                ),
            )
            if name in self.names
        )

    def build(self, inputs: DecisionInputs, market: PaperMarket) -> tuple[SharedStrategyInput, ...]:
        """Retain actual native input lineage and exact observed book features."""
        at = inputs.decision_at
        vector = FeatureVector(
            entity=inputs.entity,
            decision_at=at,
            event_at=at,
            information_start=at,
            available_at=at,
            expires_at=at + timedelta(seconds=5),
            definition=self.identity,
            fields=self.fields,
            values=tuple(
                ExactRatio.from_fraction(Fraction(value))
                for value in (market.ask.value, market.bid.value, market.ask_quantity.value)
            ),
            reasons=("native-touch",) * 3,
            input_identity=inputs.identity,
        )
        return tuple(
            SharedStrategyInput(
                instance_id=name,
                context=DecisionContext(features=vector, prediction=None),
                quote=AccountQuote(price=market.ask, at=at),
            )
            for name in self.names
        )

    def opening(self) -> AccountObservation:
        """Author complete opening funding independently of journal output."""
        return AccountObservation(
            identity="opening",
            at=self.opened_at,
            snapshot=AccountSnapshot(
                account_id="paper",
                instance_id=None,
                cash=(self.money("100000"),),
                positions=(),
                fees=(self.money("0"),),
                rebates=(self.money("0"),),
                transfers=(self.money("100000"),),
                fill_ids=(),
                posting_ids=(f"opening:{self.currency.code}",),
            ),
            open_orders=(),
        )

    def frames(self) -> tuple[bytes, ...]:
        """Supply unchanged finite touch snapshots with venue-specific native protocols."""
        if self.capture.venue == "bitfinex":
            return (
                b'{"event":"conf","status":"OK","flags":65536}',
                b'{"event":"subscribed","chanId":7,"channel":"book","symbol":"tBTCUSD","prec":"R0","freq":"F0","len":"25"}',
                b"[7,[[1,99,4],[2,100,-4]],1]",
                b"[7,[2,100,-4],2]",
                b"[7,[2,100,-4],3]",
            )
        frames = [b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}']
        for index in range(3):
            frames.append(
                self.codec.encode_json(
                    {
                        "arg": {"channel": "books", "instId": "BTC-USDT"},
                        "action": "snapshot" if index == 0 else "update",
                        "data": [
                            {
                                "prevSeqId": -1 if index == 0 else index + 9,
                                "seqId": index + 10,
                                "ts": str(time.time_ns() // 1_000_000),
                                "bids": [["99", "4", "0", "1"]],
                                "asks": [["100", "4", "0", "1"]],
                            }
                        ],
                    }
                )
            )
        return tuple(frames)

    def reconcile(
        self, journal: AccountJournal, decisions: tuple[PortfolioCommit, ...]
    ) -> AccountObservation:
        """Derive account and order expectations from source events before comparing postings."""
        traces = journal.paper_traces("paper")
        quantity, notional, fees = Fraction(0), Fraction(0), Fraction(0)
        expected_orders: list[OrderState] = []
        for decision in decisions:
            for parent in decision.net_orders:
                original = parent.order
                events = tuple(
                    event
                    for trace in traces
                    for event in trace.physical_events
                    if event.order_id == original.identity
                )
                filled, fee = Decimal(0), Decimal(0)
                acknowledged = any(event.kind == "request_ack" for event in events)
                accepted = any(event.kind == "accepted" for event in events)
                for event in events:
                    if event.fill is not None:
                        filled += abs(event.fill.quantity.value)
                        fee += event.fill.fee.value
                status: Literal["intent", "request_ack", "accepted", "partial", "filled"] = (
                    "filled"
                    if filled == original.intent.quantity.value
                    else "partial"
                    if filled
                    else "accepted"
                    if accepted
                    else "request_ack"
                    if acknowledged
                    else "intent"
                )
                expected_orders.append(
                    replace(
                        original,
                        status=status,
                        filled=self.quantity(str(filled)),
                        paid_fee=self.money(str(fee)),
                        request_acknowledged=acknowledged,
                        accepted=accepted,
                    )
                )
        assert {order.identity: order for order in expected_orders} == {
            parent.order.identity: parent.order for parent in journal.net_orders()
        }
        for trace in traces:
            for event in trace.physical_events:
                fill = event.fill
                if fill is None:
                    continue
                expected_price = Fraction(trace.market.ask.value) + Fraction(
                    self.scenario.adverse.value
                )
                units = (
                    Fraction(fill.quantity.value)
                    * expected_price
                    * Fraction(self.scenario.fee_rate)
                    / Fraction(self.currency.minor_unit)
                )
                expected_fee = round(units) * Fraction(self.currency.minor_unit)
                assert fill.reference == trace.market.ask
                assert fill.effective.value == expected_price and fill.fee.value == expected_fee
                quantity += Fraction(fill.quantity.value)
                notional += Fraction(fill.quantity.value) * expected_price
                fees += expected_fee
        fills, _ = journal.paper_report_facts("paper")
        ledger = journal.accounts()[0].ledger
        expected = AccountObservation(
            identity="independent-model-events",
            at=datetime.now(UTC),
            snapshot=AccountSnapshot(
                account_id="paper",
                instance_id=None,
                cash=(
                    self.money(str(DecimalGrid.exact_decimal(Fraction(100000) - notional - fees))),
                ),
                positions=()
                if quantity == 0
                else (self.quantity(str(DecimalGrid.exact_decimal(quantity))),),
                fees=(self.money(str(DecimalGrid.exact_decimal(fees))),),
                rebates=(self.money("0"),),
                transfers=(self.money("100000"),),
                fill_ids=tuple(item.fill.identity for item in fills),
                posting_ids=tuple(posting.identity for posting in ledger.postings),
            ),
            open_orders=tuple(order for order in expected_orders if not order.is_terminal),
        )
        assert journal.reconcile(expected)
        return expected

    async def run(self, output: Path, *, alert_socket: str) -> dict[str, object]:
        """Run the installed workflow, independently reconcile and replay exact retained inputs."""
        config, bindings = self.account_config(), self.bindings()
        request = CaptureRequest(
            config=self.capture,
            recording_id=str(uuid4()),
            implementation_identity=ImplementationIdentity.sha256(),
        )
        path = output / "account.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=False)
        (output / "reference-consumer.py").write_bytes(self.reference_source)
        result = await run_live_shared_paper(
            config,
            account_id="paper",
            bindings=bindings,
            scenario=self.scenario,
            requirement=self.requirement,
            inputs=self,
            request=request,
            journal_path=path,
            output=output / "run",
            observations=(self.opening(),),
            transport=None if self.live else ScriptedPublicFeed(self.frames()),
            alert_socket=alert_socket,
        )
        assert not result.monitoring.errors, result.monitoring
        self.verify_monitoring(output, result.monitoring)
        journal = AccountJournal(path, config)
        fills, _ = journal.paper_report_facts("paper")
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        market = result.last_market
        if market is None:
            raise ValueError("capture produced no eligible market")
        if not self.live:
            expected_size = Decimal(0) if self.no_trade else Decimal(2)
            expected_fee = (
                Decimal(0)
                if self.no_trade
                else (
                    expected_size * (Decimal(100) + self.scenario.adverse.value) * Decimal("0.001")
                ).quantize(self.currency.minor_unit)
            )
            expected_cash = (
                Decimal(100000)
                - expected_size * (Decimal(100) + self.scenario.adverse.value)
                - expected_fee
            )
            assert snapshot.cash == (self.money(str(expected_cash)),)
            assert snapshot.positions == (() if self.no_trade else (self.quantity("2"),))
            assert snapshot.fees == (self.money(str(expected_fee)),)
            assert len(fills) == (0 if self.no_trade else len(self.names))
            for item in fills:
                assert item.fill.quantity == self.quantity(str(2 // len(self.names)))
                assert item.fill.effective == self.price(
                    str(Decimal(100) + self.scenario.adverse.value)
                )
                assert item.fill.fee == self.money(str(expected_fee / len(self.names)))
        expected = self.reconcile(journal, result.paper.decisions)
        (output / "reconciliation.json").write_bytes(self.codec.encode_json(expected))
        report = result.report
        # Fixed fixture economics are independent of the production accounting/report path.
        if not self.live:
            expected_pnl = (
                Decimal(0)
                if self.no_trade
                else Decimal(-2) - 2 * self.scenario.adverse.value - expected_fee
            )
            assert report.account.currencies[0].net_pnl.value == expected_pnl
            assert (
                sum((scope.currencies[0].net_pnl.value for scope in report.instances), Decimal(0))
                == expected_pnl
            )
        before = self.codec.encode_json(
            (journal.accounts(), journal.orders(), journal.net_orders(), journal.paper_traces())
        )
        observer = SharedPaperCaptureObserver(
            source=LiveBookDecisionSource(request, self.requirement, history_capacity=1000),
            books=BookRegistry(result.book_registry),
            journal=journal,
            runtime=SharedDecisionRuntime(journal, self.bindings()),
            account_id="paper",
            scenario=self.scenario,
            inputs=self,
            delivery_path=None,
        )
        for line in (output / "run/deliveries.jsonl").read_bytes().splitlines():
            observer.deliver(self.codec.decode_json(line, SharedBookDelivery))
        assert before == self.codec.encode_json(
            (journal.accounts(), journal.orders(), journal.net_orders(), journal.paper_traces())
        )
        (output / "report.json").write_bytes(self.codec.encode_json(report))
        (output / "traces.json").write_bytes(self.codec.encode_json(journal.paper_traces()))
        summary: dict[str, object] = {
            "venue": self.capture.venue,
            "reference_consumer": self.reference_identity,
            "source": "observed-public" if self.live else "scripted-native",
            "scenario": self.scenario.identity,
            "gas_applicable": False,
            "gas_reason": self.scenario.gas_inapplicable_reason,
            "cash": str(snapshot.cash[0].value),
            "fees": str(snapshot.fees[0].value),
            "net_pnl": str(report.account.currencies[0].net_pnl.value),
            "slippage": str(report.account.currencies[0].slippage.value),
            "attributed_fills": len(fills),
            "active_strategies": self.names,
            "independent_reconciliation": True,
            "restart_replay_equal": True,
            "submission_attempted": False,
            "no_trade": self.no_trade,
            "monitoring_reconciled": True,
            "monitoring_dashboards": result.monitoring.dashboards,
        }
        if (
            not self.live
            and not self.no_trade
            and len(self.names) == 2
            and self.scenario.adverse.value == Decimal("0.50")
        ):
            await self.verify_new_capture(output, config, journal)
            summary["new_capture_receipts_isolated"] = True
        (output / "summary.json").write_bytes(self.codec.encode_json(summary))
        return summary

    async def verify_new_capture(
        self, output: Path, config: AccountConfiguration, journal: AccountJournal
    ) -> None:
        """A new capture keeps old lifecycle receipt/source bytes and cumulative economics."""
        original = (output / "run/monitoring-input.json").read_bytes()
        prior = PaperMonitoringInput.read(output / "run/monitoring-input.json")
        request = CaptureRequest(
            config=self.capture,
            recording_id=str(uuid4()),
            implementation_identity=ImplementationIdentity.sha256(),
        )
        resumed = await run_live_shared_paper(
            config,
            account_id="paper",
            bindings=self.bindings(),
            scenario=self.scenario,
            requirement=self.requirement,
            inputs=self,
            request=request,
            journal_path=journal.path,
            output=output / "resumed",
            transport=ScriptedPublicFeed(self.frames()),
        )
        assert not resumed.monitoring.errors
        later = PaperMonitoringInput.read(output / "resumed/monitoring-input.json")
        old_samples = {
            event.sample for event in prior.events if event.name.startswith("execution.event.")
        }
        assert old_samples
        assert not old_samples.intersection(
            event.sample for event in later.events if event.name.startswith("execution.event.")
        )
        assert all(event.context.source == request.identity for event in later.events)
        assert original == (output / "run/monitoring-input.json").read_bytes()
        original_net = next(
            event.value
            for event in prior.events
            if event.context.scope == "account:paper"
            and event.name == f"paper.net_pnl.{self.currency.code}"
        )
        new_net = next(
            event.value
            for event in later.events
            if event.context.scope == "account:paper"
            and event.name == f"paper.net_pnl.{self.currency.code}"
        )
        assert original_net == new_net

    def verify_monitoring(self, output: Path, status: PaperMonitoringResult) -> None:
        """Reconcile retained dashboard values to independent source-event economics."""
        saved = PaperMonitoringInput.read(output / "run/monitoring-input.json")
        views = tuple(
            DashboardSnapshot.read(output / "run/monitoring" / name) for name in status.dashboards
        )
        results = {
            (view.query.scope, result.spec.name): result
            for view in views
            for result in view.results
        }
        account_scope = "account:paper"
        traces = msgspec.json.decode(
            (output / "run/execution-traces.json").read_bytes(),
            type=tuple[AccountPaperTrace, ...],
            dec_hook=self.codec.decode_domain,
        )
        fills = tuple(
            event.fill
            for trace in traces
            for event in trace.physical_events
            if event.fill is not None
        )
        quantity = sum((Fraction(fill.quantity.value) for fill in fills), Fraction(0))
        notional = sum(
            (Fraction(fill.quantity.value) * Fraction(fill.effective.value) for fill in fills),
            Fraction(0),
        )
        fees = sum((Fraction(fill.fee.value) for fill in fills), Fraction(0))
        slip = sum(
            (
                Fraction(fill.quantity.value)
                * (Fraction(fill.effective.value) - Fraction(fill.reference.value))
                for fill in fills
            ),
            Fraction(0),
        )
        mark = traces[-1].market.bid.value
        cash = Fraction(100000) - notional - fees
        net = cash + quantity * Fraction(mark) - 100000
        expected = {
            f"account.cash.{self.currency.code}": cash,
            f"paper.fees.{self.currency.code}": fees,
            f"paper.slippage.{self.currency.code}": slip,
            f"paper.net_pnl.{self.currency.code}": net,
            f"paper.gross_pnl.{self.currency.code}": net + fees + slip,
            f"account.position.{self.dimension.instrument_id}": quantity,
        }
        for name, amount in expected.items():
            result = results[(account_scope, name)]
            assert result.status == "ok" and result.value == ExactRatio.from_fraction(amount), (
                name,
                result,
                amount,
            )
            assert result.spec.aggregation == "last"
        for name in (
            f"paper.fees.{self.currency.code}",
            f"paper.net_pnl.{self.currency.code}",
            f"paper.slippage.{self.currency.code}",
        ):
            owned = tuple(
                results[(f"account:paper:strategy:{instance}", name)].value
                for instance in self.names
            )
            assert all(value is not None for value in owned)
            assert (
                sum(
                    (
                        Fraction(int(value.numerator), int(value.denominator))
                        for value in owned
                        if value is not None
                    ),
                    Fraction(0),
                )
                == expected[name]
            )
        assert results[(account_scope, "paper.gas_applicable")].value == ExactRatio.from_fraction(
            Fraction(0)
        )
        drift = results[(account_scope, "data.source_clock_drift_seconds")]
        assert drift.status == "missing" and all(
            point.missing_reason == "not_measured" for point in drift.points
        )
        delay = results[(account_scope, "runtime.processing_seconds")]
        assert delay.status == "ok" and delay.value is not None
        first_receipt = min(event.recorded_at for event in saved.events)
        start = min(event.at for event in saved.events) - timedelta(microseconds=1)
        if first_receipt > start:
            prior = first_receipt - timedelta(microseconds=1)
            assert (
                TelemetryStore(output / "run/monitor.sqlite3").query(
                    MonitoringQuery(
                        scope=account_scope, mode="paper", start=start, end=prior, as_of=prior
                    )
                )
                == ()
            )
        assert saved.source_clocks
        assert any(clock.source_time is not None for clock in saved.source_clocks) == (
            self.capture.venue == "okx"
        )
        (output / "monitoring-reconciliation.json").write_bytes(
            self.codec.encode_json(
                {
                    "schema_version": "paper-dashboard-reconciliation-v1",
                    "venue": self.capture.venue,
                    "expected": {
                        name: ExactRatio.from_fraction(amount) for name, amount in expected.items()
                    },
                    "dashboard_identities": tuple(view.identity for view in views),
                    "input_sha256": hashlib.sha256(
                        (output / "run/monitoring-input.json").read_bytes()
                    ).hexdigest(),
                    "economic_authority": (
                        "committed physical source events; independent rational arithmetic"
                    ),
                    "exact": True,
                }
            )
        )

    def replay(self, output: Path) -> dict[str, object]:
        """Reopen retained inputs in this fresh process and prove journal idempotence."""
        manifest_bytes = (output / "run/manifest.json").read_bytes()
        manifest = msgspec.json.decode(manifest_bytes, type=dict[str, object])
        if (
            set(manifest)
            != {
                "schema_version",
                "account_configuration",
                "account_id",
                "execution_scenario",
                "capture_request",
                "book_registry",
                "requirement",
                "input_binding",
                "paper_mark_policy",
                "strategies",
                "opening_observations",
            }
            or manifest["schema_version"] != "public-paper-run-v1"
        ):
            raise ValueError("retained public paper manifest has unexpected fields or schema")

        def typed_field[T](name: str, target: type[T]) -> T:
            """Decode one retained manifest value through the installed domain codec."""
            return self.codec.decode_json(self.codec.encode_json(manifest[name]), target)

        config = typed_field("account_configuration", AccountConfiguration)
        request = typed_field("capture_request", CaptureRequest)
        books = typed_field("book_registry", BookRegistryConfiguration)
        scenario = typed_field("execution_scenario", PaperExecutionScenario)
        requirement = typed_field("requirement", InputRequirement)
        config.__post_init__()
        request.__post_init__()
        books.__post_init__()
        scenario.__post_init__()
        requirement.__post_init__()
        bindings = self.bindings()
        strategies = tuple(
            (binding.instance_id, binding.policy.identity, binding.context, binding.maximum_fee)
            for binding in bindings
        )
        if (
            self.reference_source != (output / "reference-consumer.py").read_bytes()
            or request.implementation_identity != ImplementationIdentity.sha256()
            or request.config != self.capture
            or config != replace(self.account_config(), opening_at=config.opening_at)
            or scenario != self.scenario
            or requirement != self.requirement
            or manifest["account_id"] != "paper"
            or manifest["input_binding"] != self.identity
            or manifest["paper_mark_policy"] != "last_eligible_bid_v1"
            or self.codec.encode_json(manifest["strategies"]) != self.codec.encode_json(strategies)
        ):
            raise ValueError(
                "retained run differs from reference consumer or installed implementation"
            )

        journal = AccountJournal(output / "account.sqlite3", config)

        def journal_bytes() -> dict[str, bytes]:
            """Snapshot exact durable state for comparison across delivery replay."""
            return {
                "accounts": self.codec.encode_json(journal.accounts()),
                "orders": self.codec.encode_json(journal.orders()),
                "net_orders": self.codec.encode_json(journal.net_orders()),
                "paper_traces": self.codec.encode_json(journal.paper_traces()),
            }

        before = journal_bytes()
        observer = SharedPaperCaptureObserver(
            source=LiveBookDecisionSource(
                request, requirement, history_capacity=books.history_capacity
            ),
            books=BookRegistry(books),
            journal=journal,
            runtime=SharedDecisionRuntime(journal, bindings),
            account_id="paper",
            scenario=scenario,
            inputs=self,
            delivery_path=None,
        )
        deliveries_bytes = (output / "run/deliveries.jsonl").read_bytes()
        lines = deliveries_bytes.splitlines()
        if not lines or not deliveries_bytes.endswith(b"\n"):
            raise ValueError("retained public delivery log is empty or incomplete")
        for line in lines:
            delivery = self.codec.decode_json(line, SharedBookDelivery)
            if self.codec.encode_json(delivery) != line:
                raise ValueError("retained public delivery differs from canonical event bytes")
            observer.deliver(delivery)
        after = journal_bytes()
        if before != after:
            raise ValueError("fresh-process public replay changed retained account state")
        digests = {name: hashlib.sha256(value).hexdigest() for name, value in before.items()}
        original_status = self.codec.decode_json(
            (output / "run/monitoring/monitoring-status.json").read_bytes(), PaperMonitoringResult
        )
        configured_socket = next(
            rule.address
            for name in original_status.dashboards
            for rule in DashboardSnapshot.read(output / "run/monitoring" / name).config.alerts
        )
        recovered = render_paper_monitoring(
            output / "run/monitoring-input.json",
            journal_path=output / "run/monitor.sqlite3",
            output=output / "monitoring-reopened",
            alert_socket=configured_socket,
        )
        assert not recovered.errors and recovered.inserted == 0, recovered
        assert recovered.dashboards == original_status.dashboards
        for name in recovered.dashboards:
            assert DashboardSnapshot.read(
                output / "run/monitoring" / name
            ) == DashboardSnapshot.read(output / "monitoring-reopened" / name)
        verification: dict[str, object] = {
            "schema_version": "public-paper-replay-v1",
            "equal": True,
            "monitoring_equal": True,
            "monitoring_inserted": recovered.inserted,
            "deliveries_replayed": len(lines),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "deliveries_sha256": hashlib.sha256(deliveries_bytes).hexdigest(),
            "reference_consumer_sha256": self.reference_identity,
            "implementation_identity": request.implementation_identity,
            "before": digests,
            "after": digests,
        }
        (output / "replay-verification.json").write_bytes(self.codec.encode_json(verification))
        return verification


class _Arguments(argparse.Namespace):
    """Type the explicit standalone workload selections."""

    config: Path
    output: Path
    live: bool
    no_trade: bool
    adverse: str
    dedicated: bool
    replay: bool


def main() -> None:
    """Select one explicit native venue workload and retain its complete installed result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--no-trade", action="store_true")
    parser.add_argument("--adverse", default="0.50")
    parser.add_argument("--dedicated", action="store_true")
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args(namespace=_Arguments())
    config_path, output = args.config, args.output
    if not isinstance(config_path, Path) or not isinstance(output, Path):
        raise TypeError("consumer requires explicit paths")
    config = CaptureConfig.read(config_path)
    live = bool(args.live)
    config = replace(
        config,
        duration_seconds=10,
        max_messages=20 if live else (5 if config.venue == "bitfinex" else 4),
        retries=0,
    )
    adverse = args.adverse
    if not isinstance(adverse, str):
        raise TypeError("adverse price requires an exact decimal string")
    workload = PublicPaperWorkload(
        config,
        live=live,
        no_trade=bool(args.no_trade),
        adverse=adverse,
        dedicated=args.dedicated,
        reference_source=Path(__file__).read_bytes(),
    )
    if args.replay:
        summary = workload.replay(output)
    else:
        with tempfile.TemporaryDirectory(prefix="paper-alert-") as temporary:
            address = str(Path(temporary) / "receiver.sock")
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
                receiver.bind(address)
                receiver.settimeout(1)
                summary = asyncio.run(workload.run(output, alert_socket=address))
                status = DomainCodec().decode_json(
                    (output / "run/monitoring/monitoring-status.json").read_bytes(),
                    PaperMonitoringResult,
                )
                views = tuple(
                    DashboardSnapshot.read(output / "run/monitoring" / name)
                    for name in status.dashboards
                )
                expected = tuple(
                    (alert.delivery.control_sha256, alert.delivery.identity)
                    for view in views
                    for alert in view.alert_results
                    if alert.delivery is not None
                )
                observed = tuple(receiver.recv(4096).decode() for _ in expected)
                for evidence, _ in expected:
                    assert any(evidence in message for message in observed)
                receiver.settimeout(0.05)
                try:
                    receiver.recv(4096)
                except TimeoutError:
                    pass
                else:
                    raise AssertionError("unexpected duplicate paper alert")
                (output / "alert-delivery.json").write_bytes(
                    DomainCodec().encode_json(
                        {
                            "socket_accepted": len(expected),
                            "receiver_observed": len(observed),
                            "delivery_identities": tuple(identity for _, identity in expected),
                            "human_acknowledged": "not_tested",
                            "remote_service": "not_tested",
                            "receiver": "local AF_UNIX receiver in installed paper consumer",
                        }
                    )
                )
    print(DomainCodec().encode_json(summary).decode())


if __name__ == "__main__":
    main()
