"""Carry supervised capture inputs across the spawn boundary of its child process."""

from __future__ import annotations

# standard library imports
import pickle
import sys
from pathlib import Path

# third party library imports
import pytest

# project library imports
import applications.collect.workflow as workflow
from applications.collect import main
from configuration import CaptureConfig
from market_data.adapters.transport import VenueTransport
from market_data.adapters.venues.coinbase import CoinbaseCredentials
from runtime import ProcessSupervisor
from telemetry import HealthMetrics, HealthPolicy

_ROOT = Path(__file__).parents[3]


class TestCollectSupervision:
    """Carry supervised capture inputs across the child process's spawn boundary."""

    def test_supervised_coinbase_capture_hands_its_credentials_to_the_child(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The installed command's workload survives spawn, and the child loads the credentials."""
        credential_file = tmp_path / "coinbase-exchange.cred"
        credential_file.write_text("API_KEY=example\nAPI_SECRET=c2VjcmV0\nAPI_PASSPHRASE=phrase\n")
        credential_file.chmod(0o600)
        spawn = _SpawnRecorder()
        monkeypatch.setattr(ProcessSupervisor, "run", spawn)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "alpha-collect",
                "capture",
                "--config",
                str(_ROOT / "configs/live/coinbase-btc-usd.json"),
                "--output",
                str(tmp_path / "captures"),
                "--secrets",
                str(credential_file),
                "--health-config",
                str(_ROOT / "configs/live/health.json"),
            ],
        )
        main()
        (child,) = spawn.children
        capture = _CaptureRecorder()
        monkeypatch.setattr(workflow, "monitored_capture", capture)
        child(tmp_path / "child", HealthMetrics())
        (credentials,) = capture.received
        assert isinstance(credentials, CoinbaseCredentials)


class _SpawnRecorder:
    """Cross the boundary as a spawn start does: by pickling the workload."""

    def __init__(self) -> None:
        """Start with no children."""
        self.children: list[workflow._CaptureWorkload] = []

    def __call__(
        self, root: Path, policy: HealthPolicy, workload: workflow._CaptureWorkload, **_: object
    ) -> dict[str, object]:
        """Round-trip the workload through pickle and record the child's copy."""
        child: object = pickle.loads(pickle.dumps(workload))
        assert isinstance(child, workflow._CaptureWorkload)
        self.children.append(child)
        return {"stop_reason": "completed"}


class _CaptureRecorder:
    """Record what the child would connect with instead of capturing."""

    def __init__(self) -> None:
        """Start with nothing received."""
        self.received: list[CoinbaseCredentials | None] = []

    async def __call__(
        self,
        config: CaptureConfig,
        output: Path,
        health: HealthMetrics,
        credentials: CoinbaseCredentials | None,
        transport: VenueTransport | None,
    ) -> None:
        """Record the credentials the child would use."""
        self.received.append(credentials)
