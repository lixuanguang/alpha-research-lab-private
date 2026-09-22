"""Report exact L2 scenario results through the existing research reporting boundary."""

from __future__ import annotations

# standard library imports
import html
import re
from fractions import Fraction

# project library imports
from configuration import BookRun
from research.experiments.reports import QuantStatsReport
from research.observations import BookFeature
from serialization import DomainCodec, WireRecord
from simulation import BookCheckpoint


class BookReport(WireRecord, frozen=True):
    """Retain scenario identity, descriptive evidence and independently reconciled accounts."""

    run_identity: str
    implementation: str
    environment: str
    raw_sha256: str
    request_identity: str
    configuration: BookRun
    features: tuple[BookFeature, ...]
    accounts: tuple[BookCheckpoint, ...]
    schema_version: str = "l2-book-report-v1"
    limitations: tuple[str, ...] = (
        "Engineering scenario only; no alpha, full-day coverage or live qualification claim.",
        "Original receipt times and source sequences remain unknown; continuity is unproven.",
        "Delays are constant modeled assumptions, not measured historical latency.",
        "Source order breaks source-time ties; phases: source, feed, arrival, "
        "response, decision, mark.",
        "Long-only cash-funded spot IOC; no resting orders, queues, maker fills, "
        "impact or derivatives.",
        "Each level allows take_fraction times displayed size minus prior simulated consumption.",
        "Same-price snapshots and size/count changes retain consumption; absence "
        "clears that level's debt.",
        "This conservative overlay can double-count historical depletion; "
        "exogenous flow is unchanged.",
        "Maximum target bounds each order; displayed participation is a scenario "
        "cap, not a capacity estimate.",
        "Taker fee rounds per price-level fill; depth slippage is measured from "
        "arrival best quote.",
        "Invalid/stale books refuse decisions/fills; missing marks are preserved "
        "and open terminal marks must exist.",
        "Terminal NAV uses fresh exchange best bid, without liquidation, "
        "liquidation fees or depth guarantees.",
        "Each instance has independent cash, holdings, reservation and "
        "liquidity; no shared-account allocation.",
        "Orders remain reserved until modeled response; strategies cannot see "
        "unacknowledged holdings.",
        "The trade-price vectorbt comparison and frozen P1 experiment do not "
        "apply to this L2 model.",
    )

    def __post_init__(self) -> None:
        """Require complete matched accounts and source features before reporting success."""
        if self.schema_version != "l2-book-report-v1":
            raise ValueError("unsupported book report schema")
        if any(
            type(value) is not str or not re.fullmatch(r"[a-f0-9]{64}", value)
            for value in (
                self.run_identity,
                self.implementation,
                self.environment,
                self.raw_sha256,
                self.request_identity,
            )
        ):
            raise ValueError("invalid book report identities")
        if (
            type(self.configuration) is not BookRun
            or type(self.features) is not tuple
            or type(self.accounts) is not tuple
            or not self.features
            or len(self.features) != self.configuration.history.max_records
            or len(self.accounts) != len(self.configuration.instances)
        ):
            raise ValueError("incomplete book report")
        self.configuration.__post_init__()
        for position, feature in enumerate(self.features):
            if type(feature) is not BookFeature or feature.position != position:
                raise ValueError("invalid book report feature sequence")
            feature.__post_init__()
        for instance, account in zip(self.configuration.instances, self.accounts, strict=True):
            if type(account) is not BookCheckpoint:
                raise TypeError("book report requires complete checkpoints")
            account.__post_init__()
            if (
                account.state.clock != self.configuration.end
                or account.state.ledger.initial_cash != instance.initial_cash
                or account.state.ledger.dimension != instance.quantity.dimension
                or not account.state.valuations
                or account.state.valuations[-1].at != self.configuration.end
                or account.state.valuations[-1].mark is None
            ):
                raise ValueError("book report account is not complete")

    def render(self) -> bytes:
        """Render a self-contained report with exact account metrics and limited analytical returns.

        Returns:
            Escaped UTF-8 HTML with input identities, observations, assumptions and account tables.

        Raises:
            ValueError: An account has no complete terminal valuation.
        """
        sections: list[str] = []
        for instance, checkpoint in zip(self.configuration.instances, self.accounts, strict=True):
            state = checkpoint.state
            if not state.valuations or state.valuations[-1].mark is None:
                raise ValueError("book report requires completed terminal valuation")
            terminal = state.valuations[-1]
            mark = terminal.mark
            if mark is None:
                raise ValueError("book report requires a terminal mark")
            balance = terminal.balance
            previous = Fraction(instance.initial_cash.value)
            returns: list[Fraction] = []
            for valuation in state.valuations:
                if valuation.mark is None:
                    break
                current = Fraction(valuation.mark.nav.value)
                if previous <= 0:
                    break
                returns.append(current / previous - 1)
                previous = current
            projection = (
                QuantStatsReport.project(tuple(returns))
                if len(returns) == len(state.valuations)
                else None
            )
            metrics = {
                "Initial quote cash": str(instance.initial_cash.value),
                "Terminal cash": str(balance.cash.value),
                "Base position": str(balance.holding.value),
                "Terminal NAV": str(mark.nav.value),
                "Net P&L": str(mark.net.value),
                "Realized P&L before fees": str(balance.realized.value),
                "Unrealized P&L before fees": str(mark.unrealized.value),
                "Taker fees": str(balance.fees.value),
                "Depth slippage vs arrival touch": str(balance.slippage.value),
                "Orders / level fills": f"{len(state.orders)} / {len(state.ledger.fills)}",
                "Partial / canceled IOC": (
                    f"{sum(o.status == 'partial' for o in state.orders)} / "
                    f"{sum(o.status == 'canceled' for o in state.orders)}"
                ),
                "QuantStats return / sampled drawdown": str(projection),
            }
            table = "".join(
                f"<tr><th>{html.escape(key)}</th><td>{html.escape(value)}</td></tr>"
                for key, value in metrics.items()
            )
            sections.append(
                f"<h2>{html.escape(instance.instance)} "
                f"({html.escape(balance.cash.currency.code)})</h2><table>{table}</table>"
            )
        spreads = [
            row.spread
            for row in self.features
            if row.spread is not None and row.reason == "visible_depth_only"
        ]
        evidence = html.escape(
            DomainCodec()
            .encode_json(
                {
                    "run_identity": self.run_identity,
                    "implementation": self.implementation,
                    "environment": self.environment,
                    "raw_sha256": self.raw_sha256,
                    "request_identity": self.request_identity,
                }
            )
            .decode()
        )
        assumptions = html.escape(DomainCodec().encode_json(self.configuration).decode())
        limitations = "".join(f"<li>{html.escape(item)}</li>" for item in self.limitations)
        first = self.features[0].source_at.isoformat() if self.features else "unavailable"
        last = self.features[-1].source_at.isoformat() if self.features else "unavailable"
        invalid = sum(row.reason != "visible_depth_only" for row in self.features)
        return (
            "<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<title>L2 order-book "
            "backtest</title><style>body{max-width:72rem;margin:3rem auto;"
            "font:16px system-ui;line-height:1.5}"
            "table{border-collapse:collapse;width:100%}"
            "th,td{text-align:left;padding:.5rem;border-bottom:1px solid #ddd}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f7;padding:1rem}</style>"
            "<h1>L2 order-book backtest</h1><p>Saved archive → EDA → book rule → "
            "IOC fills → exact cash, positions and P&amp;L.</p>"
            f"<p>{len(self.features)} original messages: {first} through {last}. "
            f"Invalid/missing states: {invalid}. "
            f"Spread range: {min(spreads) if spreads else 'unknown'} to "
            f"{max(spreads) if spreads else 'unknown'}.</p>"
            + "".join(sections)
            + f"<h2>Assumptions and limitations</h2><ul>{limitations}</ul>"
            f"<h2>Resolved configuration</h2><pre>{assumptions}</pre>"
            f"<h2>Reproduction identities</h2><pre>{evidence}</pre></html>"
        ).encode()
