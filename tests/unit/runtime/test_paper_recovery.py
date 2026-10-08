"""Keep historical managed paper backups quarantined and current journals resumable."""

from __future__ import annotations

# standard library imports
import gc
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger, AccountSnapshot
from configuration import (
    AccountConfiguration,
    OpeningAccount,
    PaperAuthorization,
    PaperDeployment,
    PaperExecutionScenario,
    PaperStrategyIdentity,
)
from configuration.accounts import InstrumentFeeRate
from execution import (
    AccountControl,
    AccountDecision,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    OrderDecision,
    PaperMarket,
    PaperOwner,
    PaperReductionRequest,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from runtime.account_recovery import AccountRecoveryReceipt, AccountWorkspace
from serialization import DomainCodec
from strategies import OrderIntent


class _Clock:
    """Make authorization time independent of stored event time."""

    def __init__(self, at: datetime) -> None:
        """Start the mutable UTC clock at one explicit instant."""
        self.at = at

    def __call__(self) -> datetime:
        """Return the wall time observed by an account boundary."""
        return self.at


@dataclass(frozen=True)
class _StoppedWorkspace:
    """Hold the current owner and a verified older stopped snapshot."""

    workspace: AccountWorkspace
    admin: AccountJournal
    worker: AccountJournal
    clock: _Clock
    deployment: PaperDeployment
    first_owner: PaperOwner
    receipt: AccountRecoveryReceipt
    backup_root: Path
    partial: AccountSnapshot


class TestPaperRecovery:
    """Exercise publication, quarantine and compatible rollback through public APIs."""

    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)
    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    first_release = "a" * 64
    rollback_release = "b" * 64

    @classmethod
    def _at(cls, seconds: int) -> datetime:
        """Offset one shared opening instant without local-time ambiguity."""
        return cls.opening_at + timedelta(seconds=seconds)

    @classmethod
    def _money(cls, value: str) -> Money:
        """Build exact quote-currency cash and modeled costs."""
        return Money(value=Decimal(value), currency=cls.currency)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Build exact base-unit size for the configured instrument."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _price(cls, value: str) -> Price:
        """Build exact quote-per-base price on the configured grid."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _config(cls) -> AccountConfiguration:
        """Give one paper strategy a funded and independently bounded account."""
        spot_limits: tuple[SpotLimits, ...] = (
            SpotLimits(
                maximum=cls._quantity("20"),
                lot=cls._quantity("1"),
                tick=cls._price("0.01"),
                product="spot",
            ),
        )
        return AccountConfiguration(
            mode="paper",
            opening_at=cls.opening_at,
            accounts=(OpeningAccount(account_id="shared", cash=(cls._money("1000"),)),),
            instruments=spot_limits,
            fee_rates=tuple(
                InstrumentFeeRate(
                    instrument_id=limits.maximum.dimension.instrument_id, rate=Decimal("0.01")
                )
                for limits in spot_limits
            ),
            budgets=BudgetPolicy(
                valuation_currency=cls.currency,
                firm_maximum=cls._money("1000"),
                accounts=(AccountLimit(account_id="shared", maximum=cls._money("1000")),),
                instances=(
                    InstanceLimit(
                        instance_id="alpha",
                        account_id="shared",
                        maximum=cls._money("1000"),
                        instruments=(cls.dimension.instrument_id,),
                    ),
                ),
                max_quote_age_us=10_000_000,
                max_state_age_us=60_000_000,
                max_residual_age_us=86_400_000_000,
                max_price_deviation_bps=200,
                max_order_notional=cls._money("1000"),
            ),
        )

    @classmethod
    def _scenario(cls) -> PaperExecutionScenario:
        """Pin deterministic public-book matching costs and finite liquidity."""
        return PaperExecutionScenario(
            venue="okx",
            instrument_id=cls.dimension.instrument_id,
            entry_delay_us=0,
            cancel_delay_us=0,
            adverse=cls._price("0.01"),
            fee_rate=Decimal("0.01"),
            take_fraction=Decimal(1),
            gas_inapplicable_reason="off-chain spot matching",
        )

    @classmethod
    def _opening(cls) -> AccountSnapshot:
        """Return complete independent opening facts for reconciliation."""
        return AccountSnapshot(
            account_id="shared",
            instance_id=None,
            cash=(cls._money("1000"),),
            positions=(),
            fees=(cls._money("0"),),
            rebates=(cls._money("0"),),
            transfers=(cls._money("1000"),),
            fill_ids=(),
            posting_ids=("opening:USDT",),
        )

    @classmethod
    def _deployment(cls, config: AccountConfiguration) -> PaperDeployment:
        """Bind two compatible release digests to one disabled strategy."""
        return PaperDeployment(
            account_id="shared",
            configuration_sha256=hashlib.sha256(DomainCodec().encode_json(config)).hexdigest(),
            releases=(cls.first_release, cls.rollback_release),
            strategies=(
                PaperStrategyIdentity(
                    instance_id="alpha",
                    policy_identity="policy-alpha",
                    candidate_identity="candidate-alpha",
                    model_identity="no-model",
                    feature_identity="feature-alpha",
                ),
            ),
            input_identity="public-okx-book",
            scenario=cls._scenario(),
            state_identity="paper-account-state",
        )

    @classmethod
    def _market(cls, identity: str, at: datetime, *, ask_quantity: str) -> PaperMarket:
        """Construct one finite uncrossed public quote at a chosen ask depth."""
        return PaperMarket(
            identity=identity,
            at=at,
            bid=cls._price("9.95"),
            ask=cls._price("10"),
            bid_quantity=cls._quantity("2"),
            ask_quantity=cls._quantity(ask_quantity),
        )

    @classmethod
    def _prepare(cls, tmp_path: Path) -> _StoppedWorkspace:
        """Back up a stopped owner with one actual fill and one pending unit."""
        current_root = tmp_path / "current"
        (current_root / "state").mkdir(parents=True)
        path = current_root / "state" / "accounts.sqlite3"
        config = cls._config()
        clock = _Clock(cls._at(10))
        admin = AccountJournal(path, config, clock=clock)
        assert admin.reconcile(
            AccountObservation(
                identity="opening",
                at=cls._at(1),
                snapshot=cls._opening(),
                open_orders=(),
            )
        )
        deployment = cls._deployment(config)
        admin.install_paper(deployment)
        clock.at = cls._at(11)
        admin.authorize_paper(
            PaperAuthorization(
                identity="bounded-session",
                deployment_sha256=deployment.identity,
                valid_from=cls._at(11),
                expires_at=cls._at(40),
                quantities=(cls._quantity("5"),),
                maximum_order_notional=cls._money("100"),
                maximum_orders=5,
            )
        )
        assert admin.reconcile(
            AccountObservation(
                identity="fresh-after-install",
                at=cls._at(12),
                snapshot=cls._opening(),
                open_orders=(),
            )
        )
        quote = AccountQuote(price=cls._price("10"), at=cls._at(12))
        admin.observe(quote)
        clock.at = cls._at(13)
        first_owner = admin.claim_paper(
            "shared",
            "worker-first",
            cls.first_release,
            AccountControl(
                identity="claim-first",
                account_id="shared",
                kind="restart",
                at=cls._at(13),
                expected_control_identity=f"paper-deployment:{deployment.identity}",
            ),
        )
        worker = AccountJournal(path, config, paper_owner=first_owner, clock=clock)
        clock.at = cls._at(14)
        admitted = worker.admit(
            AccountDecision(
                account_id="shared",
                instance_id="alpha",
                decision=OrderDecision(
                    identity="two-unit-buy",
                    at=cls._at(14),
                    intent=OrderIntent(
                        side="buy",
                        quantity=cls._quantity("2"),
                        limit=cls._price("10.10"),
                        time_in_force="gtc",
                    ),
                ),
                quote=quote,
                maximum_fee=cls._money("1"),
            )
        )
        assert admitted.status == "committed"
        clock.at = cls._at(15)
        first_book = cls._market("first-book", cls._at(15), ask_quantity="1")
        worker.apply_public_market("shared", first_book, cls._scenario())
        first_trace = worker.paper_trace("shared", first_book.identity)
        assert first_trace is not None
        assert len(first_trace.child_fill_events) == 1
        partial = AccountLedger(worker.accounts()[0].ledger).snapshot()
        assert partial.cash == (cls._money("989.8899"),)
        assert partial.positions == (cls._quantity("1"),)
        clock.at = cls._at(16)
        assert (
            admin.control(
                AccountControl(
                    identity="stop-for-backup",
                    account_id="shared",
                    kind="stop",
                    at=cls._at(16),
                    reason="operator recovery snapshot",
                )
            ).status
            == "applied"
        )
        clock.at = cls._at(17)
        assert worker.reconcile(
            AccountObservation(
                identity="stopped-partial",
                at=cls._at(17),
                snapshot=partial,
                open_orders=(worker.orders()[0].order,),
            )
        )
        worker.observe(AccountQuote(price=cls._price("10"), at=cls._at(17)))
        workspace = AccountWorkspace(config, component="state", journal_name="accounts.sqlite3")
        backup_root = tmp_path / "backup"
        receipt = workspace.backup(current_root, backup_root)
        assert receipt.accounts[0].phase == "stopped"
        return _StoppedWorkspace(
            workspace=workspace,
            admin=admin,
            worker=worker,
            clock=clock,
            deployment=deployment,
            first_owner=first_owner,
            receipt=receipt,
            backup_root=backup_root,
            partial=partial,
        )

    def test_old_snapshot_cannot_reactivate_but_current_journal_rolls_back(
        self, tmp_path: Path
    ) -> None:
        """A newer retained fill must not be replayed from an older valid snapshot."""
        rig = self._prepare(tmp_path)
        rig.clock.at = self._at(19)
        rollback_owner = rig.admin.claim_paper(
            "shared",
            "worker-rollback",
            self.rollback_release,
            AccountControl(
                identity="claim-rollback",
                account_id="shared",
                kind="restart",
                at=self._at(19),
                expected_control_identity="stop-for-backup",
            ),
        )
        assert rollback_owner.generation == rig.first_owner.generation + 1
        current = AccountJournal(
            rig.admin.path, rig.workspace.config, paper_owner=rollback_owner, clock=rig.clock
        )
        rig.clock.at = self._at(20)
        last_market = self._market("last-book", self._at(20), ask_quantity="2")
        final_outcome = current.apply_public_market("shared", last_market, self._scenario())
        final_trace = current.paper_trace("shared", last_market.identity)
        assert final_trace is not None and len(final_trace.child_fill_events) == 1
        final_fill = final_trace.child_fill_events[0].fill
        assert final_fill is not None
        assert (final_fill.quantity, final_fill.effective, final_fill.fee) == (
            self._quantity("1"),
            self._price("10.01"),
            self._money("0.1001"),
        )
        finished = AccountLedger(current.accounts()[0].ledger).snapshot()
        assert finished.cash == (self._money("979.7798"),)
        assert finished.positions == (self._quantity("2"),)
        assert finished.fees == (self._money("0.2002"),)
        assert current.orders()[0].order.status == "filled"
        assert current.apply_public_market("shared", last_market, self._scenario()) == final_outcome

        rig.clock.at = self._at(21)
        restored_root = tmp_path / "restored"
        assert (
            rig.workspace.restore(
                rig.backup_root,
                restored_root,
                expected_manifest_sha256=rig.receipt.manifest_sha256,
            )
            == rig.receipt
        )
        restored_path = restored_root / "state" / "accounts.sqlite3"
        restored_admin = AccountJournal(restored_path, rig.workspace.config, clock=rig.clock)
        assert AccountLedger(restored_admin.accounts()[0].ledger).snapshot() == rig.partial
        assert restored_admin.accounts()[0].phase == "stopped"
        assert restored_admin.paper_activations()[0].authorization is not None

        # Fresh state and quote do not establish that the historical snapshot has
        # observed the second retained fill, so they cannot lift quarantine.
        rig.clock.at = self._at(22)
        assert restored_admin.reconcile(
            AccountObservation(
                identity="fresh-on-old-snapshot",
                at=self._at(22),
                snapshot=rig.partial,
                open_orders=(restored_admin.orders()[0].order,),
            )
        )
        current_quote = AccountQuote(price=self._price("10"), at=self._at(22))
        restored_admin.observe(current_quote)
        restored_worker = AccountJournal(
            restored_path, rig.workspace.config, paper_owner=rig.first_owner, clock=rig.clock
        )
        rig.clock.at = self._at(23)
        with pytest.raises(ValueError, match="paper_restore_requires_current_retained_journal"):
            restored_admin.claim_paper(
                "shared",
                "old-snapshot-worker",
                self.first_release,
                AccountControl(
                    identity="unsafe-claim",
                    account_id="shared",
                    kind="restart",
                    at=self._at(23),
                    expected_control_identity="stop-for-backup",
                ),
            )
        with pytest.raises(ValueError, match="paper_restore_requires_current_retained_journal"):
            restored_worker.admit(
                AccountDecision(
                    account_id="shared",
                    instance_id="alpha",
                    decision=OrderDecision(
                        identity="unsafe-old-buy",
                        at=self._at(23),
                        intent=OrderIntent(
                            side="buy",
                            quantity=self._quantity("1"),
                            limit=self._price("10.10"),
                            time_in_force="gtc",
                        ),
                    ),
                    quote=current_quote,
                    maximum_fee=self._money("1"),
                )
            )
        with pytest.raises(ValueError, match="paper_restore_requires_current_retained_journal"):
            restored_worker.apply_public_market(
                "shared",
                self._market("replay-old-pending", self._at(23), ask_quantity="1"),
                self._scenario(),
            )
        with pytest.raises(ValueError, match="paper_restore_requires_current_retained_journal"):
            restored_worker.reduce_paper(
                PaperReductionRequest(
                    identity="unsafe-old-sale",
                    account_id="shared",
                    instance_id="alpha",
                    quantity=self._quantity("1"),
                    quote=current_quote,
                    limit=self._price("9.90"),
                    maximum_fee=self._money("1"),
                    at=self._at(23),
                )
            )
        assert len(restored_worker.orders()) == 1
        assert AccountLedger(restored_worker.accounts()[0].ledger).snapshot() == rig.partial
        reopened_current = AccountJournal(
            rig.admin.path, rig.workspace.config, paper_owner=rollback_owner, clock=rig.clock
        )
        assert AccountLedger(reopened_current.accounts()[0].ledger).snapshot() == finished
        assert (
            reopened_current.apply_public_market("shared", last_market, self._scenario())
            == final_outcome
        )
        assert reopened_current.paper_trace("shared", last_market.identity) == final_trace

    def test_a_restore_publishes_exactly_the_backup_s_files(self, tmp_path: Path) -> None:
        """No SQLite side file of the staged quarantine is published, whenever GC runs.

        The staged journal is quarantined through its owner before publication. With
        garbage collection held off, that journal's connection must still be closed
        before the staging directory is published, so the restore holds exactly the
        files the backup's payload holds.
        """
        rig = self._prepare(tmp_path)
        payload = rig.backup_root / "payload"
        expected = sorted(
            str(path.relative_to(payload)) for path in payload.rglob("*") if path.is_file()
        )
        restored_root = tmp_path / "restored-exact"
        gc.disable()
        try:
            rig.workspace.restore(
                rig.backup_root,
                restored_root,
                expected_manifest_sha256=rig.receipt.manifest_sha256,
            )
            published = sorted(
                str(path.relative_to(restored_root))
                for path in restored_root.rglob("*")
                if path.is_file()
            )
        finally:
            gc.enable()
        assert "state/accounts.sqlite3" in expected
        assert published == expected

    def test_failed_quarantine_and_mismatched_metadata_never_publish(self, tmp_path: Path) -> None:
        """A failed staged fence or wrong backup/config identity leaves no restore."""
        rig = self._prepare(tmp_path)
        failed_root = tmp_path / "failed-quarantine"
        with patch.object(
            AccountJournal,
            "quarantine_paper_restore",
            side_effect=ValueError("injected-fence-failure"),
        ):
            with pytest.raises(ValueError, match="injected-fence-failure"):
                rig.workspace.restore(
                    rig.backup_root,
                    failed_root,
                    expected_manifest_sha256=rig.receipt.manifest_sha256,
                )
        assert not failed_root.exists()
        wrong_digest_root = tmp_path / "wrong-digest"
        with pytest.raises(ValueError, match="manifest identity differs"):
            rig.workspace.restore(
                rig.backup_root,
                wrong_digest_root,
                expected_manifest_sha256="0" * 64,
            )
        assert not wrong_digest_root.exists()
        wrong_config_root = tmp_path / "wrong-config"
        wrong_config = replace(rig.workspace.config, mode="shadow")
        with pytest.raises(ValueError, match="configuration"):
            AccountWorkspace(
                wrong_config, component="state", journal_name="accounts.sqlite3"
            ).restore(
                rig.backup_root,
                wrong_config_root,
                expected_manifest_sha256=rig.receipt.manifest_sha256,
            )
        assert not wrong_config_root.exists()
        wrong_component_root = tmp_path / "wrong-component"
        with pytest.raises(ValueError, match="component or journal differs"):
            AccountWorkspace(
                rig.workspace.config, component="other", journal_name="accounts.sqlite3"
            ).restore(
                rig.backup_root,
                wrong_component_root,
                expected_manifest_sha256=rig.receipt.manifest_sha256,
            )
        assert not wrong_component_root.exists()

    def test_unknown_state_or_changed_model_config_cannot_replace_deployment(
        self, tmp_path: Path
    ) -> None:
        """The active binding rejects unsupported ABI and changed installed inputs."""
        rig = self._prepare(tmp_path)
        with pytest.raises(ValueError, match="disabled and explicitly bound"):
            replace(rig.deployment, state_identity="unknown-state")
        with pytest.raises(ValueError, match="paper strategy identity is incomplete"):
            replace(rig.deployment.strategies[0], model_identity="")
        with pytest.raises(ValueError, match="configuration differs"):
            rig.admin.install_paper(replace(rig.deployment, configuration_sha256="c" * 64))
        with pytest.raises(ValueError, match="paper_deployment_incompatible"):
            rig.admin.install_paper(
                replace(
                    rig.deployment,
                    strategies=(
                        replace(rig.deployment.strategies[0], model_identity="other-model"),
                    ),
                )
            )
        assert rig.admin.paper_activations()[0].deployment == rig.deployment
