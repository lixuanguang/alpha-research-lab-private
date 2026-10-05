"""Exercise feature-store streams served to candidates, with every serving fault."""

from __future__ import annotations

# standard library imports
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import cast

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting import AccountSnapshot
from configuration import (
    AccountConfiguration,
    BookRegistryConfiguration,
    BookSelection,
    CaptureConfig,
    OpeningAccount,
    PaperExecutionScenario,
)
from configuration.accounts import InstrumentFeeRate
from execution import AccountJournal, AccountObservation, PortfolioContext
from financial_units import Currency, Dimension, ExactRatio, Money, Price, Quantity, QuantityKind
from market_data.adapters.sources import BookAdapters
from market_data.books import BookRegistry
from market_data.contracts import BookObservation, CaptureRecord, CaptureRequest, Level
from reference_data.instruments import InstrumentId
from research.experiments import CandidateStateContract
from research.features import (
    FeastServingBridge,
    FeastServingSnapshot,
    FeatureSchema,
    FeatureStoreDefinition,
    FeatureVector,
    ProjectionFeature,
    StoredFeature,
    VersionedFeatureStore,
)
from research.observations import InputRequirement, LiveBookDecisionSource, NumericField
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from runtime import (
    AuthoredCandidates,
    LoadedCandidate,
    LocalCandidateExecutor,
    ServedFeature,
    ServedFeatures,
    SharedBookDelivery,
    SharedDecisionRuntime,
    SharedPaperCaptureObserver,
    SharedStrategyBinding,
)
from serialization import DomainCodec
from strategies import ConfirmedSignal

_AT = datetime(2026, 10, 4, 12, tzinfo=UTC)
_ENTITY = "4476df8e-6342-4417-839e-e41b88f41446"
_FIELD = NumericField(name="funding", units="dimensionless")


class _Generations:
    """Publish and serve Feast generations in process, or fail as a lost service."""

    def __init__(self) -> None:
        """Start with no generation and an available service."""
        self.snapshots: dict[str, dict[str, object]] = {}
        self.is_down = False
        self.calls = 0

    def __call__(self, request: bytes) -> bytes:
        """Answer one materialize or serve request as the isolated worker does."""
        self.calls += 1
        if self.is_down:
            raise OSError("Feast worker unavailable")
        payload = cast(dict[str, object], json.loads(request))
        if payload["schema_version"] == "feast-materialize-request":
            return self._materialize(payload)
        snapshot = self.snapshots[str(payload["snapshot_identity"])]
        rows = cast(list[dict[str, object]], snapshot["rows"])
        row = next(item for item in rows if item["entity"] == payload["entity"])
        values = cast(list[str | None], row["values"])
        return DomainCodec().encode_json(
            {
                "schema_version": "feast-online-response",
                "snapshot_identity": payload["snapshot_identity"],
                "entity": payload["entity"],
                "row_identity": (
                    None if all(value is None for value in values) else self._row(snapshot, row)
                ),
                "values": values,
            }
        )

    def _materialize(self, payload: dict[str, object]) -> bytes:
        """Write a pinned generation directory and return its receipt."""
        identity = str(payload["snapshot_identity"])
        self.snapshots[identity] = cast(dict[str, object], payload["snapshot"])
        repository = Path(str(payload["root"])) / identity
        (repository / "data").mkdir(parents=True, exist_ok=True)
        digests: dict[str, str] = {}
        for name in ("registry.db", "features.parquet", "online.db"):
            (repository / "data" / name).write_bytes(name.encode() + identity.encode())
            digests[name] = hashlib.sha256(name.encode() + identity.encode()).hexdigest()
        (repository / "feature_store.yaml").write_bytes(b"project: served\n")
        receipt = {
            "snapshot_identity": identity,
            "registry_sha256": digests["registry.db"],
            "source_sha256": digests["features.parquet"],
            "online_sha256": digests["online.db"],
            "config_sha256": hashlib.sha256(b"project: served\n").hexdigest(),
            "sdk_version": "0.66.0",
            "schema_version": "feast-generation",
        }
        (repository / "generation.json").write_text(json.dumps(receipt), encoding="utf-8")
        return DomainCodec().encode_json({**receipt, "repository_path": str(repository)})

    @staticmethod
    def _row(snapshot: dict[str, object], row: dict[str, object]) -> str:
        """Return the served row's identity, as the bridge computes it."""
        decoded = DomainCodec().decode_json(
            DomainCodec().encode_json(snapshot), FeastServingSnapshot
        )
        return decoded.row(str(row["entity"])).identity


