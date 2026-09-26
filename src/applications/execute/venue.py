"""Run bounded authenticated test-venue operations through the durable gateway."""

from __future__ import annotations

# standard library imports
import os
from pathlib import Path
from typing import Literal

# project library imports
from applications.execute.accounts import AccountExecutionRequest
from configuration import VenueAuthorization, VenueExecutionConfiguration
from execution import (
    AccountJournal,
    AccountView,
    BitfinexSpotAdapter,
    GatewayView,
    NetOrder,
    OKXSpotAdapter,
    PortfolioCommit,
    PrivateVenueSession,
    StepCommit,
    TaggedOrder,
    TlsVenueHttpTransport,
    VenueAdapter,
    VenueCredentials,
    VenueGateway,
)
from serialization import DomainCodec, WireRecord

type VenueAction = Literal[
    "inspect", "quote", "admit", "coordinate", "reconcile", "submit", "cancel", "stream"
]


class VenueApplicationResult(WireRecord, frozen=True):
    """Return transport state and the optional local account-admission outcome."""

    gateway: GatewayView
    accounts: tuple[AccountView, ...]
    orders: tuple[TaggedOrder, ...]
    net_orders: tuple[NetOrder, ...]
    admission: StepCommit | None = None
    portfolio: PortfolioCommit | None = None
    quote_observed: bool = False

    def __post_init__(self) -> None:
        """Keep local outcomes typed without inferring an external venue fill."""
        if type(self.gateway) is not GatewayView or type(self.quote_observed) is not bool:
            raise ValueError("invalid venue application result")
        if self.admission is not None:
            self.admission.__post_init__()
        if self.portfolio is not None:
            self.portfolio.__post_init__()
        for account in self.accounts:
            account.__post_init__()
        for order in self.orders:
            order.__post_init__()
        for parent in self.net_orders:
            parent.__post_init__()


