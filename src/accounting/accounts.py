"""Reconstruct exact multi-instrument spot accounts from identified postings."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from fractions import Fraction
from typing import Literal

# project library imports
from financial_units import Currency, DecimalGrid, Dimension, Money, Price, Quantity
from serialization import DomainCodec, WireRecord

type EconomicPostingKind = Literal["fill", "fee", "rebate", "transfer"]
type PostingKind = Literal["fill", "fee", "rebate", "transfer", "correction"]


class AccountPosting(WireRecord, frozen=True):
    """Record one source fact or an identified replacement of a prior fact.

    Cash is the signed effect on the physical account, except an asset-denominated
    fee or rebate uses it to retain the exact native charge. In that case
    ``asset_change`` is the physical inventory effect and cash does not move.
    A fill's signed quantity and positive execution price determine its cash
    effect exactly. Quote fees debit cash and rebates credit it.
    A correction replaces the current revision of one original fact atomically;
    an absent replacement kind voids that fact while retaining its history.
    """

    identity: str
    account_id: str
    event_at: datetime
    known_at: datetime
    kind: PostingKind
    cash: Money
    instance_id: str | None = None
    order_id: str | None = None
    quantity: Quantity | None = None
    price: Price | None = None
    asset_change: Quantity | None = None
    corrects: str | None = None
    replacement_kind: EconomicPostingKind | None = None

    def __post_init__(self) -> None:
        """Reject malformed lineage, clocks, units and economic effects."""
        self._require_utc(self.event_at, field_name="posting event")
        self._require_utc(self.known_at, field_name="posting knowledge")
        if (
            type(self.identity) is not str
            or not self.identity
            or type(self.account_id) is not str
            or not self.account_id
            or self.known_at < self.event_at
            or self.kind not in ("fill", "fee", "rebate", "transfer", "correction")
        ):
            raise ValueError("invalid account posting identity, clocks or kind")
        for name, value in (("instance", self.instance_id), ("order", self.order_id)):
            if value is not None and (type(value) is not str or not value):
                raise ValueError(f"invalid {name} identity")
        if type(self.cash) is not Money:
            raise TypeError("account posting requires exact cash")
        self.cash.model_copy()
        if self.quantity is not None:
            if type(self.quantity) is not Quantity:
                raise TypeError("account posting requires exact quantity")
            self.quantity.model_copy()
        if self.price is not None:
            if type(self.price) is not Price:
                raise TypeError("account posting requires exact price")
            self.price.model_copy()
        if self.asset_change is not None:
            if type(self.asset_change) is not Quantity:
                raise TypeError("asset cost requires exact quantity")
            self.asset_change.model_copy()
        effective_kind = self.effective_kind
        if self.kind == "correction":
            if (
                type(self.corrects) is not str
                or not self.corrects
                or self.corrects == self.identity
                or self.replacement_kind not in (None, "fill", "fee", "rebate", "transfer")
            ):
                raise ValueError("correction must reference another posting identity")
        elif self.corrects is not None or self.replacement_kind is not None:
            raise ValueError("only corrections may replace a posting")
        if effective_kind is None:
            if (
                self.cash.value != 0
                or self.quantity is not None
                or self.price is not None
                or self.asset_change is not None
            ):
                raise ValueError("void correction must have zero cash and no fill")
            return
        if effective_kind == "fill":
            if (
                self.instance_id is None
                or self.order_id is None
                or self.quantity is None
                or self.price is None
                or self.quantity.value == 0
                or self.price.value <= 0
                or self.price.per != self.quantity.dimension
                or self.price.currency != self.cash.currency
                or self.asset_change is not None
                or Fraction(self.cash.value)
                != -Fraction(self.price.value) * Fraction(self.quantity.value)
            ):
                raise ValueError("fill requires exact signed cash, quantity, price and order")
        elif self.quantity is not None or self.price is not None:
            raise ValueError("only a fill may carry quantity or price")
        elif self.asset_change is not None and (
            effective_kind not in ("fee", "rebate")
            or self.instance_id is None
            or self.order_id is None
            or Fraction(self.asset_change.value) != Fraction(self.cash.value)
            or (effective_kind == "fee" and self.cash.value >= 0)
            or (effective_kind == "rebate" and self.cash.value <= 0)
        ):
            raise ValueError("asset cost requires an owned, equally signed inventory effect")
        elif effective_kind == "fee" and self.cash.value >= 0:
            raise ValueError("fee must debit cash")
        elif effective_kind == "rebate" and self.cash.value <= 0:
            raise ValueError("rebate must credit cash")
        elif effective_kind == "transfer" and (self.cash.value == 0 or self.order_id is not None):
            raise ValueError("transfer requires nonzero cash and no order")

    @property
    def effective_kind(self) -> EconomicPostingKind | None:
        """Return the economic category after this posting, or None for a void."""
        if self.kind == "correction":
            return self.replacement_kind
        return self.kind


class EffectiveAccountPosting(WireRecord, frozen=True):
    """Expose the latest economic revision under its original source identity."""

    identity: str
    revision_id: str
    account_id: str
    event_at: datetime
    known_at: datetime
    kind: EconomicPostingKind
    cash: Money
    instance_id: str | None = None
    order_id: str | None = None
    quantity: Quantity | None = None
    price: Price | None = None
    asset_change: Quantity | None = None

    def __post_init__(self) -> None:
        """Validate the public effective projection with the posting rules."""
        AccountPosting(
            identity=self.revision_id,
            account_id=self.account_id,
            event_at=self.event_at,
            known_at=self.known_at,
            kind=self.kind,
            cash=self.cash,
            instance_id=self.instance_id,
            order_id=self.order_id,
            quantity=self.quantity,
            price=self.price,
            asset_change=self.asset_change,
        )
        if type(self.identity) is not str or not self.identity:
            raise ValueError("effective posting requires an original identity")


class AccountState(WireRecord, frozen=True):
    """Retain the complete immutable history needed for exact account recovery."""

    account_id: str
    currencies: tuple[Currency, ...]
    postings: tuple[AccountPosting, ...] = ()
    schema_version: str = "account-postings-v1"

    def __post_init__(self) -> None:
        """Require declared currencies and one account's identified facts."""
        if (
            self.schema_version != "account-postings-v1"
            or type(self.account_id) is not str
            or not self.account_id
            or type(self.currencies) is not tuple
            or not self.currencies
            or type(self.postings) is not tuple
        ):
            raise ValueError("invalid account state")
        codes: set[str] = set()
        for currency in self.currencies:
            if type(currency) is not Currency:
                raise TypeError("account state requires exact currencies")
            currency.validate_currency()
            if currency.code in codes:
                raise ValueError("duplicate account currency code")
            codes.add(currency.code)
        identities: set[str] = set()
        for posting in self.postings:
            if type(posting) is not AccountPosting:
                raise TypeError("account state requires account postings")
            posting.__post_init__()
            if posting.account_id != self.account_id or posting.identity in identities:
                raise ValueError("posting account mismatch or duplicate identity")
            identities.add(posting.identity)


