"""Shared pytest fixtures for alpha-research-lab tests."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-perf",
        action="store_true",
        default=False,
        help="Run tests marked with `@pytest.mark.perf`.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-perf"):
        return
    skip_perf = pytest.mark.skip(reason="Skipped perf test; pass --run-perf to execute.")
    for item in items:
        if "perf" in item.keywords:
            item.add_marker(skip_perf)