class VenueExecutionApplication:
    """Bind installed files and test credentials to one durable account gateway."""

    def __init__(self, adapter: VenueAdapter | None = None) -> None:
        """Accept an injected adapter for deterministic installed boundary tests."""
        self._adapter = adapter

    def run(
        self,
        *,
        config_path: Path,
        journal_path: Path,
        action: VenueAction = "inspect",
        request_path: Path | None = None,
        authorization_path: Path | None = None,
        order_id: str | None = None,
        max_messages: int | None = None,
        duration_seconds: float | None = None,
    ) -> VenueApplicationResult:
        """Validate bounded files and dispatch exactly one venue operation.

        Only non-inspection operations resolve environment credential values.
        Submission and cancellation require an independently supplied envelope.
        """
        codec = DomainCodec()
        config = codec.decode_json(self._read(config_path), VenueExecutionConfiguration)
        config.__post_init__()
        if action not in (
            "inspect",
            "quote",
            "admit",
            "coordinate",
            "reconcile",
            "submit",
            "cancel",
            "stream",
        ):
            raise ValueError("unsupported venue action")
        if action in ("quote", "admit", "coordinate"):
            if request_path is None:
                raise ValueError("local venue account action requires a request")
            request = codec.decode_json(self._read(request_path), AccountExecutionRequest)
            request.__post_init__()
            if request.action != action:
                raise ValueError("venue request action differs from selected local action")
        else:
            if request_path is not None:
                raise ValueError("venue transport action cannot use a local request")
            request = None
        if action in ("submit", "cancel"):
            if authorization_path is None or order_id is None or not order_id:
                raise ValueError("venue order action requires authorization and order identity")
            authorization = codec.decode_json(self._read(authorization_path), VenueAuthorization)
            authorization.__post_init__()
        else:
            if authorization_path is not None or order_id is not None:
                raise ValueError("venue read action cannot use order authorization")
            authorization = None
        if action == "stream":
            if (
                type(max_messages) is not int
                or max_messages <= 0
                or type(duration_seconds) is not float
                or duration_seconds <= 0
                or duration_seconds > 3600
            ):
                raise ValueError("venue stream requires bounded message count and duration")
        elif max_messages is not None or duration_seconds is not None:
            raise ValueError("stream bounds require the stream action")
        journal = AccountJournal(journal_path, config.account)
        adapter = self._adapter
        if action in ("reconcile", "submit", "cancel", "stream") and adapter is None:
            adapter = self._native_adapter(config)
        gateway = VenueGateway(journal, config, adapter)
        if action == "inspect":
            return self._result(journal, gateway.inspect())
        if action == "quote":
            if request is None or request.quote is None:
                raise ValueError("venue quote request is incomplete")
            if request.quote.price.per not in {item.dimension for item in config.instruments}:
                raise ValueError("venue quote instrument is outside account scope")
            journal.observe(request.quote)
            return self._result(journal, gateway.inspect(), quote_observed=True)
        if action == "admit":
            if request is None or request.decision is None:
                raise ValueError("venue admission request is incomplete")
            if request.decision.account_id != config.account_id:
                raise ValueError("venue admission account is outside configured scope")
            admission = journal.admit(request.decision)
            return self._result(journal, gateway.inspect(), admission=admission)
        if action == "coordinate":
            if request is None or request.batch is None:
                raise ValueError("venue portfolio request is incomplete")
            if any(
                item.request.account_id != config.account_id for item in request.batch.decisions
            ):
                raise ValueError("venue portfolio account is outside configured scope")
            portfolio = journal.coordinate(request.batch)
            return self._result(journal, gateway.inspect(), portfolio=portfolio)
        if action == "reconcile":
            return self._result(journal, gateway.reconcile())
        if action == "submit":
            if authorization is None or order_id is None:
                raise ValueError("venue submission requires an authorization")
            return self._result(journal, gateway.submit(order_id, authorization))
        if action == "cancel":
            if authorization is None or order_id is None:
                raise ValueError("venue cancellation requires an authorization")
            return self._result(journal, gateway.cancel(order_id, authorization))
        if max_messages is None or duration_seconds is None:
            raise ValueError("venue stream bounds are incomplete")
        session = PrivateVenueSession(config.venue)
        return self._result(
            journal,
            gateway.stream(session, max_messages=max_messages, duration_seconds=duration_seconds),
        )

    @staticmethod
    def _result(
        journal: AccountJournal,
        gateway: GatewayView,
        *,
        admission: StepCommit | None = None,
        portfolio: PortfolioCommit | None = None,
        quote_observed: bool = False,
    ) -> VenueApplicationResult:
        """Expose the exact durable account state alongside bounded transport facts."""
        return VenueApplicationResult(
            gateway=gateway,
            accounts=journal.accounts(),
            orders=journal.orders(),
            net_orders=journal.net_orders(),
            admission=admission,
            portfolio=portfolio,
            quote_observed=quote_observed,
        )

    @staticmethod
    def _native_adapter(config: VenueExecutionConfiguration) -> VenueAdapter:
        """Resolve secret bytes only for an explicit authenticated operation."""
        references = config.credentials
        api_key = os.environ.get(references.api_key_env)
        api_secret = os.environ.get(references.api_secret_env)
        passphrase = (
            os.environ.get(references.passphrase_env)
            if references.passphrase_env is not None
            else None
        )
        if not api_key or not api_secret or (config.venue == "okx" and not passphrase):
            raise ValueError("required venue credential environment values are absent")
        credentials = VenueCredentials(
            api_key=api_key, api_secret=api_secret, passphrase=passphrase
        )
        transport = TlsVenueHttpTransport(config.venue)
        if config.venue == "okx":
            return OKXSpotAdapter(credentials, transport)
        return BitfinexSpotAdapter(credentials, transport)

    @staticmethod
    def _read(path: Path) -> bytes:
        """Read one bounded config or authorization document before decoding."""
        payload = path.read_bytes()
        if len(payload) > 1_048_576:
            raise ValueError("venue document exceeds one MiB")
        return payload
