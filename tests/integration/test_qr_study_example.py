"""Run the maintained QR study example over authored captures and package its learned study."""

from __future__ import annotations

# standard library imports
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.util import find_spec
from pathlib import Path

# third party library imports
import msgspec
import pytest
from engineering_candidates import CenterScale
from msgspec.structs import replace

# project library imports
from applications.execute import FeaturePublisher
from configuration import (
    AccountConfiguration,
    CaptureConfig,
    InstrumentFeeRate,
    OpeningAccount,
    PackagedCandidate,
    PaperExecutionScenario,
    PaperFeaturePublisher,
    PaperFeatureServing,
    PaperServiceAccount,
    PaperServiceConfiguration,
    PaperServiceInstance,
    PaperServiceSource,
    UniverseSelection,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import CaptureRecord, CaptureRequest
from market_data.datasets import BookSnapshot, CapturePublication, DatasetPublication
from market_data.query import BookQuery, PublicTradeQuery
from market_data.storage import CaptureJournal, RawStore
from reference_data.instruments import InstrumentId
from research.experiments import (
    AttemptStore,
    CandidateManifest,
    CandidateMetricContract,
    CandidateStateContract,
)
from research.exploration import (
    BookSelection,
    PublicTradeSelection,
    ResearchReader,
    ResearchSelection,
    SavedDecisionSource,
)
from research.features import (
    FeastOfflineWorker,
    FeastServingBridge,
    FeatureMaterializer,
    FeatureSchema,
    FeatureStoreDefinition,
    FittedTransform,
    ProjectionFeature,
    TransformVersion,
    VersionedFeatureStore,
)
from research.studies import StudyResult
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from runtime import CandidatePackager, ComponentSelection
from serialization import DomainCodec

_ROOT = Path(__file__).resolve().parents[2]
_START = datetime(2026, 9, 23, 12, tzinfo=UTC)
_SECONDS = 200


class AuthoredMarket:
    """Author three minutes of OKX BTC-USDT books and trades with moving touch and flow."""

    def __init__(self, root: Path) -> None:
        """Bind the output root and both feeds' requests."""
        self.root = root
        books = replace(
            CaptureConfig.read(_ROOT / "configs/live/okx-btc-usdt.json"),
            duration_seconds=3600,
            max_messages=100_000,
            max_bytes=256_000_000,
        )
        trades = replace(
            books, channel="trades", depth=0, max_orders=1, max_frame_bytes=100_000, idle_seconds=60
        )
        selected = (books.instrument_id,)
        universes = UniverseSelection(
            collection=selected, research=selected, strategy=(), authorized_trading=()
        )
        self.books = CaptureRequest(
            config=books,
            recording_id="00000000-0000-0000-0000-000000000031",
            implementation_identity="a" * 64,
            universes=universes,
        )
        self.trades = CaptureRequest(
            config=trades,
            recording_id="00000000-0000-0000-0000-000000000032",
            implementation_identity="a" * 64,
            universes=universes,
        )

    @staticmethod
    def ns(at: datetime) -> int:
        """Return exact Unix nanoseconds."""
        return (at - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(microseconds=1) * 1000

    def book_frames(self) -> list[tuple[datetime, bytes]]:
        """A snapshot, then every half second the best bid improves or retreats."""
        frames: list[tuple[datetime, bytes]] = [
            (_START, b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}'),
        ]
        bids = '[["100.0","1","0","1"],["99.9","2","0","1"]]'
        asks = '[["100.2","1","0","1"],["100.3","2","0","1"]]'
        frames.append((_START, self.book("snapshot", -1, 1, bids, asks)))
        for index in range(2 * _SECONDS):
            at = _START + timedelta(milliseconds=500 * (index + 1))
            if index % 4 == 0:
                change = ('[["100.1","1","0","1"]]', "[]")
            elif index % 4 == 2:
                change = ('[["100.1","0","0","0"]]', "[]")
            else:
                change = ("[]", f'[["100.2","{1 + index % 3}","0","1"]]')
            frames.append((at, self.book("update", 1 + index, 2 + index, *change)))
        return frames

    @staticmethod
    def book(action: str, previous: int, sequence: int, bids: str, asks: str) -> bytes:
        """Encode one OKX books message."""
        return (
            f'{{"arg":{{"channel":"books","instId":"BTC-USDT"}},"action":"{action}",'
            f'"data":[{{"prevSeqId":{previous},"seqId":{sequence},'
            f'"bids":{bids},"asks":{asks}}}]}}'
        ).encode()

    def trade_frames(self) -> list[tuple[datetime, bytes]]:
        """Acknowledge, then one trade a second with a varying side and size."""
        frames = [(_START, b'{"event":"subscribe","arg":{"channel":"trades","instId":"BTC-USDT"}}')]
        for index in range(_SECONDS):
            at = _START + timedelta(seconds=index + 1)
            side = "buy" if index % 5 < 3 else "sell"
            frames.append(
                (
                    at,
                    DomainCodec().encode_json(
                        {
                            "arg": {"channel": "trades", "instId": "BTC-USDT"},
                            "data": [
                                {
                                    "instId": "BTC-USDT",
                                    "tradeId": str(1000 + index),
                                    "ts": str(self.ns(at) // 1_000_000),
                                    "px": "100.1",
                                    "sz": f"0.{1 + index % 7}",
                                    "side": side,
                                    "count": "1",
                                }
                            ],
                        }
                    ),
                )
            )
        return frames

    def write(self, request: CaptureRequest, frames: list[tuple[datetime, bytes]]) -> Path:
        """Write one complete capture directory."""
        directory = self.root / request.recording_id
        journal = CaptureJournal(directory, request)
        journal.start()
        journal.append(CaptureRecord(kind="session", epoch=0, received_ns=self.ns(_START)))
        for offset, (at, raw) in enumerate(frames):
            journal.append(
                CaptureRecord(kind="frame", epoch=0, received_ns=self.ns(at) + offset, raw=raw)
            )
        end = self.ns(_START + timedelta(seconds=_SECONDS + 1))
        journal.append(CaptureRecord(kind="end", epoch=0, received_ns=end, reason="message_limit"))
        journal.finish(self.ns(_START))
        return directory


class FittedMaterialization:
    """Materialize the example's projected inputs, with or without the fitted transform."""

    def __init__(
        self,
        store: VersionedFeatureStore,
        source: SavedDecisionSource,
        schema: FeatureSchema,
        bridge: FeastServingBridge,
        serving_root: Path,
        entity: str,
    ) -> None:
        """Bind the store, inputs, schema, Feast bridge and entity."""
        self.store, self.source, self.schema = store, source, schema
        self.bridge, self.serving_root, self.entity = bridge, serving_root, entity

    def run(
        self,
        definition: FeatureStoreDefinition,
        decisions: tuple[datetime, ...],
        version: TransformVersion | None,
    ) -> None:
        """Publish one snapshot of version ``v1`` over the decisions."""
        lineage = "c" * 64
        FeatureMaterializer().materialize(
            self.store,
            definition,
            source=self.source,
            kernel=ProjectionFeature(self.schema),
            instance="example",
            entities=(self.entity,),
            decisions=decisions,
            source_version=self.source.identity,
            source_sha256=lineage,
            dataset_version="example",
            dataset_sha256=lineage,
            version="v1",
            bridge=self.bridge,
            serving_root=self.serving_root,
            transform=None if version is None else FittedTransform(CenterScale()),
            transform_version=version,
        )


class ExampleStudies:
    """Author captures, publish them and run the example's three studies as a QR would."""

    @staticmethod
    def run(tmp_path: Path) -> tuple[AuthoredMarket, CapturePublication, list[dict[str, object]]]:
        """Return the market, its publication and the rule, learned and holdout summaries."""
        market = AuthoredMarket(tmp_path / "captures")
        books = market.write(market.books, market.book_frames())
        trades = market.write(market.trades, market.trade_frames())
        (tmp_path / "raw").mkdir()
        (tmp_path / "snapshots").mkdir()
        published = DatasetPublication(SourceAdapters(), "b" * 64).publish_captures(
            (books, trades),
            RawStore(tmp_path / "raw"),
            tmp_path / "snapshots",
            max_records=100_000,
            max_bytes=256_000_000,
        )
        common = [
            "--snapshots",
            str(tmp_path / "snapshots"),
            "--raw",
            str(tmp_path / "raw"),
            "--attempts",
            str(tmp_path / "attempts"),
            "--book-snapshot",
            published.book,
            "--instrument",
            str(market.books.config.instrument_id),
            "--trades-snapshot",
            published.trades[0],
            "--start",
            _START.isoformat(),
            "--end",
            (_START + timedelta(seconds=_SECONDS)).isoformat(),
            "--train",
            "40",
            "--test",
            "30",
            "--folds",
            "2",
            "--holdout",
            "30",
            "--cadence",
            "5",
            "--horizon",
            "10",
        ]
        summaries: list[dict[str, object]] = []
        for kind, partition in (
            ("rule", "validation"),
            ("learned", "validation"),
            ("learned", "holdout"),
        ):
            completed = subprocess.run(  # nosec B603  # [owner=research; rationale=runs the maintained example as a QR would; expires=2027-03-01]
                [
                    sys.executable,
                    str(_ROOT / "examples/qr_study.py"),
                    kind,
                    "--partition",
                    partition,
                    *common,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert completed.returncode == 0, completed.stderr[-4000:]
            summaries.append(msgspec.json.decode(completed.stdout, type=dict[str, object]))
        assert [item["status"] for item in summaries] == ["completed"] * 3
        return market, published, summaries


class TestQRStudyExample:
    """Prove the quickstart's study example runs and packages from published captures."""

    @pytest.mark.integration
    def test_rule_learned_holdout_and_packaging(self, tmp_path: Path) -> None:
        """Both studies complete, the holdout runs once, and the learned study packages."""
        market, _, summaries = ExampleStudies.run(tmp_path)
        learned = str(summaries[1]["attempt_id"])
        policy = DomainCodec().encode_json(
            {
                "instrument": str(market.books.config.instrument_id),
                "quantity": "0.001",
                "threshold": {"numerator": "0", "denominator": "1"},
            }
        )
        with AttemptStore(tmp_path / "attempts") as store:
            manifest = CandidatePackager().publish(
                tmp_path / "candidate",
                store=store,
                attempt_id=learned,
                extension="engineering-candidates",
                selections=(
                    ComponentSelection(role="feature", factory_key="projection", parameters=b"{}"),
                    ComponentSelection(
                        role="transform", factory_key="center-scale", parameters=b"{}"
                    ),
                    ComponentSelection(
                        role="estimator", factory_key="least-squares", parameters=b"{}"
                    ),
                    ComponentSelection(
                        role="policy", factory_key="prediction-target", parameters=policy
                    ),
                    ComponentSelection(role="metric", factory_key="fold-net", parameters=b"{}"),
                    ComponentSelection(role="chart", factory_key="fold-net-path", parameters=b"{}"),
                ),
                name="qr-learned",
                version="1",
                venue="okx",
                cadence_us=5_000_000,
                state=CandidateStateContract(
                    feature_mode="batch",
                    warmup_observations=0,
                    checkpoint_schema="candidate-checkpoint",
                    on_gap="continue",
                    on_restart="restore",
                    policy_state_schema="none",
                ),
                metrics=(
                    CandidateMetricContract(
                        name="fold-net",
                        kind="metric",
                        component_key="fold-net",
                        version="1",
                        units="USDT",
                        applies_to=("research",),
                    ),
                    CandidateMetricContract(
                        name="fold-net-path",
                        kind="chart",
                        component_key="fold-net-path",
                        version="1",
                        units="USDT",
                        applies_to=("research",),
                    ),
                ),
                limitations=("Authored example captures; no market evidence.",),
            )
        assert manifest.definition.name == "qr-learned"
        assert {item.role for item in manifest.definition.components} >= {
            "feature",
            "transform",
            "estimator",
            "policy",
        }

    @pytest.mark.integration
    def test_served_learned_features_are_fitted_and_package(self, tmp_path: Path) -> None:
        """Stored vectors carry the study's transform, and only that definition packages."""
        worker = os.environ.get("ALPHA_FEAST_WORKER_PYTHON")
        if worker is None or not Path(worker).is_file():
            pytest.skip("set ALPHA_FEAST_WORKER_PYTHON to the pinned Feast worker interpreter")
        market, published, summaries = ExampleStudies.run(tmp_path)
        holdout = str(summaries[2]["attempt_id"])
        bridge = FeastServingBridge(FeastOfflineWorker(self.worker(worker), timeout_seconds=120))
        packager = CandidatePackager()
        codec = DomainCodec()
        with AttemptStore(tmp_path / "attempts") as store:
            definition = packager.feature_store(store, holdout, name="example-signals")
            result = StudyResult.read(store, holdout)
            version = codec.decode_json(store.artifact(holdout, "transform-0000"), TransformVersion)
            schema = codec.decode_json(store.artifact(holdout, "feature-schema"), FeatureSchema)
        assert definition.transform_identity == version.identity
        assert definition.output_fields == version.output_fields
        instrument = market.books.config.instrument_id
        source = self.saved(tmp_path, published, instrument, schema)
        decisions = tuple(decision.at for decision in result.folds[0].decisions)
        features = VersionedFeatureStore.open(tmp_path / "features/history.sqlite3")
        materialize = FittedMaterialization(
            features, source, schema, bridge, tmp_path / "serving", str(instrument)
        )
        with pytest.raises(ValueError, match="matching source/schema"):
            materialize.run(definition, decisions, None)
        materialize.run(definition, decisions, version)
        stored = features.retrieve_offline(
            definition, str(instrument), decisions[-1]
        ).require_ready()
        assert stored.transform_identity == version.identity
        raw = replace(definition, transform_identity=None, output_fields=None)
        with AttemptStore(tmp_path / "attempts") as attempts:
            with pytest.raises(ValueError, match="feature-store definition differs"):
                self.package(packager, attempts, holdout, market, raw, tmp_path / "raw-candidate")
            manifest = self.package(
                packager, attempts, holdout, market, definition, tmp_path / "served-candidate"
            )
        assert manifest.definition.feature_store is not None

    @pytest.mark.integration
    def test_live_publisher_extends_the_served_stream_as_research_computes_it(
        self, tmp_path: Path
    ) -> None:
        """Followed supervisor recordings publish the values the saved captures compute."""
        worker = os.environ.get("ALPHA_FEAST_WORKER_PYTHON")
        if worker is None or not Path(worker).is_file():
            pytest.skip("set ALPHA_FEAST_WORKER_PYTHON to the pinned Feast worker interpreter")
        market, published, summaries = ExampleStudies.run(tmp_path)
        holdout = str(summaries[2]["attempt_id"])
        packager = CandidatePackager()
        codec = DomainCodec()
        with AttemptStore(tmp_path / "attempts") as attempts:
            definition = packager.feature_store(attempts, holdout, name="example-signals")
            version = codec.decode_json(
                attempts.artifact(holdout, "transform-0000"), TransformVersion
            )
            schema = codec.decode_json(attempts.artifact(holdout, "feature-schema"), FeatureSchema)
            manifest = self.package(
                packager, attempts, holdout, market, definition, tmp_path / "packaged"
            )
        candidates = tmp_path / "candidates"
        candidates.mkdir()
        (tmp_path / "packaged").rename(candidates / manifest.definition.identity)
        cadence = timedelta(seconds=5)
        starts_at = _START + -((_START - version.available_at) // cadence) * cadence
        assert starts_at < _START + timedelta(seconds=_SECONDS)
        configuration = ServedDeployment.configuration(
            market,
            manifest.definition.identity,
            starts_at,
            PaperFeatureServing(
                store_path=str(tmp_path / "served.sqlite3"),
                serving_root=str(tmp_path / "served-feast"),
                worker=self.worker(worker),
                worker_timeout_seconds=60,
                publisher=PaperFeaturePublisher(max_lag_seconds=300),
            ),
        )
        root = tmp_path / "service"
        for feed, request in (("book", market.books), ("book.trades", market.trades)):
            target = root / "runs" / "run" / feed / request.recording_id / request.recording_id
            shutil.copytree(tmp_path / "captures" / request.recording_id, target)
        now = _START + timedelta(seconds=_SECONDS + 1)
        (root / "status.json").write_bytes(
            codec.encode_json(
                {"configuration": configuration.identity, "run_id": "run", "observed_at": now}
            )
        )
        report = FeaturePublisher(
            configuration, candidates, root, clock=StoppedClock(now).read, poll_seconds=0.01
        ).run()
        assert report["stopped"] == "recordings_complete", report
        live = VersionedFeatureStore.open(tmp_path / "served.sqlite3")
        instants: list[datetime] = []
        at = starts_at
        while at < _START + timedelta(seconds=_SECONDS):
            if live.get_materialization(definition, "live", at).at == at:
                instants.append(at)
            at += cadence
        assert len(instants) >= 3, report
        instrument = market.books.config.instrument_id
        research = VersionedFeatureStore.open(tmp_path / "research.sqlite3")
        FittedMaterialization(
            research,
            self.saved(tmp_path, published, instrument, schema),
            schema,
            FeastServingBridge(FeastOfflineWorker(self.worker(worker), timeout_seconds=120)),
            tmp_path / "research-feast",
            str(instrument),
        ).run(definition, tuple(instants), version)
        for at in instants:
            served = live.retrieve_offline(definition, str(instrument), at).require_ready()
            computed = research.retrieve_offline(definition, str(instrument), at).require_ready()
            assert (served.decision_at, served.values) == (computed.decision_at, computed.values)

    @staticmethod
    def worker(python: str) -> tuple[str, ...]:
        """Return the isolated Feast worker command run by the pinned interpreter."""
        spec = find_spec("applications.explore.command")
        assert spec is not None and spec.origin is not None
        return (
            python,
            "-I",
            "-c",
            "from runpy import run_path; "
            f"raise SystemExit(run_path({spec.origin!r})['main'](['feast-serving-worker']))",
        )

    @staticmethod
    def saved(
        tmp_path: Path,
        published: CapturePublication,
        instrument: InstrumentId,
        schema: FeatureSchema,
    ) -> SavedDecisionSource:
        """Read the published book and trades snapshots as the study's joined source."""
        reader = ResearchReader(
            tmp_path / "snapshots", RawStore(tmp_path / "raw"), readers=SourceAdapters()
        )
        end = _START + timedelta(seconds=_SECONDS)
        book = BookSnapshot.read(
            tmp_path / "snapshots",
            RawStore(tmp_path / "raw"),
            readers=SourceAdapters(),
            identity=published.book,
            max_bytes=256_000_000,
        )
        return SavedDecisionSource(
            reader,
            ResearchSelection(
                inputs=(
                    BookSelection(
                        name="book",
                        query=BookQuery(
                            snapshot_id=published.book,
                            request_identity=book.request_identities[0],
                            instrument=instrument,
                            start=_START,
                            end=end,
                            known_at=end,
                            columns=("bids", "asks"),
                            batch_size=10_000,
                            max_bytes=256_000_000,
                        ),
                    ),
                    PublicTradeSelection(
                        name="trades",
                        query=PublicTradeQuery(
                            snapshot_id=published.trades[0],
                            instruments=(instrument,),
                            start=_START,
                            end=end,
                            known_at=end,
                            max_bytes=256_000_000,
                        ),
                    ),
                )
            ),
            schema.inputs,
        )

    @staticmethod
    def package(
        packager: CandidatePackager,
        store: AttemptStore,
        attempt: str,
        market: AuthoredMarket,
        feature_store: FeatureStoreDefinition,
        root: Path,
    ) -> CandidateManifest:
        """Package the learned example study as a served candidate."""
        policy = DomainCodec().encode_json(
            {
                "instrument": str(market.books.config.instrument_id),
                "quantity": "0.001",
                "threshold": {"numerator": "0", "denominator": "1"},
            }
        )
        return packager.publish(
            root,
            store=store,
            attempt_id=attempt,
            extension="engineering-candidates",
            selections=(
                ComponentSelection(role="feature", factory_key="projection", parameters=b"{}"),
                ComponentSelection(role="transform", factory_key="center-scale", parameters=b"{}"),
                ComponentSelection(role="estimator", factory_key="least-squares", parameters=b"{}"),
                ComponentSelection(
                    role="policy", factory_key="prediction-target", parameters=policy
                ),
                ComponentSelection(role="metric", factory_key="fold-net", parameters=b"{}"),
                ComponentSelection(role="chart", factory_key="fold-net-path", parameters=b"{}"),
            ),
            name="example-served",
            version="1",
            venue="okx",
            cadence_us=5_000_000,
            state=CandidateStateContract(
                feature_mode="batch",
                warmup_observations=0,
                checkpoint_schema="candidate-checkpoint",
                on_gap="continue",
                on_restart="restore",
                policy_state_schema="none",
            ),
            metrics=(
                CandidateMetricContract(
                    name="fold-net",
                    kind="metric",
                    component_key="fold-net",
                    version="1",
                    units="USDT",
                    applies_to=("research",),
                ),
                CandidateMetricContract(
                    name="fold-net-path",
                    kind="chart",
                    component_key="fold-net-path",
                    version="1",
                    units="USDT",
                    applies_to=("research",),
                ),
            ),
            limitations=("Authored example captures; no market evidence.",),
            feature_store=feature_store,
        )


class StoppedClock:
    """Hold the publisher's clock just after the authored captures end."""

    def __init__(self, at: datetime) -> None:
        """Bind the fixed UTC instant."""
        self.at = at

    def read(self) -> datetime:
        """Return the fixed instant."""
        return self.at


class ServedDeployment:
    """Configure one paper account serving the packaged learned candidate a published stream."""

    @staticmethod
    def configuration(
        market: AuthoredMarket,
        definition: str,
        starts_at: datetime,
        serving: PaperFeatureServing,
    ) -> PaperServiceConfiguration:
        """Return a supervisor selection whose served stream the publisher extends."""
        capture = market.books.config
        currency = Currency.from_code("USDT")
        dimension = Dimension(instrument_id=capture.instrument_id, kind=QuantityKind.BASE_UNIT)
        money = Money(value=Decimal("1000"), currency=currency)
        quantity = Quantity(value=Decimal("0.001"), dimension=dimension)
        tick = Price(value=Decimal("0.1"), currency=currency, per=dimension)
        account = AccountConfiguration(
            mode="paper",
            opening_at=_START,
            accounts=(OpeningAccount(account_id="shared", cash=(money,)),),
            instruments=(SpotLimits(maximum=quantity, lot=quantity, tick=tick, product="spot"),),
            fee_rates=(InstrumentFeeRate(instrument_id=capture.instrument_id, rate=Decimal(0)),),
            budgets=BudgetPolicy(
                valuation_currency=currency,
                firm_maximum=money,
                accounts=(AccountLimit(account_id="shared", maximum=money),),
                instances=(
                    InstanceLimit(
                        instance_id="served",
                        account_id="shared",
                        maximum=money,
                        instruments=(capture.instrument_id,),
                    ),
                ),
                max_quote_age_us=30_000_000,
                max_state_age_us=30_000_000,
                max_price_deviation_bps=100,
                max_order_notional=money,
            ),
        )
        source = PaperServiceSource(
            name="book",
            capture=capture,
            trades=market.trades.config,
            freshness_us=30_000_000,
            scenario=PaperExecutionScenario(
                venue="okx",
                instrument_id=capture.instrument_id,
                entry_delay_us=1000,
                cancel_delay_us=2000,
                adverse=Price(value=Decimal(0), currency=currency, per=dimension),
                fee_rate=Decimal("0.001"),
                take_fraction=Decimal("0.5"),
                gas_inapplicable_reason="Off-chain spot without blockchain transfers.",
            ),
        )
        return PaperServiceConfiguration(
            accounts=(
                PaperServiceAccount(
                    account_id="shared",
                    configuration=account,
                    socket_path="/private/tmp/qr-served.sock",
                ),
            ),
            sources=(source,),
            instances=(
                PaperServiceInstance(
                    instance_id="served",
                    account_id="shared",
                    source="book",
                    candidate=PackagedCandidate(
                        definition_sha256=definition,
                        extension="engineering-candidates",
                        starts_at=starts_at,
                        feature_version="live",
                    ),
                    quantity=quantity,
                    lot=quantity,
                    maximum_fee=Money(value=Decimal("1"), currency=currency),
                ),
            ),
            active=("served",),
            revision=1,
            duration_seconds=120,
            features=serving,
        )
