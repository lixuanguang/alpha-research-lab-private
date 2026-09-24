"""Exercise named capability admission with mismatched independent signatures."""

from __future__ import annotations

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from configuration.capabilities import (
    CapabilityBinding,
    CapabilityField,
    CapabilityProfile,
    CapabilityQualification,
    CapabilityRegistry,
    CapabilityRequirement,
    CapabilitySelection,
)
from serialization import DomainCodec


class TestCapabilityRegistry:
    """Keep manifest requirements independent of environment-specific bindings."""

    @staticmethod
    def _requirement() -> CapabilityRequirement:
        """Demand a named exact trade price and a bounded event-age envelope."""
        return CapabilityRequirement(
            name="trade_price",
            kind="market_data",
            product="spot",
            venue="OKX",
            calendar="continuous",
            channel="trades",
            representation="trades",
            clock="event",
            max_freshness_us=10_000_000,
            fields=(CapabilityField(name="price", units="USDT/BTC"),),
            operations=("read",),
        )

    @staticmethod
    def _profile(
        *,
        name: str = "saved_trades",
        mode: str = "replay",
        qualification: CapabilityQualification = "fixture",
    ) -> CapabilityProfile:
        """Describe a bounded implementation, not an account authorization."""
        return CapabilityProfile(
            name=name,
            kind="market_data",
            implementation_identity=f"installed.{name}",
            version="1",
            products=("spot",),
            venues=("OKX",),
            calendars=("continuous",),
            modes=(mode,),
            channels=("trades",),
            representations=("trades",),
            clocks=("event", "receipt"),
            max_freshness_us=5_000_000,
            fields=(CapabilityField(name="price", units="USDT/BTC"),),
            operations=("read",),
            qualification=qualification,
            evidence_reference=(
                "source-conformance-record-1" if qualification == "external" else None
            ),
        )

    def test_same_requirement_resolves_distinct_replay_and_runtime_profiles(self) -> None:
        """Keep candidate identity while selecting installed adapters by environment."""
        requirement = self._requirement()
        saved = self._profile()
        online = self._profile(
            name="online_trades", mode="runtime_intent", qualification="read_only"
        )
        registry = CapabilityRegistry((saved, online))
        replay = registry.resolve(
            (requirement,),
            (CapabilitySelection(name="trade_price", profile=saved.name),),
            mode="replay",
        )
        runtime = registry.resolve(
            (requirement,),
            (CapabilitySelection(name="trade_price", profile=online.name),),
            mode="runtime_intent",
        )
        assert replay[0].profile.qualification == "fixture"
        assert runtime[0].profile.qualification == "read_only"
        assert replay[0].requirement == runtime[0].requirement
        assert (
            replay[0].profile.implementation_identity != runtime[0].profile.implementation_identity
        )
        restored = DomainCodec().decode_json(
            DomainCodec().encode_json(runtime[0]), CapabilityBinding
        )
        assert restored == runtime[0]

    @pytest.mark.parametrize(
        ("requirements", "selections", "message"),
        (
            (("duplicate",), ("valid",), "duplicate capability requirement"),
            (("valid",), (), "missing or extra capability selection"),
            (("valid",), ("duplicate",), "duplicate capability selection"),
            (("valid",), ("unknown",), "missing or extra capability selection"),
            (("valid",), ("uninstalled",), "unknown capability profile"),
        ),
    )
    def test_names_fail_closed(
        self, requirements: tuple[str, ...], selections: tuple[str, ...], message: str
    ) -> None:
        """Do not infer a default, ignore extras or choose an arbitrary duplicate."""
        requirement = self._requirement()
        reqs = (requirement, requirement) if requirements == ("duplicate",) else (requirement,)
        choices: tuple[CapabilitySelection, ...]
        if selections == ("valid",):
            choices = (CapabilitySelection(name="trade_price", profile="saved_trades"),)
        elif selections == ("duplicate",):
            choice = CapabilitySelection(name="trade_price", profile="saved_trades")
            choices = (choice, choice)
        elif selections == ("unknown",):
            choices = (CapabilitySelection(name="other", profile="saved_trades"),)
        elif selections == ("uninstalled",):
            choices = (CapabilitySelection(name="trade_price", profile="absent"),)
        else:
            choices = ()
        with pytest.raises(ValueError, match=message):
            CapabilityRegistry((self._profile(),)).resolve(reqs, choices, mode="replay")

    @pytest.mark.parametrize(
        "change",
        (
            {"kind": "reference_data"},
            {"product": "future"},
            {"venue": "Bitfinex"},
            {"calendar": "weekday"},
            {"channel": "book"},
            {"representation": "L2"},
            {"clock": "valid"},
            {"depth": 5},
            {"max_freshness_us": 1_000_000},
            {"fields": (CapabilityField(name="price", units="USD/BTC"),)},
            {"operations": ("write",)},
            {"order_types": ("limit",)},
            {"lifecycle": ("cancel",)},
            {"qualification": "external"},
        ),
    )
    def test_signature_mismatch_rejects_before_work(self, change: dict[str, object]) -> None:
        """Require exact units and complete support instead of a matching venue label."""
        requirement = replace(self._requirement(), **change)
        registry = CapabilityRegistry((self._profile(),))
        with pytest.raises(ValueError, match="capability"):
            registry.resolve(
                (requirement,),
                (CapabilitySelection(name="trade_price", profile="saved_trades"),),
                mode="replay",
            )

    def test_mode_and_duplicate_profile_reject(self) -> None:
        """Keep the selected operating mode and installed profile names exact."""
        profile = self._profile()
        with pytest.raises(ValueError, match="duplicate capability profile"):
            CapabilityRegistry((profile, profile))
        with pytest.raises(ValueError, match="incompatible capability profile"):
            CapabilityRegistry((profile,)).resolve(
                (self._requirement(),),
                (CapabilitySelection(name="trade_price", profile=profile.name),),
                mode="runtime_intent",
            )

    def test_external_evidence_and_suppressed_execution(self) -> None:
        """Label external qualification and refuse unsupported order operations."""
        profile = self._profile()
        with pytest.raises(ValueError, match="external capability requires evidence"):
            replace(profile, qualification="external")
        external = replace(
            profile, qualification="external", evidence_reference="source-conformance-record-1"
        )
        assert external.qualification == "external"
        execution = CapabilityProfile(
            name="intent_sink",
            kind="execution",
            implementation_identity="installed.intent_sink",
            version="1",
            products=("spot",),
            venues=("OKX",),
            calendars=("continuous",),
            modes=("runtime_intent",),
            operations=("suppress",),
        )
        required = CapabilityRequirement(
            name="orders",
            kind="execution",
            product="spot",
            venue="OKX",
            calendar="continuous",
            operations=("submit",),
        )
        with pytest.raises(ValueError, match="operation unavailable"):
            CapabilityRegistry((execution,)).resolve(
                (required,),
                (CapabilitySelection(name="orders", profile="intent_sink"),),
                mode="runtime_intent",
            )

    @staticmethod
    def _spot_books() -> tuple[
        CapabilityRequirement,
        CapabilityRequirement,
        CapabilityProfile,
        CapabilityProfile,
    ]:
        """Describe distinct installed public book envelopes without source qualification."""
        okx = CapabilityRequirement(
            name="okx_book",
            kind="market_data",
            product="spot",
            venue="okx",
            calendar="continuous-utc",
            channel="books",
            representation="L2",
            depth=400,
            clock="event",
            operations=("snapshot", "read"),
            lifecycle=("new-snapshot-epoch",),
            qualification="read_only",
        )
        bitfinex = CapabilityRequirement(
            name="bitfinex_book",
            kind="market_data",
            product="spot",
            venue="bitfinex",
            calendar="continuous-utc",
            channel="R0",
            representation="L3",
            depth=25,
            clock="receipt",
            operations=("snapshot", "read"),
            lifecycle=("new-snapshot-epoch",),
            qualification="read_only",
        )
        okx_profile = CapabilityProfile(
            name="okx-public-books",
            kind="market_data",
            implementation_identity="okx.native-book:1",
            version="1",
            products=("spot",),
            venues=("okx",),
            calendars=("continuous-utc",),
            modes=("replay", "runtime"),
            channels=("books",),
            representations=("L2",),
            max_depth=400,
            clocks=("event", "receipt"),
            operations=("snapshot", "read"),
            lifecycle=("new-snapshot-epoch",),
            qualification="read_only",
        )
        bitfinex_profile = CapabilityProfile(
            name="bitfinex-public-r0",
            kind="market_data",
            implementation_identity="bitfinex.native-book:1",
            version="1",
            products=("spot",),
            venues=("bitfinex",),
            calendars=("continuous-utc",),
            modes=("replay", "runtime"),
            channels=("R0",),
            representations=("L3",),
            max_depth=25,
            clocks=("receipt",),
            operations=("snapshot", "read"),
            lifecycle=("new-snapshot-epoch",),
            qualification="read_only",
        )
        return okx, bitfinex, okx_profile, bitfinex_profile

    def test_initial_spot_book_profiles_keep_venue_and_clock_semantics(self) -> None:
        """Admit timestamped OKX L2 and receipt-clock Bitfinex R0 separately."""
        okx, bitfinex, okx_profile, bitfinex_profile = self._spot_books()
        registry = CapabilityRegistry((okx_profile, bitfinex_profile))
        selections = (
            CapabilitySelection(name=okx.name, profile=okx_profile.name),
            CapabilitySelection(name=bitfinex.name, profile=bitfinex_profile.name),
        )
        for mode in ("replay", "runtime"):
            bindings = registry.resolve((okx, bitfinex), selections, mode=mode)
            assert tuple(binding.profile.name for binding in bindings) == (
                "okx-public-books",
                "bitfinex-public-r0",
            )
            assert tuple(binding.profile.qualification for binding in bindings) == (
                "read_only",
                "read_only",
            )
            assert bindings[0].profile.representations == ("L2",)
            assert bindings[1].profile.clocks == ("receipt",)

    @pytest.mark.parametrize(
        "change",
        (
            {"clock": "event"},
            {"depth": 26},
            {"operations": ("submit",)},
            {"product": "perpetual"},
        ),
    )
    def test_bitfinex_r0_rejects_unsupported_scope(self, change: dict[str, object]) -> None:
        """Unknown native event time, extra depth and executable scope cannot be inferred."""
        _, bitfinex, _, profile = self._spot_books()
        requirement = replace(bitfinex, **change)
        with pytest.raises(ValueError, match="capability"):
            CapabilityRegistry((profile,)).resolve(
                (requirement,),
                (CapabilitySelection(name="bitfinex_book", profile=profile.name),),
                mode="runtime",
            )
