"""Reopen named, pinned research inputs without mixing data families or filling missing values."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Literal, NamedTuple

# project library imports
from market_data.datasets import DatasetReaders, PublicTradeObservation
from market_data.query import (
    BookQuery,
    BookQueryBatch,
    BookQueryReader,
    InputBinding,
    PublicTradeQuery,
    PublicTradeReader,
    PublicTradeResult,
    QueryBatch,
    QueryMarketRow,
    QueryReader,
)
from market_data.storage import RawStore
from reference_data.catalogs import InstrumentDefinition, ReferenceHistory
from reference_data.instruments import InstrumentId
from research.exploration.query import EdaQuery
from serialization import DomainCodec, WireRecord


class TradeSelection(WireRecord, frozen=True, kw_only=True, tag="trade"):
    """Name a trade cutoff input; history remains a separate non-decision EDA interface."""

    name: str
    query: EdaQuery

    def __post_init__(self) -> None:
        """Validate explicit names and refuse history as a decision-eligible input."""
        if type(self.name) is not str or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", self.name) is None:
            raise ValueError("research input requires a stable name")
        if type(self.query) is not EdaQuery or self.query.mode != "cutoff":
            raise ValueError("research trade inputs require a cutoff query")
        self.query.__post_init__()


class BookSelection(WireRecord, frozen=True, kw_only=True, tag="book"):
    """Name a native book input with its independent units and explicit receipt window."""

    name: str
    query: BookQuery

    def __post_init__(self) -> None:
        """Require an actual native query and a stable input name."""
        if type(self.name) is not str or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", self.name) is None:
            raise ValueError("research input requires a stable name")
        if type(self.query) is not BookQuery:
            raise ValueError("research book inputs require a native book query")
        self.query.__post_init__()


class ResearchSelection(WireRecord, frozen=True, kw_only=True):
    """Pin ordered named inputs at one decision cutoff, with explicit resource ceilings.

    Each input keeps its own field order and window: trade business time or book
    receipt time. No resampling, currency conversion, forward fill or implicit join
    occurs. The sum of declared byte caps bounds canonical inputs, not total RSS.
    """

    schema_version: Literal["research-selection"] = "research-selection"
    inputs: tuple[TradeSelection | BookSelection | PublicTradeSelection | ReferenceSelection, ...]

    def __post_init__(self) -> None:
        """Reject ambiguous names, unsupported input types and mixed knowledge cutoffs."""
        if (
            self.schema_version != "research-selection"
            or type(self.inputs) is not tuple
            or not self.inputs
            or any(
                type(item)
                not in (TradeSelection, BookSelection, PublicTradeSelection, ReferenceSelection)
                for item in self.inputs
            )
        ):
            raise ValueError("research selection requires supported named inputs")
        for item in self.inputs:
            item.__post_init__()
        if len({item.name for item in self.inputs}) != len(self.inputs):
            raise ValueError("research selection requires unique input names")
        if len({item.query.known_at for item in self.inputs}) != 1:
            raise ValueError("research inputs must share one knowledge cutoff")

    @property
    def identity(self) -> str:
        """Identify semantic selections independently of paths, batch size and byte ceilings.

        Returns:
            Versioned SHA-256 including all snapshots, windows, fields and precedence.
        """
        self.__post_init__()
        selected: list[tuple[object, ...]] = []
        for item in self.inputs:
            if isinstance(item, TradeSelection):
                trade = item.query
                selected.append(
                    (
                        item.name,
                        "trade",
                        trade.snapshot_id,
                        trade.precedence,
                        tuple(sorted(map(str, trade.instruments))),
                        trade.start,
                        trade.end,
                        trade.known_at,
                        trade.columns,
                        trade.mode,
                    )
                )
            elif isinstance(item, BookSelection):
                book = item.query
                selected.append(
                    (
                        item.name,
                        "book",
                        book.snapshot_id,
                        book.request_identity,
                        book.instrument,
                        book.start,
                        book.end,
                        book.known_at,
                        book.columns,
                        book.clock,
                    )
                )
            else:
                selected.append(
                    (
                        item.name,
                        "public-trades" if isinstance(item, PublicTradeSelection) else "reference",
                        item.query.identity,
                    )
                )
        return hashlib.sha256(
            DomainCodec().encode_json((self.schema_version, tuple(selected)))
        ).hexdigest()


class TradeCoverage(NamedTuple):
    """Expose per-binding missingness without asserting that an observed sample is complete."""

    binding: InputBinding
    selected_rows: int
    reasons: tuple[str, ...]


class TradeResearchInput(NamedTuple):
    """Retain selected trade values, scoped controls, membership, units and coverage together."""

    name: str
    batches: tuple[QueryBatch, ...]
    coverage: tuple[TradeCoverage, ...]


class BookResearchInput(NamedTuple):
    """Retain native book values and mandatory per-batch source/quality evidence."""

    name: str
    batches: tuple[BookQueryBatch, ...]


class PublicTradeSelection(WireRecord, frozen=True, kw_only=True, tag="public-trades"):
    """Name pinned public trades at their actual local knowledge cutoff."""

    name: str
    query: PublicTradeQuery

    def __post_init__(self) -> None:
        """Validate the named source selection before reading any bytes."""
        if (
            type(self.name) is not str
            or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", self.name) is None
            or type(self.query) is not PublicTradeQuery
        ):
            raise ValueError("invalid named public trade selection")
        self.query.__post_init__()


class ReferenceSelection(WireRecord, frozen=True, kw_only=True, tag="reference"):
    """Name a non-book input containing venue assertions known at the selected cutoff.

    The query identifies its source snapshot, instruments and permitted purpose.
    The retained bitemporal history resolves each observation/order's valid time;
    it is never converted into trade or book rows or backdated to the trade window.
    """

    name: str
    query: PublicTradeQuery

    def __post_init__(self) -> None:
        """Require a named pinned reference input and explicit knowledge cutoff."""
        if (
            type(self.name) is not str
            or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", self.name) is None
            or type(self.query) is not PublicTradeQuery
        ):
            raise ValueError("invalid named reference selection")
        self.query.__post_init__()


class PublicTradeResearchInput(NamedTuple):
    """Expose public trades with their own lineage, native units and quality reasons."""

    name: str
    result: PublicTradeResult


class ReferenceResearchInput(NamedTuple):
    """Expose non-book venue assertions as bitemporal reference records."""

    name: str
    instruments: tuple[InstrumentDefinition, ...]
    history: ReferenceHistory


class ResearchDataset(NamedTuple):
    """Return a complete bounded assembly with an immutable selection and separate typed inputs."""

    selection: ResearchSelection
    identity: str
    inputs: tuple[
        TradeResearchInput | BookResearchInput | PublicTradeResearchInput | ReferenceResearchInput,
        ...,
    ]


class ResearchReader:
    """Assemble compatible pinned inputs through the existing family-specific admission APIs.

    Inputs share a knowledge cutoff, not necessarily a business/receipt interval or
    currency. Mutable result graphs are independent between calls. Missing files or
    invalid inputs fail the whole read; empty eligible values retain their evidence.
    """

    def __init__(self, snapshots: Path, raw: RawStore, *, readers: DatasetReaders) -> None:
        """Bind explicit source and storage collaborators without reading or acquiring inputs.

        Args:
            snapshots: Existing immutable publication root; exclude external store mutation.
            raw: Retained originals required for full admission checks.
            readers: Explicit source adapters selected by application composition.
        """
        self._snapshots, self._raw, self._readers = snapshots, raw, readers

    def public_trade_versions(
        self, selection: PublicTradeSelection
    ) -> tuple[PublicTradeObservation, ...]:
        """Return every observed version of the selected trades known by the query cutoff.

        Versions come in local knowledge order, including repeats and later
        corrections, so a caller can resolve each trade at any earlier cutoff exactly
        as a read at that cutoff would.
        """
        selection.__post_init__()
        return tuple(
            row
            for _, row in PublicTradeReader(
                self._snapshots, self._raw, readers=self._readers
            ).replay(selection.query)
        )

    def read(self, selection: ResearchSelection, *, recoveries: bool = False) -> ResearchDataset:
        """Verify every named input before returning the complete research assembly.

        Args:
            selection: Validated pinned inputs at one cutoff; paths are separate from identity.
            recoveries: Also return each trade input's first-binding-message disconnect
                recoveries, for a window policy that accepts them.

        Returns:
            Typed inputs in authored order with selection/query identities and unprojectable
            evidence. Retains all rows in memory within the sum of input ceilings; batch size
            controls delivery shape, not total memory. No prior query state is cached.

        Raises:
            ValueError: Configuration, admission, fields or selected bindings are incompatible.
            OSError: Any required retained input is unavailable; no partial assembly is returned.
        """
        selection = deepcopy(selection)
        selection.__post_init__()
        results: list[
            TradeResearchInput
            | BookResearchInput
            | PublicTradeResearchInput
            | ReferenceResearchInput
        ] = []
        for item in selection.inputs:
            if isinstance(item, TradeSelection):
                query = item.query
                reader = QueryReader.read(
                    self._snapshots,
                    self._raw,
                    readers=self._readers,
                    identity=query.snapshot_id,
                    max_bytes=query.max_bytes,
                    precedence=query.precedence,
                )
                batches = tuple(
                    reader.batches(
                        query.instruments,
                        start=query.start,
                        end=query.end,
                        known_at=query.known_at,
                        columns=query.columns,
                        batch_size=query.batch_size,
                        mode="cutoff",
                        recoveries=recoveries,
                    )
                )
                results.append(
                    TradeResearchInput(item.name, batches, self._coverage(query, batches))
                )
            elif isinstance(item, BookSelection):
                book_batches = BookQueryReader.read(
                    self._snapshots, self._raw, readers=self._readers, query=item.query
                )
                results.append(BookResearchInput(item.name, book_batches))
            else:
                result = PublicTradeReader(self._snapshots, self._raw, readers=self._readers).read(
                    item.query
                )
                if isinstance(item, PublicTradeSelection):
                    results.append(PublicTradeResearchInput(item.name, result))
                else:
                    results.append(
                        ReferenceResearchInput(item.name, result.instruments, result.references)
                    )
        self._validate_units(tuple(results))
        return ResearchDataset(selection, selection.identity, tuple(results))

    @staticmethod
    def _validate_units(
        results: tuple[
            TradeResearchInput
            | BookResearchInput
            | PublicTradeResearchInput
            | ReferenceResearchInput,
            ...,
        ],
    ) -> None:
        """Reject contradictory quote units for the same canonical instrument before assembly."""
        quotes: dict[InstrumentId, str] = {}
        for result in results:
            bindings: tuple[tuple[InstrumentId, str], ...]
            if isinstance(result, TradeResearchInput):
                bindings = tuple(
                    (
                        item.request.instrument.instrument_id,
                        item.request.instrument.quote_currency.code,
                    )
                    for item in result.batches[0].evidence
                )
            elif isinstance(result, BookResearchInput):
                config = result.batches[0].evidence.request.config
                bindings = ((config.instrument_id, config.quote_currency),)
            else:
                instruments = (
                    result.result.instruments
                    if isinstance(result, PublicTradeResearchInput)
                    else result.instruments
                )
                bindings = tuple((i.instrument_id, i.quote_currency) for i in instruments)
            for instrument, quote in bindings:
                if instrument in quotes and quotes[instrument] != quote:
                    raise ValueError("research inputs disagree on canonical instrument quote units")
                quotes[instrument] = quote

    @staticmethod
    def _coverage(query: EdaQuery, batches: tuple[QueryBatch, ...]) -> tuple[TradeCoverage, ...]:
        """Retain every selected binding, including empty values and uncovered request intervals."""
        coverage: list[TradeCoverage] = []
        for binding in query.precedence:
            if binding[2] not in query.instruments:
                continue
            evidence = tuple(
                item
                for item in batches[0].evidence
                if (
                    item.request.instrument.source,
                    item.request.manifest.job.stream,
                    item.request.instrument.instrument_id,
                )
                == binding
            )
            count = sum(
                isinstance(row, QueryMarketRow) and row.binding == binding
                for batch in batches
                for row in batch.rows
            )
            reasons = ["observed values do not establish complete coverage"]
            reasons.extend(reason for item in evidence for reason in item.reasons)
            if not count:
                reasons.append(
                    "no selected trade values; inspect availability and membership evidence"
                )
            intervals = sorted(
                (
                    max(item.request.start, item.request.manifest.job.start),
                    min(item.request.end, item.request.manifest.job.end),
                )
                for item in evidence
            )
            if not ResearchReader._covers(intervals, query.start, query.end):
                reasons.append("requested interval extends outside saved request coverage")
            coverage.append(TradeCoverage(binding, count, tuple(sorted(set(reasons)))))
        return tuple(coverage)

    @staticmethod
    def _covers(intervals: list[tuple[datetime, datetime]], start: datetime, end: datetime) -> bool:
        """Check the union of declared intervals without inferring completeness within them."""
        covered = start
        for left, right in intervals:
            if left > covered:
                return False
            covered = max(covered, right)
            if covered >= end:
                return True
        return False
