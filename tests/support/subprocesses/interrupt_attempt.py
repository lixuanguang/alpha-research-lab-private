"""Interrupt a real attempt after durable result staging but before atomic completion."""

from __future__ import annotations

# standard library imports
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

# project library imports
from research.experiments import AttemptStore, ExperimentSpec
from serialization import DomainCodec


class _Interruption:
    """Stop the process at the actual completion publication boundary."""

    @staticmethod
    def before_publish(source: Path, target: Path) -> None:
        """Leave flushed staging bytes while simulating uncatchable process death."""
        assert source.read_bytes() and target.name == "event-000002.json"
        os._exit(76)


def main() -> None:
    """Create a retained holdout attempt and terminate before its result becomes visible."""
    root = Path(sys.argv[1])
    spec = DomainCodec().decode_json((root / "spec.json").read_bytes(), ExperimentSpec)
    with AttemptStore(root / "attempts") as store:
        start = store.start(spec, at=datetime.now(UTC), invocation="interrupt_attempt.py")
        store.consume_holdout(start.attempt_id, at=datetime.now(UTC), reason="final evaluation")
        with patch("research.experiments.store.os.replace", _Interruption.before_publish):
            store.finish(
                start.attempt_id,
                status="completed",
                at=datetime.now(UTC),
                reason="never committed",
                result=b"complete result bytes",
            )


if __name__ == "__main__":
    main()
