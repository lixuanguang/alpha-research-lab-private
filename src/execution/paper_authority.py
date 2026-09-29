"""Fence managed paper effects under the account journal's durable transaction."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from fractions import Fraction
from typing import TYPE_CHECKING

# third party library imports
from msgspec.structs import replace

# project library imports
from configuration import PaperAuthorization, PaperDeployment
from execution.account_records import AccountControl, AccountDecision
from serialization import WireRecord

if TYPE_CHECKING:
    # project library imports
    from execution.account_operations import AccountOperations
    from execution.account_state import _AccountTransaction


class PaperOwner(WireRecord, frozen=True):
    """Carry a replaceable worker's exact durable authority and recovery generation."""

    account_id: str
    deployment_sha256: str
    authorization_id: str
    release_identity: str
    owner_id: str
    generation: int

    def __post_init__(self) -> None:
        """Reject incomplete fencing tokens before crossing the journal boundary."""
        for value in (self.account_id, self.authorization_id, self.owner_id):
            if type(value) is not str or not value:
                raise ValueError("paper owner requires explicit identities")
        PaperDeployment.require_digest(self.deployment_sha256)
        PaperDeployment.require_digest(self.release_identity)
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("paper owner requires a positive generation")


class PaperActivation(WireRecord, frozen=True):
    """Retain disabled deployment, grant/revocation and worker ownership separately."""

    deployment: PaperDeployment
    changed_at: datetime
    authorization: PaperAuthorization | None = None
    revoked: tuple[str, ...] = ()
    authorizations: tuple[PaperAuthorization, ...] = ()
    owner: PaperOwner | None = None
    generation: int = 0

    def __post_init__(self) -> None:
        """Validate every durable binding on state restoration."""
        self.deployment.__post_init__()
        self._require_utc(self.changed_at, field_name="paper activation change")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("invalid paper generation")
        if type(self.revoked) is not tuple or len(set(self.revoked)) != len(self.revoked):
            raise ValueError("invalid paper revocation history")
        if type(self.authorizations) is not tuple or len(
            {item.identity for item in self.authorizations}
        ) != len(self.authorizations):
            raise ValueError("invalid paper authorization history")
        for historical in self.authorizations:
            historical.__post_init__()
            if historical.deployment_sha256 != self.deployment.identity:
                raise ValueError("paper authorization history deployment differs")
            self.deployment.require_authorization(historical)
        if self.authorization is not None:
            self.authorization.__post_init__()
            if self.authorization.deployment_sha256 != self.deployment.identity:
                raise ValueError("paper authorization deployment differs")
            self.deployment.require_authorization(self.authorization)
        if self.owner is not None:
            self.owner.__post_init__()
            if (
                self.owner.deployment_sha256 != self.deployment.identity
                or self.owner.account_id != self.deployment.account_id
                or self.owner.release_identity not in self.deployment.releases
                or self.owner.generation != self.generation
                or self.authorization is None
                or self.owner.authorization_id != self.authorization.identity
            ):
                raise ValueError("paper owner differs from durable activation")

    def require_authority(self, at: datetime) -> PaperAuthorization:
        """Require current non-revoked permission using a half-open validity interval."""
        self._require_utc(at, field_name="paper authority check")
        grant = self.authorization
        if grant is None:
            raise ValueError("paper_authorization_absent")
        if grant.identity in self.revoked:
            raise ValueError("paper_authorization_revoked")
        if not grant.valid_from <= at < grant.expires_at:
            raise ValueError("paper_authorization_expired_or_not_yet_valid")
        return grant


