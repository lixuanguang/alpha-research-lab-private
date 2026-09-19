"""Terminate an installed dataset command just before its atomic rename."""

# standard library imports
import os
import sys
from pathlib import Path
from unittest.mock import patch

# project library imports
from applications.publish_dataset import main as dataset_main


class _InterruptedPublication:
    """Replace only the publication visibility boundary with abrupt process death."""

    @staticmethod
    def rename(source: Path, destination: Path) -> None:
        """Stop without cleanup after all staged bytes are synchronized."""
        os._exit(75)


def main() -> None:
    """Run the real command with an injected process-level interruption.

    Raises:
        SystemExit: Propagate a command failure before the selected interruption.
    """
    with patch("market_data.datasets.snapshots.os.rename", _InterruptedPublication.rename):
        raise SystemExit(dataset_main(sys.argv[1:]))


if __name__ == "__main__":
    main()
