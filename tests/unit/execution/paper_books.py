"""Apply one public book through the account command and read back the trace it names."""

from __future__ import annotations

# standard library imports
import hashlib

# project library imports
from configuration import PaperExecutionScenario
from execution import AccountPaperTrace, PaperAccount, PaperMarket
from serialization import DomainCodec


class PaperBooks:
    """Read the trace an account's one per-book command committed or returned again."""

    @staticmethod
    def apply(
        account: PaperAccount,
        account_id: str,
        market: PaperMarket,
        scenario: PaperExecutionScenario,
    ) -> AccountPaperTrace:
        """Apply one book, then return the trace whose exact bytes its outcome names.

        Raises:
            AssertionError: The outcome names another market, or no trace or another
                trace's bytes.
        """
        outcome = account.apply_public_market(account_id, market, scenario)
        trace = account.paper_trace(account_id, market.identity)
        assert (outcome.account_id, outcome.market_identity) == (account_id, market.identity)
        assert trace is not None
        assert outcome.trace_sha256 == hashlib.sha256(DomainCodec().encode_json(trace)).hexdigest()
        return trace
