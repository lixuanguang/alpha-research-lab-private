"""Fence a dead account owner before its last heartbeat ages out."""

from __future__ import annotations

# standard library imports
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# third party library imports
from test_paper_services import TestPaperServices as _PaperFixture

# project library imports
from applications.execute.services import PaperServices, _AccountHealth
from configuration import PaperServiceConfiguration
from execution import PaperOwner
from serialization import DomainCodec


class _OwnerHealthHarness(PaperServices):
    """Exercise only owner liveness without launching a policy or source child."""

    def __init__(self, config: PaperServiceConfiguration, owner: PaperOwner) -> None:
        """Retain the fields used by the owner branch of one supervisor scan."""
        self.config = config
        self.owners = (owner,)
        self.active: set[str] = set()
        self.workers = {}
        self.sources = {}
        self.faulted_accounts: set[str] = set()
        self.faults: list[tuple[str, str]] = []
        self.codec = DomainCodec()

    def _fault_account(self, account_id: str, reason: str, detail: str) -> None:
        """Record a protective fence without opening an unavailable socket."""
        self.faults.append((account_id, reason))


def test_dead_owner_pid_fences_account_with_fresh_heartbeat() -> None:
    """A process exit is visible even while its retained heartbeat is under two seconds old."""
    with TemporaryDirectory(prefix="service-health-", dir="/private/tmp") as directory:
        config = _PaperFixture._config(Path(directory) / "account.sock")
        owner = _PaperFixture._owner()
        health = _AccountHealth(
            pid=123456,
            owner_id=owner.owner_id,
            generation=owner.generation,
            release_identity=owner.release_identity,
            heartbeat_at="2026-09-27T00:00:00Z",
            heartbeat_ns=time.monotonic_ns(),
            request_progress_ns=time.monotonic_ns(),
            status="ready",
        )
        Path(config.accounts[0].socket_path).with_suffix(".health.json").write_bytes(
            DomainCodec().encode_json(health)
        )
        services = _OwnerHealthHarness(config, owner)
        with patch(
            "applications.execute.services.os.kill", side_effect=ProcessLookupError(3, "dead")
        ):
            services._supervise()
        assert services.faults == [(owner.account_id, "account_owner_lost")]
