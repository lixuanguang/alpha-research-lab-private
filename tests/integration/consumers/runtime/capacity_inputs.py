"""Prepare four independently signed paper accounts and bounded native load."""

from __future__ import annotations

# standard library imports
import asyncio
import hashlib
import os
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import ClassVar, Literal

# third party library imports
import msgspec
from paper_services import PaperServiceWorkload

# project library imports
from configuration import (
    AccountConfiguration,
    OpeningAccount,
    PaperAuthorization,
    PaperDeployment,
    PaperServiceAccount,
    PaperServiceConfiguration,
    PaperServiceInstance,
    PaperServiceSource,
)
from execution import PaperOwner
from financial_units import Dimension, Money, Quantity
from market_data.collection import CaptureTransport
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from runtime import InstalledIdentity
from serialization import DomainCodec

type CapacityVariant = Literal["base", "quiet", "oversize", "backpressure", "reconnect"]


class CapacityNativeFixture:
    """Emit finite venue-native frames on a fixed monotonic schedule.

    The first open fixes the schedule anchor. A reconnect keeps that anchor, so
    slow receipt or recovery cannot make an authored backlog disappear. Each
    source emits 3,250 slots: 25 Hz for 40 seconds, 100 Hz for 10 seconds,
    then 25 Hz for 50 seconds. Fault variants are separate input identities.
    """

    frame_count = 3250
    burst_start = 1000
    burst_end = 2000
    reconnect_slot = 1250
    adverse_slot = 500
    ask_shift_start = 115
    ask_shift_end = 140
    codec: ClassVar[DomainCodec] = DomainCodec()

    def __init__(
        self,
        source: PaperServiceSource,
        *,
        variant: CapacityVariant = "base",
        start_high: bool = False,
        epoch_path: Path | None = None,
    ) -> None:
        """Retain only picklable native source definitions and a named fault variant."""
        source.__post_init__()
        if source.capture.venue not in ("okx", "bitfinex") or variant not in (
            "base",
            "quiet",
            "oversize",
            "backpressure",
            "reconnect",
        ):
            raise ValueError("capacity fixture requires a supported source and variant")
        if type(start_high) is not bool:
            raise ValueError("capacity recovery state must be explicit")
        if epoch_path is not None and (
            not isinstance(epoch_path, Path) or not epoch_path.is_absolute()
        ):
            raise ValueError("capacity epoch marker requires an absolute path")
        self.source, self.variant, self.start_high = source, variant, start_high
        self.epoch_path = epoch_path
        self.index = 0
        self.epoch = 0
        self.phase = 0
        self.sequence = 0
        self.started_at: float | None = None
        self.last_source_ms = 0

    @property
    def identity(self) -> str:
        """Identify source, fixed schedule, native shape and selected fault mode."""
        return self._identity(self.start_high)

    @property
    def active_identity(self) -> str:
        """Identify the actual low or high snapshot selected for this connection."""
        return self._identity(self.start_high or self.epoch > 1)

    def _identity(self, high: bool) -> str:
        """Hash the predeclared native input mode independently of local marker path."""
        return hashlib.sha256(
            self.codec.encode_json(
                (
                    "capacity-native-v1",
                    self.source.capture,
                    self.frame_count,
                    self.burst_start,
                    self.burst_end,
                    self.variant,
                    high,
                )
            )
        ).hexdigest()

    @classmethod
    def elapsed_seconds(cls, index: int) -> float:
        """Return the authored monotonic offset of one socket-message slot."""
        if type(index) is not int or not 0 <= index < cls.frame_count:
            raise ValueError("capacity slot lies outside the finite schedule")
        if index < cls.burst_start:
            return index / 25
        if index < cls.burst_end:
            return 40 + (index - cls.burst_start) / 100
        return 50 + (index - cls.burst_end) / 25

    async def open(self, timeout: float) -> CapacityNativeFixture:
        """Open a fresh native subscription epoch without resetting authored time."""
        if timeout <= 0:
            raise ValueError("capacity fixture requires positive connection timeout")
        if self.epoch_path is not None:
            marker_epoch, anchor = self._claim_epoch()
            if self.started_at is not None and self.started_at != anchor:
                raise ValueError("capacity restart marker changed the authored schedule")
            self.started_at = anchor
        else:
            marker_epoch = 1
            if self.started_at is None:
                self.started_at = asyncio.get_running_loop().time()
        self.epoch = max(self.epoch + 1, marker_epoch)
        self.phase = 0
        self.sequence = 0
        return self

    def _claim_epoch(self) -> tuple[int, float]:
        """Persist first open and schedule anchor across a fresh spawned source."""
        if self.epoch_path is None:
            raise ValueError("capacity epoch marker was not configured")
        path = self.epoch_path
        path.parent.mkdir(parents=True, exist_ok=True)
        anchor_ns = time.monotonic_ns()
        marker = f"{self.identity}\n{anchor_ns}\n".encode()
        try:
            with path.open("xb") as stream:
                stream.write(marker)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            retained = path.read_bytes()
            fields = retained.splitlines()
            if len(fields) != 2 or fields[0] != self.identity.encode() or not fields[1].isdigit():
                raise ValueError("capacity restart marker differs from predeclared input") from None
            retained_ns = int(fields[1])
            if (
                retained != f"{self.identity}\n{retained_ns}\n".encode()
                or retained_ns <= 0
                or retained_ns > anchor_ns
            ):
                raise ValueError("capacity restart marker has an invalid monotonic anchor")
            return 2, retained_ns / 1_000_000_000
        return 1, anchor_ns / 1_000_000_000

    async def send(self, message: str) -> None:
        """Accept public subscription and ping only; reject private requests."""
        if (
            not isinstance(message, str)
            or "auth" in message.casefold()
            or "order" in message.casefold()
        ):
            raise ValueError("private or malformed request reached public capacity fixture")

    async def recv(self) -> bytes:
        """Receive one scheduled frame, retaining overdue slots without delay."""
        if self.started_at is None:
            raise ValueError("capacity fixture must open before receipt")
        if self.index == self.frame_count:
            await asyncio.sleep(101)
            raise OSError("finite capacity fixture exhausted")
        index = self.index
        elapsed = self.elapsed_seconds(index)
        if self.variant == "quiet" and index >= self.adverse_slot:
            elapsed += 10
        if self.variant == "backpressure" and self.adverse_slot <= index < 2700:
            elapsed = self.elapsed_seconds(self.adverse_slot)
        delay = self.started_at + elapsed - asyncio.get_running_loop().time()
        if delay > 0:
            await asyncio.sleep(delay)
        self.index += 1
        if self.variant == "reconnect" and index == self.reconnect_slot:
            raise OSError("authored public-feed disconnect")
        if self.variant == "oversize" and index == self.adverse_slot:
            return b"x" * (self.source.capture.max_frame_bytes + 1)
        self.last_source_ms = max(self.last_source_ms, time.time_ns() // 1_000_000)
        return self._native_frame(self.last_source_ms)

    async def close(self) -> None:
        """Close the scripted epoch without changing the global schedule."""

    def snapshot(self) -> bytes:
        """Refuse REST fallback for both WebSocket-snapshot feeds."""
        raise ValueError("capacity fixture has no REST snapshot")

    def _native_frame(self, timestamp_ms: int) -> bytes:
        """Build one acknowledged native control, full snapshot or increment."""
        venue = self.source.capture.venue
        symbol = self.source.capture.symbol
        phase = self.phase
        self.phase += 1
        high = self.start_high or self.epoch > 1
        if venue == "bitfinex":
            if phase == 0:
                return b'{"event":"conf","status":"OK","flags":65536}'
            if phase == 1:
                return self.codec.encode_json(
                    {
                        "event": "subscribed",
                        "chanId": 7,
                        "channel": "book",
                        "symbol": symbol,
                        "prec": "R0",
                        "freq": "F0",
                        "len": "25",
                    }
                )
            self.sequence += 1
            if phase == 2:
                bids = [
                    [item + 1, str(Decimal("99") - Decimal("0.01") * item), 4] for item in range(25)
                ]
                bitfinex_asks = [
                    [
                        item + 26,
                        str(Decimal("104" if high else "100") + Decimal("0.01") * item),
                        -4,
                    ]
                    for item in range(25)
                ]
                return self.codec.encode_json([7, [*bids, *bitfinex_asks], self.sequence])
            if self.index % 100 == 0:
                return self.codec.encode_json([7, "hb", self.sequence])
            if not high and self.ask_shift_start <= self.index < self.ask_shift_end:
                offset = self.index - self.ask_shift_start
                return self.codec.encode_json(
                    [
                        7,
                        [offset + 26, str(Decimal("104") + Decimal("0.01") * offset), -4],
                        self.sequence,
                    ]
                )
            amount = -5 if self.index % 2 else -4
            ask_price = "104.24" if high or self.index >= self.ask_shift_end else "100.24"
            return self.codec.encode_json([7, [50, ask_price, amount], self.sequence])
        argument = {"channel": "books", "instId": symbol}
        if phase == 0:
            return self.codec.encode_json({"event": "subscribe", "arg": argument})
        if phase == 1:
            self.sequence = 10
            bids = [
                [str(Decimal("99") - Decimal("0.01") * item), "4", "0", "1"] for item in range(400)
            ]
            okx_asks = [
                [
                    str(Decimal("104" if high else "100") + Decimal("0.01") * item),
                    "4",
                    "0",
                    "1",
                ]
                for item in range(400)
            ]
            row = {
                "prevSeqId": -1,
                "seqId": self.sequence,
                "ts": str(timestamp_ms),
                "bids": bids,
                "asks": okx_asks,
            }
            return self.codec.encode_json({"arg": argument, "action": "snapshot", "data": [row]})
        if self.index % 100 == 0:
            return b"pong"
        previous = self.sequence
        self.sequence += 1
        if not high and self.index == self.ask_shift_start:
            removals = [
                [str(Decimal("100") + Decimal("0.01") * item), "0", "0", "0"] for item in range(400)
            ]
            additions = [
                [str(Decimal("104") + Decimal("0.01") * item), "4", "0", "1"] for item in range(400)
            ]
            update_asks = [*removals, *additions]
        else:
            ask_price = "104.24" if high or self.index > self.ask_shift_start else "100.24"
            update_asks = [[ask_price, "5" if self.index % 2 else "4", "0", "1"]]
        row = {
            "prevSeqId": previous,
            "seqId": self.sequence,
            "ts": str(timestamp_ms),
            "bids": [],
            "asks": update_asks,
        }
        return self.codec.encode_json({"arg": argument, "action": "update", "data": [row]})

    def authored_distribution(self) -> dict[str, object]:
        """Predeclare exact base-frame sizes using a 13-digit UTC millisecond clock."""
        if self.variant != "base" or self.index or self.phase:
            raise ValueError("capacity distribution requires an unused base fixture")
        sizes: list[int] = []
        for index in range(self.frame_count):
            self.index = index + 1
            sizes.append(len(self._native_frame(1_700_000_000_000)))
        self.index, self.phase, self.sequence = 0, 0, 0
        ordered = sorted(sizes)
        total = sum(sizes)
        return {
            "messages": self.frame_count,
            "encoded_bytes": total,
            "mean_bytes": total / self.frame_count,
            "p99_frame_bytes": ordered[(99 * self.frame_count + 99) // 100 - 1],
            "max_frame_bytes": ordered[-1],
            "first_slot_seconds": 0,
            "last_slot_seconds": self.elapsed_seconds(self.frame_count - 1),
            "burst_seconds": (40, 50),
            "base_hz": 25,
            "burst_hz": 100,
        }


class CapacityWorkload:
    """Own combined account definitions, signed inputs and finite fixture selection."""

    venues: ClassVar[tuple[Literal["okx"], Literal["bitfinex"]]] = ("okx", "bitfinex")

    def __init__(
        self,
        *,
        opening_at: datetime,
        socket_root: Path,
        mode: Literal["paper", "shadow"] = "paper",
    ) -> None:
        """Bind four venue-scoped accounts to explicit local socket locations."""
        AccountConfiguration._require_utc(opening_at, field_name="capacity opening")
        if not socket_root.is_absolute() or mode not in ("paper", "shadow"):
            raise ValueError("capacity workload requires absolute sockets and paper/shadow mode")
        self.opening_at, self.socket_root, self.mode = opening_at, socket_root, mode
        self.codec = DomainCodec()
        self.venue_workloads = {
            venue: PaperServiceWorkload(
                venue,
                opening_at=opening_at,
                socket_root=socket_root,
                mode=mode,
            )
            for venue in self.venues
        }

    def venue_workload(self, venue: str) -> PaperServiceWorkload:
        """Reject an account/source outside the two signed venue namespaces."""
        if venue == "okx":
            return self.venue_workloads["okx"]
        if venue == "bitfinex":
            return self.venue_workloads["bitfinex"]
        raise ValueError("capacity account or source has unknown venue")

    def _account_configuration(
        self, venue: Literal["okx", "bitfinex"], role: Literal["shared", "isolated"]
    ) -> AccountConfiguration:
        """Keep MR14 cash, risk and budget numbers for one independently signed owner."""
        workload = self.venue_workloads[venue]
        dimension = workload.dimensions[0 if role == "shared" else 1]
        asset = "btc" if role == "shared" else "eth"
        account_id = f"{venue}-{role}"
        return AccountConfiguration(
            mode=self.mode,
            opening_at=self.opening_at,
            accounts=(OpeningAccount(account_id=account_id, cash=(workload.money("100000"),)),),
            instruments=(
                SpotLimits(
                    maximum=workload.quantity("100", dimension),
                    lot=workload.quantity("1", dimension),
                    tick=workload.price("0.01", dimension),
                    product="spot",
                ),
            ),
            budgets=BudgetPolicy(
                valuation_currency=workload.currency,
                firm_maximum=workload.money("10000"),
                accounts=(AccountLimit(account_id=account_id, maximum=workload.money("10000")),),
                instances=tuple(
                    InstanceLimit(
                        instance_id=f"{account_id}-{policy}-{asset}",
                        account_id=account_id,
                        maximum=workload.money("5000"),
                        instruments=(dimension.instrument_id,),
                    )
                    for policy in ("fixed", "liquidity")
                ),
                max_quote_age_us=30_000_000,
                max_state_age_us=120_000_000,
                max_price_deviation_bps=500,
                max_order_notional=workload.money("1000"),
            ),
        )

    def service_configuration(self) -> PaperServiceConfiguration:
        """Select four native sources, four owners and two active policies per owner."""
        accounts: list[PaperServiceAccount] = []
        sources: list[PaperServiceSource] = []
        instances: list[PaperServiceInstance] = []
        policies: tuple[tuple[str, Literal["fixed_clip", "liquidity_clip"]], ...] = (
            ("fixed", "fixed_clip"),
            ("liquidity", "liquidity_clip"),
        )
        for venue in self.venues:
            workload = self.venue_workloads[venue]
            roles: tuple[
                tuple[Literal["shared", "isolated"], Literal["BTC", "ETH"], Dimension], ...
            ] = (
                ("shared", "BTC", workload.dimensions[0]),
                ("isolated", "ETH", workload.dimensions[1]),
            )
            for role, asset, dimension in roles:
                account_id = f"{venue}-{role}"
                native = workload.source(asset, dimension)
                source_name = f"{venue}-{asset.lower()}-book"
                capture = msgspec.structs.replace(
                    native.capture,
                    duration_seconds=100,
                    max_messages=5000,
                    max_bytes=33_554_432,
                    max_frame_bytes=8_000_000,
                    queue_capacity=2048,
                    retries=1,
                )
                sources.append(
                    PaperServiceSource(
                        name=source_name,
                        capture=capture,
                        scenario=native.scenario,
                        freshness_us=native.freshness_us,
                        market_interval_us=native.market_interval_us,
                    )
                )
                accounts.append(
                    PaperServiceAccount(
                        account_id=account_id,
                        configuration=self._account_configuration(venue, role),
                        socket_path=str(self.socket_root / f"{account_id}.sock"),
                    )
                )
                for name, policy in policies:
                    instances.append(
                        PaperServiceInstance(
                            instance_id=f"{account_id}-{name}-{asset.lower()}",
                            account_id=account_id,
                            source=source_name,
                            policy=policy,
                            quantity=workload.quantity("2", dimension),
                            lot=workload.quantity("1", dimension),
                            maximum_fee=workload.money("2"),
                        )
                    )
        service = PaperServiceConfiguration(
            accounts=tuple(accounts),
            sources=tuple(sources),
            instances=tuple(instances),
            active=tuple(item.instance_id for item in instances),
            revision=1,
            duration_seconds=75,
        )
        service.__post_init__()
        return service

    def fixture_transports(
        self,
        service: PaperServiceConfiguration,
        *,
        variant: CapacityVariant = "base",
        exclude_venue: Literal["okx", "bitfinex"] | None = None,
        start_high: frozenset[str] = frozenset(),
        epoch_root: Path | None = None,
    ) -> dict[str, CaptureTransport]:
        """Select native fixture transports; leave one venue for observed public routes."""
        expected = self.service_configuration()
        if (
            service != expected
            or exclude_venue not in (None, "okx", "bitfinex")
            or not start_high.issubset(source.name for source in service.sources)
            or (epoch_root is not None and not epoch_root.is_absolute())
        ):
            raise ValueError("capacity fixture requires the exact prepared service")
        return {
            source.name: CapacityNativeFixture(
                source,
                variant=variant,
                start_high=source.name in start_high,
                epoch_path=None if epoch_root is None else epoch_root / f"{source.name}.epoch",
            )
            for source in service.sources
            if source.capture.venue != exclude_venue
        }

    def prepare(self, output: Path) -> dict[str, object]:
        """Write immutable input definitions and native byte distribution before release."""
        output.mkdir(parents=True, exist_ok=False)
        service = self.service_configuration()
        (output / "services-initial.json").write_bytes(self.codec.encode_json(service))
        for account in service.accounts:
            (output / f"account-{account.account_id}.json").write_bytes(
                self.codec.encode_json(account.configuration)
            )
        variants: tuple[CapacityVariant, ...] = (
            "base",
            "quiet",
            "oversize",
            "backpressure",
            "reconnect",
        )
        summary: dict[str, object] = {
            "schema_version": "runtime-capacity-preparation-v1",
            "mode": self.mode,
            "implementation": "resolved-after-signed-install",
            "selection": service.identity,
            "accounts": tuple(
                (
                    account.account_id,
                    hashlib.sha256(self.codec.encode_json(account.configuration)).hexdigest(),
                )
                for account in service.accounts
            ),
            "sources": tuple(
                (
                    source.name,
                    self.venue_workload(source.capture.venue).input_identity(source),
                    CapacityNativeFixture(source).identity,
                    CapacityNativeFixture(source).authored_distribution(),
                )
                for source in service.sources
            ),
            "fixture_variants": tuple(
                (
                    source.name,
                    tuple(
                        (variant, CapacityNativeFixture(source, variant=variant).identity)
                        for variant in variants
                    ),
                    CapacityNativeFixture(source, start_high=True).identity,
                )
                for source in service.sources
            ),
            "strategies": tuple(
                (instance.instance_id, instance.policy, instance.source)
                for instance in service.instances
            ),
            "account_service_seconds": 120,
            "capture_seconds": 100,
            "supervisor_seconds": 75,
            "minimum_steady_seconds": 60,
            "startup_skew_max_seconds": 20,
        }
        (output / "preparation.json").write_bytes(self.codec.encode_json(summary))
        return summary

    def finalize(self, output: Path, releases: tuple[str, ...]) -> dict[str, object]:
        """Bind each account to an independently verified release and finite grant."""
        service = self.codec.decode_json(
            (output / "services-initial.json").read_bytes(), PaperServiceConfiguration
        )
        if service != self.service_configuration():
            raise ValueError("capacity configuration differs from prepared identity")
        implementation = InstalledIdentity.sha256()
        for workload in self.venue_workloads.values():
            workload.implementation = implementation
        at = datetime.now(UTC)
        records: list[tuple[str, str, str]] = []
        for account in service.accounts:
            venue = account.account_id.split("-", maxsplit=1)[0]
            workload = self.venue_workload(venue)
            deployment = workload.deployment(account, service, releases)
            deployment.require_configuration(account.configuration)
            authorization = workload.authorization(deployment, at)
            deployment.require_authorization(authorization)
            (output / f"deployment-{account.account_id}.json").write_bytes(
                self.codec.encode_json(deployment)
            )
            (output / f"authorization-{account.account_id}.json").write_bytes(
                self.codec.encode_json(authorization)
            )
            records.append((account.account_id, deployment.identity, authorization.identity))
        summary: dict[str, object] = {
            "schema_version": "runtime-capacity-authority-v1",
            "releases": releases,
            "accounts": tuple(records),
        }
        (output / "authority.json").write_bytes(self.codec.encode_json(summary))
        return summary

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
        """Claim one venue's separately signed paper account using MR14 controls."""
        venue = account.account_id.split("-", maxsplit=1)[0]
        return self.venue_workload(venue).install_and_claim(
            account,
            deployment,
            authorization,
            launcher=launcher,
            target=target,
            policy=policy,
            requests=requests,
        )

    def first_touch_oracle(self) -> dict[str, tuple[Money, Money, tuple[Quantity, ...]]]:
        """Return independent two-unit, one-physical-order paper economics per owner."""
        result: dict[str, tuple[Money, Money, tuple[Quantity, ...]]] = {}
        for venue in self.venues:
            workload = self.venue_workloads[venue]
            fee = workload.money("0.201" if venue == "okx" else "0.20")
            cash = workload.money("99798.799" if venue == "okx" else "99798.80")
            for role, dimension in (
                ("shared", workload.dimensions[0]),
                ("isolated", workload.dimensions[1]),
            ):
                result[f"{venue}-{role}"] = (
                    cash if self.mode == "paper" else workload.money("100000"),
                    fee if self.mode == "paper" else workload.money("0"),
                    (workload.quantity("2", dimension),) if self.mode == "paper" else (),
                )
        return result
