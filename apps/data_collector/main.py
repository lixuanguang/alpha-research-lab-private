"""CLI stub for Data Collector entrypoint."""

from __future__ import annotations

import click


@click.command()
def main() -> None:
    """Run the data collector service (stub)."""
    click.echo("data_collector: foundation stub")


if __name__ == "__main__":
    main()
