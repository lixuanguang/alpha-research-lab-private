"""Protect partition quality, retained limitations and publication refusal."""

from __future__ import annotations

# standard library imports
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# third party library imports
import msgspec
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from configuration import Configuration
from market_data.adapters.providers.binance import ArchiveRow, BinanceArchiveTrades
from market_data.adapters.providers.tardis import TardisDecoder
from market_data.adapters.sources import SourceAdapters
from market_data.adapters.venues.binance import BinancePayloadDecoder
from market_data.contracts import (
    ArchiveCapture,
    CaptureSlice,
    Disconnect,
    Occurrence,
    RawObject,
    SourceRequest,
    Trade,
)
from market_data.query import QueryMarketRow, QueryReader
from market_data.validation import Correction, QualityPolicy, QualityReport, TradeRevision
from reference_data.catalogs import CatalogSnapshot
from reference_data.eligibility import EligibilityAssertions
from runtime import ImplementationIdentity
from serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()
_START = datetime(2024, 6, 1, tzinfo=UTC)
_RAW = b"12,100.00,2.0,200,1717200000000,true,true\n"


class TestPartitionQuality:
    """Exercise the pure gate using synthetic archive and captured occurrences."""

    @pytest.fixture()
    def selection(self) -> SourceRequest:
        """Resolve the maintained archive selection.

        Returns:
            A BTC trade partition selecting the first hour of a UTC day.
        """
        config = Configuration.read(_ROOT / "configs/data-jobs/binance-archive.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        return SourceRequest.partition(
            config.resolve(
                "btc-archive", catalog, implementation_identity=ImplementationIdentity.sha256()
            )
        )[0]

    @staticmethod
    def _history(selection: SourceRequest) -> EligibilityAssertions:
        """Bind the retained synthetic assertions to this test's selected catalog."""
        saved = _CODEC.decode_json(
            (_ROOT / "tests/fixtures/eligibility/membership-corrections.json").read_bytes(),
            EligibilityAssertions,
        )
        return replace(saved, catalog=selection.manifest.catalog)

    @staticmethod
    def _policy() -> QualityPolicy:
        """Declare exploratory use with an exact one-hour silence tolerance."""
        return QualityPolicy(use="exploratory", known_at=_START, max_gap=timedelta(hours=1))

    @staticmethod
    def _item(
        selection: SourceRequest, raw: bytes = _RAW, position: int = 0, digest: str = "a" * 64
    ) -> Occurrence:
        """Decode an exact synthetic source row with stable acquisition metadata."""
        origin = RawObject(
            sha256=digest,
            size_bytes=1000,
            request_identity=selection.identity,
            retrieval_reference="synthetic:mr13",
            ts_received=_START,
            ts_ingested=_START,
        )
        row = ArchiveRow(
            origin=origin,
            position=position,
            payload=raw,
            selection_start=selection.manifest.job.start,
            selection_end=selection.manifest.job.end,
        )
        return Occurrence(
            request=selection,
            origin=origin,
            position=position,
            raw=raw,
            event=BinanceArchiveTrades.from_row(row, selection),
        )

    def test_duplicate_rebuild_roundtrip_and_causal_refusal(self, selection: SourceRequest) -> None:
        """Keep duplicate lineage once and reject a completeness claim even with no gaps."""
        item = self._item(selection)
        duplicate = self._item(selection, position=1, digest="b" * 64)
        policy, history = self._policy(), self._history(selection)
        report = policy.validate(
            selection,
            (item, duplicate, item),
            verifier=SourceAdapters.verifier(selection),
            eligibility=history,
        )
        assert report.scope == "exploratory_degraded"
        assert (report.invalid_count, report.gap_count, report.duplicate_count) == (0, 0, 1)
        assert "recorder coverage unknown" in report.reasons
        assert "original trade availability unknown" in report.reasons
        assert report == policy.validate(
            selection,
            (duplicate, item),
            verifier=SourceAdapters.verifier(selection),
            eligibility=history,
        )
        payload = report.require_canonical()
        assert payload.count(b'"position":') == 2
        assert b'"scope":"exploratory_degraded"' in payload
        assert _CODEC.decode_json(_CODEC.encode_json(report), QualityReport) == report
        assert _CODEC.decode_json(_CODEC.encode_json(policy), QualityPolicy) == policy
        strict = replace(policy, use="causal").validate(
            selection, (item,), verifier=SourceAdapters.verifier(selection), eligibility=history
        )
        assert strict.scope == "rejected" and strict.canonical is None
        with pytest.raises(ValueError, match=r"publication refused.*coverage unknown"):
            strict.require_canonical()
        assert (
            replace(policy, max_gap=timedelta(hours=2))
            .validate(
                selection,
                (item, duplicate),
                verifier=SourceAdapters.verifier(selection),
                eligibility=history,
            )
            .canonical
            != payload
        )

    def test_gaps_include_leading_internal_trailing_and_empty(
        self, selection: SourceRequest
    ) -> None:
        """Count declared silence violations without treating trade IDs as a sequence."""
        first = self._item(selection, _RAW.replace(b"1717200000000", b"1717200600000"))
        last = self._item(
            selection,
            _RAW.replace(b"12,", b"999,").replace(b"1717200000000", b"1717202400000"),
            position=1,
        )
        policy = replace(self._policy(), max_gap=timedelta(minutes=5))
        report = policy.validate(
            selection,
            (first, last),
            verifier=SourceAdapters.verifier(selection),
            eligibility=self._history(selection),
        )
        assert report.gap_count == 3 and report.scope == "exploratory_degraded"
        empty = policy.validate(
            selection,
            (),
            verifier=SourceAdapters.verifier(selection),
            eligibility=self._history(selection),
        )
        assert empty.gap_count == 1 and empty.canonical is None
        assert "no admissible trades" in " ".join(empty.reasons)
        assert (
            replace(policy, max_gap=timedelta(minutes=20))
            .validate(
                selection,
                (first, last),
                verifier=SourceAdapters.verifier(selection),
                eligibility=self._history(selection),
            )
            .gap_count
            == 1
        )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("price", Decimal("NaN")),
            ("quantity", Decimal("-1")),
        ],
    )
    def test_unsafe_event_rejections_retain_reasons(
        self, selection: SourceRequest, field: str, value: object
    ) -> None:
        """Invalid nested inputs cannot bypass constructors or poison a later valid run."""
        bad = self._item(selection)
        force_setattr(bad.event, field, value)
        report = self._policy().validate(
            selection,
            (bad,),
            verifier=SourceAdapters.verifier(selection),
            eligibility=self._history(selection),
        )
        assert report.invalid_count == 1 and report.canonical is None
        assert any(reason.startswith("input 0:") for reason in report.reasons)
        with pytest.raises(ValueError, match="publication refused"):
            report.require_canonical()
        assert (
            self._policy()
            .validate(
                selection,
                (self._item(selection),),
                verifier=SourceAdapters.verifier(selection),
                eligibility=self._history(selection),
            )
            .canonical
            is not None
        )

    @pytest.mark.parametrize(
        "raw",
        [
            _RAW.replace(b"100.00", b"1e5000"),
            _RAW.replace(b"2.0", b"1e-31"),
            _RAW.replace(b",200,", b",0e-1000000000,"),
        ],
    )
    def test_unbounded_source_decimals_are_rejected_without_canonical_bytes(
        self, selection: SourceRequest, raw: bytes
    ) -> None:
        """Reject hostile rows lazily before quality can perform rational arithmetic."""
        report = self._policy().validate(
            selection,
            (self._item(selection, payload) for payload in (raw,)),
            verifier=SourceAdapters.verifier(selection),
            eligibility=self._history(selection),
        )
        assert report.invalid_count == 1 and report.canonical is None
        assert "supported decimal bounds" in " ".join(report.reasons)
        with pytest.raises(ValueError, match="publication refused"):
            report.require_canonical()

    @pytest.mark.parametrize(
        "raw,reason",
        [
            (_RAW.replace(b",2.0,", b",0,"), "trade quantity must be positive"),
            (_RAW.replace(b"100.00", b"100.001"), "tick grid"),
            (_RAW.replace(b"1717200000000", b"1717203600000"), "half-open"),
        ],
    )
    def test_stream_quantity_tick_and_selection(
        self, selection: SourceRequest, raw: bytes, reason: str
    ) -> None:
        """Enforce trade-specific positive quantity, exact ticks and exclusive selection end."""
        report = self._policy().validate(
            selection,
            (self._item(selection, raw),),
            verifier=SourceAdapters.verifier(selection),
            eligibility=self._history(selection),
        )
        assert report.invalid_count == 1 and report.canonical is None
        assert reason in " ".join(report.reasons)

    def test_wrong_binding_schema_source_order_and_altered_payload(
        self, selection: SourceRequest
    ) -> None:
        """Reject foreign instruments, malformed envelopes, reversals and raw reinterpretation."""
        run = replace(selection.manifest, instruments=selection.manifest.catalog.instruments)
        foreign_selection = SourceRequest.partition(run)[1]
        foreign = self._item(foreign_selection)
        bad_schema = self._item(selection)
        force_setattr(bad_schema, "schema_version", "9")
        altered = self._item(selection)
        force_setattr(altered.event, "price", Decimal("101"))
        ordered = self._item(selection, _RAW.replace(b"12,", b"13,"), position=1)
        earlier = self._item(selection, _RAW.replace(b"1717200000000", b"1717200001000"))
        scenarios = (
            ((foreign,), "selected partition"),
            ((bad_schema,), "version 1"),
            ((altered,), "original bytes"),
            ((ordered, self._item(selection)), "regressed"),
            ((earlier, ordered), "regressed"),
        )
        for items, expected in scenarios:
            report = self._policy().validate(
                selection,
                items,
                verifier=SourceAdapters.verifier(selection),
                eligibility=self._history(selection),
            )
            assert report.invalid_count == 1 and report.canonical is None
            assert expected in " ".join(report.reasons)
        collision = self._policy().validate(
            selection,
            (self._item(selection), replace(ordered, position=0)),
            verifier=SourceAdapters.verifier(selection),
            eligibility=self._history(selection),
        )
        assert "conflicting content" in " ".join(collision.reasons)

    def test_conflicting_corrections_and_retained_prior_availability(
        self, selection: SourceRequest
    ) -> None:
        """Require evidence and preserve originals even when a later payload becomes usable."""
        original = self._item(selection)
        changed = self._item(selection, _RAW.replace(b"100.00", b"101.00"), digest="b" * 64)
        policy, history = self._policy(), self._history(selection)
        rejected = policy.validate(
            selection,
            (original, changed),
            verifier=SourceAdapters.verifier(selection),
            eligibility=history,
        )
        assert rejected.canonical is None and "revision admission" in " ".join(rejected.reasons)
        correction = Correction(
            supersedes=TradeRevision(occurrences=(original,)).identity,
            replacement=TradeRevision(occurrences=(changed,)).identity,
            ts_published=_START + timedelta(hours=2),
            ts_available=_START + timedelta(hours=3),
            evidence_reference="synthetic:mr13-late-revision",
        )
        report = policy.validate(
            selection,
            (original, changed),
            verifier=SourceAdapters.verifier(selection),
            eligibility=history,
            corrections=(correction,),
        )
        payload = report.require_canonical()
        assert b'"previous":{' in payload and b'"ts_available":"2024-06-01T03:00:00Z"' in payload
        assert payload.count(b'"ts_knowledge":null') == 2
        assert report.duplicate_count == 0
        assert report == policy.validate(
            selection,
            (changed, original),
            verifier=SourceAdapters.verifier(selection),
            eligibility=history,
            corrections=(correction,),
        )
        assert (
            policy.validate(
                selection,
                (original, changed),
                verifier=SourceAdapters.verifier(selection),
                eligibility=history,
                corrections=(replace(correction, supersedes="0" * 64),),
            ).canonical
            is None
        )

    def test_eligibility_intervals_exclusions_and_future_perturbation(
        self, selection: SourceRequest
    ) -> None:
        """Check empty parts of the interval, retain exclusions and respect the fixed cutoff."""
        history = self._history(selection)
        original = history.assertions[0]
        early = replace(original, valid_to=_START + timedelta(minutes=30))
        excluded = replace(original, valid_from=early.valid_to, state="excluded", reason="delisted")
        history = replace(history, schema_version="1", assertions=(early, excluded))
        policy = self._policy()
        item = self._item(selection)
        report = policy.validate(
            selection, (item,), verifier=SourceAdapters.verifier(selection), eligibility=history
        )
        assert b'"reason":"delisted"' in report.require_canonical()
        assert "excluded" in " ".join(report.reasons)
        assert (
            replace(policy, use="causal")
            .validate(
                selection, (item,), verifier=SourceAdapters.verifier(selection), eligibility=history
            )
            .canonical
            is None
        )
        unknown = policy.validate(
            selection,
            (item,),
            verifier=SourceAdapters.verifier(selection),
            eligibility=replace(history, assertions=()),
        )
        assert "unknown" in " ".join(unknown.reasons)
        full = self._history(selection)
        before = replace(full, schema_version="1", assertions=full.assertions[:-1])
        assert (
            policy.validate(
                selection, (item,), verifier=SourceAdapters.verifier(selection), eligibility=before
            ).reasons
            == policy.validate(
                selection, (item,), verifier=SourceAdapters.verifier(selection), eligibility=full
            ).reasons
        )
        assert "unknown" in " ".join(
            replace(policy, known_at=_START + timedelta(hours=12))
            .validate(
                selection, (item,), verifier=SourceAdapters.verifier(selection), eligibility=full
            )
            .reasons
        )
        changed_catalog = replace(full.catalog, evidence="changed catalog/units identity")
        with pytest.raises(ValueError, match="catalog/units"):
            policy.validate(
                selection,
                (item,),
                verifier=SourceAdapters.verifier(selection),
                eligibility=replace(full, catalog=changed_catalog),
            )

    def test_terminal_reader_failure_rejects_prefix(self, selection: SourceRequest) -> None:
        """Retain the first iterator failure without claiming to count unread records."""
        item = self._item(selection)

        def interrupted() -> Iterator[Occurrence]:
            """Fail after one valid source occurrence.

            Yields:
                The valid prefix that must never become a publishable partial result.

            Raises:
                OSError: The next original object is unavailable.
            """
            yield item
            raise OSError("missing raw object: synthetic interruption")

        report = self._policy().validate(
            selection,
            interrupted(),
            verifier=SourceAdapters.verifier(selection),
            eligibility=self._history(selection),
        )
        assert report.invalid_count == 1 and report.canonical is None
        assert "unread remainder not validated" in " ".join(report.reasons)

    def test_capture_redecode_rejects_future_clock_repair_and_retains_control(self) -> None:
        """A whole-sample knowledge shift cannot rewrite the original captured availability."""
        config = Configuration.read(_ROOT / "configs/data-jobs/fixture-inspection.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        selection = SourceRequest.partition(
            config.resolve(
                "btc-fixture", catalog, implementation_identity=ImplementationIdentity.sha256()
            )
        )[0]
        decoder = TardisDecoder(
            BinancePayloadDecoder(selection.manifest.instruments), selection.instrument.source
        )
        raw = (_ROOT / "tests/fixtures/market_data/tardis/btcusdt.txt").read_bytes()
        origin = RawObject(
            sha256="a" * 64,
            size_bytes=len(raw),
            request_identity=selection.identity,
            retrieval_reference="synthetic:mr13-capture",
            ts_received=_START,
            ts_ingested=_START,
        )
        event = decoder.decode_line(
            raw.decode().strip(),
            source_sequence=0,
            local_received=_START,
            local_ingested=_START,
            source_digest=origin.sha256,
        )
        assert isinstance(event, Trade)
        item = Occurrence(request=selection, origin=origin, position=0, raw=raw, event=event)
        policy, history = self._policy(), self._history(selection)
        prior_bytes = policy.validate(
            selection, (item,), verifier=SourceAdapters.verifier(selection), eligibility=history
        ).require_canonical()
        shifted = replace(
            item,
            event=replace(
                event,
                provenance=replace(
                    event.provenance,
                    ts_knowledge=event.provenance.ts_knowledge + timedelta(seconds=10),
                ),
            ),
        )
        rejected = policy.validate(
            selection, (shifted,), verifier=SourceAdapters.verifier(selection), eligibility=history
        )
        assert rejected.invalid_count == 1 and "original bytes/clocks" in " ".join(rejected.reasons)
        assert (
            policy.validate(
                selection, (item,), verifier=SourceAdapters.verifier(selection), eligibility=history
            ).canonical
            == prior_bytes
        )
        disconnect = decoder.decode_line(
            "",
            source_sequence=1,
            local_received=_START,
            local_ingested=_START,
            source_digest=origin.sha256,
            disconnect_capture_time=selection.end,
            disconnect_capture_reason="interval_end",
        )
        assert isinstance(disconnect, Disconnect)
        control = Occurrence(
            request=selection, origin=origin, position=1, raw=b"\n", event=disconnect
        )
        report = policy.validate(
            selection,
            (item, control),
            verifier=SourceAdapters.verifier(selection),
            eligibility=history,
        )
        assert report.gap_count == 1 and b'"disconnect"' in report.require_canonical()

    def test_policy_and_report_boundaries(self, selection: SourceRequest) -> None:
        """Reject unsafe construction, unknown wire fields and inconsistent publication status."""
        policy = self._policy()
        invalid_policies: tuple[tuple[str, object], ...] = (
            ("use", "unchecked"),
            ("schema_version", "2"),
            ("max_gap", timedelta(0)),
        )
        for field, value in invalid_policies:
            invalid_policy = replace(policy)
            force_setattr(invalid_policy, field, value)
            with pytest.raises(ValueError):
                invalid_policy.__post_init__()
        with pytest.raises(TypeError, match="aware"):
            replace(policy, known_at=datetime(2024, 6, 1))
        with pytest.raises(msgspec.ValidationError):
            _CODEC.decode_json(
                _CODEC.encode_json(policy)[:-1] + b',"complete":true}', QualityPolicy
            )
        report = policy.validate(
            selection,
            (self._item(selection),),
            verifier=SourceAdapters.verifier(selection),
            eligibility=self._history(selection),
        )
        invalid_reports: tuple[tuple[str, object], ...] = (
            ("scope", "rejected"),
            ("invalid_count", 1),
            ("reasons", ()),
        )
        for field, value in invalid_reports:
            invalid_report = replace(report)
            force_setattr(invalid_report, field, value)
            with pytest.raises(ValueError):
                invalid_report.__post_init__()
        force_setattr(report, "invalid_count", 1)
        with pytest.raises(ValueError, match="disagree"):
            report.require_canonical()

    @staticmethod
    def _capture(selection: SourceRequest, payload: bytes) -> ArchiveCapture:
        """Bind a synthetic native tape; fixture clocks are never empirical evidence."""
        return ArchiveCapture(
            request_identity=selection.identity,
            archive_sha256="a" * 64,
            access_reference="synthetic fixture; no historical source claim",
            slices=tuple(
                CaptureSlice(
                    start=_START + timedelta(minutes=10 * index),
                    minutes=10,
                    received_at=_START + timedelta(days=1),
                    payload=payload if index == 0 else b"",
                )
                for index in range(6)
            ),
        )

    @staticmethod
    def _native(price: str = "100.00", capture: str = "00:00:00.0000001") -> bytes:
        """Represent one independent native message with sub-microsecond recorder precision."""
        return (
            f'2024-06-01T{capture}Z {{"stream":"btcusdt@trade","data":'
            f'{{"e":"trade","E":1717200000000,"s":"BTCUSDT","t":12,'
            f'"p":"{price}","q":"2.0","T":1717200000000,"m":true}}}}\n'
        ).encode()

    def test_witnessed_availability_late_correction_and_strict_scope(
        self, selection: SourceRequest
    ) -> None:
        """Prove capture ceiling, late revision cutoffs and preservation of unknown coverage."""
        original = self._item(selection)
        changed = self._item(selection, _RAW.replace(b"100.00", b"101.00"), position=1)
        assertion = self._history(selection).assertions[0]
        history = EligibilityAssertions(
            catalog=selection.manifest.catalog,
            assertions=(
                replace(
                    assertion,
                    evidence=replace(assertion.evidence, basis="source_evidence"),
                ),
            ),
        )
        capture = self._capture(selection, self._native() + self._native("101.00", "00:00:30"))
        correction = Correction(
            supersedes=TradeRevision(occurrences=(original,)).identity,
            replacement=TradeRevision(occurrences=(changed,)).identity,
            ts_published=_START + timedelta(seconds=40),
            ts_available=_START + timedelta(seconds=50),
            evidence_reference="synthetic correction",
        )
        policy = replace(self._policy(), use="witnessed")
        report = policy.validate(
            selection,
            (original, changed),
            eligibility=history,
            corrections=(correction,),
            capture=capture,
            verifier=SourceAdapters.verifier(selection),
        )
        assert report.scope == "causal_witnessed"
        assert "recorder coverage unknown" in report.reasons
        binding = (selection.instrument.source, "trade", selection.instrument.instrument_id)
        reader = QueryReader(
            (report.require_canonical(),),
            readers=SourceAdapters(),
            precedence=(binding,),
            max_bytes=100_000,
        )
        for second, expected in (
            (0, None),
            (1, Decimal("100")),
            (49, Decimal("100")),
            (50, Decimal("101")),
        ):
            batches = tuple(
                reader.batches(
                    (binding[2],),
                    start=_START,
                    end=_START + timedelta(minutes=1),
                    known_at=_START + timedelta(seconds=second),
                    columns=("price",),
                    batch_size=1,
                )
            )
            rows = tuple(row for batch in batches for row in batch.rows)
            if expected is None:
                assert rows == ()
            else:
                assert isinstance(rows[0], QueryMarketRow) and rows[0].values == (expected,)
        strict = replace(policy, use="causal").validate(
            selection,
            (original, changed),
            eligibility=history,
            corrections=(correction,),
            capture=capture,
            verifier=SourceAdapters.verifier(selection),
        )
        assert strict.canonical is None

    def test_witness_rejects_missing_conflicts_gaps_and_late_eligibility(
        self, selection: SourceRequest
    ) -> None:
        """No partially matching tape, gap or retrospectively authored membership is admitted."""
        item = self._item(selection)
        assertion = self._history(selection).assertions[0]
        sourced = replace(assertion, evidence=replace(assertion.evidence, basis="source_evidence"))
        history = EligibilityAssertions(catalog=selection.manifest.catalog, assertions=(sourced,))
        policy = replace(self._policy(), use="witnessed")
        for tape, membership in (
            (None, history),
            (self._capture(selection, self._native("99")), history),
            (self._capture(selection, self._native() + b"\n"), history),
            (self._capture(selection, self._native()), replace(history, assertions=())),
            (self._capture(selection, self._native()), replace(history, assertions=(assertion,))),
            (
                self._capture(selection, self._native()),
                replace(
                    history,
                    assertions=(replace(sourced, ts_knowledge=_START + timedelta(seconds=1)),),
                ),
            ),
        ):
            report = policy.validate(
                selection,
                (item,),
                eligibility=membership,
                capture=tape,
                verifier=SourceAdapters.verifier(selection),
            )
            assert report.canonical is None
            with pytest.raises(ValueError, match="publication refused"):
                report.require_canonical()
        report = replace(policy, max_gap=timedelta(seconds=30)).validate(
            selection,
            (item,),
            eligibility=history,
            capture=self._capture(selection, self._native()),
            verifier=SourceAdapters.verifier(selection),
        )
        assert report.canonical is None and report.gap_count == 1
