"""Reconstruct decision-time membership from an isolated installed candidate."""

from __future__ import annotations

# standard library imports
import argparse
from datetime import timedelta
from pathlib import Path

# third party library imports
from msgspec.structs import replace

# project library imports
import alpha_research
from alpha_research.data.eligibility import EligibilityAssertions
from alpha_research.instrument_identity import InstrumentId
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec


def main() -> None:
    """Read copied history, reproduce boundaries and reject invalid corrections.

    Raises:
        AssertionError: The installed candidate violates the eligibility selection contract.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path)
    arguments = parser.parse_args()
    inputs: Path = arguments.inputs
    package = Path(alpha_research.__file__).resolve()
    assert "site-packages" in package.parts
    codec = DomainCodec()
    catalog = codec.decode_json(
        (inputs / "binance-archive-spot.json").read_bytes(), CatalogSnapshot
    )
    history = EligibilityAssertions.read(inputs / "membership-corrections.json", catalog=catalog)
    original, _, excluded, correction = history.assertions
    before = replace(history, schema_version="1", assertions=history.assertions[:-1])
    assert before.append(correction) == history
    assert codec.decode_json(codec.encode_json(history), EligibilityAssertions) == history
    tick = timedelta(microseconds=1)
    for cutoff, expected in (
        (original.ts_knowledge - tick, "unknown"),
        (original.ts_knowledge, original),
        (correction.ts_knowledge - tick, original),
        (correction.ts_knowledge, correction),
        (correction.ts_knowledge + tick, correction),
    ):
        assert (
            history.select(original.instrument_id, valid_at=correction.valid_from, known_at=cutoff)
            == expected
        )
    for valid_at in (correction.valid_from - tick, correction.valid_to, correction.valid_to + tick):
        assert (
            history.select(
                original.instrument_id, valid_at=valid_at, known_at=correction.ts_knowledge
            )
            == "unknown"
        )
    assert (
        history.select(
            excluded.instrument_id, valid_at=excluded.valid_from, known_at=excluded.ts_knowledge
        )
        == excluded
    )
    unknown = InstrumentId.from_canonical_text("33333333-3333-4333-8333-333333333333")
    assert (
        history.select(unknown, valid_at=original.valid_from, known_at=original.ts_knowledge)
        == "unsupported"
    )
    for invalid in (replace(correction, supersedes=None), replace(correction, supersedes="0" * 64)):
        try:
            before.append(invalid)
        except ValueError as error:
            print(f"Required rejection: {error}")
        else:
            raise AssertionError("invalid correction admitted")
    assert before.append(correction) == history
    print(f"Installed runtime: {package}")
    print(
        "eligibility selection passed: prior universe, both clocks, half-open endpoints, "
        "unknown/unsupported, round trip and recovery"
    )


if __name__ == "__main__":
    main()
