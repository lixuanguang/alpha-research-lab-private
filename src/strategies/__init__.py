"""Expose strategy contracts while loading research policies only when requested."""

# standard library imports
from typing import TYPE_CHECKING

# project library imports
from strategies.intents import (
    DecisionIntent,
    ExposureIntent,
    OrderIntent,
    QuoteIntent,
    TargetIntent,
)

if TYPE_CHECKING:
    # project library imports
    from strategies.books import BookImbalance, BookNoTrade, BookRule, BookRules
    from strategies.decisions import (
        ConfirmedSignal,
        DecisionContext,
        DecisionPolicy,
        DecisionRecord,
        DecisionTransition,
    )
    from strategies.rules import Momentum, NoTrade, Reversal, RuleFactory, RuleRegistry, TargetRule
    from strategies.state import DecisionSession, DecisionState


def __getattr__(name: str) -> object:
    """Resolve the selected research policy only when a consumer asks for it."""
    if name in {"BookImbalance", "BookNoTrade", "BookRule", "BookRules"}:
        # project library imports
        from strategies import books

        exports: dict[str, object] = {
            "BookImbalance": books.BookImbalance,
            "BookNoTrade": books.BookNoTrade,
            "BookRule": books.BookRule,
            "BookRules": books.BookRules,
        }
        return exports[name]
    if name in {
        "ConfirmedSignal",
        "DecisionContext",
        "DecisionPolicy",
        "DecisionRecord",
        "DecisionTransition",
    }:
        # project library imports
        from strategies import decisions

        exports = {
            "ConfirmedSignal": decisions.ConfirmedSignal,
            "DecisionContext": decisions.DecisionContext,
            "DecisionPolicy": decisions.DecisionPolicy,
            "DecisionRecord": decisions.DecisionRecord,
            "DecisionTransition": decisions.DecisionTransition,
        }
        return exports[name]
    if name in {"Momentum", "NoTrade", "Reversal", "RuleFactory", "RuleRegistry", "TargetRule"}:
        # project library imports
        from strategies import rules

        exports = {
            "Momentum": rules.Momentum,
            "NoTrade": rules.NoTrade,
            "Reversal": rules.Reversal,
            "RuleFactory": rules.RuleFactory,
            "RuleRegistry": rules.RuleRegistry,
            "TargetRule": rules.TargetRule,
        }
        return exports[name]
    if name in {"DecisionSession", "DecisionState"}:
        # project library imports
        from strategies import state

        exports = {
            "DecisionSession": state.DecisionSession,
            "DecisionState": state.DecisionState,
        }
        return exports[name]
    raise AttributeError(name)


__all__ = [
    "BookImbalance",
    "BookNoTrade",
    "BookRule",
    "BookRules",
    "ConfirmedSignal",
    "DecisionContext",
    "DecisionIntent",
    "DecisionPolicy",
    "DecisionRecord",
    "DecisionSession",
    "DecisionState",
    "DecisionTransition",
    "ExposureIntent",
    "Momentum",
    "NoTrade",
    "OrderIntent",
    "QuoteIntent",
    "Reversal",
    "RuleFactory",
    "RuleRegistry",
    "TargetIntent",
    "TargetRule",
]
