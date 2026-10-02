"""Reject stale or incomplete health witnesses during bounded capacity measurement."""

from __future__ import annotations

# standard library imports
import os
import subprocess
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

# third party library imports
import msgspec
import pytest
from capacity_inputs import CapacityWorkload
from capacity_trial import CapacityTrial, _AccountPhase, _Child, _Health, _Status

# project library imports
from execution import PaperOwner
from serialization import DomainCodec

# A short existing root keeps AF_UNIX paths in limits on macOS and Linux.
_SOCKET_ROOT = "/private/tmp" if os.path.isdir("/private/tmp") else "/tmp"


class _RunningSupervisor:
    """Expose an independently running supervisor without launching a service."""

    @property
    def pid(self) -> int:
        """Bind the retained status to this independently observed live process."""
        return os.getpid()

    def poll(self) -> int | None:
        """Keep the test focused on retained status and owner identity."""
        return None


class TestCapacityHealth:
    """Require fresh observations and the exact active owner cohort throughout a run."""

    @pytest.fixture()
    def health_root(self) -> Iterator[Path]:
        """Keep admitted Unix endpoint paths within their platform byte limit."""
        with TemporaryDirectory(prefix="capacity-health-", dir=_SOCKET_ROOT) as root:
            yield Path(root)

    @staticmethod
    def _trial(root: Path) -> tuple[CapacityTrial, _Status]:
        """Create an exact healthy cohort with current-process liveness witnesses."""
        now = datetime.now(UTC)
        config = CapacityWorkload(opening_at=now, socket_root=root).service_configuration()
        trial = object.__new__(CapacityTrial)
        trial.config, trial.output, trial.service_root = config, root, root
        trial.codec = DomainCodec()
        trial.child_pids = set()
        trial.account_pids = {account.account_id: os.getpid() for account in config.accounts}
        trial.owners = {
            account.account_id: PaperOwner(
                account_id=account.account_id,
                deployment_sha256="a" * 64,
                authorization_id="test-grant",
                release_identity="b" * 64,
                owner_id="test-owner",
                generation=1,
            )
            for account in config.accounts
        }
        trial.supervisor = cast(subprocess.Popen[bytes], _RunningSupervisor())
        trial._health_run_id = None
        trial._health_last_ns = None
        selected = msgspec.structs.replace(config, alert_socket=str(root / "alerts.sock"))
        trial._health_configuration = selected.identity
        for account in config.accounts:
            owner = trial.owners[account.account_id]
            Path(account.socket_path).with_suffix(".health.json").write_bytes(
                trial.codec.encode_json(
                    _Health(
                        os.getpid(), 1, time.monotonic_ns(), owner.owner_id, owner.release_identity
                    )
                )
            )
        status = _Status(
            active=tuple(item.instance_id for item in config.instances),
            workers={item.instance_id: _Child(os.getpid(), True) for item in config.instances},
            sources={item.name: _Child(os.getpid(), True) for item in config.sources},
            faulted_accounts=(),
            stopping=False,
            observed_at=now,
            configuration=selected.identity,
            run_id="current-run",
            pid=os.getpid(),
            owners=tuple(trial.owners.values()),
            account_phases={
                name: _AccountPhase(now, "observed", "running") for name in trial.owners
            },
        )
        (root / "status.json").write_bytes(trial.codec.encode_json(status))
        return trial, status

    @pytest.mark.parametrize(
        "fault",
        (
            "stale_status",
            "stale_phase",
            "missing_phase",
            "missing_owner",
            "prior_run",
            "sample_gap",
            "unselected_configuration",
        ),
    )
    def test_stale_or_partial_status_cannot_qualify_healthy_seconds(
        self, health_root: Path, fault: str
    ) -> None:
        """A still-active endpoint snapshot cannot hide stale or missing interval evidence."""
        trial, status = self._trial(health_root)
        trial._sample_health()
        if fault == "stale_status":
            status = msgspec.structs.replace(
                status, observed_at=datetime.now(UTC) - timedelta(seconds=3)
            )
        elif fault == "stale_phase":
            stale_phases: dict[str, _AccountPhase] = {
                name: _AccountPhase(datetime.now(UTC) - timedelta(seconds=3), "observed", "running")
                for name in trial.owners
            }
            status = msgspec.structs.replace(
                status,
                account_phases=stale_phases,
            )
        elif fault == "missing_phase":
            empty_phases: dict[str, _AccountPhase] = {}
            status = msgspec.structs.replace(status, account_phases=empty_phases)
        elif fault == "missing_owner":
            status = msgspec.structs.replace(status, owners=status.owners[1:])
        elif fault == "prior_run":
            status = msgspec.structs.replace(status, run_id="other-run")
        elif fault == "sample_gap":
            trial._health_last_ns = time.monotonic_ns() - 3_000_000_000
        else:
            status = msgspec.structs.replace(status, configuration=trial.config.identity)
        (health_root / "status.json").write_bytes(trial.codec.encode_json(status))
        with pytest.raises(ValueError, match="stale, missing or unhealthy"):
            trial._sample_health()
