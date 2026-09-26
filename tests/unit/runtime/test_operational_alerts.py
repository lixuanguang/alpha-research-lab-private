"""Check retained local alerts without coupling delivery to independent hard stops."""

from __future__ import annotations

# standard library imports
import socket
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest

# project library imports
from serialization import DomainCodec
from telemetry import OperationalAlerts, OperationAlert


class TestOperationalAlerts:
    """Check local delivery semantics, changed retries and interrupted attempts."""

    def test_delivery_failure_and_exact_retry_are_retained(self, tmp_path: Path) -> None:
        """A missing local receiver is explicit and an identical retry sends no duplicate."""
        store = OperationalAlerts(tmp_path / "alerts.sqlite3")
        address = str(tmp_path / "absent.sock")
        first = store.send(identity="stop", control_sha256="1" * 64, address=address)
        assert first.status == "failed"
        with patch(
            "telemetry.operations.HealthAlert.deliver", side_effect=AssertionError("resent")
        ):
            assert store.send(identity="stop", control_sha256="1" * 64, address=address) == first
        assert OperationalAlerts(store.path).read() == (first,)
        with pytest.raises(ValueError, match="different content"):
            store.send(identity="stop", control_sha256="2" * 64, address=address)

    def test_real_local_datagram_and_pending_attempt(self, tmp_path: Path) -> None:
        """A received datagram proves local delivery; process loss cannot claim delivery."""
        store = OperationalAlerts(tmp_path / "alerts.sqlite3")
        address = str(tmp_path / "alerts.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
            receiver.bind(address)
            receiver.settimeout(1)
            delivered = store.send(identity="fault", control_sha256="a" * 64, address=address)
            assert delivered.status == "delivered"
            assert ("account-control:" + "a" * 64).encode() in receiver.recv(1024)
        pending = OperationAlert(
            identity="interrupted", control_sha256="b" * 64, address=address, status="pending"
        )
        with closing(sqlite3.connect(store.path)) as connection:
            connection.execute(
                "INSERT INTO alerts VALUES (?, ?)",
                (pending.identity, DomainCodec().encode_json(pending)),
            )
            connection.commit()
        with patch(
            "telemetry.operations.HealthAlert.deliver", side_effect=AssertionError("resent")
        ):
            assert (
                store.send(
                    identity=pending.identity,
                    control_sha256=pending.control_sha256,
                    address=address,
                )
                == pending
            )

    def test_invalid_wire_fields_and_absent_inspection(self, tmp_path: Path) -> None:
        """Reject malformed endpoints before creating a store or attempting a socket."""
        store = OperationalAlerts(tmp_path / "absent.sqlite3")
        assert store.read() == () and not store.path.exists()
        with pytest.raises(ValueError, match="invalid"):
            store.send(identity="fault", control_sha256="not-a-digest", address="relative.sock")
        assert not store.path.exists()
