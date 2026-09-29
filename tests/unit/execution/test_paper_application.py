"""Exercise the installed paper command's non-submitting account workflow."""

from __future__ import annotations

# standard library imports
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

# third party library imports
import pytest

# project library imports
from accounting import Fill
from applications.execute import (
    PaperExecutionApplication,
    PaperExecutionRequest,
    PaperExecutionResult,
)
from applications.execute import main as execute_main
from configuration import PaperConfiguration, PaperExecutionScenario
from execution import OrderDecision, OrderEvent, PaperMarket
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from serialization import DomainCodec
from strategies import OrderIntent


class TestPaperExecutionApplication:
    """Run the same serialized request shape over separate command invocations."""

    currency = Currency(code="TEST", minor_unit=Decimal("0.01"))
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    start = datetime(2024, 6, 1, tzinfo=UTC)

    @classmethod
    def _money(cls, value: str) -> Money:
        """Construct exact test cash and fees."""
        return Money(value=Decimal(value), currency=cls.currency)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Construct exact test base units."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _price(cls, value: str) -> Price:
        """Construct exact test quote-currency limits."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _config(cls, mode: str) -> PaperConfiguration:
        """Select one flat dedicated paper or shadow account."""
        if mode not in ("paper", "shadow"):
            raise ValueError("unsupported test mode")
        return PaperConfiguration(
            account="reference-account",
            mode="paper" if mode == "paper" else "shadow",
            initial_cash=cls._money("1000"),
            maximum=cls._quantity("10"),
            lot=cls._quantity("1"),
            tick=cls._price("0.01"),
            maximum_fee=cls._money("1"),
            fee_rate=Decimal("0.001"),
            market_max_age_us=60_000_000,
            execution=PaperExecutionScenario(
                venue="okx",
                instrument_id=cls.dimension.instrument_id,
                entry_delay_us=0,
                cancel_delay_us=0,
                adverse=cls._price("0"),
                fee_rate=Decimal("0.001"),
                take_fraction=Decimal("1"),
                gas_inapplicable_reason="off-chain spot orders have no on-chain settlement",
            ),
        )

    @staticmethod
    def _write(path: Path, record: object) -> Path:
        """Write the exact typed request bytes consumed by the command."""
        path.write_bytes(DomainCodec().encode_json(record))
        return path

    @staticmethod
    def _json_object(payload: str) -> dict[str, object]:
        """Narrow a public CLI JSON object without a dynamic domain decoder."""
        value = cast(object, json.loads(payload))
        if not isinstance(value, dict) or any(type(key) is not str for key in value):
            raise ValueError("execution CLI returned a malformed JSON object")
        return cast(dict[str, object], value)

    @classmethod
    def _decision(cls) -> OrderDecision:
        """Create a single funded paper buy with no client submission semantics."""
        return OrderDecision(
            identity="reference-buy",
            at=cls.start,
            intent=OrderIntent(
                side="buy",
                quantity=cls._quantity("1"),
                limit=cls._price("100"),
                time_in_force="ioc",
            ),
        )

    @classmethod
    def _market(cls) -> PaperMarket:
        """Provide one later quote with finite displayed liquidity."""
        return PaperMarket(
            identity="received-quote",
            at=cls.start + timedelta(seconds=1),
            bid=cls._price("99"),
            ask=cls._price("100"),
            bid_quantity=cls._quantity("1"),
            ask_quantity=cls._quantity("1"),
        )

    def test_paper_cli_decides_matches_and_inspects_without_submission(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Use real JSON files and the public command entry across independent invocations."""
        config = self._write(tmp_path / "paper-config.json", self._config("paper"))
        journal = tmp_path / "paper.sqlite3"
        decide = self._write(
            tmp_path / "decide.json",
            PaperExecutionRequest(
                action="decide",
                identity="decision-step",
                checkpoint=b"candidate-checkpoint",
                decision=self._decision(),
            ),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "alpha-execute",
                "paper",
                "--config",
                str(config),
                "--journal",
                str(journal),
                "--instance",
                "reference-instance",
                "--request",
                str(decide),
            ],
        )
        execute_main()
        first = DomainCodec().decode_json(capsys.readouterr().out, PaperExecutionResult)
        assert first.step is not None and first.step.reason == "reserved"
        assert first.submission_attempted is False
        assert first.qualification == "fixture"
        assert first.reservations.cash.value == Decimal("101")
        market = self._write(
            tmp_path / "market.json",
            PaperExecutionRequest(action="market", identity="market-step", market=self._market()),
        )
        monkeypatch.setattr(sys, "argv", [*sys.argv[:-1], str(market)])
        execute_main()
        matched = DomainCodec().decode_json(capsys.readouterr().out, PaperExecutionResult)
        assert matched.balance.cash.value == Decimal("899.90")
        assert matched.balance.holding.value == 1
        assert matched.reservations.cash.value == 0
        assert matched.last_event_sequence == 3
        assert matched.orders[0].status == "filled"
        monkeypatch.setattr(sys, "argv", sys.argv[:-2])
        execute_main()
        inspected = DomainCodec().decode_json(capsys.readouterr().out, PaperExecutionResult)
        assert inspected.action == "inspect"
        assert inspected.orders == matched.orders
        assert inspected.submission_attempted is False
        assert inspected.binding_identity == matched.binding_identity

    def test_profiled_market_request_retries_after_newer_quote_and_reopen(
        self, tmp_path: Path
    ) -> None:
        """An older exact request reopens its result without rewinding liquidity or fills."""
        scenario = PaperExecutionScenario(
            venue="okx",
            instrument_id=self.dimension.instrument_id,
            entry_delay_us=0,
            cancel_delay_us=0,
            adverse=self._price("0"),
            fee_rate=Decimal("0.001"),
            take_fraction=Decimal("1"),
            gas_inapplicable_reason="off-chain spot venue matching has no chain gas",
        )
        config = PaperConfiguration(
            account="reference-account",
            mode="paper",
            initial_cash=self._money("1000"),
            maximum=self._quantity("10"),
            lot=self._quantity("1"),
            tick=self._price("0.01"),
            maximum_fee=self._money("1"),
            fee_rate=scenario.fee_rate,
            market_max_age_us=60_000_000,
            execution=scenario,
        )
        config_path = self._write(tmp_path / "scenario-config.json", config)
        journal_path = tmp_path / "scenario.sqlite3"
        decide = self._write(
            tmp_path / "scenario-decide.json",
            PaperExecutionRequest(action="decide", identity="decision", decision=self._decision()),
        )
        first = self._write(
            tmp_path / "scenario-first.json",
            PaperExecutionRequest(action="market", identity="first", market=self._market()),
        )
        later_market = PaperMarket(
            identity="received-next",
            at=self.start + timedelta(seconds=2),
            bid=self._price("99"),
            ask=self._price("100"),
            bid_quantity=self._quantity("1"),
            ask_quantity=self._quantity("1"),
        )
        later = self._write(
            tmp_path / "scenario-later.json",
            PaperExecutionRequest(action="market", identity="later", market=later_market),
        )
        application = PaperExecutionApplication()
        for request in (decide, first):
            application.run(
                config_path=config_path,
                journal_path=journal_path,
                instance="reference-instance",
                request_path=request,
            )
        current = application.run(
            config_path=config_path,
            journal_path=journal_path,
            instance="reference-instance",
            request_path=later,
        )
        reopened = PaperExecutionApplication().run(
            config_path=config_path,
            journal_path=journal_path,
            instance="reference-instance",
            request_path=first,
        )
        assert reopened.orders == current.orders
        assert reopened.balance == current.balance
        assert reopened.last_event_sequence == current.last_event_sequence

    def test_shadow_refuses_modeled_fill_and_reconciliation_blocks_new_risk(
        self, tmp_path: Path
    ) -> None:
        """Shadow preserves intent state but has no paper matcher or fill posting."""
        config = self._write(tmp_path / "shadow-config.json", self._config("shadow"))
        journal = tmp_path / "shadow.sqlite3"
        application = PaperExecutionApplication()
        decide = self._write(
            tmp_path / "decide.json",
            PaperExecutionRequest(
                action="decide", identity="decision-step", decision=self._decision()
            ),
        )
        admitted = application.run(
            config_path=config,
            journal_path=journal,
            instance="reference-instance",
            request_path=decide,
        )
        assert admitted.step is not None and admitted.step.status == "committed"
        order = admitted.orders[0]
        market = self._write(
            tmp_path / "market.json",
            PaperExecutionRequest(action="market", identity="market-step", market=self._market()),
        )
        with pytest.raises(ValueError, match="paper mode"):
            application.run(
                config_path=config,
                journal_path=journal,
                instance="reference-instance",
                request_path=market,
            )
        fill = Fill(
            identity="imagined-fill",
            decision_at=self.start,
            filled_at=self.start + timedelta(seconds=1),
            quantity=self._quantity("1"),
            reference=self._price("100"),
            effective=self._price("100"),
            fee=self._money("0.10"),
        )
        fill_request = self._write(
            tmp_path / "fill.json",
            PaperExecutionRequest(
                action="event",
                identity="received-fill",
                event=OrderEvent(
                    identity="received-fill",
                    order_id=order.identity,
                    at=fill.filled_at,
                    kind="fill",
                    fill=fill,
                ),
            ),
        )
        with pytest.raises(ValueError, match="shadow mode"):
            application.run(
                config_path=config,
                journal_path=journal,
                instance="reference-instance",
                request_path=fill_request,
            )
        mismatch = self._write(
            tmp_path / "mismatch.json",
            PaperExecutionRequest(
                action="reconcile",
                identity="account-break",
                expected_cash=self._money("999"),
                expected_holding=self._quantity("0"),
                open_order_ids=(order.identity,),
            ),
        )
        broken = application.run(
            config_path=config,
            journal_path=journal,
            instance="reference-instance",
            request_path=mismatch,
        )
        assert broken.reconciled is False and broken.blocked_reason == "account_break"
        restored = self._write(
            tmp_path / "restored.json",
            PaperExecutionRequest(
                action="reconcile",
                identity="matched-account",
                expected_cash=self._money("1000"),
                expected_holding=self._quantity("0"),
                open_order_ids=(order.identity,),
            ),
        )
        matched = application.run(
            config_path=config,
            journal_path=journal,
            instance="reference-instance",
            request_path=restored,
        )
        assert matched.reconciled is True and matched.blocked_reason is None
        assert matched.balance.cash.value == Decimal("1000")

    def test_paper_event_and_cancel_commands_keep_commitment_until_terminal(
        self, tmp_path: Path
    ) -> None:
        """Separate command invocations cannot treat a cancel acknowledgement as cancellation."""
        config = self._write(tmp_path / "paper-config.json", self._config("paper"))
        journal = tmp_path / "cancel.sqlite3"
        application = PaperExecutionApplication()
        decision = self._write(
            tmp_path / "decision.json",
            PaperExecutionRequest(
                action="decide", identity="order-step", decision=self._decision()
            ),
        )
        admitted = application.run(
            config_path=config,
            journal_path=journal,
            instance="reference-instance",
            request_path=decision,
        )
        order_id = admitted.orders[0].identity
        later = self.start + timedelta(seconds=1)
        accepted = self._write(
            tmp_path / "accepted.json",
            PaperExecutionRequest(
                action="event",
                identity="accepted-event",
                event=OrderEvent(
                    identity="accepted-event", order_id=order_id, at=later, kind="accepted"
                ),
            ),
        )
        observed = application.run(
            config_path=config,
            journal_path=journal,
            instance="reference-instance",
            request_path=accepted,
        )
        assert observed.order is not None and observed.order.accepted
        cancel = self._write(
            tmp_path / "cancel.json",
            PaperExecutionRequest(
                action="cancel", identity="cancel-request", order_id=order_id, at=later
            ),
        )
        requested = application.run(
            config_path=config,
            journal_path=journal,
            instance="reference-instance",
            request_path=cancel,
        )
        assert requested.order is not None and requested.order.status == "cancel_requested"
        assert requested.reservations.cash.value == Decimal("101")
        acknowledged = self._write(
            tmp_path / "cancel-ack.json",
            PaperExecutionRequest(
                action="event",
                identity="cancel-ack-event",
                event=OrderEvent(
                    identity="cancel-ack-event", order_id=order_id, at=later, kind="cancel_ack"
                ),
            ),
        )
        pending = application.run(
            config_path=config,
            journal_path=journal,
            instance="reference-instance",
            request_path=acknowledged,
        )
        assert pending.order is not None and pending.order.status == "cancel_ack"
        assert pending.reservations.cash.value == Decimal("101")
        replacement = self._write(
            tmp_path / "replace.json",
            PaperExecutionRequest(
                action="replace",
                identity="replacement-step",
                order_id=order_id,
                checkpoint=b"replacement-candidate",
                decision=OrderDecision(
                    identity="replacement-decision",
                    at=later + timedelta(seconds=1),
                    intent=OrderIntent(
                        side="buy",
                        quantity=self._quantity("1"),
                        limit=self._price("99"),
                        time_in_force="gtc",
                    ),
                ),
            ),
        )
        with pytest.raises(ValueError, match="confirmed terminal"):
            application.run(
                config_path=config,
                journal_path=journal,
                instance="reference-instance",
                request_path=replacement,
            )
        terminal = self._write(
            tmp_path / "cancelled.json",
            PaperExecutionRequest(
                action="event",
                identity="cancelled-event",
                event=OrderEvent(
                    identity="cancelled-event", order_id=order_id, at=later, kind="cancelled"
                ),
            ),
        )
        closed = application.run(
            config_path=config,
            journal_path=journal,
            instance="reference-instance",
            request_path=terminal,
        )
        assert closed.order is not None and closed.order.is_terminal
        assert closed.reservations.cash.value == 0
        replaced = application.run(
            config_path=config,
            journal_path=journal,
            instance="reference-instance",
            request_path=replacement,
        )
        assert replaced.step is not None and replaced.step.status == "committed"
        assert len(replaced.orders) == 2
        assert replaced.step.orders[0].replace_of == order_id
        assert replaced.step.orders[0].identity != order_id
        assert replaced.reservations.cash.value == Decimal("100")
        replayed = application.run(
            config_path=config,
            journal_path=journal,
            instance="reference-instance",
            request_path=replacement,
        )
        assert replayed.orders == replaced.orders
        assert replayed.reservations == replaced.reservations

    def test_paper_request_rejects_mixed_commands_and_binding_change(self, tmp_path: Path) -> None:
        """A changed installed scenario cannot reopen the same durable account."""
        config = self._write(tmp_path / "paper-config.json", self._config("paper"))
        journal = tmp_path / "paper.sqlite3"
        application = PaperExecutionApplication()
        application.run(
            config_path=config,
            journal_path=journal,
            instance="reference-instance",
            request_path=None,
        )
        with pytest.raises(ValueError, match="differs"):
            application.run(
                config_path=config,
                journal_path=journal,
                instance="foreign-instance",
                request_path=None,
            )
        with pytest.raises(ValueError, match="payload is inconsistent"):
            PaperExecutionRequest(
                action="event",
                identity="event",
                event=OrderEvent(
                    identity="event",
                    order_id="order",
                    at=self.start,
                    kind="unknown",
                ),
                market=self._market(),
            )

    def test_existing_admission_commands_keep_their_read_only_output(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The installed MR06 command path still reports suppressed admission."""
        fixtures = Path(__file__).parents[2] / "fixtures" / "execution"
        config = fixtures / "shadow-config.json"
        request = fixtures / "shadow-request.json"
        monkeypatch.setattr(sys, "argv", ["alpha-execute", "inspect", "--config", str(config)])
        execute_main()
        inspection = self._json_object(capsys.readouterr().out)
        assert inspection["schema_version"] == "execution-admission"
        assert inspection["submission_available"] is False
        monkeypatch.setattr(
            sys,
            "argv",
            ["alpha-execute", "admit", "--config", str(config), "--request", str(request)],
        )
        execute_main()
        admission = self._json_object(capsys.readouterr().out)
        assert admission["status"] == "suppressed"
        assert admission["submission_attempted"] is False
