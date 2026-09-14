"""Verify configured saved-frame composition and the installed command boundary."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research.configuration import Configuration
from alpha_research.data.venues.binance.codecs import MarketEventCodec
from alpha_research.pipelines.dataset import inspect_fixture, main
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CONFIG = _ROOT / "configs/data-jobs/fixture-inspection.json"
_CATALOG = _ROOT / "configs/reference/binance-spot.json"
_FIXTURES = _ROOT / "tests/fixtures/m0"
_RECEIVED = datetime(2026, 9, 14, tzinfo=UTC)
_INGESTED = _RECEIVED + timedelta(seconds=1)
_CODEC = DomainCodec()


class TestFixtureInspection:
    """Exercise exact events, receipt metadata and controlled failures with no source access."""

    @pytest.mark.parametrize(
        ("job", "symbol", "price"),
        [
            ("btc-fixture", "BTCUSDT", "67540.01000000"),
            ("eth-fixture", "ETHUSDT", "3800.01000000"),
            ("both-fixture", "ETHUSDT", "3800.01000000"),
        ],
    )
    def test_saved_frame_binds_exact_request_and_clocks(
        self, job: str, symbol: str, price: str
    ) -> None:
        """Reuse the same pipeline for either listing and preserve all original clock meanings."""
        manifest = Configuration.read(_CONFIG).resolve(
            job, _CODEC.decode_json(_CATALOG.read_bytes(), CatalogSnapshot)
        )
        fixture = _FIXTURES / f"{symbol.lower()}.txt"
        request, event, digest = inspect_fixture(
            manifest, fixture, local_received=_RECEIVED, local_ingested=_INGESTED, source_sequence=4
        )
        assert event.symbol == symbol
        assert event.price == Decimal(price)
        assert request.instrument.instrument_id == event.instrument_id
        assert request.offset_minutes == 0
        assert event.provenance.ts_event == datetime(2024, 5, 31, 23, 59, 59, 993000, tzinfo=UTC)
        assert event.provenance.ts_knowledge == manifest.job.start + timedelta(microseconds=4103)
        assert event.provenance.ts_received == _RECEIVED
        assert event.provenance.ts_ingested == _INGESTED
        assert event.provenance.source_sequence == 4
        assert (
            digest
            == hashlib.sha256(fixture.read_bytes()).hexdigest()
            == event.provenance.source_digest
        )
        assert MarketEventCodec().decode(MarketEventCodec().encode(event)) == event

    @pytest.mark.parametrize(
        ("before", "after", "message"),
        [
            ("btcusdt@trade", "ethusdt@trade", "unsupported stream symbol ETHUSDT"),
            ('"s":"BTCUSDT"', '"s":"ETHUSDT"', "does not match payload symbol"),
            ("2024-06-01T00:00:00.0041023Z", "not-a-timestamp", "capture timestamp"),
            ("2024-06-01T00:00:00.0041023Z", "2024-06-01T01:00:00Z", "half-open interval"),
            ("2024-06-01T00:00:00.0041023Z", "2024-05-31T23:59:59Z", "half-open interval"),
            ("1717199999993", "-1", "T must be nonnegative"),
            ("1717199999993", "9999999999999999999", "T is outside datetime range"),
            ("1717199999993", '"invalid"', "source payload fields are invalid"),
        ],
    )
    def test_invalid_frame_fails_and_subsequent_valid_inspection_recovers(
        self,
        tmp_path: Path,
        before: str,
        after: str,
        message: str,
    ) -> None:
        """Fail explicitly on wrong instruments and clocks without poisoning a later invocation."""
        manifest = Configuration.read(_CONFIG).resolve(
            "btc-fixture", _CODEC.decode_json(_CATALOG.read_bytes(), CatalogSnapshot)
        )
        path = tmp_path / "invalid.txt"
        path.write_text(
            (_FIXTURES / "btcusdt.txt").read_text().replace(before, after), encoding="utf-8"
        )
        with pytest.raises(ValueError, match=message):
            inspect_fixture(
                manifest,
                path,
                local_received=_RECEIVED,
                local_ingested=_INGESTED,
                source_sequence=0,
            )
        _, event, _ = inspect_fixture(
            manifest,
            _FIXTURES / "btcusdt.txt",
            local_received=_RECEIVED,
            local_ingested=_INGESTED,
            source_sequence=0,
        )
        assert event.symbol == "BTCUSDT"

    @pytest.mark.parametrize("payload", [b"", b"\n", b"\xff", b"x\ny\n", b" " * 1_048_577])
    def test_saved_input_is_one_bounded_utf8_frame(self, tmp_path: Path, payload: bytes) -> None:
        """Reject blank, multiline, oversized or non-UTF-8 saved inputs."""
        manifest = Configuration.read(_CONFIG).resolve(
            "btc-fixture", _CODEC.decode_json(_CATALOG.read_bytes(), CatalogSnapshot)
        )
        path = tmp_path / "invalid.txt"
        path.write_bytes(payload)
        with pytest.raises(ValueError):
            inspect_fixture(
                manifest,
                path,
                local_received=_RECEIVED,
                local_ingested=_INGESTED,
                source_sequence=0,
            )

    def test_trade_configuration_rejects_a_valid_depth_frame(self, tmp_path: Path) -> None:
        """Existing decoder support alone cannot enable an unconfigured stream."""
        manifest = Configuration.read(_CONFIG).resolve(
            "btc-fixture", _CODEC.decode_json(_CATALOG.read_bytes(), CatalogSnapshot)
        )
        path = tmp_path / "snapshot.txt"
        path.write_text(
            '2024-06-01T00:00:00Z {"stream":"btcusdt@depthSnapshot",'
            '"data":{"lastUpdateId":9,"bids":[["1","2"]],"asks":[]}}\n'
        )
        with pytest.raises(ValueError, match="configured stream is trade"):
            inspect_fixture(
                manifest,
                path,
                local_received=_RECEIVED,
                local_ingested=_INGESTED,
                source_sequence=0,
            )

    def test_configuration_is_resolved_before_fixture_access(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Unknown references fail as configuration errors even when the fixture is absent."""
        arguments = self._arguments(_CONFIG, _CATALOG, "missing-binding", tmp_path / "absent.txt")
        assert main(arguments) == 2
        output = capsys.readouterr()
        assert output.out == ""
        assert "unknown data-job binding" in output.err
        assert '"run_identity":null' in output.err

    @pytest.mark.parametrize(
        ("option", "value", "message"),
        [
            ("--received", "2026-09-14", "timezone-aware"),
            ("--ingested", "2026-09-14", "timezone-aware"),
            ("--sequence", "-1", "nonnegative"),
        ],
    )
    def test_original_receipt_metadata_must_be_valid(
        self,
        capsys: pytest.CaptureFixture[str],
        option: str,
        value: str,
        message: str,
    ) -> None:
        """Reject missing clock zones and invalid original source positions."""
        arguments = self._arguments(_CONFIG, _CATALOG, "btc-fixture", _FIXTURES / "btcusdt.txt")
        arguments[arguments.index(option) + 1] = value
        assert main(arguments) == 3
        assert message in capsys.readouterr().err

    @staticmethod
    def _arguments(config: Path, catalog: Path, job: str, fixture: Path) -> list[str]:
        """Supply all explicit saved-input metadata to the installed command."""
        return [
            "--config",
            str(config),
            "--catalog",
            str(catalog),
            "--job",
            job,
            "--fixture",
            str(fixture),
            "--received",
            _RECEIVED.isoformat(),
            "--ingested",
            _INGESTED.isoformat(),
            "--sequence",
            "0",
        ]

    @pytest.mark.integration
    def test_installed_command_outside_checkout(self, tmp_path: Path) -> None:
        """Run installed scripts with copied saved inputs and check successful and failed exits."""
        config = Path(shutil.copyfile(_CONFIG, tmp_path / "jobs.json"))
        catalog = Path(shutil.copyfile(_CATALOG, tmp_path / "catalog.json"))
        for path in _FIXTURES.iterdir():
            shutil.copyfile(path, tmp_path / path.name)
        command = Path(sys.executable).parent / "alpha-inspect-fixture"
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        cases = [
            (config, "btc-fixture", "btcusdt.txt", 0, '"symbol":"BTCUSDT"'),
            (config, "eth-fixture", "ethusdt.txt", 0, '"symbol":"ETHUSDT"'),
            (tmp_path / "unsupported-product.json", "btc-fixture", "absent.txt", 2, "product"),
            (config, "unknown", "absent.txt", 2, "unknown data-job binding"),
            (config, "btc-fixture", "ethusdt.txt", 3, "unsupported stream symbol"),
            (config, "btc-fixture", "invalid-timestamp.txt", 3, "T must be nonnegative"),
            (config, "btc-fixture", "absent.txt", 4, "No such file"),
        ]
        for selected, job, filename, status, message in cases:
            result = subprocess.run(
                [str(command), *self._arguments(selected, catalog, job, tmp_path / filename)],
                cwd=tmp_path,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == status, result.stderr
            assert message in (result.stdout if status == 0 else result.stderr)
            assert not (result.stderr if status == 0 else result.stdout)
            if status == 3:
                assert '"run_identity":null' not in result.stderr
