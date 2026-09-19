"""Protect configured EDA identities, exact summaries and neutral extension boundaries."""

from __future__ import annotations

# standard library imports
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace
from test_asof import TestAsOfSelector as _Scenario
from test_query import TestQueryReader as _QueryScenario

# project library imports
from financial_units import Dimension, Multiplier, Price, Quantity, QuantityKind, UnitError
from market_data.query import QueryBatch, QueryMarketRow
from reference_data.instruments import InstrumentId, InstrumentIdentity, InstrumentKind
from research.exploration import EdaQuery, QuerySummary
from serialization import DomainCodec


class TestEda:
    """Exercise the existing query boundary with changed delivery and temporal selections."""

    @staticmethod
    def _config() -> EdaQuery:
        """Select two explicit subscriptions and a bounded cutoff projection."""
        requests = tuple(_Scenario._request(instrument=i) for i in (0, 1))
        return EdaQuery(
            snapshot_id="a" * 64,
            precedence=tuple(_Scenario._binding(r) for r in requests),
            instruments=tuple(r.instrument.instrument_id for r in requests),
            start=requests[0].start,
            end=requests[0].end,
            known_at=requests[0].start + timedelta(seconds=10),
            columns=("price", "quantity"),
            mode="cutoff",
            batch_size=1,
            max_bytes=262_144,
        )

    def test_roundtrip_and_invalid_configuration(self) -> None:
        """Unknown capabilities, unsafe bounds and clocks fail before opening input files."""
        config = self._config()
        codec = DomainCodec()
        assert codec.decode_json(codec.encode_json(config), EdaQuery) == config
        invalid: tuple[dict[str, object], ...] = (
            {"schema_version": "2"},
            {"snapshot_id": "latest"},
            {"end": config.start},
            {"start": config.start.replace(tzinfo=None)},
            {"batch_size": True},
            {"max_bytes": 0},
            {"columns": ("price", "price")},
            {"mode": "settlement"},
            {"mode": "history"},
            {"instruments": ()},
            {"precedence": ()},
            {"precedence": (config.precedence[0], config.precedence[0])},
            {"precedence": (("", "trade", config.instruments[0]),)},
            {"lifecycle": "cash_settlement"},
            {"adapter": "futures"},
        )
        fields = msgspec.json.decode(codec.encode_json(config), type=dict[str, object])
        for change in invalid:
            with pytest.raises((ValueError, TypeError)):
                codec.decode_json(codec.encode_json(fields | change), EdaQuery)
        with pytest.raises(ValueError, match="bounds"):
            replace(config, batch_size=True)

    def test_exact_groups_controls_and_batch_independent_identity(self) -> None:
        """Separate bindings and controls while retaining identical semantic query identities."""
        config, reader = self._config(), _QueryScenario._reader()
        summaries = []
        for size in (1, 8):
            summaries.append(
                QuerySummary.collect(
                    reader.batches(
                        config.instruments,
                        start=config.start,
                        end=config.end,
                        known_at=config.known_at,
                        columns=config.columns,
                        batch_size=size,
                    )
                )
            )
        assert summaries[0]["summary_identity"] == summaries[1]["summary_identity"]
        assert summaries[0]["query_identity"] == summaries[1]["query_identity"]
        assert summaries[0]["groups"] == tuple(
            (binding, 1, Decimal("101.00"), Decimal("101.00")) for binding in config.precedence
        )
        assert summaries[0]["rows"] == 4 and summaries[0]["controls"] == 2
        assert summaries[0]["batches"] == 4 and summaries[1]["batches"] == 1
        earlier = QuerySummary.collect(
            reader.batches(
                config.instruments,
                start=config.start,
                end=config.end,
                known_at=config.start,
                columns=config.columns,
                batch_size=1,
            )
        )
        assert earlier["rows"] == 0 and earlier["evidence"]
        assert earlier["summary_identity"] != summaries[0]["summary_identity"]

    def test_summary_refuses_mixed_inputs_and_failed_observer(self) -> None:
        """An incomplete query cannot become a completed summary or poison a later attempt."""
        batches = list(_QueryScenario._batches(_QueryScenario._reader()))
        with pytest.raises(ValueError, match="one query"):
            QuerySummary.collect((batches[0], batches[1]._replace(identity="b" * 64)))
        with pytest.raises(ValueError, match="empty evidence batch"):
            QuerySummary.collect(())
        with pytest.raises(RuntimeError, match="observer stopped"):
            QuerySummary.collect(batches, consume=self._fail)
        assert QuerySummary.collect(batches)["rows"] == 2

    @staticmethod
    def _fail(batch: QueryBatch) -> None:
        """Fail a synchronous plot/export observer after receiving a real batch."""
        raise RuntimeError("observer stopped")

    def test_different_family_projection_retains_contract_units(self) -> None:
        """A synthetic future crosses neutral projection only, with a non-unit multiplier."""
        path = Path(__file__).parents[2] / "fixtures/instruments/contract.json"
        fields = msgspec.json.decode(path.read_bytes(), type=dict[str, msgspec.Raw])
        codec = DomainCodec()
        instrument = codec.decode_json(fields["instrument_id"], InstrumentId)
        identity = InstrumentIdentity(
            instrument_id=instrument,
            instrument_kind=InstrumentKind.CONTRACT,
            economic_instrument_id=codec.decode_json(fields["economic_root"], InstrumentId),
        )
        quantity = codec.decode_json(fields["quantity"], Quantity)
        price = codec.decode_json(fields["price"], Price)
        multiplier = Multiplier(
            value=codec.decode_json(fields["units_per_contract"], Decimal),
            input_dimension=quantity.dimension,
            output_dimension=price.per,
        )
        assert identity.instrument_id == quantity.dimension.instrument_id
        assert quantity.dimension.kind is QuantityKind.CONTRACT
        assert price.amount(multiplier.apply(quantity)).value == Decimal("420025.00")
        with pytest.raises(UnitError):
            price.amount(quantity)
        with pytest.raises(UnitError):
            multiplier.apply(
                Quantity(
                    value=Decimal("2"),
                    dimension=Dimension(
                        instrument_id=instrument,
                        kind=QuantityKind.SHARE,
                    ),
                )
            )
        binding = ("synthetic.future", "trade", instrument)
        batch = QueryBatch(
            "f" * 64,
            "cutoff",
            ("price", "quantity"),
            (QueryMarketRow(binding, (price.value, quantity.value)),),
            (),
        )
        summary = QuerySummary.collect((batch,))
        assert summary["groups"] == ((binding, 1, price.value, price.value),)
        assert summary["evidence"] == ()  # Explicit fixture, never published support.
        assert codec.decode_json(codec.encode_json(price), Price) == price
        assert codec.decode_json(codec.encode_json(quantity), Quantity) == quantity
        for invalid in (Decimal("NaN"), None):
            with pytest.raises(ValueError, match="finite exact"):
                QuerySummary.collect((batch._replace(rows=(QueryMarketRow(binding, (invalid,)),)),))
