"""Exercise the existing backtest application's saved-input feature qualification."""

# standard library imports
import hashlib

# third party library imports
import pytest
from economic_examples import CODEC, ReplayInputs
from msgspec.structs import replace

# project library imports
from applications.backtest import qualify_scheduled_features, run_backtest
from research.features import ScheduledFeatureParity
from simulation import EconomicResult


class TestScheduledParity(ReplayInputs):
    """Compare real replay output with isolated scheduled consumers and explicit divergences."""

    def test_ordering_gaps_late_data_and_independent_instruments(self) -> None:
        """Keep exact parity under batch delivery, gaps and late/out-of-order event clocks."""
        for instrument in (0, 1):
            for rows in (
                self.rows,
                (*self.rows[:2], (115, 130, "999"), *self.rows[2:]),
                (*self.rows[:2], (110, 110, "120"), *self.rows[2:]),
                (*self.rows[:2], (120, 120, None), *self.rows[2:]),
                ((1, 1, "100"), self.rows[1], *self.rows[3:]),
            ):
                reader, spec = self._inputs(rows, instrument=instrument)
                reference = run_backtest(reader, replace(spec, rule="no-trade"), batch_size=1)
                assert isinstance(reference, EconomicResult)
                parity = qualify_scheduled_features(reader, reference, batch_size=2)
                assert parity.is_equal and parity.first_divergence is None
                assert (
                    CODEC.decode_json(CODEC.encode_json(parity), ScheduledFeatureParity) == parity
                )
                assert len(parity.replay.values) == 3

    def test_changed_source_and_first_divergence_remain_visible(self) -> None:
        """Reject a different saved source and identify a missing scheduled close precisely."""
        reader, spec = self._inputs(self.rows)
        reference = run_backtest(reader, spec)
        assert isinstance(reference, EconomicResult)
        changed, _ = self._inputs((*self.rows[:-1], (230, 230, "1000")))
        with pytest.raises(ValueError, match="checkpoint"):
            qualify_scheduled_features(changed, reference)
        parity = qualify_scheduled_features(reader, reference)
        short = parity.batch.values[:1]
        rejected = replace(
            parity,
            batch=replace(
                parity.batch,
                values=short,
                values_sha256=hashlib.sha256(CODEC.encode_json(short)).hexdigest(),
                cursor=None,
                observation_state=None,
            ),
        )
        assert not rejected.is_equal
        assert rejected.first_divergence == "batch decision 2 at 2024-06-01T00:02:00+00:00"
        assert (
            CODEC.decode_json(CODEC.encode_json(rejected), ScheduledFeatureParity).first_divergence
            == rejected.first_divergence
        )
