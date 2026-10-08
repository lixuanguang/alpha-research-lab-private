"""Protect exact foundation values and strict P1 record decoding with msgspec."""

from __future__ import annotations

# standard library imports
import os
from decimal import Decimal
from importlib import resources
from pathlib import Path

# third party library imports
import msgspec
import pytest

# project library imports
from financial_units import Currency, Money
from serialization import DomainCodec, DurableDirectory, DurableLines

_CODEC = DomainCodec()


class _DomainCodecFixture:
    """Build exact fixtures for the component boundary."""

    @staticmethod
    def _packaged_currency_definitions() -> tuple[tuple[str, str], ...]:
        """Read currency code and quantum pairs from the packaged configuration."""
        payload = (
            resources.files("financial_units").joinpath("default_currencies.json").read_bytes()
        )
        definitions = msgspec.json.decode(
            payload,
            type=tuple[dict[str, str], ...],
            strict=True,
        )
        return tuple((definition["code"], definition["minor_unit"]) for definition in definitions)


class TestDomainCodec:
    """Protect exact wire values and reusable strict schema lifetimes."""

    def test_reuse_after_failure_keeps_schemas_and_instances_independent(self) -> None:
        """Recover from bad money and currency inputs without contaminating later schemas."""
        codec = DomainCodec()
        amount = Money(value=Decimal("1.25"), currency=Currency.from_code("USD"))
        encoded = codec.encode_json(amount)
        for _ in range(2):
            with pytest.raises(ValueError):
                codec.decode_json(b'{"value":"NaN","currency":"USD"}', Money)
            with pytest.raises(ValueError):
                codec.decode_json(b'{"code":"USD","minor_unit":"0"}', Currency)
            assert codec.decode_json(encoded, Money) == amount
            with pytest.raises(ValueError, match="unsupported currency schema"):
                codec.decode_json(b'"USD"', Currency)
        other = DomainCodec()
        assert other.decode_json(encoded, Money) == amount
        assert other.encode_json(amount) == encoded

    def test_money_round_trip_keeps_exact_precision_and_currency(self) -> None:
        """Preserve exact digits and an authored currency object's complete identity."""
        currency = Currency(code="QXX", minor_unit=Decimal("0.05"))
        amount = Money(value=Decimal("9007199254740993.00000001"), currency=currency)
        encoded = _CODEC.encode_json(amount)
        assert encoded == (
            b'{"currency":{"code":"QXX","minor_unit":"0.05"},"value":"9007199254740993.00000001"}'
        )
        assert _CODEC.decode_json(encoded, Money) == amount

    @pytest.mark.parametrize(
        "payload",
        [
            b'{"value":0.1,"currency":{"code":"QXX","minor_unit":"0.05"}}',
            b'{"value":"invalid","currency":{"code":"QXX","minor_unit":"0.05"}}',
            b'{"value":"NaN","currency":{"code":"QXX","minor_unit":"0.05"}}',
            b'{"value":"Infinity","currency":{"code":"QXX","minor_unit":"0.05"}}',
            b'{"value":"1","currency":{"code":"QXX"}}',
            b'{"value":"1","currency":{"code":"QXX","minor_unit":0.05}}',
            b'{"value":"1","currency":{"code":"QXX","minor_unit":"NaN"}}',
            b'{"value":"1","currency":{"code":"QXX","minor_unit":"0"}}',
            b'{"value":"1","currency":{"code":"qxx","minor_unit":"0.05"}}',
            b'{"value":"1","currency":{"code":"QXX","minor_unit":"0.05","unknown":1}}',
            b'{"value":"1","currency":{"code":"QXX","minor_unit":"0.05"},"unknown":1}',
            b'{"value":"1","currency":"UNKNOWN"}',
        ],
    )
    def test_money_decoder_rejects_inexact_or_invalid_wire_values(self, payload: bytes) -> None:
        """Reject malformed currency objects, bare currency codes and numeric coercion."""
        with pytest.raises(ValueError):
            _CODEC.decode_json(payload, Money)

    @pytest.mark.parametrize(
        "currency_definition",
        _DomainCodecFixture._packaged_currency_definitions(),
    )
    def test_money_decoder_refuses_bare_currency_codes(
        self,
        currency_definition: tuple[str, str],
    ) -> None:
        """Refuse even a packaged code unless the amount carries its complete currency object."""
        code, _ = currency_definition
        payload = ('{"value":"1","currency":"' + code + '"}').encode()
        with pytest.raises(ValueError, match="unsupported currency schema"):
            _CODEC.decode_json(payload, Money)


