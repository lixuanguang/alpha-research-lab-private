"""Select bounded local paper services without changing installed account authority."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

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
    """Bind a native feed, paper matching assumptions and source freshness.

    With ``chain`` the source records one rolled-over segment chain per recording;
    without it, one finite journal. The candidates' decision grids select which
    books match orders. ``trades`` adds the same instrument's public trades feed,
    recorded alongside the book with the same chain limits, for candidates that
    declare trade inputs.
    """

    name: str
    capture: CaptureConfig
    scenario: PaperExecutionScenario
    freshness_us: int
    chain: PaperSourceChain | None = None
    trades: CaptureConfig | None = None

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
        ):
            raise ValueError("paper source route or freshness is incompatible")
        if self.capture.channel == "trades":
            raise ValueError("paper source capture must be a book feed")
        if self.trades is not None:
            if type(self.trades) is not CaptureConfig:
                raise TypeError("paper source trades require a typed capture definition")
            self.trades.__post_init__()
            if self.trades.channel != "trades" or self._route(self.trades) != self._route(
                self.capture
            ):
                raise ValueError("paper source trades must be the same instrument's trades feed")
        if self.chain is not None:
            if type(self.chain) is not PaperSourceChain:
                raise TypeError("paper source chain requires typed run limits")
            self.chain.__post_init__()
            if (
                self.capture.venue not in ("okx", "bitfinex")
                or self.capture.retries > 32
                or self.chain.max_bytes < self.capture.max_frame_bytes * 2 + 8192
                or (
                    self.trades is not None
                    and (
                        self.trades.retries > 32
                        or self.chain.max_bytes < self.trades.max_frame_bytes * 2 + 8192
                    )
                )
            ):
                raise ValueError("paper source chain is incompatible with its capture")

    @staticmethod
    def _route(capture: CaptureConfig) -> tuple[str, str, str, str, str]:
        """Name a feed's venue, native symbol, instrument and currencies."""
        return (
            capture.venue,
            capture.symbol,
            str(capture.instrument_id),
            capture.base_currency,
            capture.quote_currency,
        )


class ReferenceCandidate(WireRecord, frozen=True, tag="reference"):
    """Select one installed reference formula and its UTC decision grid."""

    formula: Literal["fixed_clip", "liquidity_clip", "target_clip"]
    cadence_us: int
    starts_at: datetime

    def __post_init__(self) -> None:
        """Require a named formula and a positive grid with an explicit UTC origin."""
        self._require_utc(self.starts_at, field_name="reference candidate grid origin")
        if (
            self.formula not in ("fixed_clip", "liquidity_clip", "target_clip")
            or type(self.cadence_us) is not int
            or not 0 < self.cadence_us <= 86_400_000_000
        ):
            raise ValueError("invalid reference candidate")


class PackagedCandidate(WireRecord, frozen=True, tag="packaged"):
    """Select one signed candidate bundle and the installed extension providing its code.

    The bundle is read from the paper services release's signed candidates by its
    definition identity; its definition fixes the cadence. ``feature_version`` serves
    the candidate that version's feature-store stream instead of source inputs; the
    bundle must package its feature-store definition.
    """

    definition_sha256: str
    extension: str
    starts_at: datetime
    feature_version: str | None = None

    def __post_init__(self) -> None:
        """Require an exact definition digest, an extension project and a UTC grid origin."""
        self._require_utc(self.starts_at, field_name="packaged candidate grid origin")
        if (
            type(self.definition_sha256) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", self.definition_sha256)
            or type(self.extension) is not str
            or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", self.extension)
            or self.extension.startswith("alpha-research-")
            or (
                self.feature_version is not None
                and (
                    type(self.feature_version) is not str
                    or not self.feature_version
                    or self.feature_version != self.feature_version.strip()
                )
            )
        ):
            raise ValueError("invalid packaged candidate")


class PaperFeatureServing(WireRecord, frozen=True):
    """Bind the feature store, Feast generation root and worker for served candidates.

    The worker is the separately locked Feast environment's command; its first
    element is an absolute executable. Nothing here grants trading authority.
    """

    store_path: str
    serving_root: str
    worker: tuple[str, ...]
    worker_timeout_seconds: int = 10

    def __post_init__(self) -> None:
        """Require absolute paths, an absolute worker executable and a bounded timeout."""
        if (
            any(
                type(value) is not str or not Path(value).is_absolute()
                for value in (self.store_path, self.serving_root)
            )
            or type(self.worker) is not tuple
            or not self.worker
            or any(type(item) is not str or not item for item in self.worker)
            or not Path(self.worker[0]).is_absolute()
            or type(self.worker_timeout_seconds) is not int
            or not 1 <= self.worker_timeout_seconds <= 60
        ):
            raise ValueError("invalid paper feature serving")


class PaperServiceInstance(WireRecord, frozen=True):
    """Provision one candidate independently of the active scheduling selection.

    ``quantity`` and ``lot`` select the instance's instrument limits; a reference
    formula also uses them as its clip.
    """

    instance_id: str
    account_id: str
    source: str
    candidate: ReferenceCandidate | PackagedCandidate
    quantity: Quantity
    lot: Quantity
    maximum_fee: Money

    def __post_init__(self) -> None:
        """Require a typed candidate and exact positive clip parameters."""
        if (
            type(self.candidate) not in (ReferenceCandidate, PackagedCandidate)
            or type(self.quantity) is not Quantity
            or type(self.lot) is not Quantity
            or type(self.maximum_fee) is not Money
        ):
            raise TypeError("paper service instance requires a candidate, quantity and money")
        self.candidate.__post_init__()
        self.quantity.model_copy()
        self.lot.model_copy()
        self.maximum_fee.model_copy()
        if (
            any(
                not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", name)
                for name in (self.instance_id, self.account_id, self.source)
            )
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
    # Diagnostic telemetry cadence; protection reads stay every poll.
    telemetry_seconds: int = 1
    features: PaperFeatureServing | None = None

    @property
    def telemetry_interval(self) -> int:
        """Return the declared diagnostic telemetry cadence in seconds."""
        return self.telemetry_seconds

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
            or type(self.telemetry_seconds) is not int
            or not 1 <= self.telemetry_seconds <= 300
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
        if self.features is not None:
            if type(self.features) is not PaperFeatureServing:
                raise TypeError("paper feature serving requires a typed definition")
            self.features.__post_init__()
        for source_definition in self.sources:
            if type(source_definition) is not PaperServiceSource:
                raise TypeError("paper selection requires typed source services")
            source_definition.__post_init__()
        for instance_definition in self.instances:
            if type(instance_definition) is not PaperServiceInstance:
                raise TypeError("paper selection requires typed instances")
            instance_definition.__post_init__()
        feeds = len(self.sources) + sum(item.trades is not None for item in self.sources)
        if len(self.accounts) > 4 or feeds > 8 or len(self.instances) > 16:
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
                or (
                    type(instance.candidate) is ReferenceCandidate
                    and instance.candidate.cadence_us
                    > min(source.freshness_us, source.capture.idle_seconds * 1_000_000)
                )
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
