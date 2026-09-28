"""Exercise independent economic replay and fail-closed field comparisons."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

# third party library imports
from capacity_inputs import CapacityWorkload
from capacity_parity import CapacityEconomicParity

# project library imports
from execution import AccountExecutionResult, AccountJournal, AccountQuote
from market_data.contracts import BookObservation, CaptureRecord, CaptureRequest
from runtime import LiveBookDelivery, SharedBookDelivery
from serialization import DomainCodec


class TestCapacityParity:
    """Require complete exact comparison and a separately checked oracle."""

    def test_unmanaged_replay_checks_all_accounts_and_independent_oracle(
        self, tmp_path: Path
    ) -> None:
        """Replay canonical source sessions through four fresh local journals."""
        root = tmp_path / "selection"
        root.mkdir()
        workload = CapacityWorkload(
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-parity-sockets"),
        )
        workload.prepare(root / "preparation")
        service = workload.service_configuration()
        codec = DomainCodec()
        trial = root / "trial"
        trial.mkdir()
        (trial / "configuration.json").write_bytes(codec.encode_json(service))
        (trial / "summary.json").write_bytes(codec.encode_json({"implementation": "f" * 64}))
        run = trial / "operating/runs/single"
        run.mkdir(parents=True)
        signed_root = trial / "signed-journals"
        signed_root.mkdir()
        reconciled_at = datetime(2026, 9, 27, 13, tzinfo=UTC)
        for account in service.accounts:
            source = next(
                source
                for source in service.sources
                if any(
                    instance.account_id == account.account_id and instance.source == source.name
                    for instance in service.instances
                )
            )
            venue = workload.venue_workload(source.capture.venue)
            signed_path = signed_root / f"{account.account_id}.sqlite3"
            signed = AccountJournal(signed_path, account.configuration)
            signed.observe(
                AccountQuote(
                    price=venue.price("100", source.scenario.adverse.per),
                    at=reconciled_at - timedelta(microseconds=1),
                )
            )
            assert signed.reconcile(venue.opening_observation(account.account_id, reconciled_at))
            final = AccountExecutionResult(
                accounts=signed.accounts(),
                orders=signed.orders(),
                net_orders=signed.net_orders(),
                paper_traces=signed.paper_traces(),
                journal_path=str(signed_path),
            )
            (trial / f"final-{account.account_id}.json").write_bytes(codec.encode_json(final))
            request = CaptureRequest(
                config=source.capture,
                recording_id=str(uuid4()),
                implementation_identity="f" * 64,
            )
            request.__post_init__()
            source_directory = run / source.name
            request_directory = source_directory / request.recording_id / request.recording_id
            request_directory.mkdir(parents=True, exist_ok=True)
            (request_directory / "request.json").write_bytes(codec.encode_json(request))
            available_at = reconciled_at + timedelta(seconds=1)
            received_ns = int(available_at.timestamp()) * 1_000_000_000
            record = CaptureRecord(kind="session", epoch=0, received_ns=received_ns)
            book = BookObservation(
                position=0,
                epoch=0,
                received_ns=received_ns,
                source_time=None,
                sequence=None,
                outcome="session",
                status="recovering",
                reason="validated snapshot required",
                state_identity="0" * 64,
            )
            delivery = SharedBookDelivery(
                source=LiveBookDelivery(record=record, book=book, available_at=available_at),
                inputs=(),
                coordinated_at=None,
            )
            (source_directory / f"{request.recording_id}-{account.account_id}.jsonl").write_bytes(
                codec.encode_json(delivery) + b"\n"
            )

        report = CapacityEconomicParity(root, trial).write(tmp_path / "comparison.json")
        assert report["qualified"] is False
        accounts = cast(tuple[dict[str, object], ...], report["accounts"])
        assert len(accounts) == 4
        for result in accounts:
            assert result["replayed_deliveries"] == 1
            assert result["oracle_equal"] is False
            comparisons = cast(dict[str, dict[str, object]], result["comparisons"])
            assert set(comparisons) == set(CapacityEconomicParity.fields)
            assert all(comparison["equal"] is True for comparison in comparisons.values())

        stream = next(run.rglob("*-okx-shared.jsonl"))
        stream.write_bytes(stream.read_bytes().removesuffix(b"\n"))
        invalid = CapacityEconomicParity(root, trial).write(tmp_path / "invalid.json")
        invalid_accounts = cast(tuple[dict[str, object], ...], invalid["accounts"])
        failed = next(item for item in invalid_accounts if item["account"] == "okx-shared")
        assert failed["qualified"] is False
        assert "incomplete" in cast(str, failed["failure"])
        assert failed["signed"] is not None
        assert Path(cast(str, failed["replay_journal"])).is_file()

    def test_mismatch_retains_complete_signed_and_replay_values(self) -> None:
        """A changed fill and checkpoint must survive as full reviewable evidence."""
        signed: dict[str, object] = {
            field: (field, "same") for field in CapacityEconomicParity.fields
        }
        replay = dict(signed)
        replay["paper_fills"] = ("changed-fill",)
        replay["checkpoints"] = {"fixed": b"different"}
        comparison = CapacityEconomicParity._compare(signed, replay)
        assert set(comparison) == set(CapacityEconomicParity.fields)
        assert {field for field, value in comparison.items() if value["equal"] is False} == {
            "paper_fills",
            "checkpoints",
        }
        for field in ("paper_fills", "checkpoints"):
            assert comparison[field]["signed"] == signed[field]
            assert comparison[field]["replay"] == replay[field]
            assert comparison[field]["signed_sha256"] != comparison[field]["replay_sha256"]