class PaperAuthority:
    """Check generation and authorization within the same lock as economic effects."""

    @staticmethod
    def find(transaction: _AccountTransaction, account_id: str) -> PaperActivation | None:
        """Resolve the account's sole immutable deployment."""
        return next(
            (
                item
                for item in transaction.state.paper_activations
                if item.deployment.account_id == account_id
            ),
            None,
        )

    @staticmethod
    def save(transaction: _AccountTransaction, value: PaperActivation) -> None:
        """Replace only one account's activation and require the managed state reader.

        A v2 journal is promoted to v3; a v4 journal records activation only by
        the presence of the activation itself.
        """
        value.__post_init__()
        values = tuple(
            item
            for item in transaction.state.paper_activations
            if item.deployment.account_id != value.deployment.account_id
        )
        activations: tuple[PaperActivation, ...] = (*values, value)
        transaction.state = replace(
            transaction.state,
            paper_activations=activations,
            schema_version=(
                "account-journal-v4"
                if transaction.state.schema_version == "account-journal-v4"
                else "account-journal-v3"
            ),
        )

    @classmethod
    def require_owner(
        cls,
        transaction: _AccountTransaction,
        account_id: str,
        owner: PaperOwner | None,
        *,
        at: datetime,
        new_exposure: bool,
    ) -> PaperActivation | None:
        """Reject missing/replaced workers; expiry blocks new exposure but not obligations."""
        activation = cls.find(transaction, account_id)
        if activation is None:
            if owner is not None:
                raise ValueError("paper_deployment_absent")
            return None
        if transaction.state.paper_restore_quarantine:
            raise ValueError("paper_restore_requires_current_retained_journal")
        if owner is None or activation.owner != owner:
            raise ValueError("paper_owner_stale_or_absent")
        if at < activation.changed_at:
            raise ValueError("paper_owner_clock_regressed")
        if new_exposure:
            activation.require_authority(at)
        return activation

    @classmethod
    def require_decision(
        cls,
        transaction: _AccountTransaction,
        request: AccountDecision,
        owner: PaperOwner | None,
        *,
        now: datetime,
    ) -> None:
        """Check authority and instance/instrument identity before staging new orders."""
        activation = cls.require_owner(
            transaction,
            request.account_id,
            owner,
            at=now,
            new_exposure=True,
        )
        if activation is None:
            return
        activation.require_authority(request.decision.at)
        try:
            source = activation.deployment.scope_for(request.instance_id)
        except ValueError as error:
            raise ValueError("paper_authorization_scope_differs") from error
        if (
            request.quote.price.per != source.scenario.adverse.per
            or request.quote.price.currency != source.scenario.adverse.currency
        ):
            raise ValueError("paper_authorization_scope_differs")

    @classmethod
    def require_limits(cls, transaction: _AccountTransaction, account_id: str) -> None:
        """Bound lifetime admitted children, counting pending/uncertain buys conservatively."""
        activation = cls.find(transaction, account_id)
        if activation is None or activation.authorization is None:
            return
        grant = activation.authorization
        selected = {item.instance_id for item in activation.deployment.strategies}
        reduction_ids = {
            order.identity for saved in transaction.state.paper_reductions for order in saved.orders
        }
        orders = tuple(
            item.order
            for item in transaction.state.orders
            if item.account_id == account_id
            and item.instance_id in selected
            and item.order.identity not in reduction_ids
        )
        if len(orders) > grant.maximum_orders:
            raise ValueError("paper_authorization_order_limit")
        for order in orders:
            intent = order.intent
            if intent.limit.currency != grant.maximum_order_notional.currency or Fraction(
                intent.quantity.value
            ) * Fraction(intent.limit.value) > Fraction(grant.maximum_order_notional.value):
                raise ValueError("paper_authorization_notional_limit")
            maximum = next(
                (q for q in grant.quantities if q.dimension == intent.quantity.dimension), None
            )
            if maximum is None:
                raise ValueError("paper_authorization_instrument_limit")
            bought = sum(
                (
                    Fraction(item.intent.quantity.value)
                    for item in orders
                    if item.intent.side == "buy"
                    and item.intent.quantity.dimension == maximum.dimension
                ),
                Fraction(0),
            )
            if bought > Fraction(maximum.value):
                raise ValueError("paper_authorization_quantity_limit")

    @classmethod
    def claim(
        cls,
        transaction: _AccountTransaction,
        *,
        account_id: str,
        owner_id: str,
        release_identity: str,
        control: AccountControl,
        operations: AccountOperations,
        now: datetime,
    ) -> PaperOwner:
        """Reconcile/restart under existing controls before issuing a replacement generation."""
        activation = cls.find(transaction, account_id)
        if activation is None:
            raise ValueError("paper_deployment_absent")
        if transaction.state.paper_restore_quarantine:
            raise ValueError("paper_restore_requires_current_retained_journal")
        grant = activation.require_authority(now)
        activation.require_authority(control.at)
        if release_identity not in activation.deployment.releases:
            raise ValueError("paper_release_incompatible")
        if (
            now < activation.changed_at
            or control.at > now
            or control.account_id != account_id
            or control.kind != "restart"
        ):
            raise ValueError("paper_claim_requires_current_restart")
        if any(
            saved.request.identity == control.identity
            for saved in transaction.state.account_controls
        ):
            raise ValueError("paper_claim_requires_fresh_restart")
        result = operations.apply(transaction, control)
        if result.status != "applied":
            raise ValueError(result.reason or "paper_recovery_rejected")
        owner = PaperOwner(
            account_id=account_id,
            deployment_sha256=activation.deployment.identity,
            authorization_id=grant.identity,
            release_identity=release_identity,
            owner_id=owner_id,
            generation=activation.generation + 1,
        )
        cls.save(
            transaction,
            replace(
                activation,
                owner=owner,
                generation=owner.generation,
                changed_at=now,
            ),
        )
        return owner
