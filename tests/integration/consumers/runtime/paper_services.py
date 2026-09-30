"""Prepare signed multi-instance public-paper services for two native spot venues."""

from __future__ import annotations

# standard library imports
import argparse
import asyncio
import hashlib
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import ClassVar, Literal

# project library imports
from accounting import AccountSnapshot
from applications.execute.service_inputs import ServiceBookInputs
from configuration import (
    AccountConfiguration,
    CaptureConfig,
    OpeningAccount,
    PaperAuthorization,
    PaperDeployment,
    PaperExecutionScenario,
    PaperServiceAccount,
    PaperServiceConfiguration,
    PaperServiceInstance,
    PaperServiceSource,
    PaperSourceBinding,
    PaperStrategyIdentity,
)
from configuration.accounts import InstrumentFeeRate
from execution import (
    AccountControl,
    AccountExecutionRequest,
    AccountObservation,
    AccountQuote,
    InstalledPaperAccount,
    PaperOwner,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from market_data.collection import CaptureTransport
from market_data.contracts import FeedSocket
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from runtime import InstalledIdentity
from serialization import DomainCodec
from strategies import LiquidityClipPolicy, ReferenceClipPolicy


class NativeBookFixture:
    """Emit fresh, finite venue-native public books at an authored exact touch."""

    def __init__(
        self,
        source: PaperServiceSource,
        *,
        frame_count: int = 12,
        interval_seconds: float = 1.25,
        start_high: bool = False,
    ) -> None:
        """Retain only picklable source definitions for spawned capture children."""
        if (
            type(frame_count) is not int
            or not 1 <= frame_count <= 78
            or not 0.5 <= interval_seconds <= 2.0
        ):
            raise ValueError("native fixture requires bounded frames and cadence")
        self.source, self.frame_count, self.index = source, frame_count, 0
        self.interval_seconds, self.start_high = interval_seconds, start_high

    async def open(self, timeout: float) -> FeedSocket:
        """Reset the finite read-only connection after each source recovery."""
        if timeout <= 0:
            raise ValueError("native fixture requires a positive connection timeout")
        self.index = 0
        return self

    async def send(self, message: str) -> None:
        """Allow public subscriptions but reject any private request on the fixture."""
        if "auth" in message.casefold() or "order" in message.casefold():
            raise ValueError("private request reached public fixture")

    async def recv(self) -> bytes:
        """Return one fresh native acknowledgement, snapshot or book update."""
        await asyncio.sleep(self.interval_seconds)
        index = self.index
        self.index += 1
        capture = self.source.capture
        if capture.venue == "bitfinex":
            if index == 0:
                return b'{"event":"conf","status":"OK","flags":65536}'
            if index == 1:
                return DomainCodec().encode_json(
                    {
                        "event": "subscribed",
                        "chanId": 7,
                        "channel": "book",
                        "symbol": capture.symbol,
                        "prec": "R0",
                        "freq": "F0",
                        "len": "25",
                    }
                )
            sequence = index - 1
            if sequence > self.frame_count:
                raise OSError("finite native book fixture exhausted")
            if sequence == 1:
                ask = 103 if self.start_high else 100
                return DomainCodec().encode_json(
                    [7, [[1, 99, 4], [2, ask, -2 if self.start_high else -4]], sequence]
                )
            ask = 103 if self.start_high or sequence > 3 else 100
            return DomainCodec().encode_json([7, [2, ask, -2 if ask == 103 else -4], sequence])
        if index == 0:
            return DomainCodec().encode_json(
                {"event": "subscribe", "arg": {"channel": "books", "instId": capture.symbol}}
            )
        if index > self.frame_count:
            raise OSError("finite native book fixture exhausted")
        sequence = index + 9
        asks = (
            [["103", "2", "0", "1"]]
            if self.start_high or index > 4
            else [["100", "4", "0", "1"]]
            if index in (1, 2, 3)
            else [["100", "0", "0", "0"], ["103", "2", "0", "1"]]
        )
        return DomainCodec().encode_json(
            {
                "arg": {"channel": "books", "instId": capture.symbol},
                "action": "snapshot" if index == 1 else "update",
                "data": [
                    {
                        "prevSeqId": -1 if index == 1 else sequence - 1,
                        "seqId": sequence,
                        "ts": str(time.time_ns() // 1_000_000),
                        "bids": [["99", "4", "0", "1"]],
                        "asks": asks,
                    }
                ],
            }
        )

    async def close(self) -> None:
        """Release the scripted connection without external side effects."""

    def snapshot(self) -> bytes:
        """Reject REST fallback for these selected WebSocket books."""
        raise ValueError("native fixture has no REST snapshot")


class PaperServiceWorkload:
    """Keep installed account budgets fixed while selecting a new strategy instance."""

    instrument_text: ClassVar[dict[str, tuple[str, str]]] = {
        "okx": (
            "4476df8e-6342-4417-839e-e41b88f41446",
            "7c03e264-bd70-4e5e-bcf7-fb9db7d4c843",
        ),
        "bitfinex": (
            "c87d983f-e7ec-4e64-8d54-9f2be67a64b8",
            "fef5f20d-c2d7-4aef-941c-dc4cff41f93d",
        ),
    }

    def __init__(
        self,
        venue: Literal["okx", "bitfinex"],
        *,
        opening_at: datetime,
        socket_root: Path,
        mode: Literal["paper", "shadow"] = "paper",
    ) -> None:
        """Bind a stable reference universe and a short absolute socket location."""
        if venue not in ("okx", "bitfinex") or not socket_root.is_absolute():
            raise ValueError("paper workload requires a supported venue and socket root")
        AccountConfiguration._require_utc(opening_at, field_name="paper workload opening")
        self.venue, self.opening_at, self.socket_root, self.mode = (
            venue,
            opening_at,
            socket_root,
            mode,
        )
        self.currency = Currency.from_code("USDT" if venue == "okx" else "USD")
        self.dimensions = tuple(
            Dimension(
                instrument_id=InstrumentId.from_canonical_text(text),
                kind=QuantityKind.BASE_UNIT,
            )
            for text in self.instrument_text[venue]
        )
        self.codec = DomainCodec()
        self.implementation: str | None = None

    def money(self, value: str) -> Money:
        """Construct an exact common quote-currency amount."""
        return Money(value=Decimal(value), currency=self.currency)

    @staticmethod
    def quantity(value: str, dimension: Dimension) -> Quantity:
        """Construct exact base units for a selected spot instrument."""
        return Quantity(value=Decimal(value), dimension=dimension)

    def price(self, value: str, dimension: Dimension) -> Price:
        """Construct a per-instrument quote price in the common currency."""
        return Price(value=Decimal(value), currency=self.currency, per=dimension)

    def account_configuration(
        self, account_id: Literal["shared", "isolated"]
    ) -> AccountConfiguration:
        """Provision immutable budgets for current and later active instances."""
        dimensions = self.dimensions if account_id == "shared" else self.dimensions[:1]
        owned = (
            (
                ("shared-fixed-btc", self.dimensions[0]),
                ("shared-liquidity-btc", self.dimensions[0]),
                ("shared-fixed-eth", self.dimensions[1]),
            )
            if account_id == "shared"
            else (("isolated-fixed-btc", self.dimensions[0]),)
        )
        spot_limits: tuple[SpotLimits, ...] = tuple(
            SpotLimits(
                maximum=self.quantity("100", dimension),
                lot=self.quantity("1", dimension),
                tick=self.price("0.01", dimension),
                product="spot",
            )
            for dimension in dimensions
        )
        return AccountConfiguration(
            mode=self.mode,
            opening_at=self.opening_at,
            accounts=(OpeningAccount(account_id=account_id, cash=(self.money("100000"),)),),
            instruments=spot_limits,
            fee_rates=tuple(
                InstrumentFeeRate(
                    instrument_id=limits.maximum.dimension.instrument_id, rate=Decimal(0)
                )
                for limits in spot_limits
            ),
            budgets=BudgetPolicy(
                valuation_currency=self.currency,
                firm_maximum=self.money("10000"),
                accounts=(AccountLimit(account_id=account_id, maximum=self.money("10000")),),
                instances=tuple(
                    InstanceLimit(
                        instance_id=name,
                        account_id=account_id,
                        maximum=self.money("5000"),
                        instruments=(dimension.instrument_id,),
                    )
                    for name, dimension in owned
                ),
                max_quote_age_us=30_000_000,
                max_state_age_us=120_000_000,
                max_price_deviation_bps=500,
                max_order_notional=self.money("1000"),
            ),
        )

    def source(self, asset: Literal["BTC", "ETH"], dimension: Dimension) -> PaperServiceSource:
        """Describe one public native book and finite authored matching costs."""
        quote = self.currency.code
        capture = CaptureConfig(
            venue=self.venue,
            symbol=f"{asset}-{quote}" if self.venue == "okx" else f"t{asset}{quote}",
            instrument_id=dimension.instrument_id,
            base_currency=asset,
            quote_currency=quote,
            channel="books" if self.venue == "okx" else "R0",
            depth=400 if self.venue == "okx" else 25,
            duration_seconds=60,
            max_messages=2000,
            max_bytes=32_000_000,
            max_frame_bytes=8_000_000,
            queue_capacity=1024,
            max_orders=800 if self.venue == "okx" else 100000,
            retries=0,
            idle_seconds=5,
        )
        scenario = PaperExecutionScenario(
            venue=self.venue,
            instrument_id=dimension.instrument_id,
            entry_delay_us=1000,
            cancel_delay_us=2000,
            adverse=self.price("0.50", dimension),
            fee_rate=Decimal("0.001"),
            take_fraction=Decimal("0.5"),
            gas_inapplicable_reason="Off-chain spot matching without blockchain activity.",
        )
        return PaperServiceSource(
            name=f"{asset.lower()}-book",
            capture=capture,
            scenario=scenario,
            freshness_us=30_000_000,
            market_interval_us=3_000_000,
        )

    def service_configuration(self) -> PaperServiceConfiguration:
        """Select two formulas on a shared BTC book and one isolated BTC formula."""
        sources = (
            self.source("BTC", self.dimensions[0]),
            self.source("ETH", self.dimensions[1]),
        )
        definitions: tuple[
            tuple[str, str, str, Literal["fixed_clip", "liquidity_clip"], Dimension], ...
        ] = (
            ("shared-fixed-btc", "shared", "btc-book", "fixed_clip", self.dimensions[0]),
            (
                "shared-liquidity-btc",
                "shared",
                "btc-book",
                "liquidity_clip",
                self.dimensions[0],
            ),
            ("shared-fixed-eth", "shared", "eth-book", "fixed_clip", self.dimensions[1]),
            ("isolated-fixed-btc", "isolated", "btc-book", "fixed_clip", self.dimensions[0]),
        )
        instances = tuple(
            PaperServiceInstance(
                instance_id=name,
                account_id=account_id,
                source=source,
                policy=policy,
                quantity=self.quantity("2", dimension),
                lot=self.quantity("1", dimension),
                maximum_fee=self.money("2"),
            )
            for name, account_id, source, policy, dimension in definitions
        )
        return PaperServiceConfiguration(
            accounts=tuple(
                PaperServiceAccount(
                    account_id=account_id,
                    configuration=self.account_configuration(account_id),
                    socket_path=str(self.socket_root / f"{account_id}.sock"),
                )
                for account_id in ("shared", "isolated")
            ),
            sources=sources,
            instances=instances,
            active=("shared-fixed-btc", "shared-liquidity-btc", "isolated-fixed-btc"),
            revision=1,
            duration_seconds=45,
        )

    @staticmethod
    def successor(initial: PaperServiceConfiguration) -> PaperServiceConfiguration:
        """Activate the pre-provisioned ETH instance without changing account budgets."""
        return PaperServiceConfiguration(
            accounts=initial.accounts,
            sources=initial.sources,
            instances=initial.instances,
            active=(*initial.active, "shared-fixed-eth"),
            revision=initial.revision + 1,
            previous_sha256=initial.identity,
            duration_seconds=initial.duration_seconds,
            poll_seconds=initial.poll_seconds,
            worker_timeout_seconds=initial.worker_timeout_seconds,
            alert_socket=initial.alert_socket,
        )

    def policy_identity(
        self,
        service: PaperServiceConfiguration,
        instance: PaperServiceInstance,
        source: PaperServiceSource,
    ) -> str:
        """Match the installed service's selected policy constructor exactly."""
        if self.implementation is None:
            raise ValueError("policy identity requires the installed release")
        factory = ReferenceClipPolicy if instance.policy == "fixed_clip" else LiquidityClipPolicy
        return factory(
            instance.quantity,
            source.scenario.adverse.currency,
            instance.lot,
            tick=service.instance_limits(instance).tick,
            implementation=self.implementation,
        ).identity

    def input_identity(self, source: PaperServiceSource) -> str:
        """Pin one native capture and stable feature requirement to its input digest."""
        inputs = ServiceBookInputs((), source.freshness_us, source.market_interval_us)
        return hashlib.sha256(
            self.codec.encode_json((source.capture, inputs.requirement, inputs.identity))
        ).hexdigest()

    def deployment(
        self,
        account: PaperServiceAccount,
        service: PaperServiceConfiguration,
        releases: tuple[str, ...],
    ) -> PaperDeployment:
        """Sign all provisioned policies, including a later selectable ETH instance."""
        definitions = tuple(
            item for item in service.instances if item.account_id == account.account_id
        )
        sources = {item.name: item for item in service.sources}
        primary = sources[definitions[0].source]
        strategies = tuple(
            PaperStrategyIdentity(
                instance_id=item.instance_id,
                policy_identity=self.policy_identity(service, item, sources[item.source]),
                candidate_identity="paper-services-reference",
                model_identity="rule-only",
                feature_identity=ServiceBookInputs(
                    (),
                    sources[item.source].freshness_us,
                    sources[item.source].market_interval_us,
                ).identity,
            )
            for item in definitions
        )
        return PaperDeployment(
            account_id=account.account_id,
            configuration_sha256=hashlib.sha256(
                self.codec.encode_json(account.configuration)
            ).hexdigest(),
            releases=releases,
            strategies=strategies,
            input_identity=self.input_identity(primary),
            scenario=primary.scenario,
            state_identity="paper-account-state",
            submission_authority=self.mode,
            additional_sources=(
                tuple(
                    PaperSourceBinding(
                        instance_id=item.instance_id,
                        input_identity=self.input_identity(sources[item.source]),
                        scenario=sources[item.source].scenario,
                    )
                    for item in definitions[1:]
                    if item.source != definitions[0].source
                )
                if account.account_id == "shared"
                else ()
            ),
        )

    def authorization(self, deployment: PaperDeployment, at: datetime) -> PaperAuthorization:
        """Grant finite count, notional and quantity for each signed instrument."""
        return PaperAuthorization(
            identity=f"{deployment.account_id}-{self.venue}-session",
            deployment_sha256=deployment.identity,
            valid_from=at - timedelta(minutes=1),
            expires_at=at + timedelta(hours=1),
            quantities=tuple(
                self.quantity("100", scenario.adverse.per) for scenario in deployment.scenarios
            ),
            maximum_order_notional=self.money("1000"),
            maximum_orders=80,
            submission_authority=self.mode,
        )

    @staticmethod
    def fixture_transports(
        service: PaperServiceConfiguration,
        *,
        frame_count: int = 12,
        interval_seconds: float = 1.25,
        start_high: frozenset[str] = frozenset(),
    ) -> dict[str, CaptureTransport]:
        """Inject one independent venue-native transport per selected source."""
        if not start_high.issubset(source.name for source in service.sources):
            raise ValueError("native fixture source is not configured")
        return {
            source.name: NativeBookFixture(
                source,
                frame_count=frame_count,
                interval_seconds=interval_seconds,
                start_high=source.name in start_high,
            )
            for source in service.sources
        }

    def opening_observation(self, account_id: str, at: datetime) -> AccountObservation:
        """Supply a flat independently authored account observation for installation."""
        return AccountObservation(
            identity=f"{account_id}-{self.venue}-opening",
            at=at,
            snapshot=AccountSnapshot(
                account_id=account_id,
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

    def first_touch_oracle(self) -> dict[str, object]:
        """State hand-calculated first eligible BTC fill economics at ask 100.

        The second native book repeats ask 100. Its four displayed units permit
        two modeled units per account at the one-half take fraction. The shared
        physical order attributes one unit to each strategy; the isolated order
        attributes two units to its sole strategy. Adverse price is 100.50 and
        physical fee is 0.1% of 201, rounded to the currency's minor unit.
        """
        if self.mode == "shadow":
            return {
                "shared": (self.money("100000"), self.money("0"), ()),
                "isolated": (self.money("100000"), self.money("0"), ()),
                "attributed": (),
            }
        fee = self.money("0.201" if self.venue == "okx" else "0.20")
        cash = self.money("99798.799" if self.venue == "okx" else "99798.80")
        return {
            "shared": (cash, fee, (self.quantity("2", self.dimensions[0]),)),
            "isolated": (cash, fee, (self.quantity("2", self.dimensions[0]),)),
            "attributed": (
                ("shared-fixed-btc", self.quantity("1", self.dimensions[0])),
                ("shared-liquidity-btc", self.quantity("1", self.dimensions[0])),
                ("isolated-fixed-btc", self.quantity("2", self.dimensions[0])),
            ),
        }

    def install_and_claim(
        self,
        account: PaperServiceAccount,
        deployment: PaperDeployment,
        authorization: PaperAuthorization,
        *,
        launcher: Path,
        target: Path,
        policy: Path,
        requests: Path,
    ) -> PaperOwner:
        """Install one signed account, reconcile opening facts and claim its owner."""
        deployment.require_configuration(account.configuration)
        deployment.require_authorization(authorization)
        installed = InstalledPaperAccount(
            config=account.configuration,
            launcher=launcher,
            target=target,
            policy=policy,
            requests=requests,
        )
        retained = installed.execute(
            AccountExecutionRequest(action="install_paper", deployment=deployment)
        )
        if (
            len(retained.paper_activations) != 1
            or retained.paper_activations[0].deployment != deployment
        ):
            raise ValueError("signed account did not retain the disabled deployment")
        installed.execute(
            AccountExecutionRequest(action="authorize_paper", authorization=authorization)
        )
        stopped = installed.accounts()[0]
        if stopped.phase != "stopped" or stopped.active_control_identity is None:
            raise ValueError("signed account did not retain its disabled stop")
        observed_at = datetime.now(UTC)
        for scenario in deployment.scenarios:
            installed.observe(
                AccountQuote(price=self.price("100", scenario.adverse.per), at=observed_at)
            )
        if not installed.reconcile(self.opening_observation(account.account_id, datetime.now(UTC))):
            raise ValueError("signed account opening reconciliation differed")
        claimed = installed.execute(
            AccountExecutionRequest(
                action="claim_paper",
                account_id=account.account_id,
                owner_id=f"{self.venue}-{account.account_id}-worker",
                control=AccountControl(
                    identity=f"{self.venue}-{account.account_id}-start",
                    account_id=account.account_id,
                    kind="restart",
                    at=datetime.now(UTC),
                    expected_control_identity=stopped.active_control_identity,
                ),
            )
        )
        if claimed.claimed_owner is None:
            raise ValueError("signed account did not claim an owner")
        return claimed.claimed_owner

    def prepare(self, output: Path) -> dict[str, object]:
        """Emit stable account and scheduling definitions before release construction."""
        output.mkdir(parents=True, exist_ok=False)
        service = self.service_configuration()
        successor = self.successor(service)
        successor.require_successor(service)
        for account in service.accounts:
            (output / f"account-{account.account_id}.json").write_bytes(
                self.codec.encode_json(account.configuration)
            )
        (output / "services-initial.json").write_bytes(self.codec.encode_json(service))
        (output / "services-addition.json").write_bytes(self.codec.encode_json(successor))
        summary: dict[str, object] = {
            "schema_version": "multi-instance-paper-preparation",
            "venue": self.venue,
            "mode": self.mode,
            "implementation": "resolved-after-signed-install",
            "initial_selection": service.identity,
            "addition_selection": successor.identity,
            "accounts": tuple(
                (
                    item.account_id,
                    hashlib.sha256(self.codec.encode_json(item.configuration)).hexdigest(),
                )
                for item in service.accounts
            ),
            "sources": tuple(
                (item.name, self.input_identity(item), item.scenario.identity)
                for item in service.sources
            ),
            "strategies": tuple(
                (item.instance_id, item.policy, item.source) for item in service.instances
            ),
            "opening_cash": self.money("100000"),
            "reference_touch": (
                self.price("99", self.dimensions[0]),
                self.price("100", self.dimensions[0]),
                self.quantity("4", self.dimensions[0]),
            ),
            "first_touch_oracle": self.first_touch_oracle(),
        }
        (output / "preparation.json").write_bytes(self.codec.encode_json(summary))
        return summary

    def finalize(self, output: Path, releases: tuple[str, ...]) -> dict[str, object]:
        """Add disabled deployments and grants after signed release identities exist."""
        service = self.codec.decode_json(
            (output / "services-initial.json").read_bytes(), PaperServiceConfiguration
        )
        self.implementation = InstalledIdentity.sha256()
        at = datetime.now(UTC)
        records: list[tuple[str, str, str]] = []
        for account in service.accounts:
            deployment = self.deployment(account, service, releases)
            deployment.require_configuration(account.configuration)
            authorization = self.authorization(deployment, at)
            deployment.require_authorization(authorization)
            (output / f"deployment-{account.account_id}.json").write_bytes(
                self.codec.encode_json(deployment)
            )
            (output / f"authorization-{account.account_id}.json").write_bytes(
                self.codec.encode_json(authorization)
            )
            records.append((account.account_id, deployment.identity, authorization.identity))
        summary: dict[str, object] = {
            "schema_version": "multi-instance-paper-authority",
            "venue": self.venue,
            "releases": releases,
            "accounts": tuple(records),
        }
        (output / "authority.json").write_bytes(self.codec.encode_json(summary))
        return summary


class _Arguments(argparse.Namespace):
    """Hold preparation and signing inputs from the installed test driver."""

    venue: Literal["okx", "bitfinex"]
    mode: Literal["paper", "shadow"]
    output: Path
    socket_root: Path
    finalize: bool
    release_identity: list[str]


def main() -> None:
    """Write the configured venue workload, then add signed authority when available."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venue", choices=("okx", "bitfinex"), required=True)
    parser.add_argument("--mode", choices=("paper", "shadow"), default="paper")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--socket-root", type=Path, required=True)
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--release-identity", action="append")
    args = parser.parse_args(namespace=_Arguments())
    workload = PaperServiceWorkload(
        args.venue,
        opening_at=datetime.now(UTC) - timedelta(seconds=5),
        socket_root=args.socket_root,
        mode=args.mode,
    )
    summary = (
        workload.finalize(args.output, tuple(args.release_identity or ()))
        if args.finalize
        else workload.prepare(args.output)
    )
    print(DomainCodec().encode_json(summary).decode())


if __name__ == "__main__":
    main()
