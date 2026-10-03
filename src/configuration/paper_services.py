"""Select bounded local paper services without changing installed account authority."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec

# project library imports
from configuration.accounts import SERVICE_LIFE_MAXIMUM_SECONDS, AccountConfiguration
from configuration.capture import CaptureConfig
from configuration.paper import PaperExecutionScenario
from configuration.paper_activation import PaperDeployment
from financial_units import Money, Quantity
from risk import SpotLimits
from serialization import DomainCodec, WireRecord


class PaperServiceAccount(WireRecord, frozen=True):
    """Locate one independently installed account owner and its exact configuration."""

    account_id: str
    configuration: AccountConfiguration
    socket_path: str

    def __post_init__(self) -> None:
        """Keep each local service and its atomic budget in one explicit journal scope."""
        if type(self.configuration) is not AccountConfiguration:
            raise TypeError("paper service requires a typed account configuration")
        self.configuration.__post_init__()
        if (
            self.configuration.mode not in ("paper", "shadow")
            or tuple(item.account_id for item in self.configuration.accounts) != (self.account_id,)
            or not Path(self.socket_path).is_absolute()
            or len(self.socket_path.encode()) > 100
            or "\0" in self.socket_path
        ):
            raise ValueError("paper service requires one account and an absolute local socket")


class PaperSourceChain(WireRecord, frozen=True):
    """Bound one source's whole segment-chain recording; the capture bounds each segment."""

    max_messages: int
    max_bytes: int
    max_segments: int

    def __post_init__(self) -> None:
        """Keep the whole run inside the collector's finite run-window ceilings."""
        for value, minimum, maximum in (
            (self.max_messages, 1, 100_000_000),
            (self.max_bytes, 8192, 160 * 1024**3),
            (self.max_segments, 1, 512),
        ):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError("invalid finite paper source chain limit")


class PaperServiceSource(WireRecord, frozen=True):
    """Bind a native feed, paper matching assumptions and admission cadence.

    With ``chain`` the source records one rolled-over segment chain per recording;
    without it, one finite journal, exactly as before.
    """

    name: str
    capture: CaptureConfig
    scenario: PaperExecutionScenario
    freshness_us: int
    market_interval_us: int = 3_000_000
    # Omitted from the encoding when unset, so earlier selections keep their bytes.
    chain: PaperSourceChain | msgspec.UnsetType = msgspec.UNSET

    def __post_init__(self) -> None:
        """Reject ambiguous venue, instrument, currency and source freshness routing."""
        if (
            type(self.capture) is not CaptureConfig
            or type(self.scenario) is not PaperExecutionScenario
        ):
            raise TypeError("paper source requires typed capture and execution definitions")
        self.capture.__post_init__()
        self.scenario.__post_init__()
        if (
            not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", self.name)
            or self.capture.venue != self.scenario.venue
            or self.capture.instrument_id != self.scenario.instrument_id
            or self.capture.quote_currency != self.scenario.adverse.currency.code
            or type(self.freshness_us) is not int
            or not 0 < self.freshness_us <= 30_000_000
            or type(self.market_interval_us) is not int
            or not 0
            < self.market_interval_us
            <= min(self.freshness_us, self.capture.idle_seconds * 1_000_000)
        ):
            raise ValueError("paper source route or freshness is incompatible")
        if self.chain is not msgspec.UNSET:
            if type(self.chain) is not PaperSourceChain:
                raise TypeError("paper source chain requires typed run limits")
            self.chain.__post_init__()
            if (
                self.capture.venue not in ("okx", "bitfinex")
                or self.capture.retries > 32
                or self.chain.max_bytes < self.capture.max_frame_bytes * 2 + 8192
            ):
                raise ValueError("paper source chain is incompatible with its capture")


class PaperServiceInstance(WireRecord, frozen=True):
    """Provision one reference policy independently of the active scheduling selection."""

    instance_id: str
    account_id: str
    source: str
    policy: Literal["fixed_clip", "liquidity_clip"]
    quantity: Quantity
    lot: Quantity
    maximum_fee: Money

    def __post_init__(self) -> None:
        """Require a named installed reference formula and exact positive clip parameters."""
        if (
            type(self.quantity) is not Quantity
            or type(self.lot) is not Quantity
            or type(self.maximum_fee) is not Money
        ):
            raise TypeError("paper service instance requires exact quantity and money")
        self.quantity.model_copy()
        self.lot.model_copy()
        self.maximum_fee.model_copy()
        if (
            any(
                not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", name)
                for name in (self.instance_id, self.account_id, self.source)
            )
            or self.policy not in ("fixed_clip", "liquidity_clip")
            or self.quantity.dimension != self.lot.dimension
            or self.quantity.value <= 0
            or self.lot.value <= 0
            or self.maximum_fee.value < 0
        ):
            raise ValueError("invalid paper service instance")