class TestServedFeatures:
    """Serve a non-book feature stream through the store and an isolated Feast generation."""

    @staticmethod
    def _definition() -> FeatureStoreDefinition:
        """Declare a funding-rate projection whose input no live paper feed provides."""
        schema = FeatureSchema(
            implementation="named-projection",
            inputs=(
                InputRequirement(
                    name="funding",
                    family="non-book",
                    clock="valid",
                    field=_FIELD,
                    max_age_us=10_000_000,
                ),
            ),
            outputs=(_FIELD,),
            parameters=(),
            mode="batch",
            ttl_us=10_000_000,
        )
        return FeatureStoreDefinition(name="funding", entity_type="instrument", schema=schema)

    @staticmethod
    def _row(
        definition: FeatureStoreDefinition,
        seconds: int,
        value: str,
        *,
        available: int | None = None,
        revision: str = "1",
    ) -> StoredFeature:
        """Author one exact value decided at ``seconds`` and known at ``available``."""
        at = _AT + timedelta(seconds=seconds)
        known = at if available is None else _AT + timedelta(seconds=available)
        return StoredFeature(
            definition_identity=definition.identity,
            vector=FeatureVector(
                entity=_ENTITY,
                decision_at=at,
                event_at=at,
                information_start=at,
                available_at=known,
                expires_at=at + timedelta(seconds=10),
                definition=definition.schema.identity,
                fields=definition.fields,
                values=(ExactRatio.from_fraction(Fraction(value)),),
                reasons=("authored",),
                input_identity="a" * 64,
            ),
            source_version="funding-source",
            source_sha256="b" * 64,
            dataset_version="funding-dataset",
            dataset_sha256="c" * 64,
            revision_identity=hashlib.sha256(f"{seconds}:{revision}".encode()).hexdigest(),
        )

    @staticmethod
    def _publish(
        store: VersionedFeatureStore,
        bridge: FeastServingBridge,
        root: Path,
        definition: FeatureStoreDefinition,
        version: str,
        seconds: int,
    ) -> None:
        """Prepare, publish the generation, then append the snapshot, as a publisher does."""
        at = _AT + timedelta(seconds=seconds)
        prepared = store.prepare(definition, version, at, (_ENTITY,))
        bridge.materialize(FeastServingSnapshot.from_materialization(prepared), root)
        store.materialize(definition, version, at, (_ENTITY,), expected_identity=prepared.identity)

    @staticmethod
    def _candidate(
        definition: FeatureStoreDefinition, version: str, *, starts_at: datetime = _AT
    ) -> LoadedCandidate:
        """Load an authored candidate that targets one unit while funding is positive."""
        dimension = Dimension(
            instrument_id=InstrumentId.from_canonical_text(_ENTITY), kind=QuantityKind.BASE_UNIT
        )
        return AuthoredCandidates(venue="okx").load(
            name="served-funding",
            feature=ProjectionFeature(definition.schema),
            policy=ConfirmedSignal(
                field=_FIELD,
                quantity=Quantity(value=Decimal(1), dimension=dimension),
                confirmations=1,
            ),
            instance="served",
            entity=_ENTITY,
            cadence_us=1_000_000,
            starts_at=starts_at,
            source_identity="unused",
            state=CandidateStateContract(
                feature_mode="batch",
                warmup_observations=0,
                checkpoint_schema="candidate-checkpoint",
                on_gap="continue",
                on_restart="restore",
                policy_state_schema="confirmed-signal",
            ),
            served=definition,
            feature_version=version,
        )

    def _setup(
        self, root: Path
    ) -> tuple[
        VersionedFeatureStore,
        FeatureStoreDefinition,
        _Generations,
        FeastServingBridge,
        ServedFeatures,
        LoadedCandidate,
    ]:
        """Publish a two-snapshot stream and bind its served candidate."""
        definition = self._definition()
        store = VersionedFeatureStore.open(root / "features.sqlite3")
        store.register(definition)
        worker = _Generations()
        bridge = FeastServingBridge(worker)
        store.append(definition, self._row(definition, 0, "1/100"))
        self._publish(store, bridge, root, definition, "stream", 0)
        store.activate(definition, "stream")
        store.append(definition, self._row(definition, 2, "-1/100"))
        self._publish(store, bridge, root, definition, "stream", 2)
        served = ServedFeatures(store, bridge=bridge, serving_root=root)
        return store, definition, worker, bridge, served, self._candidate(definition, "stream")

    def test_a_stream_serves_each_instant_exactly_its_own_snapshot(self, tmp_path: Path) -> None:
        """An instant reads its own snapshot or waits; replay reopens each exact snapshot."""
        _, definition, _, _, served, candidate = self._setup(tmp_path)
        assert served.serve(candidate, _AT + timedelta(seconds=1)) == "feature-pending"
        first = served.serve(candidate, _AT)
        later = served.serve(candidate, _AT + timedelta(seconds=2))
        assert isinstance(first, ServedFeature) and isinstance(later, ServedFeature)
        assert first.materialized_at == _AT and later.materialized_at == _AT + timedelta(seconds=2)
        assert first.vector.values == (ExactRatio.from_fraction(Fraction(1, 100)),)
        assert later.vector.values == (ExactRatio.from_fraction(Fraction(-1, 100)),)
        assert first.stream == VersionedFeatureStore.stream_identity(definition, "stream")
        served.verify(candidate, first)
        served.verify(candidate, later)
        forged = replace(
            first,
            vector=replace(first.vector, values=(ExactRatio.from_fraction(Fraction(1)),)),
        )
        with pytest.raises(ValueError, match="retained snapshot"):
            served.verify(candidate, forged)
        with pytest.raises(ValueError, match="retained snapshot"):
            served.verify(candidate, replace(first, served_at=_AT + timedelta(seconds=1)))
        step = LocalCandidateExecutor(candidate).step(first, None)
        assert step.status == "decided" and step.at == first.served_at
        assert step.feature == first.vector

    def test_a_stream_not_yet_published_is_pending(self, tmp_path: Path) -> None:
        """Before the publisher's first publication a served instant waits, never faults."""
        definition = self._definition()
        store = VersionedFeatureStore.open(tmp_path / "features.sqlite3")
        served = ServedFeatures(
            store, bridge=FeastServingBridge(_Generations()), serving_root=tmp_path
        )
        candidate = self._candidate(definition, "stream")
        assert store.published_version(definition) is None
        assert served.serve(candidate, _AT) == "feature-pending"
        store.register(definition)
        assert store.published_version(definition) is None
        assert served.serve(candidate, _AT) == "feature-pending"

    def test_faults_pause_and_recover_without_substitute_values(self, tmp_path: Path) -> None:
        """Pending, rolled-back and unreachable serving name their reasons."""
        store, definition, worker, bridge, served, candidate = self._setup(tmp_path)
        assert served.serve(candidate, _AT - timedelta(seconds=1)) == "feature-pending"
        assert served.serve(candidate, _AT + timedelta(seconds=13)) == "feature-pending"
        store.append(definition, self._row(definition, 3, "1/50"))
        self._publish(store, bridge, tmp_path, definition, "stream", 13)
        assert served.serve(candidate, _AT + timedelta(seconds=14)) == "feature-pending"
        store.append(definition, self._row(definition, 0, "1/10", available=1, revision="2"))
        self._publish(store, bridge, tmp_path, definition, "previous", 1)
        store.activate(definition, "previous")
        assert served.serve(candidate, _AT + timedelta(seconds=2)) == "feature-version-changed"
        store.activate(definition, "stream")
        worker.is_down = True
        assert served.serve(candidate, _AT + timedelta(seconds=13)) == (
            "feature-service-unavailable"
        )
        worker.is_down = False
        recovered = served.serve(candidate, _AT + timedelta(seconds=13))
        assert isinstance(recovered, ServedFeature)
        assert recovered.vector.values == (ExactRatio.from_fraction(Fraction(1, 50)),)

    def test_a_late_revision_reaches_only_later_snapshots(self, tmp_path: Path) -> None:
        """A correction known after a snapshot appears in the next one; the old one is kept."""
        store, definition, _, bridge, served, candidate = self._setup(tmp_path)
        before = served.serve(candidate, _AT + timedelta(seconds=2))
        assert isinstance(before, ServedFeature)
        store.append(definition, self._row(definition, 2, "3/100", available=4, revision="2"))
        self._publish(store, bridge, tmp_path, definition, "stream", 4)
        after = served.serve(candidate, _AT + timedelta(seconds=4))
        assert isinstance(after, ServedFeature)
        assert after.vector.values == (ExactRatio.from_fraction(Fraction(3, 100)),)
        served.verify(candidate, before)
        with pytest.raises(ValueError, match="pinned stream"):
            served.verify(self._candidate(definition, "other"), before)


