"""Resolve bounded EDA selections and summarize projected rows without mixing units."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from collections.abc import Callable, Iterable
from datetime import datetime
from decimal import Decimal
from typing import Literal

# project library imports
from configuration import Universe
from market_data.query import InputBinding, QueryBatch, QueryColumn, QueryMarketRow
from reference_data.instruments import InstrumentId
from serialization import DomainCodec, WireRecord


class EdaQuery(WireRecord, frozen=True, kw_only=True):
    """Select a saved reference snapshot; paths and attempt observations are separate.

    All clocks are UTC: business time is [start, end), knowledge is inclusive.
    The byte budget bounds canonical inputs, not process memory. History summaries
    describe retained heads, not every predecessor or eligible economic state.
    """

    schema_version: Literal["eda-query"] = "eda-query"
    snapshot_id: str
    precedence: tuple[InputBinding, ...]
    instruments: tuple[InstrumentId, ...]
    start: datetime
    end: datetime
    known_at: datetime
    columns: tuple[QueryColumn, ...]
    mode: Literal["cutoff", "history"]
    batch_size: int
    max_bytes: int

    def __post_init__(self) -> None:
        """Reject invalid selections before any snapshot access.

        Raises:
            ValueError: Identity, selection, projection or bounds are invalid.
            TypeError: A clock is not aware UTC.
        """
        Universe(name="eda", instrument_ids=self.instruments)
        for name, instant in (
            ("start", self.start),
            ("end", self.end),
            ("known_at", self.known_at),
        ):
            self._require_utc(instant, field_name=name)
        if (
            self.schema_version != "eda-query"
            or not isinstance(self.snapshot_id, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.snapshot_id) is None
            or self.end <= self.start
            or any(type(v) is not int or v <= 0 for v in (self.batch_size, self.max_bytes))
            or self.mode not in ("cutoff", "history")
            or type(self.columns) is not tuple
            or not self.columns
            or any(
                c not in ("identity", "ts_knowledge", "price", "quantity", "revision")
                for c in self.columns
            )
            or len(set(self.columns)) != len(self.columns)
            or (self.mode == "history" and "revision" not in self.columns)
        ):
            raise ValueError(
                "invalid EDA identity, window, bounds or projection; history requires revision"
            )
        if type(self.precedence) is not tuple or not self.precedence:
            raise ValueError("EDA requires explicit input precedence")
        for binding in self.precedence:
            if type(binding) is not tuple or len(binding) != 3:
                raise ValueError("invalid EDA input binding")
            for name in (binding[0], binding[1]):
                Universe._text(name)
            Universe(name="binding", instrument_ids=(binding[2],))
        if len(set(self.precedence)) != len(self.precedence) or not set(self.instruments) <= {
            binding[2] for binding in self.precedence
        }:
            raise ValueError("EDA requires unique bindings covering selected instruments")


class QuerySummary:
    """Reduce admitted projections by source/stream/instrument with exact price ranges."""

    @staticmethod
    def collect(
        batches: Iterable[QueryBatch], *, consume: Callable[[QueryBatch], None] | None = None
    ) -> dict[str, object]:
        """Summarize one complete query without retaining its rows.

        Args:
            batches: Trusted projected batches from one query, including its empty batch.
            consume: Optional synchronous observer for plotting or export; failures propagate.
                The observer owns any retained rows and must not mutate input evidence.

        Returns:
            Stable query/summary identities, complete evidence, per-binding row counts and
            exact price ranges when projected. Batch counts are separate observations.
            No quantity, price or currency aggregation crosses a binding.

        Raises:
            ValueError: The stream is empty, mixes queries or contains invalid prices.
        """
        codec = DomainCodec()
        digest = hashlib.sha256()
        first: QueryBatch | None = None
        groups: dict[InputBinding, tuple[int, Decimal | None, Decimal | None]] = {}
        rows = controls = count = peak = 0
        for batch in batches:
            if first is None:
                first = batch._replace(rows=())
                digest.update(codec.encode_json(first))
            if batch._replace(rows=()) != first:
                raise ValueError("summary requires batches from one query and evidence set")
            count += 1
            rows += len(batch.rows)
            peak = max(peak, len(batch.rows))
            for row in batch.rows:
                digest.update(b"\n" + codec.encode_json(row))
                if isinstance(row, QueryMarketRow):
                    n, low, high = groups.get(row.binding, (0, None, None))
                    if "price" in batch.columns:
                        price = row.values[batch.columns.index("price")]
                        if not isinstance(price, Decimal) or not price.is_finite():
                            raise ValueError("summary requires finite exact prices")
                        low, high = (
                            min(low, price) if low is not None else price,
                            max(high, price) if high is not None else price,
                        )
                    groups[row.binding] = (n + 1, low, high)
                else:
                    controls += 1
            if consume is not None:
                consume(batch)
        if first is None:
            raise ValueError("summary requires the query's empty evidence batch")
        return {
            "query_identity": first.identity,
            "summary_identity": hashlib.sha256(b"eda-summary\n" + digest.digest()).hexdigest(),
            "mode": first.mode,
            "columns": first.columns,
            "evidence": first.evidence,
            "groups": tuple((binding, *values) for binding, values in groups.items()),
            "rows": rows,
            "controls": controls,
            "batches": count,
            "max_batch_rows": peak,
        }
