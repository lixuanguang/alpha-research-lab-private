"""Gate bounded trade partitions without upgrading unknown source evidence to validity."""

from __future__ import annotations

# standard library imports
from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from itertools import pairwise
from typing import ClassVar, Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from market_data.contracts import (
    ArchiveAvailability,
    ArchiveCapture,
    ArchiveCaptureVerifier,
    ArchiveTrade,
    Disconnect,
    MarketEventRecord,
    Occurrence,
    OccurrenceVerifier,
    SourceRequest,
    Trade,
)
from market_data.validation.revisions import Correction, TradeRevision
from reference_data.eligibility import EligibilityAssertion, EligibilityAssertions
from serialization import DomainCodec, WireRecord


class QualityReport(WireRecord, frozen=True, kw_only=True):
    """Report observed failures and a scoped publication gate, never a snapshot.

    Invalid count covers observed invalid records/input failures, not unread rows after
    a terminal reader error. Gap count includes quiet intervals beyond the policy and
    disconnects; neither zero gaps nor consecutive trade IDs prove recorder coverage.
    Rejected raw bytes remain in the supplied occurrences or immutable raw store.
    """

    scope: Literal["exploratory_degraded", "causal_witnessed", "rejected"]
    reasons: tuple[str, ...]
    invalid_count: int
    gap_count: int
    duplicate_count: int
    canonical: bytes | None

    def __post_init__(self) -> None:
        """Reject inconsistent outcomes and malformed report fields.

        Raises:
            ValueError: Scope, reasons, counts or canonical-byte disposition is invalid.
            TypeError: A count has an unsafe Python type.
        """
        if self.scope not in ("exploratory_degraded", "causal_witnessed", "rejected") or (
            type(self.reasons) is not tuple
            or not self.reasons
            or any(type(reason) is not str or not reason for reason in self.reasons)
        ):
            raise ValueError("quality report requires explicit scope and retained reasons")
        for count in (self.invalid_count, self.gap_count, self.duplicate_count):
            MarketEventRecord._require_int(count, field_name="quality count")
        if (self.scope == "rejected" and self.canonical is not None) or (
            self.scope in ("exploratory_degraded", "causal_witnessed")
            and (type(self.canonical) is not bytes or not self.canonical or self.invalid_count)
        ):
            raise ValueError("quality outcome and canonical bytes disagree")

    def require_canonical(self) -> bytes:
        """Release bytes only for the accepted declared and explicitly limited scope.

        Returns:
            Deterministic bytes retaining quality policy, limitations and full histories.

        Raises:
            ValueError: Publication is refused, with retained reasons on this report.
        """
        self.__post_init__()
        if self.canonical is None:
            raise ValueError("partition publication refused: " + "; ".join(self.reasons))
        return self.canonical


