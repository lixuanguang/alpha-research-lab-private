"""Exercise exact suppressed order admission and fail-closed mode boundaries."""

from __future__ import annotations

# standard library imports
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from configuration import ExecutionConfiguration, ExecutionRequest
from financial_units import Money, Quantity
from risk import AdmissionDecision, SubmissionAdmission

_FIXTURES = Path(__file__).parents[2] / "fixtures/execution"


class TestExecutionAdmission:
    """Check the source, capability, account and credential decisions independently."""

    @staticmethod
    def _inputs() -> tuple[ExecutionConfiguration, ExecutionRequest]:
        """Read the retained OKX observation and authored no-submit account scenario."""
        return (
            ExecutionConfiguration.read(_FIXTURES / "shadow-config.json"),
            ExecutionRequest.read(_FIXTURES / "shadow-request.json"),
        )

    def test_exact_buy_is_suppressed_with_selected_reference_identity(self) -> None:
        """A 0.00001 BTC buy at 84000 plus 0.01 maximum fee fits 1000 USDT cash."""
        config, request = self._inputs()
        decision = SubmissionAdmission().evaluate(config, request)

        assert decision.status == "suppressed"
        assert decision.reason == "submission_disabled"
        assert decision.submission_attempted is False
        assert decision.specification_identity == (
            "3837bf935938de124bb7edc9d66cded62a03219b14af91c3161b8807ab368322"
        )
        assert config.inspect().state_schema == "none"

    @pytest.mark.parametrize("mode", ("research", "paper", "shadow"))
    def test_credential_scope_cannot_be_promoted(self, mode: str) -> None:
        """A signed research or shadow reference never admits a production request."""
        config, request = self._inputs()
        if mode != "shadow":
            with pytest.raises(ValueError, match="credential reference"):
                replace(config, mode=mode)
        with pytest.raises(ValueError, match="production submission"):
            replace(config, mode="production")
        with pytest.raises(ValueError, match="request mode differs"):
            SubmissionAdmission().evaluate(config, replace(request, requested_mode="production"))

    def test_capability_and_observation_must_cover_the_order(self) -> None:
        """Reject a foreign venue profile and an observation older than the allowed age."""
        config, request = self._inputs()
        with pytest.raises(ValueError, match="incompatible capability profile"):
            SubmissionAdmission().evaluate(
                replace(config, profile=replace(config.profile, venues=("bitfinex",))), request
            )
        late = replace(
            request,
            valid_at=request.valid_at + timedelta(seconds=61),
            known_at=request.known_at + timedelta(seconds=61),
        )
        with pytest.raises(ValueError, match="unknown, stale"):
            SubmissionAdmission().evaluate(config, late)

    def test_exact_account_limits_reject_affordability_lot_and_pending(self) -> None:
        """At the limit, 0.84 cost plus 0.01 fee exceeds 0.84 cash exactly."""
        config, request = self._inputs()
        low_cash = replace(
            request, cash=Money(value=Decimal("0.84"), currency=request.cash.currency)
        )
        assert SubmissionAdmission().evaluate(config, low_cash).reason == "insufficient_cash"
        off_lot = replace(
            request,
            intent=replace(
                request.intent,
                quantity=Quantity(
                    value=Decimal("0.000010005"), dimension=request.intent.quantity.dimension
                ),
            ),
        )
        assert SubmissionAdmission().evaluate(config, off_lot).reason == "off_lot_order"
        assert (
            SubmissionAdmission().evaluate(config, replace(request, pending=True)).reason
            == "pending_intent"
        )

    def test_decision_record_refuses_false_submission_claim(self) -> None:
        """Direct callers cannot construct an invalid decision reason or identity."""
        with pytest.raises(ValueError, match="invalid admission reason"):
            AdmissionDecision(
                status="suppressed",
                reason="unknown reason",
                mode="shadow",
                specification_identity="a" * 64,
                profile_identity="spot-intent-only",
            )
