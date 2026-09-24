"""Configure the installed intent admission boundary without storing secrets."""

from __future__ import annotations

# standard library imports
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

# project library imports
from configuration.capabilities import CapabilityProfile
from financial_units import Currency, Money, Quantity
from reference_data.catalogs import ReferenceHistory
from serialization import DomainCodec, WireRecord
from strategies import OrderIntent

type ExecutionMode = Literal["research", "paper", "shadow", "production"]


class CredentialReference(WireRecord, frozen=True, kw_only=True):
    """Identify a separately managed credential without carrying its secret bytes."""

    identifier: str
    environment: str
    mode: ExecutionMode

    def __post_init__(self) -> None:
        """Require a bounded reference whose mode and environment can be checked."""
        for value in (self.identifier, self.environment):
            if (
                type(value) is not str
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", value) is None
            ):
                raise ValueError("invalid credential reference")
        if self.mode not in ("research", "paper", "shadow", "production"):
            raise ValueError("invalid credential mode")


class ExecutionInspection(WireRecord, frozen=True, kw_only=True):
    """Report the installed mode and schema without exposing a credential identifier."""

    schema_version: Literal["execution-admission-v1"]
    state_schema: Literal["none-v1"]
    mode: Literal["research", "paper", "shadow"]
    environment: str
    credential_mode: Literal["research", "paper", "shadow"]
    profile: str
    profile_identity: str
    submission_available: Literal[False]

    def __post_init__(self) -> None:
        """Keep inspection aligned with the accepted read-only deployment envelope."""
        if (
            self.schema_version != "execution-admission-v1"
            or self.state_schema != "none-v1"
            or self.mode not in ("research", "paper", "shadow")
            or self.credential_mode != self.mode
            or self.submission_available is not False
        ):
            raise ValueError("invalid execution inspection")
        for value in (self.environment, self.profile, self.profile_identity):
            if (
                type(value) is not str
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", value) is None
            ):
                raise ValueError("invalid execution inspection identity")


class ExecutionConfiguration(WireRecord, frozen=True, kw_only=True):
    """Bind a read-only installed execution profile and evidenced spot reference."""

    schema_version: Literal["execution-admission-v1"] = "execution-admission-v1"
    mode: ExecutionMode
    environment: str
    credential: CredentialReference
    profile: CapabilityProfile
    reference: ReferenceHistory
    maximum: Quantity
    quote_currency: Currency

    def __post_init__(self) -> None:
        """Reject any executable authority or mismatch before reading an intent."""
        if self.schema_version != "execution-admission-v1":
            raise ValueError("unsupported execution configuration schema")
        if self.mode not in ("research", "paper", "shadow"):
            raise ValueError("production submission is unavailable in this package")
        if type(self.credential) is not CredentialReference:
            raise ValueError("execution configuration requires a credential reference")
        self.credential.__post_init__()
        if (
            type(self.environment) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", self.environment) is None
            or self.credential.environment != self.environment
            or self.credential.mode != self.mode
        ):
            raise ValueError("credential reference is outside execution mode or environment")
        if type(self.profile) is not CapabilityProfile:
            raise ValueError("execution configuration requires a capability profile")
        self.profile.__post_init__()
        if (
            self.profile.kind != "execution"
            or self.profile.qualification not in ("fixture", "read_only")
            or "submit" in self.profile.operations
            or "production" in self.profile.modes
            or self.mode not in self.profile.modes
        ):
            raise ValueError("execution profile cannot supply order admission without submission")
        if type(self.reference) is not ReferenceHistory:
            raise ValueError("execution configuration requires reference history")
        self.reference.__post_init__()
        if type(self.maximum) is not Quantity or type(self.quote_currency) is not Currency:
            raise ValueError("execution configuration requires exact financial units")
        self.maximum.model_copy()
        self.quote_currency.validate_currency()

    @classmethod
    def read(cls, path: Path) -> ExecutionConfiguration:
        """Read a bounded signed configuration through the shared exact-value codec."""
        payload = path.read_bytes()
        if len(payload) > 1_048_576:
            raise ValueError("execution configuration exceeds one MiB")
        config = DomainCodec().decode_json(payload, cls)
        config.__post_init__()
        return config

    def inspect(self) -> ExecutionInspection:
        """Expose the configuration's installed mode and empty-state schema."""
        self.__post_init__()
        if self.mode not in ("research", "paper", "shadow") or self.credential.mode not in (
            "research",
            "paper",
            "shadow",
        ):
            raise ValueError("production submission is unavailable in this package")
        return ExecutionInspection(
            schema_version=self.schema_version,
            state_schema="none-v1",
            mode=self.mode,
            environment=self.environment,
            credential_mode=self.credential.mode,
            profile=self.profile.name,
            profile_identity=self.profile.implementation_identity,
            submission_available=False,
        )


class ExecutionRequest(WireRecord, frozen=True, kw_only=True):
    """Carry one limit intent and a separately supplied account snapshot for suppression."""

    requested_mode: ExecutionMode
    intent: OrderIntent
    holding: Quantity
    cash: Money
    maximum_fee: Money
    pending: bool
    valid_at: datetime
    known_at: datetime
    max_reference_age_us: int

    def __post_init__(self) -> None:
        """Validate complete exact economics and causal reference cutoffs."""
        if self.requested_mode not in ("research", "paper", "shadow", "production"):
            raise ValueError("invalid requested mode")
        if type(self.intent) is not OrderIntent:
            raise ValueError("execution request requires a limit order intent")
        self.intent.__post_init__()
        if (
            type(self.holding) is not Quantity
            or type(self.cash) is not Money
            or type(self.maximum_fee) is not Money
        ):
            raise ValueError("execution request requires exact account units")
        self.holding.model_copy()
        self.cash.model_copy()
        self.maximum_fee.model_copy()
        self._require_utc(self.valid_at, field_name="valid at")
        self._require_utc(self.known_at, field_name="known at")
        if (
            self.known_at < self.valid_at
            or type(self.pending) is not bool
            or type(self.max_reference_age_us) is not int
            or self.max_reference_age_us <= 0
            or self.maximum_fee.value < 0
        ):
            raise ValueError("invalid execution request clocks, fee or pending state")

    @classmethod
    def read(cls, path: Path) -> ExecutionRequest:
        """Read a bounded intent separately from the installed configuration."""
        payload = path.read_bytes()
        if len(payload) > 1_048_576:
            raise ValueError("execution request exceeds one MiB")
        request = DomainCodec().decode_json(payload, cls)
        request.__post_init__()
        return request
