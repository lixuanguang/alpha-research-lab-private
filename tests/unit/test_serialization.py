"""Protect exact foundation values and strict P1 record decoding with msgspec."""

from __future__ import annotations

# standard library imports
from decimal import Decimal
from importlib import resources

# third party library imports
import msgspec
import pytest

# project library imports
from financial_units import Currency, Money
from serialization import DomainCodec

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
            assert codec.decode_json(b'"USD"', Currency) == amount.currency
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
        """Reject malformed currency objects, legacy unknown strings and numeric coercion."""
        with pytest.raises(ValueError):
            _CODEC.decode_json(payload, Money)

    @pytest.mark.parametrize(
        "currency_definition",
        _DomainCodecFixture._packaged_currency_definitions(),
    )
    def test_money_decoder_reads_known_legacy_currency_strings(
        self,
        currency_definition: tuple[str, str],
    ) -> None:
        """Keep every authored legacy amount code readable with its configured quantum."""
        code, quantum = currency_definition
        payload = ('{"value":"1","currency":"' + code + '"}').encode()
        decoded = _CODEC.decode_json(payload, Money)
        assert decoded.currency == Currency.from_code(code)
        assert decoded.currency.minor_unit == Decimal(quantum)
