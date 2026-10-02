"""Fence account owner loss and replacement within the original health deadline."""

from __future__ import annotations

# standard library imports
import concurrent.futures
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import replace
from test_paper_services import TestPaperServices as _PaperFixture

# project library imports
from applications.execute.services import PaperServices
from configuration import PaperServiceAccount, PaperServiceConfiguration
from execution import PaperOwner
from serialization import DomainCodec

# A short existing root keeps AF_UNIX paths in limits on macOS and Linux.
_SOCKET_ROOT = "/private/tmp" if os.path.isdir("/private/tmp") else "/tmp"


class _OwnerHealthHarness(PaperServices):
    """Exercise owner liveness without launching a policy or source child."""

    def __init__(self, config: PaperServiceConfiguration, owners: tuple[PaperOwner, ...]) -> None:
        """Retain the fields used by one supervisor health turn."""
        self.config = config
        self.owners = owners
        self.active: set[str] = set()
        self.workers = {}
        self.sources = {}
        self.faulted_accounts: set[str] = set()
        self.faults: list[tuple[str, str]] = []
        self.codec = DomainCodec()
        self._observation_executor = None
        self._has_disjoint_source_accounts = self._sources_have_disjoint_accounts()
        self._pending_observations = {}
        self._observation_wake_receiver = self._observation_wake_sender = None
        self._next_owner_health_ns = 0

    def _fault_account(self, account_id: str, reason: str, detail: str) -> None:
        """Record protective fencing without opening an unavailable account socket."""
        self.faults.append((account_id, reason))
        self.faulted_accounts.add(account_id)


class TestServiceOwnerHealth:
    """Preserve owner death/replacement protection while coalescing redundant reads."""

    @staticmethod
    def _owner_harness(root: Path, *, shared: bool = False) -> _OwnerHealthHarness:
        """Retain the real shared/disjoint topology with short test-owned socket paths."""
        config = _PaperFixture._two_source_config(shared=shared)
        accounts: tuple[PaperServiceAccount, ...] = tuple(
            replace(account, socket_path=str(root / f"{account.account_id}.sock"))
            for account in config.accounts
        )
        config = replace(config, accounts=accounts)
        return _OwnerHealthHarness(
            config,
            tuple(_PaperFixture._owner(account.account_id) for account in config.accounts),
        )

    def test_disjoint_owner_health_is_checked_on_the_first_turn(self) -> None:
        """The first parallel turn fences a missing owner file without waiting for a deadline."""
        with TemporaryDirectory(prefix="service-health-", dir=_SOCKET_ROOT) as directory:
            services = self._owner_harness(Path(directory))
            owner = services.owners[1]
            Path(services.config.accounts[1].socket_path).with_suffix(".health.json").write_bytes(
                services.codec.encode_json(_PaperFixture._owner_health(owner, time.monotonic_ns()))
            )
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                services._observation_executor = executor
                assert services._supervise() is False
            assert services.faults == [(services.owners[0].account_id, "account_owner_lost")]

    @pytest.mark.parametrize("shared", (False, True))
    def test_owner_replacement_is_fenced_by_the_original_idle_deadline(self, shared: bool) -> None:
        """Owner replacement respects parallel deadlines and immediate shared checks."""
        with TemporaryDirectory(prefix="service-health-", dir=_SOCKET_ROOT) as directory:
            services = self._owner_harness(Path(directory), shared=shared)
            checked_ns = 9_000_000_000
            for account, owner in zip(services.config.accounts, services.owners, strict=True):
                Path(account.socket_path).with_suffix(".health.json").write_bytes(
                    services.codec.encode_json(_PaperFixture._owner_health(owner, checked_ns))
                )
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                services._observation_executor = executor
                with patch(
                    "applications.execute.services.time.monotonic_ns", return_value=checked_ns
                ):
                    assert services._supervise() is False
                assert services.faults == []
                owner = services.owners[0]
                replaced_health = replace(
                    _PaperFixture._owner_health(owner, checked_ns), generation=owner.generation + 1
                )
                Path(services.config.accounts[0].socket_path).with_suffix(
                    ".health.json"
                ).write_bytes(services.codec.encode_json(replaced_health))
                expected = [(owner.account_id, "account_owner_lost")]
                for elapsed_ns, faults in (
                    (19_999_999, expected if shared else []),
                    (20_000_000, expected),
                ):
                    with patch(
                        "applications.execute.services.time.monotonic_ns",
                        return_value=checked_ns + elapsed_ns,
                    ):
                        assert services._supervise() is False
                    assert services.faults == faults

    def test_dead_owner_pid_fences_account_with_fresh_heartbeat(self) -> None:
        """Process exit is visible even while the retained heartbeat is under two seconds old."""
        with TemporaryDirectory(prefix="service-health-", dir=_SOCKET_ROOT) as directory:
            config = _PaperFixture._config(Path(directory) / "account.sock")
            owner = _PaperFixture._owner()
            health = replace(_PaperFixture._owner_health(owner, time.monotonic_ns()), pid=123456)
            services = _OwnerHealthHarness(config, (owner,))
            Path(config.accounts[0].socket_path).with_suffix(".health.json").write_bytes(
                services.codec.encode_json(health)
            )
            with patch(
                "applications.execute.services.os.kill", side_effect=ProcessLookupError(3, "dead")
            ):
                services._supervise()
            assert services.faults == [(owner.account_id, "account_owner_lost")]
