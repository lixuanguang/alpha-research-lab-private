"""
lab.core.logging
~~~~~~~~~~~~~~~~
Structured logging setup for the research lab.

Uses the stdlib ``logging`` module with ``rich`` pretty-printing when
running interactively, and plain JSON lines in CI / batch mode.
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def setup_logging(
    level: int | str = logging.INFO,
    *,
    json_mode: bool = False,
) -> logging.Logger:
    """Configure the root ``lab`` logger.

    Parameters
    ----------
    level : int | str
        Logging level (e.g. ``"DEBUG"`` or ``logging.INFO``).
    json_mode : bool
        If *True*, emit JSON-lines to stdout (for CI pipelines).
        Otherwise use rich console handler if available.

    Returns
    -------
    logging.Logger
        The configured ``lab`` logger.
    """
    global _CONFIGURED

    logger = logging.getLogger("lab")

    if _CONFIGURED:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    if json_mode:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                '{"ts":"%(asctime)s","level":"%(levelname)s","module":"%(name)s","msg":"%(message)s"}'
            )
        )
    else:
        try:
            from rich.logging import RichHandler

            handler = RichHandler(rich_tracebacks=True, show_path=False)
        except ImportError:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(
                logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
            )

    logger.addHandler(handler)
    _CONFIGURED = True
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``lab`` namespace.

    Example
    -------
    >>> log = get_logger("backtest.engine")
    >>> log.info("Starting walk-forward …")
    """
    return logging.getLogger(f"lab.{name}")
