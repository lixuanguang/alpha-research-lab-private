"""Exercise historical eligibility from copied files and an isolated installed wheel."""

from __future__ import annotations

# standard library imports
import argparse
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

# third party library imports
from msgspec.structs import replace

# project library imports
import alpha_research
from alpha_research.data.eligibility import EligibilityAssertions
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec


def main() -> None:
    """Read retained history, exercise failures and recover using the installed candidate.

    Raises:
        AssertionError: An installed result differs from the eligibility assertions contract.
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
    source = inputs / "assumptions-and-membership.json"
    history = EligibilityAssertions.read(source, catalog=catalog)
    assumption, evidenced, included, excluded = history.assertions
    assert assumption.valid_from == evidenced.valid_from == datetime(2024, 6, 1, tzinfo=UTC)
    assert assumption.ts_knowledge == datetime(2026, 9, 16, tzinfo=UTC)
    assert evidenced.ts_knowledge == datetime(2024, 6, 1, tzinfo=UTC)
    assert evidenced.evidence.basis == "synthetic"
    assert excluded.state == "excluded" and excluded.instrument_id == included.instrument_id
    assert excluded.valid_to > catalog.instruments[1].valid_to
    assert codec.decode_json(codec.encode_json(history), EligibilityAssertions) == history
    failures = 0
    with TemporaryDirectory(prefix="read-eligibility-") as temporary:
        path = Path(temporary) / "eligibility.json"
        raw = source.read_bytes()
        for payload in (
            raw.replace(b'"identity": "synthetic:mr11:authored-assumption-v1"', b'"identity": ""'),
            raw.replace(
                b'"ts_knowledge": "2026-09-16T00:00:00Z"', b'"ts_knowledge": "2024-06-01T00:00:00Z"'
            ),
            raw.replace(b'"state": "included"', b'"state": "excluded"', 1),
        ):
            path.write_bytes(payload)
            try:
                EligibilityAssertions.read(path, catalog=catalog)
            except ValueError as error:
                failures += 1
                print(f"Required rejection: {error}")
            else:
                raise AssertionError("invalid eligibility file admitted")
        first, second = catalog.instruments
        changed_catalog = replace(
            catalog, instruments=(replace(first, price_tick=Decimal("0.02")), second)
        )
        try:
            EligibilityAssertions.read(source, catalog=changed_catalog)
        except ValueError as error:
            failures += 1
            print(f"Required rejection: {error}")
        else:
            raise AssertionError("changed catalog units admitted")
        path.write_bytes(raw)
        assert EligibilityAssertions.read(path, catalog=catalog) == history
    assert failures == 4
    print(f"Installed runtime: {package}")
    print(
        "Eligibility assertions passed: four retained assertions, exact round trip, "
        "four rejections and recovery"
    )


if __name__ == "__main__":
    main()
