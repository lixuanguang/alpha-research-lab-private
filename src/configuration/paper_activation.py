"""Separate installed paper identity from explicitly bounded simulation authority."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from typing import Literal

# third party library imports
import msgspec

# project library imports
from configuration.accounts import AccountConfiguration
from configuration.paper import PaperExecutionScenario
from financial_units import Money, Quantity
from serialization import DomainCodec, WireRecord


class PaperStrategyIdentity(WireRecord, frozen=True):
    """Bind one instance to immutable policy, candidate/model and feature identities."""

    instance_id: str
    policy_identity: str
    candidate_identity: str
    model_identity: str
    feature_identity: str

    def __post_init__(self) -> None:
        """Require explicit identities, including an explicit no-model selection."""
        for value in (
            self.instance_id,
            self.policy_identity,
            self.candidate_identity,
            self.model_identity,
            self.feature_identity,
        ):
            if type(value) is not str or not value.strip():
                raise ValueError("paper strategy identity is incomplete")


class PaperSourceBinding(WireRecord, frozen=True):
    """Bind one strategy instance to its public input and paper mechanics."""

    instance_id: str
    input_identity: str
    scenario: PaperExecutionScenario

    def __post_init__(self) -> None:
        """Require an identified source and a complete spot scenario."""
        if (
            type(self.instance_id) is not str
            or not self.instance_id.strip()
            or type(self.input_identity) is not str
            or not self.input_identity.strip()
        ):
            raise ValueError("paper source binding requires instance and input identities")
        if type(self.scenario) is not PaperExecutionScenario:
            raise TypeError("paper source binding requires an execution scenario")
        self.scenario.__post_init__()


class PaperDeployment(WireRecord, frozen=True):
    """Describe compatible installed code and state without granting permission to trade.

    Release identities are signed release-manifest digests verified by the signed
    launcher. Compatible rollback code must be listed before authorization; every
    other binding remains exact. A new manifest cannot replace an existing one.
    """

    account_id: str
    configuration_sha256: str
    releases: tuple[str, ...]
    strategies: tuple[PaperStrategyIdentity, ...]
    input_identity: str
    scenario: PaperExecutionScenario
    state_identity: str
    enabled: bool = False
    submission_authority: Literal["paper", "shadow"] = "paper"
    state_schema: Literal["account-journal-v4"] = "account-journal-v4"
    schema_version: Literal["paper-deployment-v1"] = "paper-deployment-v1"
    additional_sources: tuple[PaperSourceBinding, ...] | msgspec.UnsetType = msgspec.UNSET

    def __post_init__(self) -> None:
        """Reject production flags, missing bindings and incompatible state readers."""
        if (
            self.enabled is not False
            or self.submission_authority not in ("paper", "shadow")
            or self.state_schema != "account-journal-v4"
            or self.schema_version != "paper-deployment-v1"
            or type(self.account_id) is not str
            or not self.account_id
            or type(self.input_identity) is not str
            or not self.input_identity
            or self.state_identity != "paper-account-state-v1"
            or type(self.releases) is not tuple
            or not self.releases
            or len(set(self.releases)) != len(self.releases)
            or type(self.strategies) is not tuple
            or not self.strategies
        ):
            raise ValueError("paper deployment must be disabled and explicitly bound")
        for digest in (self.configuration_sha256, *self.releases):
            self.require_digest(digest)
        for strategy in self.strategies:
            if type(strategy) is not PaperStrategyIdentity:
                raise TypeError("paper deployment requires strategy identities")
            strategy.__post_init__()
        if len({item.instance_id for item in self.strategies}) != len(self.strategies):
            raise ValueError("paper deployment requires distinct instances")
        if type(self.scenario) is not PaperExecutionScenario:
            raise TypeError("paper deployment requires an execution scenario")
        self.scenario.__post_init__()
        if self.additional_sources is not msgspec.UNSET:
            if type(self.additional_sources) is not tuple:
                raise TypeError("paper deployment requires source bindings")
            if not self.additional_sources:
                raise ValueError("paper deployment omits empty source overrides")
            selected = {item.instance_id for item in self.strategies[1:]}
            seen: set[str] = set()
            for source in self.additional_sources:
                if type(source) is not PaperSourceBinding:
                    raise TypeError("paper deployment requires source bindings")
                source.__post_init__()
                if source.instance_id not in selected or source.instance_id in seen:
                    raise ValueError("paper deployment source instance differs")
                if (source.input_identity, source.scenario) == (self.input_identity, self.scenario):
                    raise ValueError("paper deployment source override is redundant")
                seen.add(source.instance_id)
        by_instrument: dict[object, tuple[str, PaperExecutionScenario]] = {}
        for source in self.source_bindings:
            instrument_id = source.scenario.instrument_id
            prior = by_instrument.get(instrument_id)
            if prior is not None and prior != (source.input_identity, source.scenario):
                raise ValueError("paper deployment instrument source differs")
            by_instrument[instrument_id] = (source.input_identity, source.scenario)

    @property
    def source_bindings(self) -> tuple[PaperSourceBinding, ...]:
        """Resolve each strategy's exact source, defaulting to the deployment's shared scope."""
        extras = () if self.additional_sources is msgspec.UNSET else self.additional_sources
        overrides = {item.instance_id: item for item in extras}
        return tuple(
            overrides.get(
                strategy.instance_id,
                PaperSourceBinding(
                    instance_id=strategy.instance_id,
                    input_identity=self.input_identity,
                    scenario=self.scenario,
                ),
            )
            for strategy in self.strategies
        )

    @property
    def scenarios(self) -> tuple[PaperExecutionScenario, ...]:
        """Expose each distinct instrument scenario in signed strategy order."""
        scenarios: list[PaperExecutionScenario] = []
        for source in self.source_bindings:
            if source.scenario.instrument_id not in {
                scenario.instrument_id for scenario in scenarios
            }:
                scenarios.append(source.scenario)
        return tuple(scenarios)

    def scope_for(self, instance_id: str) -> PaperSourceBinding:
        """Resolve one installed strategy's signed instrument and input scope."""
        self.__post_init__()
        for source in self.source_bindings:
            if source.instance_id == instance_id:
                return source
        raise ValueError("paper deployment instance differs")

    @property
    def identity(self) -> str:
        """Identify all compatible code, policy, input, configuration and state bindings."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    def require_configuration(self, config: AccountConfiguration) -> None:
        """Check exact configuration and owned spot instruments before installing state."""
        if (
            config.mode != self.submission_authority
            or self.configuration_sha256
            != hashlib.sha256(DomainCodec().encode_json(config)).hexdigest()
            or self.account_id not in {account.account_id for account in config.accounts}
        ):
            raise ValueError("paper deployment configuration differs")
        for strategy in self.strategies:
            scenario = self.scope_for(strategy.instance_id).scenario
            if not any(
                owner.instance_id == strategy.instance_id
                and owner.account_id == self.account_id
                and scenario.instrument_id in owner.instruments
                for owner in config.budgets.instances
            ):
                raise ValueError("paper deployment instance or instrument differs")

    def require_authorization(self, authorization: PaperAuthorization) -> None:
        """Require a grant bounded to every signed instrument and quote currency."""
        if (
            authorization.submission_authority != self.submission_authority
            or {quantity.dimension for quantity in authorization.quantities}
            != {scenario.adverse.per for scenario in self.scenarios}
            or any(
                scenario.adverse.currency != authorization.maximum_order_notional.currency
                for scenario in self.scenarios
            )
        ):
            raise ValueError("paper_authorization_instrument_or_currency_differs")

    @staticmethod
    def require_digest(value: str) -> None:
        """Require a canonical SHA-256 identity at an administrative boundary."""
        if (
            type(value) is not str
            or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
        ):
            raise ValueError("paper identity requires SHA-256")


class PaperAuthorization(WireRecord, frozen=True):
    """Authorize finite simulated gross size and order count for one exact deployment.

    Quantity limits bound lifetime admitted buy quantities per instrument, including
    pending or uncertain orders. Selling does not replenish the budget. Independent
    account/instance risk limits and funded reservations remain authoritative.
    """

    identity: str
    deployment_sha256: str
    valid_from: datetime
    expires_at: datetime
    quantities: tuple[Quantity, ...]
    maximum_order_notional: Money
    maximum_orders: int
    submission_authority: Literal["paper", "shadow"] = "paper"
    schema_version: Literal["paper-authorization-v1"] = "paper-authorization-v1"

    def __post_init__(self) -> None:
        """Require explicit positive bounds and a half-open UTC validity interval."""
        self._require_utc(self.valid_from, field_name="paper authorization start")
        self._require_utc(self.expires_at, field_name="paper authorization expiry")
        PaperDeployment.require_digest(self.deployment_sha256)
        if (
            type(self.identity) is not str
            or not self.identity
            or self.submission_authority not in ("paper", "shadow")
            or self.schema_version != "paper-authorization-v1"
            or self.expires_at <= self.valid_from
            or type(self.quantities) is not tuple
            or not self.quantities
            or type(self.maximum_orders) is not int
            or self.maximum_orders <= 0
        ):
            raise ValueError("invalid bounded paper authorization")
        self.maximum_order_notional.model_copy()
        if self.maximum_order_notional.value <= 0:
            raise ValueError("paper authorization requires a positive notional bound")
        for quantity in self.quantities:
            quantity.model_copy()
            if quantity.value <= 0:
                raise ValueError("paper authorization requires positive quantity limits")
        if len({q.dimension for q in self.quantities}) != len(self.quantities):
            raise ValueError("paper authorization instrument limits must be distinct")