class AccountSnapshot(WireRecord, frozen=True):
    """Expose exact currency cash, inventory and posting totals for reconciliation."""

    account_id: str
    instance_id: str | None
    cash: tuple[Money, ...]
    positions: tuple[Quantity, ...]
    fees: tuple[Money, ...]
    rebates: tuple[Money, ...]
    transfers: tuple[Money, ...]
    fill_ids: tuple[str, ...]
    posting_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject malformed externally supplied snapshots."""
        if type(self.account_id) is not str or not self.account_id:
            raise ValueError("snapshot requires an account identity")
        if self.instance_id is not None and (
            type(self.instance_id) is not str or not self.instance_id
        ):
            raise ValueError("invalid snapshot instance identity")
        if any(
            type(values) is not tuple
            for values in (self.cash, self.positions, self.fees, self.rebates, self.transfers)
        ):
            raise TypeError("snapshot values must be immutable tuples")
        for values in (self.cash, self.fees, self.rebates, self.transfers):
            for amount in values:
                if type(amount) is not Money:
                    raise TypeError("snapshot requires exact money")
                amount.model_copy()
        for quantity in self.positions:
            if type(quantity) is not Quantity:
                raise TypeError("snapshot requires exact quantity")
            quantity.model_copy()
        if type(self.fill_ids) is not tuple or type(self.posting_ids) is not tuple:
            raise TypeError("snapshot identities must be immutable tuples")
        if (
            not self.cash
            or len(self.cash) != len(self.fees)
            or len(self.cash) != len(self.rebates)
            or len(self.cash) != len(self.transfers)
        ):
            raise ValueError("snapshot currency totals do not align")
        codes: set[str] = set()
        for cash, fee, rebate, transfer in zip(
            self.cash, self.fees, self.rebates, self.transfers, strict=True
        ):
            if (
                cash.currency.code in codes
                or any(amount.currency != cash.currency for amount in (fee, rebate, transfer))
                or fee.value < 0
                or rebate.value < 0
                or (self.instance_id is None and cash.value < 0)
            ):
                raise ValueError("snapshot has invalid cash or cost totals")
            codes.add(cash.currency.code)
        if any(position.value <= 0 for position in self.positions) or len(
            {position.dimension for position in self.positions}
        ) != len(self.positions):
            raise ValueError("snapshot positions must be distinct and positive")
        for identities in (self.fill_ids, self.posting_ids):
            if any(type(identity) is not str or not identity for identity in identities) or len(
                set(identities)
            ) != len(identities):
                raise ValueError("snapshot identities must be distinct and nonempty")


class AccountLedger:
    """Apply spot account facts atomically and replay corrections without rewriting history."""

    def __init__(self, state: AccountState) -> None:
        """Reconstruct a zero-funded account from its complete ordered history.

        Args:
            state: Declared currencies and all known source postings.

        Raises:
            ValueError: History is incompatible, out of order or unfunded.
        """
        if type(state) is not AccountState:
            raise TypeError("account ledger requires AccountState")
        state.__post_init__()
        self._state = state
        self._effective = self._replay(state)
        self._validate_snapshots(state, self._effective)

    @property
    def state(self) -> AccountState:
        """Return complete immutable restart state."""
        return self._state

    def effective_postings(self) -> tuple[EffectiveAccountPosting, ...]:
        """Return current economic facts under stable original fill identities."""
        return self._effective

    def post(self, posting: AccountPosting) -> AccountSnapshot:
        """Commit one fact or accept only an identical retry without double-booking.

        Args:
            posting: Complete source fact or revision in this account.

        Returns:
            The resulting physical account snapshot.

        Raises:
            ValueError: A conflicting retry or invalid economic state is rejected.
        """
        if type(posting) is not AccountPosting:
            raise TypeError("account ledger requires AccountPosting")
        posting.__post_init__()
        codec = DomainCodec()
        for prior in self._state.postings:
            if prior.identity == posting.identity:
                if codec.encode_json(prior) != codec.encode_json(posting):
                    raise ValueError("conflicting posting retry")
                return self.snapshot()
        candidate = AccountState(
            account_id=self._state.account_id,
            currencies=self._state.currencies,
            postings=(*self._state.postings, posting),
        )
        effective = self._replay(candidate)
        result = self._validate_snapshots(candidate, effective)
        self._state = candidate
        self._effective = effective
        return result

    def snapshot(self, instance_id: str | None = None) -> AccountSnapshot:
        """Project physical balances or one instance's attributed activity.

        Account-level transfers are excluded from an instance's view. Its cash
        attribution may therefore be negative while physical account cash is
        always nonnegative. Only nonzero positions appear in the snapshot.

        Args:
            instance_id: Optional instance whose own postings should be projected.

        Returns:
            Exact balances, cumulative cash-flow categories and current fill IDs.
        """
        return self._snapshot(self._state, self._effective, instance_id)

    @classmethod
    def _validate_snapshots(
        cls, state: AccountState, effective: tuple[EffectiveAccountPosting, ...]
    ) -> AccountSnapshot:
        """Prove every projected balance is representable before state becomes visible."""
        result = cls._snapshot(state, effective, None)
        for instance_id in {
            posting.instance_id for posting in state.postings if posting.instance_id is not None
        }:
            cls._snapshot(state, effective, instance_id)
        return result

    @classmethod
    def _snapshot(
        cls,
        state: AccountState,
        effective: tuple[EffectiveAccountPosting, ...],
        instance_id: str | None,
    ) -> AccountSnapshot:
        """Project a staged state without mutating the live ledger."""
        if instance_id is not None and (type(instance_id) is not str or not instance_id):
            raise ValueError("invalid snapshot instance identity")
        currencies = state.currencies
        cash: dict[str, Fraction] = {currency.code: Fraction(0) for currency in currencies}
        fees = cash.copy()
        rebates = cash.copy()
        transfers = cash.copy()
        positions: dict[Dimension, Fraction] = {}
        fill_ids: list[str] = []
        for effect in effective:
            if instance_id is not None and effect.instance_id != instance_id:
                continue
            code = effect.cash.currency.code
            value = Fraction(effect.cash.value)
            if effect.asset_change is None:
                cash[code] += value
            if effect.kind == "fill":
                if effect.quantity is None:
                    raise ValueError("effective fill lacks quantity")
                dimension = effect.quantity.dimension
                positions[dimension] = positions.get(dimension, Fraction(0)) + Fraction(
                    effect.quantity.value
                )
                fill_ids.append(effect.identity)
            if effect.asset_change is not None:
                dimension = effect.asset_change.dimension
                positions[dimension] = positions.get(dimension, Fraction(0)) + Fraction(
                    effect.asset_change.value
                )
            if effect.kind == "fee":
                fees[code] -= value
            elif effect.kind == "rebate":
                rebates[code] += value
            elif effect.kind == "transfer":
                transfers[code] += value
        posting_ids = tuple(
            posting.identity
            for posting in state.postings
            if instance_id is None or posting.instance_id == instance_id
        )
        return AccountSnapshot(
            account_id=state.account_id,
            instance_id=instance_id,
            cash=tuple(cls._money(cash[currency.code], currency) for currency in currencies),
            positions=tuple(
                Quantity(value=DecimalGrid.exact_decimal(value), dimension=dimension)
                for dimension, value in sorted(positions.items(), key=cls._dimension_order)
                if value
            ),
            fees=tuple(cls._money(fees[currency.code], currency) for currency in currencies),
            rebates=tuple(cls._money(rebates[currency.code], currency) for currency in currencies),
            transfers=tuple(
                cls._money(transfers[currency.code], currency) for currency in currencies
            ),
            fill_ids=tuple(fill_ids),
            posting_ids=posting_ids,
        )

    @staticmethod
    def _money(value: Fraction, currency: Currency) -> Money:
        """Create a bounded exact money value without Decimal context rounding."""
        return Money(value=DecimalGrid.exact_decimal(value), currency=currency)

    @staticmethod
    def _dimension_order(item: tuple[Dimension, Fraction]) -> bytes:
        """Order dimensions by their stable lossless wire representation."""
        return DomainCodec().encode_json(item[0])

    @staticmethod
    def _effect(posting: AccountPosting, root_id: str) -> EffectiveAccountPosting | None:
        """Project a validated posting's current economics under the original ID."""
        kind = posting.effective_kind
        if kind is None:
            return None
        return EffectiveAccountPosting(
            identity=root_id,
            revision_id=posting.identity,
            account_id=posting.account_id,
            event_at=posting.event_at,
            known_at=posting.known_at,
            kind=kind,
            cash=posting.cash,
            instance_id=posting.instance_id,
            order_id=posting.order_id,
            quantity=posting.quantity,
            price=posting.price,
            asset_change=posting.asset_change,
        )

    @staticmethod
    def _adjust(
        effect: EffectiveAccountPosting,
        sign: int,
        cash: dict[str, Fraction],
        positions: dict[Dimension, Fraction],
        instance_positions: dict[tuple[str, Dimension], Fraction],
    ) -> None:
        """Apply or reverse one effective fact in exact running totals."""
        if effect.asset_change is None:
            cash[effect.cash.currency.code] += sign * Fraction(effect.cash.value)
        movement = effect.quantity if effect.quantity is not None else effect.asset_change
        if movement is not None:
            dimension = movement.dimension
            delta = sign * Fraction(movement.value)
            positions[dimension] = positions.get(dimension, Fraction(0)) + delta
            if effect.instance_id is None:
                raise ValueError("fill lacks instance identity")
            key = (effect.instance_id, dimension)
            instance_positions[key] = instance_positions.get(key, Fraction(0)) + delta

    @classmethod
    def _replay(cls, state: AccountState) -> tuple[EffectiveAccountPosting, ...]:
        """Validate every observed boundary and resolve only current revisions."""
        currencies = {currency.code: currency for currency in state.currencies}
        cash = {code: Fraction(0) for code in currencies}
        positions: dict[Dimension, Fraction] = {}
        instance_positions: dict[tuple[str, Dimension], Fraction] = {}
        originals: dict[str, AccountPosting] = {}
        revisions: dict[str, str] = {}
        active: dict[str, EffectiveAccountPosting | None] = {}
        previous_known_at: datetime | None = None
        for posting in state.postings:
            if (
                posting.account_id != state.account_id
                or currencies.get(posting.cash.currency.code) != posting.cash.currency
            ):
                raise ValueError("posting account or currency is not declared")
            if previous_known_at is not None and posting.known_at < previous_known_at:
                raise ValueError("posting knowledge clocks are out of order")
            previous_known_at = posting.known_at
            if posting.kind == "correction":
                if posting.corrects is None or posting.corrects not in revisions:
                    raise ValueError("correction must reference the current revision")
                root_id = revisions.pop(posting.corrects)
                original = originals[root_id]
                if (
                    posting.instance_id != original.instance_id
                    or posting.order_id != original.order_id
                    or posting.cash.currency != original.cash.currency
                    or posting.replacement_kind not in (None, original.kind)
                    or (
                        original.quantity is not None
                        and posting.quantity is not None
                        and posting.quantity.dimension != original.quantity.dimension
                    )
                    or (
                        posting.replacement_kind is not None
                        and (posting.asset_change is None) != (original.asset_change is None)
                    )
                    or (
                        original.asset_change is not None
                        and posting.asset_change is not None
                        and posting.asset_change.dimension != original.asset_change.dimension
                    )
                ):
                    raise ValueError("correction changes original ownership or units")
                before = active[root_id]
                if before is not None:
                    cls._adjust(before, -1, cash, positions, instance_positions)
                active[root_id] = cls._effect(posting, root_id)
                revisions[posting.identity] = root_id
            else:
                root_id = posting.identity
                originals[root_id] = posting
                active[root_id] = cls._effect(posting, root_id)
                revisions[root_id] = root_id
            after = active[root_id]
            if after is not None:
                cls._adjust(after, 1, cash, positions, instance_positions)
            if any(value < 0 for value in cash.values()):
                raise ValueError("insufficient account cash")
            if any(value < 0 for value in positions.values()) or any(
                value < 0 for value in instance_positions.values()
            ):
                raise ValueError("spot inventory cannot be short")
            for value in (*cash.values(), *positions.values(), *instance_positions.values()):
                DecimalGrid.exact_decimal(value)
        return tuple(effect for effect in active.values() if effect is not None)