class TestServedSharedDecisions:
    """Decide a feature-served candidate on a shared account and replay its retained inputs."""

    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text(_ENTITY), kind=QuantityKind.BASE_UNIT
    )

    @classmethod
    def _money(cls, value: str) -> Money:
        """Create exact USDT cash."""
        return Money(value=Decimal(value), currency=cls.currency)

    @classmethod
    def _price(cls, value: str) -> Price:
        """Create an exact USDT price per base unit."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _account(cls) -> AccountConfiguration:
        """Fund one paper account and the served instance's budget."""
        quantity = Quantity(value=Decimal(10), dimension=cls.dimension)
        lot = Quantity(value=Decimal(1), dimension=cls.dimension)
        return AccountConfiguration(
            mode="paper",
            opening_at=_AT - timedelta(seconds=1),
            accounts=(OpeningAccount(account_id="paper", cash=(cls._money("1000"),)),),
            instruments=(
                SpotLimits(maximum=quantity, lot=lot, tick=cls._price("0.01"), product="spot"),
            ),
            fee_rates=(
                InstrumentFeeRate(instrument_id=cls.dimension.instrument_id, rate=Decimal(0)),
            ),
            budgets=BudgetPolicy(
                valuation_currency=cls.currency,
                firm_maximum=cls._money("1000"),
                accounts=(AccountLimit(account_id="paper", maximum=cls._money("1000")),),
                instances=(
                    InstanceLimit(
                        instance_id="served",
                        account_id="paper",
                        maximum=cls._money("900"),
                        instruments=(cls.dimension.instrument_id,),
                    ),
                ),
                max_quote_age_us=5_000_000,
                max_state_age_us=86_400_000_000,
                max_price_deviation_bps=500,
                max_order_notional=cls._money("900"),
            ),
        )

    @classmethod
    def _opening(cls) -> AccountObservation:
        """Author the independent opening cash and no-order observation."""
        return AccountObservation(
            identity="opening",
            at=_AT - timedelta(seconds=1),
            snapshot=AccountSnapshot(
                account_id="paper",
                instance_id=None,
                cash=(cls._money("1000"),),
                positions=(),
                fees=(cls._money("0"),),
                rebates=(cls._money("0"),),
                transfers=(cls._money("1000"),),
                fill_ids=(),
                posting_ids=("opening:USDT",),
            ),
            open_orders=(),
        )

    @classmethod
    def _observer(
        cls, path: Path, served: ServedFeatures, candidate: LoadedCandidate
    ) -> tuple[SharedPaperCaptureObserver, AccountJournal]:
        """Bind the native book, a fresh account journal and the served candidate."""
        request = CaptureRequest(
            config=CaptureConfig.read(Path("configs/live/okx-btc-usdt.json")),
            recording_id="33333333-3333-4333-8333-333333333333",
            implementation_identity="a" * 64,
        )
        ask = InputRequirement(
            name="book",
            family="book",
            clock="receipt",
            field=NumericField(name="ask", units="quote/base"),
            max_age_us=5_000_000,
        )
        journal = AccountJournal(path, cls._account())
        binding = SharedStrategyBinding(
            instance_id="served",
            account_id="paper",
            entity=_ENTITY,
            candidate=candidate,
            context=PortfolioContext(
                portfolio_id="served-portfolio",
                strategy_id="served",
                model_revision="rule-only",
                config_revision="test",
                horizon="short",
                reason="served-feature-test",
                venue="okx",
                settlement="spot",
                risk_bucket="cash",
                authority_scope="paper",
            ),
            maximum_fee=cls._money("1"),
        )
        observer = SharedPaperCaptureObserver(
            source=LiveBookDecisionSource(request, (ask,), history_capacity=20),
            books=BookRegistry(
                BookRegistryConfiguration(
                    selections=(
                        BookSelection.from_capture(
                            request.config,
                            source_id=request.identity,
                            capability=BookAdapters.capability(request.config),
                            max_age_ns=5_000_000_000,
                            allow_degraded=True,
                        ),
                    ),
                    equivalences=(),
                    history_capacity=20,
                )
            ),
            journal=journal,
            runtime=SharedDecisionRuntime(journal, (binding,)),
            account_id="paper",
            scenario=PaperExecutionScenario(
                venue="okx",
                instrument_id=cls.dimension.instrument_id,
                entry_delay_us=1000,
                cancel_delay_us=2000,
                adverse=cls._price("0"),
                fee_rate=Decimal("0"),
                take_fraction=Decimal("1"),
                gas_inapplicable_reason="public spot paper matching has no blockchain activity",
            ),
            delivery_path=path.with_suffix(".jsonl"),
            clock=_Clock(tuple(_AT + timedelta(seconds=item) for item in range(6))),
            features=served,
        )
        return observer, journal

    @staticmethod
    def _book(position: int, seconds: int) -> tuple[CaptureRecord, BookObservation]:
        """Author a session control or a two-sided market at a whole second."""
        received_ns = int((_AT + timedelta(seconds=seconds)).timestamp()) * 1_000_000_000
        market = position > 0
        level = Level(size=Decimal("4"), order_count=1)
        return (
            CaptureRecord(
                kind="frame" if market else "session",
                epoch=0,
                received_ns=received_ns,
                raw=b"{}" if market else b"",
            ),
            BookObservation(
                position=position,
                epoch=0,
                received_ns=received_ns,
                source_time=str(received_ns // 1_000_000) if market else None,
                sequence=None,
                outcome=("snapshot" if position == 1 else "update") if market else "session",
                status="degraded" if market else "recovering",
                reason="visible_depth_only" if market else "new",
                state_identity="1" * 64,
                bids=((Decimal("99"), level),) if market else (),
                asks=((Decimal("100"), level),) if market else (),
            ),
        )

    def test_served_decisions_wait_for_their_snapshot_and_replay_exactly(
        self, tmp_path: Path
    ) -> None:
        """Each instant decides on its own snapshot, waiting for it; replay is exact."""
        setup = TestServedFeatures()
        store, definition, _, bridge, served, _ = setup._setup(tmp_path)
        candidate = TestServedFeatures._candidate(definition, "stream", starts_at=_AT)
        observer, journal = self._observer(tmp_path / "live.sqlite3", served, candidate)
        assert journal.reconcile(self._opening())
        for position in range(4):
            observer.observe(*self._book(position, position))
        # Instant 1 has no snapshot: it waited at 2 and was skipped when 2 decided at 3.
        assert observer.feature_pauses["served"] == "feature-not-published"
        observer.observe(*self._book(4, 4))
        assert observer.feature_pauses["served"] == "feature-pending"
        store.append(definition, setup._row(definition, 3, "1/50"))
        setup._publish(store, bridge, tmp_path, definition, "stream", 3)
        observer.observe(*self._book(5, 5))
        retained = tuple(
            DomainCodec().decode_json(line, SharedBookDelivery)
            for line in (tmp_path / "live.jsonl").read_bytes().splitlines()
        )
        groups = [(index, group) for index, item in enumerate(retained) for group in item.decisions]
        assert [(index, group.at) for index, group in groups] == [
            (3, _AT + timedelta(seconds=2)),
            (5, _AT + timedelta(seconds=3)),
        ]
        waited = groups[1][1]
        assert waited.coordinated_at == _AT + timedelta(seconds=4, microseconds=1)
        # Priced at the market known when it was decided, not the instant's own.
        assert waited.quote.at == _AT + timedelta(seconds=4)
        served_items = [group.inputs[0].served for _, group in groups]
        assert [item.materialized_at for item in served_items if item is not None] == [
            _AT + timedelta(seconds=2),
            _AT + timedelta(seconds=3),
        ]
        replay, recovered = self._observer(tmp_path / "replay.sqlite3", served, candidate)
        assert recovered.reconcile(self._opening())
        for delivery in retained:
            replay.deliver(delivery)
        assert recovered.checkpoint("served") == journal.checkpoint("served")
        assert recovered.accounts() == journal.accounts()
        # Replaying into the live journal itself is an exact retry that changes nothing.
        before = (journal.checkpoint("served"), journal.accounts(), journal.orders())
        retry, reopened = self._observer(tmp_path / "live.sqlite3", served, candidate)
        for delivery in retained:
            retry.deliver(delivery)
        assert before == (reopened.checkpoint("served"), reopened.accounts(), reopened.orders())
        awaited = served_items[1]
        assert awaited is not None
        forged_value = replace(
            waited,
            inputs=(
                replace(
                    waited.inputs[0],
                    served=replace(
                        awaited,
                        vector=replace(
                            awaited.vector, values=(ExactRatio.from_fraction(Fraction(1)),)
                        ),
                    ),
                ),
            ),
        )
        shifted = replace(waited, coordinated_at=_AT + timedelta(seconds=4, microseconds=2))
        for forged, message in (
            (forged_value, "native input lineage"),
            (shifted, "coordination differs"),
        ):
            fresh, opened = self._observer(tmp_path / f"{message}.sqlite3", served, candidate)
            assert opened.reconcile(self._opening())
            for delivery in retained[:5]:
                fresh.deliver(delivery)
            with pytest.raises(ValueError, match=message):
                fresh.deliver(replace(retained[5], decisions=(forged,)))


class _Clock:
    """Return authored delivery clocks in order, repeating the last."""

    def __init__(self, times: tuple[datetime, ...]) -> None:
        """Bind the scripted UTC clock values."""
        self.times, self.index = times, 0

    def __call__(self) -> datetime:
        """Read the next scripted clock value."""
        value = self.times[min(self.index, len(self.times) - 1)]
        self.index += 1
        return value
