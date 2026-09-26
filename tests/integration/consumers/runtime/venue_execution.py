"""Exercise installed strategy-to-venue spot execution with scripted native HTTP."""

from __future__ import annotations

# standard library imports
import argparse
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec

# project library imports
from accounting import AccountLedger
from applications.execute import VenueApplicationResult
from configuration import (
    AccountConfiguration,
    OpeningAccount,
    VenueAuthorization,
    VenueCredentialReferences,
    VenueExecutionConfiguration,
    VenueInstrument,
)
from execution import (
    AccountDecision,
    AccountJournal,
    AccountQuote,
    BitfinexSpotAdapter,
    OKXSpotAdapter,
    OrderDecision,
    PortfolioBatch,
    PortfolioContext,
    PortfolioDecision,
    VenueAdapter,
    VenueCredentials,
    VenueGateway,
    VenueHttpRequest,
    VenueHttpResponse,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.catalogs import InstrumentDefinition, ReferenceHistory, VenueSpecification
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec, WireRecord
from strategies import OrderIntent

type VenueName = Literal["okx", "bitfinex"]


class ScenarioClock:
    """Advance request and exchange observation clocks without waiting in real time."""

    def __init__(self, at: datetime) -> None:
        """Start one explicit UTC test clock."""
        self.at = at

    def now(self) -> datetime:
        """Return the current synthetic receipt and knowledge time."""
        return self.at

    def sleep(self, seconds: float) -> None:
        """Advance through a conservative venue request interval."""
        self.at += timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        """Move to a later independent exchange event time."""
        self.at += timedelta(seconds=seconds)


class ScriptedVenueTransport:
    """Return native spot account bytes while preserving request identities."""

    def __init__(self, venue: VenueName, clock: ScenarioClock, symbol: str, quote: str) -> None:
        """Start an empty cash-funded test account with no physical order."""
        self.venue = venue
        self.clock = clock
        self.symbol = symbol
        self.quote = quote
        self.cash = Decimal("1000")
        self.base = Decimal("0")
        self.client_id: str | None = None
        self.created_at: datetime | None = None
        self.fill_at: datetime | None = None
        self.state: Literal["none", "open", "partial", "cancelled"] = "none"
        self.submit_count = 0
        self.cancel_count = 0

    def request(self, request: VenueHttpRequest) -> VenueHttpResponse:
        """Dispatch one signed protocol request to a complete native fixture."""
        if self.venue == "okx":
            return self._okx(request)
        return self._bitfinex(request)

    def fill_one(self) -> None:
        """Execute one of two base units with a 0.10 quote-currency fee."""
        if self.state != "open":
            raise ValueError("scripted fill requires an open physical order")
        self.state = "partial"
        self.fill_at = self.clock.now()
        self.cash -= Decimal("100.10")
        self.base += Decimal("1")

    def _response(self, value: object) -> VenueHttpResponse:
        """Encode one native body and retain its independent local receipt time."""
        return VenueHttpResponse(
            status=200, body=msgspec.json.encode(value), received_at=self.clock.now()
        )

    def _record_submit(self, body: bytes, *, client_field: str) -> None:
        """Read a native submitted client identity exactly once."""
        if self.submit_count:
            raise ValueError("duplicate physical submit reached scripted transport")
        fields = msgspec.json.decode(body, type=dict[str, object])
        client = fields.get(client_field)
        if self.venue == "okx" and type(client) is str:
            self.client_id = client
        elif self.venue == "bitfinex" and type(client) is int:
            self.client_id = str(client)
        else:
            raise ValueError("scripted native submit lacks client identity")
        self.created_at = self.clock.now()
        self.state = "open"
        self.submit_count += 1

    def _milliseconds(self, at: datetime | None) -> int:
        """Encode one known UTC source time without inventing a missing event."""
        if at is None:
            raise ValueError("scripted source time is missing")
        delta = at - datetime(1970, 1, 1, tzinfo=UTC)
        return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000

    def _okx_order(self) -> dict[str, object]:
        """Describe cumulative physical order state in OKX spot fields."""
        if self.client_id is None:
            raise ValueError("scripted OKX order lacks a client identity")
        states = {"open": "live", "partial": "partially_filled", "cancelled": "canceled"}
        if self.state not in states:
            raise ValueError("scripted OKX order is absent")
        return {
            "instType": "SPOT",
            "tdMode": "cash",
            "instId": self.symbol,
            "ordId": "9001",
            "clOrdId": self.client_id,
            "side": "buy",
            "ordType": "limit",
            "sz": "2",
            "accFillSz": "0" if self.state == "open" else "1",
            "px": "100",
            "state": states[self.state],
            "cTime": str(self._milliseconds(self.created_at)),
        }

    def _okx_fill(self) -> dict[str, object]:
        """Describe one independently identified quote-fee execution."""
        if self.client_id is None:
            raise ValueError("scripted OKX fill lacks a client identity")
        return {
            "instType": "SPOT",
            "instId": self.symbol,
            "ordId": "9001",
            "clOrdId": self.client_id,
            "billId": "7001",
            "side": "buy",
            "fillSz": "1",
            "fillPx": "100",
            "fee": "-0.10",
            "feeCcy": self.quote,
            "fillTime": str(self._milliseconds(self.fill_at)),
        }

    def _okx(self, request: VenueHttpRequest) -> VenueHttpResponse:
        """Serve the documented demo account, order, fill and balance envelopes."""
        path = request.path
        if path == "/api/v5/account/config":
            data: object = [{"acctLv": "1", "uid": "42"}]
        elif path.startswith("/api/v5/trade/orders-pending?"):
            data = [self._okx_order()] if self.state in ("open", "partial") else []
        elif path.startswith("/api/v5/trade/fills-history?"):
            data = [self._okx_fill()] if self.fill_at is not None else []
        elif path == "/api/v5/account/balance":
            data = [
                {
                    "details": [
                        {
                            "ccy": self.quote,
                            "cashBal": str(self.cash),
                            "availBal": str(self.cash),
                            "liab": "0",
                        },
                        {
                            "ccy": "ETH",
                            "cashBal": str(self.base),
                            "availBal": str(self.base),
                            "liab": "0",
                        },
                    ]
                }
            ]
        elif path.startswith("/api/v5/trade/order?"):
            data = [self._okx_order()] if self.state != "none" else []
        elif path == "/api/v5/trade/order" and request.method == "POST":
            self._record_submit(request.body, client_field="clOrdId")
            data = [{"sCode": "0", "clOrdId": self.client_id, "ordId": "9001"}]
        elif path == "/api/v5/trade/cancel-order" and request.method == "POST":
            if self.state not in ("open", "partial"):
                raise ValueError("scripted OKX cancel requires active order")
            self.state = "cancelled"
            self.cancel_count += 1
            data = [{"sCode": "0", "clOrdId": self.client_id, "ordId": "9001"}]
        else:
            raise ValueError("unexpected OKX protocol request")
        return self._response({"code": "0", "data": data})

    def _bitfinex_order(self) -> list[object]:
        """Describe one complete exchange order with native signed quantities."""
        if self.client_id is None or self.state == "none":
            raise ValueError("scripted Bitfinex order lacks a client identity")
        statuses = {
            "open": "ACTIVE",
            "partial": "PARTIALLY FILLED @ 100",
            "cancelled": "CANCELED was: PARTIALLY FILLED @ 100",
        }
        created = self._milliseconds(self.created_at)
        remaining = "2" if self.state == "open" else "1"
        return [
            9001,
            None,
            int(self.client_id),
            self.symbol,
            created,
            created,
            remaining,
            "2",
            "EXCHANGE LIMIT",
            None,
            None,
            None,
            0,
            statuses[self.state],
            None,
            None,
            "100",
        ]

    def _bitfinex_fill(self) -> list[object]:
        """Describe one trade with native negative quote-currency fee."""
        if self.client_id is None:
            raise ValueError("scripted Bitfinex fill lacks a client identity")
        return [
            7001,
            self.symbol,
            self._milliseconds(self.fill_at),
            9001,
            "1",
            "100",
            "EXCHANGE LIMIT",
            None,
            None,
            "-0.10",
            self.quote,
            int(self.client_id),
        ]

    def _bitfinex(self, request: VenueHttpRequest) -> VenueHttpResponse:
        """Serve paper account info, exchange orders, trades and wallets."""
        path = request.path
        if path == "/v2/auth/r/info/user":
            return self._response([42, *([None] * 20), 1])
        if path == "/v2/auth/r/orders":
            if self.state in ("open", "partial"):
                return self._response([self._bitfinex_order()])
            return self._response([])
        if path == "/v2/auth/r/orders/hist":
            return self._response([self._bitfinex_order()] if self.state == "cancelled" else [])
        if path.startswith("/v2/auth/r/trades/") and path.endswith("/hist"):
            return self._response([self._bitfinex_fill()] if self.fill_at is not None else [])
        if path == "/v2/auth/r/wallets":
            return self._response(
                [
                    ["exchange", self.quote, str(self.cash), 0, str(self.cash)],
                    ["exchange", "ETH", str(self.base), 0, str(self.base)],
                ]
            )
        if path == "/v2/auth/w/order/submit":
            self._record_submit(request.body, client_field="cid")
            return self._response(
                [0, "on-req", None, None, [self._bitfinex_order()], None, "SUCCESS"]
            )
        if path == "/v2/auth/w/order/cancel":
            if self.state not in ("open", "partial"):
                raise ValueError("scripted Bitfinex cancel requires active order")
            self.state = "cancelled"
            self.cancel_count += 1
            return self._response(
                [0, "oc-req", None, None, self._bitfinex_order(), None, "SUCCESS"]
            )
        raise ValueError("unexpected Bitfinex protocol request")


class VenueScenarioResult(WireRecord, frozen=True):
    """Report software evidence without claiming authenticated venue access."""

    venue: VenueName
    config_sha256: str
    cash: str
    base_position: str
    fee: str
    child_positions: tuple[str, str]
    child_fees: tuple[str, str]
    terminal_status: str
    submits: int
    cancels: int
    qualification: Literal["scripted-native-http"] = "scripted-native-http"


class InstalledVenueScenario:
    """Run two reference strategy orders through installed account and adapters."""

    opening_at = datetime(2026, 9, 26, 12, tzinfo=UTC)
    instrument_id = InstrumentId.from_canonical_text("44444444-4444-4444-8444-444444444444")
    dimension = Dimension(instrument_id=instrument_id, kind=QuantityKind.BASE_UNIT)
    base = Currency(code="ETH", minor_unit=Decimal("0.00000001"))

    def __init__(self, venue: VenueName, root: Path) -> None:
        """Bind one isolated state root and its native account fixture."""
        self.venue = venue
        self.root = root
        self.quote = Currency.from_code("USDT" if venue == "okx" else "USD")
        self.symbol = "ETH-USDT" if venue == "okx" else "tETHUSD"
        self.clock = ScenarioClock(self.opening_at)
        self.transport = ScriptedVenueTransport(venue, self.clock, self.symbol, self.quote.code)

    def _money(self, value: str) -> Money:
        """Construct one exact quote-currency amount."""
        return Money(value=Decimal(value), currency=self.quote)

    def _quantity(self, value: str) -> Quantity:
        """Construct one exact canonical base-unit quantity."""
        return Quantity(value=Decimal(value), dimension=self.dimension)

    def _price(self, value: str) -> Price:
        """Construct one exact quote-per-base spot price."""
        return Price(value=Decimal(value), currency=self.quote, per=self.dimension)

    def _config(self) -> VenueExecutionConfiguration:
        """Bind observed native rules to independently owned strategy budgets."""
        specification = VenueSpecification(
            instrument=InstrumentDefinition(
                instrument_id=self.instrument_id,
                venue=self.venue,
                symbol=self.symbol,
                product="spot",
                base_currency=self.base.code,
                quote_currency=self.quote.code,
                calendar="24x7",
            ),
            valid_from=self.opening_at,
            valid_to=None,
            ts_knowledge=self.opening_at,
            source_digest="b" * 64,
            basis="current_observation",
            price_tick=Decimal("0.01"),
            quantity_step=Decimal("0.01"),
            minimum_quantity=Decimal("0.01"),
            status="live",
        )
        reference = ReferenceHistory(specifications=(specification,))
        limits = SpotLimits.from_reference(
            reference,
            maximum=self._quantity("10"),
            quote_currency=self.quote,
            valid_at=self.opening_at,
            known_at=self.opening_at,
            max_age=timedelta(days=1),
        )
        account = AccountConfiguration(
            mode="venue_test",
            opening_at=self.opening_at,
            accounts=(OpeningAccount(account_id="venue-account", cash=(self._money("1000"),)),),
            instruments=(limits,),
            budgets=BudgetPolicy(
                valuation_currency=self.quote,
                firm_maximum=self._money("1000"),
                accounts=(AccountLimit(account_id="venue-account", maximum=self._money("1000")),),
                instances=tuple(
                    InstanceLimit(
                        instance_id=instance,
                        account_id="venue-account",
                        maximum=self._money("500"),
                        instruments=(self.instrument_id,),
                    )
                    for instance in ("alpha", "beta")
                ),
                max_quote_age_us=1_800_000_000,
                max_state_age_us=1_800_000_000,
                max_price_deviation_bps=100,
                max_order_notional=self._money("500"),
            ),
        )
        credentials = (
            VenueCredentialReferences(
                api_key_env="SCRIPTED_OKX_KEY",
                api_secret_env="SCRIPTED_OKX_SECRET",
                passphrase_env="SCRIPTED_OKX_PASSPHRASE",
            )
            if self.venue == "okx"
            else VenueCredentialReferences(
                api_key_env="SCRIPTED_BITFINEX_KEY", api_secret_env="SCRIPTED_BITFINEX_SECRET"
            )
        )
        return VenueExecutionConfiguration(
            account=account,
            account_id="venue-account",
            venue_account_id="42",
            venue=self.venue,
            environment="okx_demo" if self.venue == "okx" else "bitfinex_paper",
            instruments=(
                VenueInstrument(
                    dimension=self.dimension,
                    base_currency=self.base,
                    quote_currency=self.quote,
                    native_symbol=self.symbol,
                ),
            ),
            reference=reference,
            max_reference_age_us=86_400_000_000,
            credentials=credentials,
        )

    def _adapter(self) -> VenueAdapter:
        """Exercise the real venue protocol class over one scripted HTTP transport."""
        credentials = VenueCredentials(
            api_key="scripted-key",
            api_secret="scripted-secret",
            passphrase="scripted-passphrase" if self.venue == "okx" else None,
        )
        if self.venue == "okx":
            return OKXSpotAdapter(credentials, self.transport)
        return BitfinexSpotAdapter(credentials, self.transport)

    def _batch(self, at: datetime) -> PortfolioBatch:
        """Apply two distinct reference policies to one compatible physical order."""
        quote = AccountQuote(price=self._price("100"), at=at)
        return PortfolioBatch(
            identity="two-reference-strategies",
            at=at + timedelta(microseconds=1),
            decisions=tuple(
                PortfolioDecision(
                    request=AccountDecision(
                        account_id="venue-account",
                        instance_id=instance,
                        decision=OrderDecision(
                            identity=f"{instance}-buy",
                            at=at,
                            intent=OrderIntent(
                                side="buy",
                                quantity=self._quantity("1"),
                                limit=self._price("100"),
                                time_in_force="gtc",
                            ),
                        ),
                        quote=quote,
                        maximum_fee=self._money("0.10"),
                        checkpoint=f"{instance}-state".encode(),
                    ),
                    context=PortfolioContext(
                        portfolio_id="reference-portfolio",
                        strategy_id=instance,
                        model_revision="fixed-policy-v1",
                        config_revision="fixed-test-v1",
                        horizon="one-minute",
                        reason="bounded-test-order",
                        venue=self.venue,
                        settlement="spot-immediate",
                        risk_bucket="cash-spot",
                        authority_scope="venue-test",
                    ),
                )
                for instance in ("alpha", "beta")
            ),
        )

    def run(self) -> VenueScenarioResult:
        """Prove exact fees, child allocation, duplicate suppression and restart."""
        self.root.mkdir(parents=True, exist_ok=True)
        config = self._config()
        journal_path = self.root / "account.sqlite3"
        config_path = self.root / "venue.json"
        config_path.write_bytes(DomainCodec().encode_json(config))
        command = subprocess.run(
            [
                str(Path(sys.executable).with_name("alpha-execute")),
                "venue",
                "--config",
                str(config_path),
                "--journal",
                str(journal_path),
                "--action",
                "inspect",
            ],
            cwd=self.root,
            capture_output=True,
            check=False,
            timeout=15,
        )
        assert command.returncode == 0, command.stderr.decode()
        inspected = DomainCodec().decode_json(command.stdout, VenueApplicationResult)
        assert inspected.gateway.config_sha256 == config.identity
        journal = AccountJournal(journal_path, config.account)
        gateway = VenueGateway(journal, config, self._adapter(), clock=self.clock)
        assert not gateway.reconcile().recovery_required
        decision_at = self.clock.now()
        journal.observe(AccountQuote(price=self._price("100"), at=decision_at))
        batch = journal.coordinate(self._batch(decision_at))
        assert batch.status == "committed" and len(batch.net_orders) == 1
        assert len(batch.children) == 2
        parent_id = batch.net_orders[0].order.identity
        authority = VenueAuthorization(
            config_sha256=config.identity,
            account_id=config.account_id,
            environment=config.environment,
            instrument_ids=(self.instrument_id,),
            valid_from=self.opening_at,
            valid_until=self.opening_at + timedelta(hours=1),
            maximum_order_notional=self._money("500"),
            submit_enabled=True,
        )
        self.clock.advance(0.001)
        assert gateway.submit(parent_id, authority).submission_attempted
        assert self.transport.submit_count == 1
        self.clock.advance(1)
        self.transport.fill_one()
        assert not gateway.reconcile().recovery_required
        restarted = AccountJournal(journal_path, config.account)
        gateway = VenueGateway(restarted, config, self._adapter(), clock=self.clock)
        gateway.submit(parent_id, authority)
        assert self.transport.submit_count == 1
        gateway.cancel(parent_id, authority)
        assert self.transport.cancel_count == 1
        assert not gateway.reconcile().recovery_required
        gateway.reconcile()
        assert self.transport.submit_count == 1 and self.transport.cancel_count == 1
        parent = next(item for item in restarted.net_orders() if item.order.identity == parent_id)
        account = AccountLedger(restarted.accounts()[0].ledger)
        physical = account.snapshot()
        children = tuple(account.snapshot(instance_id=name) for name in ("alpha", "beta"))
        assert physical.cash == (self._money("899.90"),)
        assert physical.positions == (self._quantity("1"),)
        assert physical.fees == (self._money("0.10"),)
        assert tuple(snapshot.positions for snapshot in children) == (
            (self._quantity("0.5"),),
            (self._quantity("0.5"),),
        )
        assert tuple(snapshot.fees for snapshot in children) == (
            (self._money("0.05"),),
            (self._money("0.05"),),
        )
        assert parent.order.status == "cancelled"
        return VenueScenarioResult(
            venue=self.venue,
            config_sha256=config.identity,
            cash=str(physical.cash[0].value),
            base_position=str(physical.positions[0].value),
            fee=str(physical.fees[0].value),
            child_positions=(
                str(children[0].positions[0].value),
                str(children[1].positions[0].value),
            ),
            child_fees=(str(children[0].fees[0].value), str(children[1].fees[0].value)),
            terminal_status=parent.order.status,
            submits=self.transport.submit_count,
            cancels=self.transport.cancel_count,
        )


class ScenarioArguments(argparse.Namespace):
    """Hold typed command arguments for the isolated installed consumer."""

    venue: VenueName
    state: Path


def main() -> None:
    """Run one native scripted venue scenario outside the repository checkout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venue", choices=("okx", "bitfinex"), required=True)
    parser.add_argument("--state", type=Path, required=True)
    arguments = parser.parse_args(namespace=ScenarioArguments())
    result = InstalledVenueScenario(arguments.venue, arguments.state).run()
    print(DomainCodec().encode_json(result).decode(), flush=True)


if __name__ == "__main__":
    main()
