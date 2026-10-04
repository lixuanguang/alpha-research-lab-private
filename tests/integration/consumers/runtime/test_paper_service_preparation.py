"""Exercise installed-service definitions and native fixture lineage before signed trials."""

from __future__ import annotations

# standard library imports
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from multiprocessing.reduction import ForkingPickler
from pathlib import Path
from typing import Literal
from unittest.mock import patch

# third party library imports
import pytest
from paper_services import NativeBookFixture, PaperServiceWorkload

# project library imports
from configuration import (
    PaperAuthorization,
    PaperDeployment,
    PaperServiceConfiguration,
)
from market_data.adapters.sources import BookAdapters
from runtime import InstalledIdentity
from serialization import DomainCodec


class TestPaperServicePreparation:
    """Keep both venues' signed account envelopes separate from active selection."""

    @staticmethod
    async def _native_data(fixture: NativeBookFixture) -> tuple[bytes, ...]:
        """Read acknowledgements and four successive native book observations."""
        assert ForkingPickler.dumps(fixture)
        await fixture.open(1.0)
        await fixture.send("public book subscription")
        count = 5 if fixture.source.capture.venue == "okx" else 6
        frames = tuple([await fixture.recv() for _ in range(count)])
        await fixture.close()
        return frames

    @pytest.mark.parametrize("venue", ("okx", "bitfinex"))
    def test_preparation_and_additive_selection(
        self, venue: Literal["okx", "bitfinex"], tmp_path: Path
    ) -> None:
        """Preserve immutable budgets while later selecting provisioned ETH."""
        workload = PaperServiceWorkload(
            venue,
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path(f"/private/tmp/ps-{venue}-unit"),
        )
        output = tmp_path / venue
        summary = workload.prepare(output)
        codec = DomainCodec()
        initial = codec.decode_json(
            (output / "services-initial.json").read_bytes(), PaperServiceConfiguration
        )
        successor = codec.decode_json(
            (output / "services-addition.json").read_bytes(), PaperServiceConfiguration
        )
        successor.require_successor(initial)
        assert summary["initial_selection"] == initial.identity
        assert initial.duration_seconds == 45
        assert all(source.capture.duration_seconds == 60 for source in initial.sources)
        oracle = workload.first_touch_oracle()
        assert oracle["shared"] == (
            workload.money("99798.799" if venue == "okx" else "99798.80"),
            workload.money("0.201" if venue == "okx" else "0.20"),
            (workload.quantity("2", workload.dimensions[0]),),
        )
        assert {item.instance_id for item in initial.instances} == {
            "shared-fixed-btc",
            "shared-liquidity-btc",
            "shared-fixed-eth",
            "isolated-fixed-btc",
        }
        assert "shared-fixed-eth" not in initial.active
        assert "shared-fixed-eth" in successor.active
        assert successor.accounts == initial.accounts
        assert {item.scenario.adverse.currency for item in initial.sources} == {workload.currency}
        with patch.object(InstalledIdentity, "sha256", return_value="f" * 64):
            authority = workload.finalize(output, ("a" * 64,))
        assert authority["releases"] == ("a" * 64,)
        deployments = {
            account.account_id: codec.decode_json(
                (output / f"deployment-{account.account_id}.json").read_bytes(), PaperDeployment
            )
            for account in initial.accounts
        }
        shared = deployments["shared"]
        isolated = deployments["isolated"]
        assert (
            shared.scope_for("shared-fixed-btc").input_identity
            == shared.scope_for("shared-liquidity-btc").input_identity
        )
        assert shared.scope_for("shared-fixed-eth").input_identity != shared.input_identity
        assert len(shared.scenarios) == 2
        assert len(isolated.scenarios) == 1
        for account in initial.accounts:
            deployment = deployments[account.account_id]
            deployment.require_configuration(account.configuration)
            definitions = tuple(
                item for item in initial.instances if item.account_id == account.account_id
            )
            for strategy in deployment.strategies:
                definition = next(
                    item for item in definitions if item.instance_id == strategy.instance_id
                )
                source = next(item for item in initial.sources if item.name == definition.source)
                candidate = workload.candidate(initial, definition, source)
                assert definition.candidate.cadence_us == 3_000_000
                assert strategy.feature_identity == candidate.feature.schema.identity
                assert strategy.policy_identity == candidate.policy.identity
                assert strategy.candidate_identity == candidate.definition.identity
                assert deployment.scope_for(strategy.instance_id).input_identity == (
                    workload.input_identity(source)
                )
            grant = codec.decode_json(
                (output / f"authorization-{account.account_id}.json").read_bytes(),
                PaperAuthorization,
            )
            deployment.require_authorization(grant)
            assert grant.deployment_sha256 == deployment.identity

    @pytest.mark.parametrize("venue", ("okx", "bitfinex"))
    def test_native_touch_then_recovery_high_book(self, venue: Literal["okx", "bitfinex"]) -> None:
        """Keep ask 100 through entry delay, then move away from residual buys."""
        workload = PaperServiceWorkload(
            venue,
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path(f"/private/tmp/ps-{venue}-fixture"),
        )
        source = workload.service_configuration().sources[0]
        first = asyncio.run(
            self._native_data(NativeBookFixture(source, frame_count=4, interval_seconds=0.5))
        )
        offset = 1 if venue == "okx" else 2
        assert b"100" in first[offset]
        assert b"100" in first[offset + 1]
        assert b"100" in first[offset + 2]
        assert b"103" in first[offset + 3]
        book = BookAdapters.create(source.capture)
        observed_asks: list[Decimal] = []
        for frame in first:
            book.apply(frame)
            if book.ready:
                observed_asks.append(min(book.asks))
        assert observed_asks == [Decimal(100), Decimal(100), Decimal(100), Decimal(103)]
        recovery = asyncio.run(
            self._native_data(
                NativeBookFixture(source, frame_count=4, interval_seconds=0.5, start_high=True)
            )
        )
        # The native frame carries a wall-clock timestamp, so check parsed asks, not bytes.
        assert b"103" in recovery[offset]
        recovered_book = BookAdapters.create(source.capture)
        for frame in recovery:
            recovered_book.apply(frame)
            if recovered_book.ready:
                assert min(recovered_book.asks) == Decimal(103)

    def test_shadow_definitions_bind_shadow_only(self, tmp_path: Path) -> None:
        """A separate shadow envelope carries no paper-mode authorization."""
        workload = PaperServiceWorkload(
            "okx",
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/ps-shadow-unit"),
            mode="shadow",
        )
        output = tmp_path / "shadow"
        workload.prepare(output)
        with patch.object(InstalledIdentity, "sha256", return_value="f" * 64):
            workload.finalize(output, ("b" * 64,))
        codec = DomainCodec()
        deployment = codec.decode_json(
            (output / "deployment-shared.json").read_bytes(), PaperDeployment
        )
        grant = codec.decode_json(
            (output / "authorization-shared.json").read_bytes(), PaperAuthorization
        )
        assert deployment.submission_authority == grant.submission_authority == "shadow"