class TestDurableDirectories:
    """Publish staged directories whole, synchronizing each name before reporting it."""

    def test_publish_synchronizes_the_staging_then_the_parent(self, tmp_path: Path) -> None:
        """A published directory holds its files, and both names were synchronized."""
        staging, destination = tmp_path / ".staging", tmp_path / "view"
        staging.mkdir()
        (staging / "file").write_bytes(b"content")
        synced: list[Path] = []
        assert DurableDirectory.publish(staging, destination, sync=synced.append)
        assert synced == [staging, tmp_path]
        assert (destination / "file").read_bytes() == b"content" and not staging.exists()
        DurableDirectory.sync(destination)

    def test_publish_leaves_an_existing_destination_to_the_caller(self, tmp_path: Path) -> None:
        """A publisher that went first keeps its view; the staging directory is left."""
        staging, destination = tmp_path / ".staging", tmp_path / "view"
        staging.mkdir()
        (staging / "file").write_bytes(b"late")
        destination.mkdir()
        (destination / "file").write_bytes(b"first")
        synced: list[Path] = []
        assert not DurableDirectory.publish(staging, destination, sync=synced.append)
        assert synced == [staging]
        assert (destination / "file").read_bytes() == b"first" and staging.is_dir()

    def test_publish_raises_other_rename_failures(self, tmp_path: Path) -> None:
        """Only an existing destination is a lost race; a missing staging directory is not."""
        with pytest.raises(FileNotFoundError):
            DurableDirectory.publish(tmp_path / "absent", tmp_path / "view")


class _InjectedFailure:
    """Stand in for one operating-system call that always fails."""

    def __init__(self, message: str) -> None:
        """Bind the failure's message."""
        self.message = message

    def __call__(self, *arguments: int) -> None:
        """Raise the injected failure whatever the call's arguments."""
        raise OSError(self.message)


class TestDurableLines:
    """Append whole records durably, and keep the log whole when an append fails."""

    def test_records_are_appended_whole_and_the_new_name_is_synchronized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The first append creates the log and synchronizes its directory once."""
        synced: list[Path] = []
        monkeypatch.setattr(DurableDirectory, "sync", staticmethod(synced.append))
        log = DurableLines(tmp_path / "requests" / "life.jsonl")
        log.append(b'{"first":1}')
        log.append(b'{"second":2}', sync=False)
        log.append(b'{"third":3}')
        assert log.path.read_bytes() == b'{"first":1}\n{"second":2}\n{"third":3}\n'
        assert synced == [tmp_path / "requests"]
        with pytest.raises(ValueError, match="contains a newline"):
            log.append(b'{"split":\n1}')
        with pytest.raises(ValueError, match="must be absolute"):
            DurableLines(Path("relative.jsonl"))

    def test_an_obstructed_directory_fails_without_writing_elsewhere(self, tmp_path: Path) -> None:
        """A file in place of the directory refuses the append; nothing is retained."""
        directory = tmp_path / "requests"
        directory.write_text("obstruction\n")
        with pytest.raises(OSError):
            DurableLines(directory / "life.jsonl").append(b'{"request":1}')
        assert directory.read_text() == "obstruction\n"
        assert sorted(item.name for item in tmp_path.iterdir()) == ["requests"]

    def test_a_failed_append_is_removed_and_an_unremovable_one_stops_the_log(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed fsync leaves the earlier records; a failed truncation refuses more."""
        log = DurableLines(tmp_path / "life.jsonl")
        log.append(b'{"kept":1}')
        fsync = os.fsync
        failing_fsync = _InjectedFailure("injected fsync failure")
        monkeypatch.setattr(os, "fsync", failing_fsync)
        with pytest.raises(OSError, match="injected fsync failure"):
            log.append(b'{"lost":2}')
        monkeypatch.setattr(os, "fsync", fsync)
        assert log.path.read_bytes() == b'{"kept":1}\n'
        log.append(b'{"after":3}')
        assert log.path.read_bytes() == b'{"kept":1}\n{"after":3}\n'
        monkeypatch.setattr(os, "fsync", failing_fsync)
        monkeypatch.setattr(os, "ftruncate", _InjectedFailure("injected truncation failure"))
        with pytest.raises(OSError, match="injected fsync failure"):
            log.append(b'{"torn":4}')
        monkeypatch.undo()
        with pytest.raises(ValueError, match="incomplete record"):
            log.append(b'{"refused":5}')