class QualityPolicy(WireRecord, frozen=True, kw_only=True):
    """Own declared use, fixed eligibility cutoff and observed-gap tolerance.

    Exploratory use admits evidence limitations with explicit degraded annotations;
    strict causal use requires complete source evidence and remains fail-closed.
    Witnessed use requires exact native capture agreement and historical source
    eligibility, but retains unknown upstream coverage and unseen revision history.
    This boundary does not accept a caller-authored completeness flag.
    """

    _codec: ClassVar[DomainCodec] = DomainCodec()
    schema_version: Literal["1"] = "1"
    use: Literal["exploratory", "causal", "witnessed"]
    known_at: datetime
    max_gap: timedelta

    def __post_init__(self) -> None:
        """Reject unsupported policy versions, unsafe cutoffs and gap tolerances.

        Raises:
            ValueError: Version, use, UTC cutoff or positive gap tolerance is invalid.
            TypeError: The cutoff is not an aware datetime.
        """
        self._require_utc(self.known_at, field_name="known_at")
        if self.schema_version != "1" or self.use not in ("exploratory", "causal", "witnessed"):
            raise ValueError("unsupported quality policy")
        if type(self.max_gap) is not timedelta or self.max_gap <= timedelta(0):
            raise ValueError("max_gap must be a positive timedelta")

    def validate(
        self,
        request: SourceRequest,
        occurrences: Iterable[Occurrence],
        *,
        eligibility: EligibilityAssertions,
        verifier: OccurrenceVerifier,
        corrections: tuple[Correction, ...] = (),
        capture: ArchiveCapture | None = None,
    ) -> QualityReport:
        """Check one selected partition completely before releasing canonical bytes.

        Args:
            request: Exact selected source binding, catalog/units and half-open interval.
            occurrences: Original ordered records per raw object; consumed into memory.
            verifier: Explicit native re-decoder bound to this source request.
            eligibility: Complete retained history, linked to the request's authored catalog.
            corrections: Explicit revision evidence; conflicts without links fail.
            capture: Native Tardis slices corroborating the exact archive. Witnessed use
                requires every selected economic version and source-backed eligibility;
                it does not assert upstream completeness or an exhaustive revision history.

        Returns:
            Accepted degraded bytes or a rejected report with no publishable prefix.
            Ordering is checked within each raw origin; file traversal order is irrelevant.

        Raises:
            ValueError: Policy, request or eligibility configuration is invalid or mismatched.
            TypeError: A configuration value has an unsafe type.
        """
        self.__post_init__()
        if type(request) is not SourceRequest or type(eligibility) is not EligibilityAssertions:
            raise TypeError("quality requires a SourceRequest and EligibilityAssertions")
        request.__post_init__()
        eligibility.__post_init__()
        if request.manifest.catalog.identity != eligibility.catalog.identity:
            raise ValueError("quality eligibility differs from the selected catalog/units")
        start = max(request.start, request.manifest.job.start)
        end = min(request.end, request.manifest.job.end)
        errors: list[str] = []
        reasons = ["recorder coverage unknown", "catalog units are authored research assumptions"]
        retained: dict[str, Occurrence] = {}
        order: dict[str, tuple[int, int, datetime]] = {}
        times: set[datetime] = {start, end}
        invalid_count = 0
        unknown_availability = False
        try:
            for index, item in enumerate(occurrences):
                try:
                    instant, knowledge = self._check_occurrence(item, request, verifier)
                    if not start <= instant < end and not (
                        isinstance(item.event, Disconnect) and instant == end
                    ):
                        raise ValueError("observation outside selected half-open interval")
                    key = (item.position, item.record_index, instant)
                    identity = item.identity
                    if identity in retained:
                        if retained[identity] != item:
                            raise ValueError("one raw occurrence identity has conflicting content")
                        continue
                    previous = order.get(item.origin.sha256)
                    if previous is not None and (
                        (key[0], key[1]) < (previous[0], previous[1]) or instant < previous[2]
                    ):
                        raise ValueError("source position or timestamp regressed within raw object")
                    order[item.origin.sha256] = key
                    retained[identity] = item
                    times.add(instant)
                    if not isinstance(item.event, Disconnect) and knowledge is None:
                        unknown_availability = True
                except (ValueError, TypeError, OverflowError) as error:
                    invalid_count += 1
                    errors.append(f"input {index}: {error}")
        except (ValueError, TypeError, OSError, OverflowError) as error:
            invalid_count += 1
            errors.append(f"input incomplete; unread remainder not validated: {error}")
        trades = tuple(item for item in retained.values() if not isinstance(item.event, Disconnect))
        controls = tuple(item for item in retained.values() if isinstance(item.event, Disconnect))
        disconnects = len(controls)
        heads: tuple[TradeRevision, ...] = ()
        try:
            heads = TradeRevision.admit(trades, policy="evidenced", corrections=corrections)
        except (ValueError, TypeError) as error:
            errors.append(f"revision admission: {error}")
        if not trades:
            errors.append("no admissible trades in selected interval")
        ordered_times = sorted(times)
        gaps = sum(right - left > self.max_gap for left, right in pairwise(ordered_times))
        if gaps or disconnects:
            reasons.append(f"observed gaps: {gaps}; disconnects: {disconnects}")
        boundaries = sorted(
            {start, end}
            | {
                bound
                for assertion in eligibility.assertions
                for bound in (
                    (assertion.valid_from, assertion.valid_to, assertion.ts_knowledge)
                    if self.use == "witnessed"
                    else (assertion.valid_from, assertion.valid_to)
                )
                if start < bound < end
            }
        )
        membership = tuple(
            (
                left,
                right,
                eligibility.select(
                    request.instrument.instrument_id,
                    valid_at=left,
                    known_at=min(left, self.known_at) if self.use == "witnessed" else self.known_at,
                ),
            )
            for left, right in pairwise(boundaries)
        )
        for left, right, selected in membership:
            if not isinstance(selected, EligibilityAssertion) or selected.state != "included":
                reasons.append(f"eligibility {left.isoformat()}..{right.isoformat()}: {selected}")
        if unknown_availability:
            reasons.append("original trade availability unknown")
        if capture is not None:
            try:
                heads = self._witness(heads, capture, verifier, request)
                unknown_availability = False
            except (ValueError, TypeError, OverflowError) as error:
                errors.append(f"capture evidence: {error}")
        if self.use == "witnessed":
            if capture is None:
                errors.append("witnessed admission requires native archive capture evidence")
            for left, right, selected in membership:
                if (
                    not isinstance(selected, EligibilityAssertion)
                    or selected.state != "included"
                    or selected.evidence.basis != "source_evidence"
                    or selected.ts_knowledge > left
                ):
                    errors.append(f"historical source eligibility unavailable: {left}..{right}")
            if gaps or disconnects:
                errors.append("witnessed admission refuses observed coverage failures")
        if capture is not None and not unknown_availability:
            reasons = [
                reason for reason in reasons if reason != "original trade availability unknown"
            ]
            reasons.extend(
                (
                    "Captures corroborate selected ID/event/price/quantity/maker fields only",
                    "Capture agreement cannot prove upstream completeness or unseen revisions",
                )
            )
        versions = {TradeRevision(occurrences=(item,)).identity for item in trades}
        duplicate_count = len(trades) - len(versions)
        reasons = sorted(set(reasons + errors))
        canonical = None
        scope = "causal_witnessed" if self.use == "witnessed" else "exploratory_degraded"
        if not errors and self.use in ("exploratory", "witnessed"):
            canonical = self._codec.encode_json(
                {
                    "schema_version": "canonical-trade-partition-v2"
                    if capture is not None
                    else "canonical-trade-partition-v1",
                    "scope": scope,
                    "policy": self,
                    "request": request,
                    "eligibility": eligibility,
                    "membership": membership,
                    "reasons": tuple(reasons),
                    "revisions": heads,
                    "controls": tuple(sorted(controls, key=self._codec.encode_json)),
                    **({"capture": capture} if capture is not None else {}),
                }
            )
        return QualityReport(
            scope=("causal_witnessed" if self.use == "witnessed" else "exploratory_degraded")
            if canonical is not None
            else "rejected",
            reasons=tuple(reasons),
            invalid_count=invalid_count,
            gap_count=gaps + disconnects,
            duplicate_count=duplicate_count,
            canonical=canonical,
        )

    @classmethod
    def _witness(
        cls,
        heads: tuple[TradeRevision, ...],
        capture: ArchiveCapture,
        verifier: OccurrenceVerifier,
        request: SourceRequest,
    ) -> tuple[TradeRevision, ...]:
        """Match every retained economic version to native recorder evidence, without inference."""
        if not isinstance(verifier, ArchiveCaptureVerifier):
            raise ValueError("source verifier does not support archive capture evidence")
        observed: dict[tuple[int, datetime, Decimal, Decimal, bool], datetime] = {}
        start, end = request.manifest.job.start, request.manifest.job.end
        for event in verifier.captures(capture):
            key = cls._capture_key(event)
            observed[key] = min(
                observed.get(key, event.provenance.ts_knowledge), event.provenance.ts_knowledge
            )
        used: set[tuple[int, datetime, Decimal, Decimal, bool]] = set()
        result: list[TradeRevision] = []
        identity = capture.identity
        for head in heads:
            chain: list[TradeRevision] = []
            current: TradeRevision | None = head
            while current is not None:
                chain.append(current)
                current = current.previous
            for version in reversed(chain):
                if any(
                    item.origin.sha256 != capture.archive_sha256 for item in version.occurrences
                ):
                    raise ValueError("capture refers to another archive object")
                archive_event = version.occurrences[0].event
                if not isinstance(archive_event, ArchiveTrade):
                    raise ValueError("capture witness requires original archive trades")
                key = cls._capture_key(archive_event)
                if key not in observed or key in used:
                    raise ValueError("archive version missing or ambiguous in native capture")
                used.add(key)
                current = replace(
                    version,
                    previous=current,
                    availability=ArchiveAvailability(
                        evidence_identity=identity,
                        available_at=observed[key],
                    ),
                )
            if current is not None:
                result.append(current)
        if {key for key in observed if start <= key[1] < end} != used:
            raise ValueError(
                "native capture includes unmatched selected archive trades or revisions"
            )
        return tuple(result)

    @staticmethod
    def _capture_key(event: ArchiveTrade | Trade) -> tuple[int, datetime, Decimal, Decimal, bool]:
        """Bind only fields actually present in both independent source representations."""
        instant = event.ts_event if isinstance(event, ArchiveTrade) else event.provenance.ts_event
        return event.trade_id, instant, event.price, event.quantity, event.is_buyer_maker

    @staticmethod
    def _check_occurrence(
        item: Occurrence,
        request: SourceRequest,
        verifier: OccurrenceVerifier,
    ) -> tuple[datetime, datetime | None]:
        """Re-decode original bytes to reject altered units, values or retroactive clocks."""
        if type(item) is not Occurrence:
            raise TypeError("quality requires an Occurrence")
        item.__post_init__()
        if item.request.identity != request.identity:
            raise ValueError("occurrence differs from selected partition/instrument/units")
        instant, knowledge = verifier.check(item)
        event = item.event
        if not isinstance(event, Disconnect):
            MarketEventRecord._validate_decimal(
                event.quantity, field_name="trade quantity", allow_zero=False
            )
            if (Fraction(event.price) / Fraction(request.instrument.price_tick)).denominator != 1:
                raise ValueError("trade price is off the authored instrument tick grid")
        return instant, knowledge
