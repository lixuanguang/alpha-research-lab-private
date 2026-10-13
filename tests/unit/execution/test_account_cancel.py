"""Operator account cancel withdraws working intent and leaves holdings and phase alone."""

from __future__ import annotations

# standard library imports
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

# third party library imports
import pytest
from msgspec.structs import replace
from paper_books import PaperBooks
from test_portfolio_accounts import TestPortfolioAccounts as _Portfolio

# project library imports
from accounting.accounts import AccountLedger
from configuration.accounts import OpeningAccount
from execution import (
    AccountControl,
    AccountControlResult,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    OrderEvent,
    PortfolioBatch,
)
from execution.account_state import AccountStateStore
from risk.budgets import AccountLimit, InstanceLimit
from serialization import DomainCodec


class TestAccountCancel:
    """Pin the selected D1 contract: withdraw working intent without stopping the account.

    Every scenario uses the portfolio fixtures: one ``shared`` account with 50,000
    cash and a 10,000 limit, strategies capped at 9,000, and in paper a 1 ms entry and
    a 5 ms cancellation delay.
    """

    opening_at = _Portfolio.opening_at
    MS = timedelta(milliseconds=1)

    @staticmethod
    def _cancel(identity: str, at: datetime, account_id: str = "shared") -> AccountControl:
        """Build one operator account cancel."""
        return AccountControl(identity=identity, account_id=account_id, kind="cancel", at=at)

    @staticmethod
    def _batch(identity: str, at: datetime, *names: str) -> PortfolioBatch:
        """Rest a two-unit 99.50 bid for each named strategy, decided at ``at``."""
        return PortfolioBatch(
            identity=identity,
            at=at + timedelta(microseconds=1),
            decisions=tuple(_Portfolio._below(name, at, "2") for name in names),
        )

    @staticmethod
    def _live(journal: AccountJournal) -> list[tuple[str, str, bool]]:
        """List each nonterminal strategy order's instance, status and cancel mark."""
        return [
            (item.instance_id, item.order.status, item.order.cancel_requested)
            for item in journal.orders()
            if not item.order.is_terminal
        ]

    def test_a_cancelled_shared_order_ends_its_children_instead_of_reissuing_them(
        self, tmp_path: Path
    ) -> None:
        """Alpha and beta share one physical buy; the account cancel ends both children.

        The children stay reserved (``intent``, marked) until the physical order's own
        ``cancelled_on_request`` at +1.1 s, then end with it. A later reconciliation and
        explicit reissue send nothing, across a reopen. Before D1 both were reissued.
        """
        path = tmp_path / "shared-order.sqlite3"
        journal = _Portfolio._ready(path)
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=_Portfolio._price(), at=at))
        (parent,) = journal.coordinate(
            PortfolioBatch(
                identity="pair",
                at=at + timedelta(microseconds=1),
                decisions=tuple(
                    _Portfolio._decision(
                        instance=name, identity=f"{name}-buy", at=at, maximum_fee="0"
                    )
                    for name in ("alpha", "beta")
                ),
            )
        ).net_orders
        result = journal.control(self._cancel("cancel", at + timedelta(seconds=1)))
        assert (result.status, result.phase) == ("applied", "running")
        assert result.cancel_order_ids == (parent.order.identity,)
        assert (result.withdrawn_decision_ids, result.withdrawn_order_ids) == ((), ())
        assert self._live(journal) == [("alpha", "intent", True), ("beta", "intent", True)]
        journal.apply_net_event(
            OrderEvent(
                identity="pair-cancelled",
                order_id=parent.order.identity,
                at=at + timedelta(milliseconds=1100),
                kind="cancelled_on_request",
            )
        )
        assert self._live(journal) == []
        journal.close()
        journal = AccountJournal(path, _Portfolio._config())
        later = at + timedelta(seconds=2)
        journal.observe(AccountQuote(price=_Portfolio._price(), at=later))
        assert journal.reconcile(
            AccountObservation(
                identity="after-cancel", at=later, snapshot=_Portfolio._opening(), open_orders=()
            )
        )
        assert journal.reissue_pending("shared", later + timedelta(microseconds=1)) == ()
        assert journal.portfolio_residuals("shared") == ()
        assert [item.order.identity for item in journal.net_orders()] == [parent.order.identity]

    @pytest.mark.parametrize("listed", (False, True), ids=("unlisted", "listed"))
    def test_unsent_children_are_withdrawn_and_release_their_reservations(
        self, tmp_path: Path, listed: bool
    ) -> None:
        """Unsent intent ends whether or not a residual record names it.

        Alpha holds 85 bought at 100. Gamma's selective stop ends the physical order it
        shared with alpha and beta, leaving each an unsent two-unit buy at 100. Listed:
        a reissue at a 112 quote, 12% from their limits against a 10% bound, first holds
        both back as visible ``price_deviation`` residuals. The account cancel ends both
        and clears any record. Valued at 100, the account then commits 8,500, so a fresh
        beta buy of 12 (1,200) fits under its 10,000 limit; the two 200 reservations
        would have made it 10,100.
        """
        journal = _Portfolio._holding(
            tmp_path / f"{'listed' if listed else 'unlisted'}.sqlite3",
            instances=("alpha", "beta", "gamma"),
        )
        start = self.opening_at + timedelta(seconds=2)
        cancelled_at = _Portfolio._cancelled_pair(journal, start)
        unsent = [
            (item.instance_id, item.order.identity)
            for item in journal.orders()
            if not item.order.is_terminal
        ]
        assert [name for name, _ in unsent] == ["alpha", "beta"]
        if listed:
            reissue_at = cancelled_at + timedelta(milliseconds=400)
            journal.observe(AccountQuote(price=_Portfolio._price("112"), at=reissue_at))
            assert journal.reconcile(
                AccountObservation(
                    identity="before-cancel",
                    at=reissue_at,
                    snapshot=AccountLedger(journal.accounts()[0].ledger).snapshot(),
                    open_orders=(),
                )
            )
            assert journal.reissue_pending("shared", reissue_at) == ()
            assert [
                (item.instance_id, item.reason) for item in journal.portfolio_residuals("shared")
            ] == [("alpha", "price_deviation"), ("beta", "price_deviation")]
        else:
            assert journal.portfolio_residuals("shared") == ()
        cancel_at = start + timedelta(seconds=2)
        result = journal.control(self._cancel("cancel", cancel_at))
        assert result.status == "applied"
        assert result.withdrawn_order_ids == tuple(identity for _, identity in unsent)
        assert (result.cancel_order_ids, result.withdrawn_decision_ids) == ((), ())
        assert self._live(journal) == []
        assert journal.portfolio_residuals("shared") == ()
        fresh_at = cancel_at + timedelta(milliseconds=500)
        journal.observe(AccountQuote(price=_Portfolio._price(), at=fresh_at))
        fresh = journal.coordinate(
            PortfolioBatch(
                identity="beta-fresh",
                at=fresh_at + timedelta(microseconds=1),
                decisions=(
                    _Portfolio._decision(
                        instance="beta",
                        identity="beta-fresh",
                        at=fresh_at,
                        quantity="12",
                        maximum_fee="0",
                    ),
                ),
            )
        )
        assert fresh.status == "committed", fresh.reason
        assert [item.order.intent.quantity for item in fresh.net_orders] == [
            _Portfolio._quantity("12")
        ]

    @pytest.mark.parametrize("exact", (False, True), ids=("after-arrival", "at-arrival"))
    def test_a_plan_due_at_the_cancel_is_withdrawn_and_an_earlier_arrival_is_cancelled(
        self, tmp_path: Path, exact: bool
    ) -> None:
        """Arrivals strictly before the cancel are settled first; one due at it is withdrawn.

        Alpha's bid decided at 1 s arrives at +1 ms. A cancel at +2 ms finds it
        admitted and requests its physical order's cancellation, effective at +7 ms. A
        cancel at exactly +1 ms withdraws the plan instead, so no order ever exists.
        Neither advancing nor reopening revives anything.
        """
        path = tmp_path / "arrival.sqlite3"
        journal = _Portfolio._bound(path)
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=_Portfolio._price(), at=at))
        assert journal.coordinate(self._batch("alpha", at, "alpha")).reason == "arrival_pending"
        result = journal.control(self._cancel("cancel", at + (1 if exact else 2) * self.MS))
        assert result.status == "applied"
        if exact:
            assert result.withdrawn_decision_ids == ("alpha-bid",)
            assert (result.cancel_order_ids, journal.net_orders(), journal.orders()) == (
                (),
                (),
                (),
            )
            expected = [
                ("alpha", timedelta(0), "arrival_pending"),
                ("alpha", self.MS, "withdrawn_by_account_cancel"),
            ]
        else:
            (parent,) = journal.net_orders()
            assert result.cancel_order_ids == (parent.order.identity,)
            assert result.withdrawn_decision_ids == ()
            assert self._live(journal) == [("alpha", "intent", True)]
            expected = [
                ("alpha", timedelta(0), "arrival_pending"),
                ("alpha", self.MS, "reserved"),
            ]
        assert _Portfolio._outcomes(journal, at) == expected
        journal.advance_paper(at + 20 * self.MS)
        journal.close()
        journal = AccountJournal(path, _Portfolio._config())
        journal.advance_paper(at + 30 * self.MS)
        assert _Portfolio._outcomes(journal, at) == expected
        assert self._live(journal) == []
        cancellations = [
            saved.event.at
            for saved in AccountStateStore(path, _Portfolio._config(), DomainCodec())
            .read()
            .net_events
            if saved.event.kind == "cancelled_on_request"
        ]
        assert cancellations == ([] if exact else [at + 7 * self.MS])

    def test_a_fill_in_the_cancellation_window_counts_and_the_target_is_withdrawn(
        self, tmp_path: Path
    ) -> None:
        """A withdrawn replacement leaves a window fill and the holding it bought.

        Alpha's two-unit bid rests from +1 ms; its +3 ms target of two waits for the
        bid's D2 cancellation (effective +8 ms, arrival +9 ms). The +5 ms account cancel
        withdraws the target and lists the already-requested bid. A +6 ms book offering
        ten at 99.50 fills the bid's two inside the window. Nothing arrives at +9 ms and
        nothing reduces the two held, across a reopen.
        """
        path = tmp_path / "window.sqlite3"
        journal, at = _Portfolio()._quiet_target(path)
        (bid,) = journal.net_orders()
        result = journal.control(self._cancel("cancel", at + 5 * self.MS))
        assert result.withdrawn_decision_ids == ("alpha-target",)
        assert result.cancel_order_ids == (bid.order.identity,)
        PaperBooks.apply(
            journal,
            "shared",
            _Portfolio._touch("crossing", at + 6 * self.MS, "99", "99.50"),
            _Portfolio._delayed_scenario(),
        )
        journal.advance_paper(at + 20 * self.MS)
        journal.close()
        journal = AccountJournal(path, _Portfolio._config())
        journal.advance_paper(at + 30 * self.MS)
        assert _Portfolio._outcomes(journal, at) == [
            ("alpha", timedelta(0), "arrival_pending"),
            ("alpha", self.MS, "reserved"),
            ("alpha", 3 * self.MS, "replacement_pending"),
            ("alpha", 5 * self.MS, "withdrawn_by_account_cancel"),
        ]
        assert _Portfolio._physical_fills(journal) == [(at + 6 * self.MS, Decimal(2))]
        assert [item.order.status for item in journal.orders()] == ["filled"]
        assert len(journal.net_orders()) == 1
        ledger = AccountLedger(journal.accounts()[0].ledger)
        assert ledger.snapshot(instance_id="alpha").positions == (_Portfolio._quantity("2"),)

    def test_a_backdated_cancel_withdraws_nothing_and_changes_no_outcome(
        self, tmp_path: Path
    ) -> None:
        """A cancel dated before the account's clock is rejected with no economic effect.

        The same waiting target and resting bid run with and without a cancel dated
        +1 ms, after the account has seen +3 ms. Both journals reach identical outcomes
        and orders, and no account-control cancel request exists.
        """
        journal, at = _Portfolio()._quiet_target(tmp_path / "backdated.sqlite3")
        control, _ = _Portfolio()._quiet_target(tmp_path / "control.sqlite3")
        result = journal.control(self._cancel("late", at + self.MS))
        assert (result.status, result.reason) == ("rejected", "account_control_clock_regressed")
        assert (result.cancel_order_ids, result.withdrawn_decision_ids) == ((), ())
        for item in (journal, control):
            item.advance_paper(at + 20 * self.MS)
        assert _Portfolio._outcomes(journal, at) == _Portfolio._outcomes(control, at)
        assert _Portfolio._outcomes(journal, at)[-1] == ("alpha", 9 * self.MS, "reserved")
        assert [item.order for item in journal.orders()] == [
            item.order for item in control.orders()
        ]
        assert not any(
            event.identity.startswith("account-control:") for event in journal.failed_net_events()
        )
        assert all(
            not saved.event.identity.startswith("account-control:")
            for saved in AccountStateStore(
                tmp_path / "backdated.sqlite3", _Portfolio._config(), DomainCodec()
            )
            .read()
            .net_events
        )

    def test_a_retry_withdraws_nothing_newer_and_a_conflicting_reuse_changes_nothing(
        self, tmp_path: Path
    ) -> None:
        """An exact retry returns its first outcome even after a newer decision.

        The +0.5 ms cancel withdraws alpha's 1 s bid. Beta then decides at +2 ms, so its
        bid arrives at +3 ms while the account keeps running. Retrying the cancel returns
        the first outcome; reusing its identity with another time is refused. Neither
        touches beta's waiting plan, which arrives at +3 ms after a reopen.
        """
        path = tmp_path / "retry.sqlite3"
        journal = _Portfolio._bound(path)
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=_Portfolio._price(), at=at))
        journal.coordinate(self._batch("alpha", at, "alpha"))
        request = self._cancel("cancel", at + timedelta(microseconds=500))
        first = journal.control(request)
        assert first.withdrawn_decision_ids == ("alpha-bid",)
        beta_at = at + 2 * self.MS
        journal.observe(AccountQuote(price=_Portfolio._price(), at=beta_at))
        assert journal.coordinate(self._batch("beta", beta_at, "beta")).reason == (
            "arrival_pending"
        )
        assert journal.control(request) == first
        with pytest.raises(ValueError, match="different content"):
            journal.control(replace(request, at=at + 4 * self.MS))
        journal.close()
        assert AccountJournal.verify(path, _Portfolio._config())
        journal = AccountJournal(path, _Portfolio._config())
        assert journal.control(request) == first
        journal.advance_paper(at + 10 * self.MS)
        assert journal.controls("shared") == (first,)
        assert _Portfolio._outcomes(journal, at) == [
            ("alpha", timedelta(0), "arrival_pending"),
            ("alpha", timedelta(microseconds=500), "withdrawn_by_account_cancel"),
            ("beta", 2 * self.MS, "arrival_pending"),
            ("beta", 3 * self.MS, "reserved"),
        ]
        assert self._live(journal) == [("beta", "intent", False)]

    def test_stop_cancel_restart_revives_nothing_and_only_fresh_decisions_trade(
        self, tmp_path: Path
    ) -> None:
        """After stop, cancel and restart, only a decision made after the restart trades.

        Alpha's and beta's bids arrive at +1 ms. The +2 ms stop then cancel request their
        physical cancellation, effective at +7 ms; both children end with it. After a
        reopen, a +11 ms reconciliation and quote, and a +12 ms restart, an explicit
        reissue after a +12.5 ms reconciliation sends nothing. Beta's fresh +13 ms bid
        arrives at +14 ms.
        """
        path = tmp_path / "restart.sqlite3"
        journal = _Portfolio._bound(path)
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=_Portfolio._price(), at=at))
        journal.coordinate(self._batch("pair", at, "alpha", "beta"))
        journal.advance_paper(at + timedelta(microseconds=1_500))
        parents = tuple(item.order.identity for item in journal.net_orders())
        assert parents and self._live(journal) == [
            ("alpha", "intent", False),
            ("beta", "intent", False),
        ]
        stop = AccountControl(
            identity="stop", account_id="shared", kind="stop", at=at + 2 * self.MS, reason="halt"
        )
        assert journal.control(stop).status == "applied"
        cancelled = journal.control(self._cancel("cancel", at + 2 * self.MS))
        assert (cancelled.phase, cancelled.cancel_order_ids) == ("stopped", parents)
        journal.advance_paper(at + 10 * self.MS)
        assert self._live(journal) == []
        journal.close()
        journal = AccountJournal(path, _Portfolio._config())
        recovered_at = at + 11 * self.MS
        assert journal.reconcile(
            AccountObservation(
                identity="recovered",
                at=recovered_at,
                snapshot=_Portfolio._opening(),
                open_orders=(),
            )
        )
        journal.observe(AccountQuote(price=_Portfolio._price(), at=recovered_at))
        restart = AccountControl(
            identity="restart",
            account_id="shared",
            kind="restart",
            at=at + 12 * self.MS,
            expected_control_identity="stop",
        )
        assert journal.control(restart).status == "applied"
        reissue_at = at + timedelta(microseconds=12_500)
        assert journal.reconcile(
            AccountObservation(
                identity="restarted",
                at=reissue_at,
                snapshot=_Portfolio._opening(),
                open_orders=(),
            )
        )
        assert journal.reissue_pending("shared", reissue_at) == ()
        fresh_at = at + 13 * self.MS
        journal.observe(AccountQuote(price=_Portfolio._price(), at=fresh_at))
        fresh = _Portfolio._below("beta", fresh_at, "2")
        request = fresh.request
        journal.coordinate(
            PortfolioBatch(
                identity="fresh",
                at=fresh_at + timedelta(microseconds=1),
                decisions=(
                    replace(
                        fresh,
                        request=replace(
                            request, decision=replace(request.decision, identity="beta-fresh")
                        ),
                    ),
                ),
            )
        )
        journal.advance_paper(at + 20 * self.MS)
        assert _Portfolio._outcomes(journal, at)[-2:] == [
            ("beta", 13 * self.MS, "arrival_pending"),
            ("beta", 14 * self.MS, "reserved"),
        ]
        assert self._live(journal) == [("beta", "intent", False)]
        assert len(journal.net_orders()) == len(parents) + 1

    def test_an_unknown_order_stays_unknown_and_reserved_under_a_cancel(
        self, tmp_path: Path
    ) -> None:
        """Neither the cancel nor elapsed time ends an order whose outcome is unknown.

        Alpha's and beta's bids arrive at +1 ms and their physical outcome becomes
        unknown at +1.5 ms. The +2 ms cancel marks the order and both children; through
        +60 ms and a reopen the order stays unknown and both children stay reserved.
        """
        path = tmp_path / "unknown.sqlite3"
        journal = _Portfolio._bound(path)
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=_Portfolio._price(), at=at))
        journal.coordinate(self._batch("pair", at, "alpha", "beta"))
        journal.advance_paper(at + timedelta(microseconds=1_500))
        for parent in journal.net_orders():
            journal.apply_net_event(
                OrderEvent(
                    identity=f"unknown-{parent.order.identity}",
                    order_id=parent.order.identity,
                    at=at + timedelta(microseconds=1_500),
                    kind="unknown",
                )
            )
        result = journal.control(self._cancel("cancel", at + 2 * self.MS))
        assert result.withdrawn_order_ids == ()
        journal.advance_paper(at + 50 * self.MS)
        journal.close()
        journal = AccountJournal(path, _Portfolio._config())
        journal.advance_paper(at + 60 * self.MS)
        assert {
            (item.order.status, item.order.cancel_requested) for item in journal.net_orders()
        } == {("unknown", True)}
        assert self._live(journal) == [("alpha", "intent", True), ("beta", "intent", True)]

    def test_another_accounts_waiting_plan_is_untouched(self, tmp_path: Path) -> None:
        """Cancelling ``shared`` withdraws alpha's plan; ``other``'s omega still arrives."""
        base = _Portfolio._config(("alpha",))
        accounts: tuple[OpeningAccount, ...] = (
            *base.accounts,
            OpeningAccount(account_id="other", cash=(_Portfolio._money("50000"),)),
        )
        limits: tuple[AccountLimit, ...] = (
            *base.budgets.accounts,
            AccountLimit(account_id="other", maximum=_Portfolio._money("10000")),
        )
        omega_limit: InstanceLimit = replace(
            base.budgets.instances[0], instance_id="omega", account_id="other"
        )
        instances: tuple[InstanceLimit, ...] = (*base.budgets.instances, omega_limit)
        config = replace(
            base,
            accounts=accounts,
            budgets=replace(base.budgets, accounts=limits, instances=instances),
        )
        journal = AccountJournal(tmp_path / "accounts.sqlite3", config)
        for account_id in ("shared", "other"):
            journal.bind_paper_scenario(account_id, _Portfolio._delayed_scenario())
            assert journal.reconcile(
                AccountObservation(
                    identity=f"opening-{account_id}",
                    at=self.opening_at,
                    snapshot=replace(_Portfolio._opening(), account_id=account_id),
                    open_orders=(),
                )
            )
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=_Portfolio._price(), at=at))
        journal.coordinate(self._batch("alpha", at, "alpha"))
        omega = _Portfolio._below("omega", at, "2")
        journal.coordinate(
            PortfolioBatch(
                identity="omega",
                at=at + timedelta(microseconds=1),
                decisions=(replace(omega, request=replace(omega.request, account_id="other")),),
            )
        )
        result = journal.control(self._cancel("cancel", at + timedelta(microseconds=500)))
        assert result.withdrawn_decision_ids == ("alpha-bid",)
        journal.advance_paper(at + 10 * self.MS)
        assert _Portfolio._outcomes(journal, at) == [
            ("alpha", timedelta(0), "arrival_pending"),
            ("omega", timedelta(0), "arrival_pending"),
            ("alpha", timedelta(microseconds=500), "withdrawn_by_account_cancel"),
            ("omega", self.MS, "reserved"),
        ]
        assert self._live(journal) == [("omega", "intent", False)]

    @pytest.mark.parametrize(
        "missing",
        (
            ("withdrawn_decision_ids", "withdrawn_order_ids"),
            ("withdrawn_decision_ids",),
            ("withdrawn_order_ids",),
        ),
        ids=("pre-d1", "no-decisions", "no-orders"),
    )
    def test_a_saved_cancel_receipt_without_withdrawal_lists_is_refused_unchanged(
        self, tmp_path: Path, missing: tuple[str, ...]
    ) -> None:
        """A journal whose cancel receipt predates D1 is refused, not reread or migrated.

        Before D1 a cancel receipt named only its physical orders. Removing either
        withdrawal list from a saved receipt gives that shape; the journal open and both
        verifiers refuse it as an unsupported schema, so no exact retry can return it,
        and the file's bytes stay as they were.
        """
        path = tmp_path / "pre-d1.sqlite3"
        journal = _Portfolio._ready(path)
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=_Portfolio._price(), at=at))
        journal.coordinate(
            PortfolioBatch(
                identity="pair",
                at=at + timedelta(microseconds=1),
                decisions=tuple(
                    _Portfolio._decision(instance=name, identity=f"{name}-buy", at=at)
                    for name in ("alpha", "beta")
                ),
            )
        )
        request = self._cancel("cancel", at + timedelta(seconds=1))
        assert journal.control(request).cancel_order_ids
        journal.close()
        with closing(sqlite3.connect(path)) as connection:
            row = cast(
                tuple[object, ...],
                connection.execute("SELECT payload FROM firm WHERE id=1").fetchone(),
            )
            payload = row[0]
            assert isinstance(payload, bytes)
            for name in missing:
                field = f',"{name}":[]'.encode()
                assert payload.count(field) == 1
                payload = payload.replace(field, b"")
            connection.execute("UPDATE firm SET payload=? WHERE id=1", (payload,))
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = path.read_bytes()
        config = _Portfolio._config()
        with pytest.raises(ValueError, match="unsupported account journal state schema"):
            AccountJournal(path, config)
        with pytest.raises(ValueError, match="unsupported account journal state schema"):
            AccountJournal.verify(path, config)
        with pytest.raises(ValueError, match="unsupported account journal state schema"):
            AccountStateStore.verify(path, config, DomainCodec())
        assert path.read_bytes() == before

    @pytest.mark.parametrize("name", ("withdrawn_decision_ids", "withdrawn_order_ids"))
    def test_a_receipt_missing_a_withdrawal_list_is_refused_where_it_is_decoded(
        self, name: str
    ) -> None:
        """Decoding a receipt never fills a missing withdrawal list with an empty one."""
        codec = DomainCodec()
        receipt = AccountControlResult(
            request=self._cancel("cancel", self.opening_at),
            status="applied",
            phase="running",
            recovery_generation=0,
            withdrawn_decision_ids=("alpha-bid",),
            withdrawn_order_ids=(),
        )
        encoded = codec.encode_json(receipt)
        assert codec.decode_json(encoded, AccountControlResult) == receipt
        values = {"withdrawn_decision_ids": b'["alpha-bid"]', "withdrawn_order_ids": b"[]"}
        field = f',"{name}":'.encode() + values[name]
        assert encoded.count(field) == 1
        with pytest.raises(ValueError, match=f"missing required field `{name}`"):
            codec.decode_json(encoded.replace(field, b""), AccountControlResult)