class PaperServiceConfiguration(WireRecord, frozen=True):
    """Select active instances within an immutable, separately authorized service envelope.

    A controlled restart can revise ``active`` and bounded invocation settings while
    incrementing ``revision`` and naming the prior complete configuration digest.
    Definitions and account budgets remain exact; this is not economic-state migration.
    """

    accounts: tuple[PaperServiceAccount, ...]
    sources: tuple[PaperServiceSource, ...]
    instances: tuple[PaperServiceInstance, ...]
    active: tuple[str, ...]
    revision: int
    previous_sha256: str | None = None
    duration_seconds: int = 90
    poll_seconds: int = 1
    worker_timeout_seconds: int = 2
    alert_socket: str | None = None
    schema_version: Literal["paper-services"] = "paper-services"

    def __post_init__(self) -> None:
        """Validate all definitions, budgets and scheduling bounds before spawning work."""
        if (
            self.schema_version != "paper-services"
            or any(
                type(items) is not tuple or not items
                for items in (self.accounts, self.sources, self.instances, self.active)
            )
            or type(self.revision) is not int
            or self.revision < 1
            or type(self.duration_seconds) is not int
            or not 1 <= self.duration_seconds <= SERVICE_LIFE_MAXIMUM_SECONDS
            or self.poll_seconds != 1
            or self.worker_timeout_seconds != 2
        ):
            raise ValueError("invalid bounded paper service selection")
        if self.previous_sha256 is not None:
            PaperDeployment.require_digest(self.previous_sha256)
        if (self.revision == 1) != (self.previous_sha256 is None):
            raise ValueError("paper selection requires an explicit predecessor")
        if self.alert_socket is not None and (
            not Path(self.alert_socket).is_absolute() or len(self.alert_socket.encode()) > 100
        ):
            raise ValueError("paper alerts require a bounded absolute local socket")
        for account_definition in self.accounts:
            if type(account_definition) is not PaperServiceAccount:
                raise TypeError("paper selection requires typed account services")
            account_definition.__post_init__()
            # The supervisor never outlives the signed life of an account owner it uses.
            if self.duration_seconds > account_definition.configuration.service_life_limit:
                raise ValueError("paper supervisor outlives an account service life")
        for source_definition in self.sources:
            if type(source_definition) is not PaperServiceSource:
                raise TypeError("paper selection requires typed source services")
            source_definition.__post_init__()
        for instance_definition in self.instances:
            if type(instance_definition) is not PaperServiceInstance:
                raise TypeError("paper selection requires typed instances")
            instance_definition.__post_init__()
        if len(self.accounts) > 4 or len(self.sources) > 8 or len(self.instances) > 16:
            raise ValueError("paper selection exceeds the supported local process envelope")
        accounts = {item.account_id: item for item in self.accounts}
        sources = {item.name: item for item in self.sources}
        instances = {item.instance_id: item for item in self.instances}
        if (
            len(accounts) != len(self.accounts)
            or len(sources) != len(self.sources)
            or len(instances) != len(self.instances)
            or len(set(self.active)) != len(self.active)
            or not set(self.active).issubset(instances)
            or len({item.socket_path for item in self.accounts}) != len(self.accounts)
            or len({(item.capture.venue, item.capture.instrument_id) for item in self.sources})
            != len(self.sources)
        ):
            raise ValueError("duplicate or unknown paper service selection")
        for instance in self.instances:
            account, source = accounts.get(instance.account_id), sources.get(instance.source)
            if account is None or source is None:
                raise ValueError("unknown paper instance account or source")
            owner = next(
                (
                    item
                    for item in account.configuration.budgets.instances
                    if item.instance_id == instance.instance_id
                ),
                None,
            )
            limits = next(
                (
                    item
                    for item in account.configuration.instruments
                    if item.maximum.dimension == instance.quantity.dimension
                ),
                None,
            )
            if (
                owner is None
                or owner.account_id != instance.account_id
                or source.scenario.instrument_id not in owner.instruments
                or instance.quantity.dimension != source.scenario.adverse.per
                or instance.maximum_fee.currency != source.scenario.adverse.currency
                or limits is None
                or limits.lot != instance.lot
                or source.freshness_us > account.configuration.budgets.max_quote_age_us
            ):
                raise ValueError("paper instance exceeds its installed account definition")

    def instance_limits(self, instance: PaperServiceInstance) -> SpotLimits:
        """Return the installed account limits that govern one instance's instrument.

        Raises:
            ValueError: The instance is not part of this validated selection.
        """
        if instance not in self.instances:
            raise ValueError("unknown paper instance")
        account = next(item for item in self.accounts if item.account_id == instance.account_id)
        return next(
            item
            for item in account.configuration.instruments
            if item.maximum.dimension == instance.quantity.dimension
        )

    @property
    def identity(self) -> str:
        """Pin the complete selected invocation independently of account configuration."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    def require_successor(self, previous: PaperServiceConfiguration) -> None:
        """Allow selection-only revisions without reinterpreting any retained state."""
        if self == previous:
            return
        if (
            self.previous_sha256 != previous.identity
            or self.revision != previous.revision + 1
            or self.accounts != previous.accounts
            or self.sources != previous.sources
            or self.instances != previous.instances
        ):
            raise ValueError("paper service revision changes immutable definitions or ancestry")
