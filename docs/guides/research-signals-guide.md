# Research Signals Guide — Prediction Markets

> **When to start:** After R1 (Dataset Builder) is implemented  
> **Full workflow unlocked:** After R5 (Evaluation Metrics)  
> **Audience:** You (the researcher/developer), working in the alpha-research-lab codebase

---

## Table of Contents

1. [Where Research Fits in the Implementation Plan](#1-where-research-fits-in-the-implementation-plan)
2. [The Research Lifecycle](#2-the-research-lifecycle)
3. [Phase 1 — Exploratory Research (Post-R1)](#3-phase-1--exploratory-research-post-r1)
4. [Phase 2 — Signal Prototyping (During/Post-R2)](#4-phase-2--signal-prototyping-duringpost-r2)
5. [Phase 3 — Signal Validation (Post-R3)](#5-phase-3--signal-validation-post-r3)
6. [Phase 4 — Signal Iteration (Post-R4)](#6-phase-4--signal-iteration-post-r4)
7. [Phase 5 — Signal Evaluation & Selection (Post-R5)](#7-phase-5--signal-evaluation--selection-post-r5)
8. [Phase 6 — Research Workflow Automation (Post-R6)](#8-phase-6--research-workflow-automation-post-r6)
9. [Signal Taxonomy for Prediction Markets](#9-signal-taxonomy-for-prediction-markets)
10. [Signal Ideas — Starter Catalogue](#10-signal-ideas--starter-catalogue)
11. [Research Anti-Patterns & Pitfalls](#11-research-anti-patterns--pitfalls)
12. [Research Journal Template](#12-research-journal-template)
13. [Microstructure Signals Implementation Track (R1→R6)](#13-microstructure-signals-implementation-track-r1r6)
14. [Notebook Placement for Alpha Research](#14-notebook-placement-for-alpha-research)

---

## 1. Where Research Fits in the Implementation Plan

The R1–R6 steps build **infrastructure**. Your actual research — forming hypotheses, testing signals, discovering alpha — runs **in parallel** with the later steps once the prerequisites are in place.

```
R1  R2  R3  R4  R5  R6
│   │   │   │   │   │
│   │   │   │   │   └── Full CLI automation    ─── Phase 6: Automated workflows
│   │   │   │   └────── Proper metrics         ─── Phase 5: Rigorous evaluation
│   │   │   └────────── Fast iteration         ─── Phase 4: Rapid sweep
│   │   └────────────── Tick-by-tick testing    ─── Phase 3: Signal validation
│   └────────────────── Feature computation     ─── Phase 2: Signal prototyping
└────────────────────── Gold datasets + DuckDB  ─── Phase 1: Exploratory research
                                                  ▲
                                                  │
                                           YOU START HERE
```

### The Key Insight

You don't wait until R6 is done to start researching. Each completed step unlocks a new level of research capability:

| Step Complete | Research Capability Unlocked |
|---|---|
| **R1** | Explore gold datasets via DuckDB. Form hypotheses. Spot patterns manually. |
| **R2** | Compute features. Prototype signals as feature combinations. Inspect feature distributions. |
| **R3** | Validate signals tick-by-tick. See realistic fills, fees, resolution. Get PnL for single signals. |
| **R4** | Sweep parameters rapidly. Compare signal variants. Cross-sectional strategies. |
| **R5** | Proper Sharpe, Brier, calibration. Compare signals rigorously. Kill bad ideas with data. |
| **R6** | Automate the full loop. Run research pipelines from CLI. Persist and version everything. |

**Recommended approach:** Start R1 implementation. As soon as R1 is testable (gold datasets can be built), begin Phase 1 exploratory research *while you implement R2*. Each subsequent research phase runs alongside the corresponding implementation step.

---

## 2. The Research Lifecycle

Every research signal follows this lifecycle. The phases map directly to implementation steps:

```
                ┌──────────────────────────────────────────────┐
                │                                              │
                ▼                                              │
┌──────────────────────┐                                       │
│  1. OBSERVE          │  Post-R1                              │
│  Explore gold data   │  DuckDB queries, eyeball patterns     │
│  via DuckDB & pandas │  No code yet — just curiosity         │
└──────────┬───────────┘                                       │
           │                                                   │
           ▼                                                   │
┌──────────────────────┐                                       │
│  2. HYPOTHESISE      │  Post-R1                              │
│  "I think X predicts │  Write it down. Be specific.          │
│   Y because Z"       │  Include expected direction & size.   │
└──────────┬───────────┘                                       │
           │                                                   │
           ▼                                                   │
┌──────────────────────┐                                       │
│  3. ENGINEER         │  Post-R2                              │
│  Build the feature   │  Implement as Feature subclass.       │
│  that captures X     │  Register in FeatureRegistry.         │
└──────────┬───────────┘                                       │
           │                                                   │
           ▼                                                   │
┌──────────────────────┐                                       │
│  4. VALIDATE         │  Post-R3                              │
│  Backtest a simple   │  Use EventBacktestEngine.             │
│  strategy using X    │  Realistic fills + fees + resolution. │
└──────────┬───────────┘                                       │
           │                                                   │
           ▼                                                   │
┌──────────────────────┐                                       │
│  5. ITERATE          │  Post-R4                              │
│  Sweep parameters,   │  Use VecBacktestEngine + sweep.       │
│  combine signals     │  Fast cross-sectional testing.        │
└──────────┬───────────┘                                       │
           │                                                   │
           ▼                                                   │
┌──────────────────────┐                                       │
│  6. EVALUATE         │  Post-R5                              │
│  Full metrics suite  │  Sharpe, Brier, calibration,          │
│  Decide: keep/kill   │  resolution decomposition.            │
└──────────┬───────────┘                                       │
           │                                                   │
           ├── KEEP ──► Promote to strategy catalogue          │
           │            Tag version. Document rationale.        │
           │                                                   │
           └── KILL ──► Log reasoning. Archive.                │
                        Return to OBSERVE ─────────────────────┘
```

---

## 3. Phase 1 — Exploratory Research (Post-R1)

**Prerequisites:** R1 complete (gold datasets buildable)  
**Tools available:** `GoldDataset`, `DuckDBAnalytics`, `MarketMaster`, `pandas`

### What You Can Do

Once R1 is done, you have gold-tier Parquet datasets with point-in-time discipline. This is enough to start real research:

### 3.1 Build Your First Gold Dataset

```python
from alpha_core.research.dataset_builder import DatasetBuilder, DatasetConfig
from alpha_core.research.universe import UniverseManager
from alpha_core.instruments.master import MarketMaster
from alpha_core.storage.parquet_reader import ParquetEventReader
from alpha_core.quality.gap_detector import GapDetector
from alpha_core.quality.partition_validator import PartitionValidator
from pathlib import Path
from datetime import datetime, timezone

# Configure — adjust venues and date range to your collected data
config = DatasetConfig(
    name="exploration_v1",
    start=datetime(2026, 1, 1, tzinfo=timezone.utc),
    end=datetime(2026, 3, 1, tzinfo=timezone.utc),
    venues=["kalshi", "polymarket"],
    event_types=["trades", "ohlcv"],
    require_quality_pass=True,
)

# Build
master = MarketMaster(Path("data/instruments"))
reader = ParquetEventReader(Path("data/silver"))
universe_mgr = UniverseManager(master)
builder = DatasetBuilder(reader, universe_mgr, PartitionValidator(...), GapDetector(...), Path("data/gold"))

manifest = builder.build(config)
dataset = builder.load(manifest.dataset_id)
print(f"Built: {manifest.instrument_count} instruments, {manifest.row_counts}")
```

### 3.2 Exploratory Queries with DuckDB

Use `DuckDBAnalytics` to ask questions about your data. These queries inform hypotheses:

```python
from alpha_core.storage.duckdb_layer import DuckDBAnalytics

db = DuckDBAnalytics(Path("data/gold/datasets/exploration_v1"))

# --- Question: How does volume distribute across venues? ---
volume_by_venue = db.query("""
    SELECT venue, COUNT(*) as trade_count, SUM(size) as total_volume
    FROM trades
    GROUP BY venue
    ORDER BY total_volume DESC
""")

# --- Question: Are there time-of-day patterns in trading? ---
hourly_pattern = db.query("""
    SELECT EXTRACT(HOUR FROM ts_event) as hour, 
           COUNT(*) as trades,
           AVG(price) as avg_price,
           STDDEV(price) as price_vol
    FROM trades
    GROUP BY hour
    ORDER BY hour
""")

# --- Question: Do prices cluster near 0 and 1 (strong convictions)? ---
price_distribution = db.query("""
    SELECT 
        CASE 
            WHEN price < 0.1 THEN '0.0-0.1'
            WHEN price < 0.2 THEN '0.1-0.2'
            WHEN price < 0.3 THEN '0.2-0.3'
            WHEN price < 0.4 THEN '0.3-0.4'
            WHEN price < 0.5 THEN '0.4-0.5'
            WHEN price < 0.6 THEN '0.5-0.6'
            WHEN price < 0.7 THEN '0.6-0.7'
            WHEN price < 0.8 THEN '0.7-0.8'
            WHEN price < 0.9 THEN '0.8-0.9'
            ELSE '0.9-1.0'
        END as price_bucket,
        COUNT(*) as trade_count
    FROM trades
    GROUP BY price_bucket
    ORDER BY price_bucket
""")

# --- Question: Cross-venue price divergence for same market? ---
# Requires market_master join
cross_venue = db.query("""
    SELECT a.canonical_market_id,
           a.venue as venue_a, b.venue as venue_b,
           AVG(ABS(a.price - b.price)) as avg_spread,
           MAX(ABS(a.price - b.price)) as max_spread
    FROM trades a
    JOIN trades b ON a.canonical_market_id = b.canonical_market_id
                  AND a.venue != b.venue
                  AND ABS(EXTRACT(EPOCH FROM a.ts_event - b.ts_event)) < 60
    GROUP BY a.canonical_market_id, a.venue, b.venue
    HAVING COUNT(*) > 10
    ORDER BY avg_spread DESC
    LIMIT 20
""")
```

### 3.3 Visual Pattern Spotting with Pandas

```python
import pandas as pd

# Load trades for a specific active market
df = dataset.to_pandas(event_type="trades")
market_df = df[df["canonical_market_id"] == "some_interesting_market"]

# Price over time — does it trend, mean-revert, or jump?
market_df.set_index("ts_event")["price"].plot(title="Price History")

# Volume spikes — do they precede price moves?
market_df.set_index("ts_event")["size"].rolling(20).sum().plot(title="Rolling Volume")

# Price acceleration — second derivative
market_df["price_change"] = market_df["price"].diff()
market_df["price_accel"] = market_df["price_change"].diff()
```

### 3.4 What to Look For

Focus your exploration on these prediction-market-specific phenomena:

| Phenomenon | What to Query | Why It Matters |
|---|---|---|
| **Probability clustering** | Price distribution near 0/0.5/1 | Markets spend most time near certainty — alpha lives in transitions |
| **Resolution patterns** | How fast do prices converge to 0/1 before resolution? | Late-stage certainty creates structural patterns |
| **Cross-venue spreads** | Same question, different venues — how wide? | Arbitrage and information flow signals |
| **Volume-price lead/lag** | Does volume spike before price moves? | Information arrival proxy |
| **Time-of-day effects** | Trading activity and volatility by hour | Market microstructure artifacts |
| **Category momentum** | Do politics/crypto/sports markets move together? | Thematic alpha |
| **New market patterns** | How do newly listed markets behave? | IPO-like effects in prediction markets |
| **Liquidity variation** | Bid-ask spread patterns by market age/volume | Execution cost estimation |

### 3.5 Forming Hypotheses

Write down every observation as a testable hypothesis. Be specific:

**Bad:** "Markets are predictable"
**Good:** "Markets priced between 0.2–0.8 that experience >5% probability move in 24h tend to continue in the same direction for the next 48h, with an average continuation of 2–3%"

**Bad:** "Cross-venue arbitrage works"
**Good:** "When the same binary outcome is priced >$0.03 apart on Kalshi vs Polymarket for >5 minutes, buying the cheaper and selling the more expensive produces a positive expected value after fees (Kalshi: 7bps taker + 1¢/contract, Polymarket: 0bps)"

---

## 4. Phase 2 — Signal Prototyping (During/Post-R2)

**Prerequisites:** R2 complete (feature engine + registry)  
**Tools available:** Everything from Phase 1 + `FeatureRegistry`, all Feature subclasses

### 4.1 Understanding Features vs Signals vs Strategies

These three concepts are distinct in your codebase:

```
FEATURE (R2)          SIGNAL (Your research)       STRATEGY (R3/R4)
────────────          ──────────────────────       ────────────────
A computed numeric    A feature (or combination)   A signal + rules for
series aligned to     with a directional           position sizing,
timestamps.           interpretation.              execution, and risk.

Example:              Example:                     Example:
ImpliedProbMomentum   "Go long when                ProbabilityMomentumStrategy
  → 0.03, -0.01,       momentum > 0.02,             → on_data(): check signal,
     0.05, ...          short when < -0.02"            size position, emit order
```

- **Feature** = observation (neutral, computed from data)
- **Signal** = opinion (directional, derived from features + thresholds)
- **Strategy** = action (trades, sizes, timing)

Your research focuses on the **signal layer** — deciding which features matter, how to combine them, and what thresholds generate profitable opinions.

### 4.2 Prototyping a Signal from a Feature

Once R2 gives you the Feature engine, signal prototyping is fast:

```python
from alpha_core.features.registry import FeatureRegistry
from alpha_core.features.primitives import RollingMean, ZScore, Diff
from alpha_core.features.pm_specific import (
    ImpliedProbMomentum,
    CrossVenueSpread,
    BookImbalance,
    TimeToResolutionDecay,
    VolumeWeightedProb,
)

# Build a feature registry with your candidate signals
registry = FeatureRegistry()
registry.register(ImpliedProbMomentum(window=20))
registry.register(ImpliedProbMomentum(window=5))   # Short-term variant
registry.register(CrossVenueSpread())
registry.register(BookImbalance(levels=3))
registry.register(TimeToResolutionDecay())
registry.register(VolumeWeightedProb(window=50))
registry.register(ZScore(window=50))

# Compute on your gold dataset
feature_table = registry.compute_all(dataset.trades())
df = feature_table.to_pandas()
```

### 4.3 Signal Exploration Workflow

Once you have features computed, use pandas/DuckDB to test your hypotheses:

```python
# Hypothesis: "High probability momentum predicts continuation"
# Test: Compare future returns for momentum > 0.02 vs momentum < -0.02

df["future_return_24h"] = df.groupby("instrument_id")["price"].shift(-24) - df["price"]

high_momentum = df[df["implied_prob_momentum_20"] > 0.02]["future_return_24h"]
low_momentum = df[df["implied_prob_momentum_20"] < -0.02]["future_return_24h"]
neutral = df[df["implied_prob_momentum_20"].abs() <= 0.02]["future_return_24h"]

print(f"High momentum avg future return: {high_momentum.mean():.4f}")
print(f"Low  momentum avg future return: {low_momentum.mean():.4f}")
print(f"Neutral       avg future return: {neutral.mean():.4f}")
print(f"Signal spread: {high_momentum.mean() - low_momentum.mean():.4f}")
```

```python
# Hypothesis: "Cross-venue spread > 3¢ generates arb profit"
spread_df = df[df["cross_venue_spread"].abs() > 0.03]
print(f"Opportunities: {len(spread_df)}")
print(f"Avg spread: {spread_df['cross_venue_spread'].abs().mean():.4f}")
print(f"Avg spread after 1h: {spread_df['future_spread_1h'].abs().mean():.4f}")  # Does it close?
```

```python
# Hypothesis: "Book imbalance predicts short-term direction"
df["future_return_1h"] = df.groupby("instrument_id")["price"].shift(-1) - df["price"]

from scipy import stats
corr, pval = stats.spearmanr(
    df["book_imbalance"].dropna(),
    df.loc[df["book_imbalance"].notna(), "future_return_1h"]
)
print(f"Rank correlation: {corr:.4f}, p-value: {pval:.6f}")
```

### 4.4 Feature Combination — Multi-Signal Prototyping

Real signals are usually combinations. Explore these interactively:

```python
# Combined signal: momentum + book imbalance confirmation
df["combined_signal"] = (
    df["implied_prob_momentum_20"].rank(pct=True)  # Normalise to [0, 1]
    + df["book_imbalance"].rank(pct=True)           # Both contribute equally
) / 2

# Does the combined signal predict better than either alone?
for signal_col in ["implied_prob_momentum_20", "book_imbalance", "combined_signal"]:
    ic = df[signal_col].corr(df["future_return_24h"])
    print(f"{signal_col:40s} IC = {ic:.4f}")
```

```python
# Conditional signal: momentum only when time-to-resolution > 7 days
# (Avoid end-of-life markets where everything converges)
mask = df["time_to_resolution_decay"] > 0.3  # Normalised: 0.3 ≈ plenty of time
df.loc[mask, "conditional_momentum"] = df.loc[mask, "implied_prob_momentum_20"]
df.loc[~mask, "conditional_momentum"] = 0.0  # No signal when close to resolution

ic_unconditional = df["implied_prob_momentum_20"].corr(df["future_return_24h"])
ic_conditional = df["conditional_momentum"].corr(df["future_return_24h"])
print(f"Unconditional IC: {ic_unconditional:.4f}")
print(f"Conditional IC:   {ic_conditional:.4f}")
```

### 4.5 Custom Feature Implementation

When your hypothesis needs a feature not in the primitives or PM-specific set, implement it:

```python
# Example: "Surprised Volume" — volume spike relative to recent average
# File: libs/core/alpha_core/features/pm_specific.py (or a new file for custom)

from alpha_core.features.base import Feature, FeatureResult
import numpy as np
import pyarrow as pa

class SurprisedVolume(Feature):
    """Ratio of current volume to rolling average.
    Values >> 1.0 indicate unusual activity (potential information arrival).
    """
    name = "surprised_volume"
    
    def __init__(self, window: int = 50):
        self.params = {"window": window}
        self._window = window
    
    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        volumes = data.column("size").to_numpy()
        rolling_avg = np.convolve(volumes, np.ones(self._window) / self._window, mode="full")[:len(volumes)]
        # Avoid division by zero
        rolling_avg = np.where(rolling_avg == 0, np.nan, rolling_avg)
        surprised = volumes / rolling_avg
        return FeatureResult(
            name=self.name,
            values=surprised,
            computed_at=datetime.now(timezone.utc),
            params=self.params,
        )
```

Then register and test it:
```python
registry.register(SurprisedVolume(window=50))
features = registry.compute_all(dataset.trades())
```

---

## 5. Phase 3 — Signal Validation (Post-R3)

**Prerequisites:** R3 complete (event-driven backtester + execution simulator + portfolio tracker)  
**Tools available:** Everything from Phase 2 + `EventBacktestEngine`, `Strategy`, `PortfolioTracker`

### 5.1 Why You Need This Phase

Phases 1–2 test signals with **idealised** assumptions:
- Instant fills at mid-price
- No fees
- No position tracking
- No resolution handling
- Forward-looking returns (potential look-ahead)

Phase 3 fixes all of that. The event-driven backtester simulates **realistic execution** tick-by-tick.

### 5.2 Turning a Signal into a Strategy

Take your best signal hypothesis from Phase 2 and embed it in a `Strategy` subclass:

```python
# apps/research/strategies/my_first_signal.py
from apps.research.backtester.strategy import Strategy, StrategyState
from alpha_core.execution.models import OrderIntent, Side
from decimal import Decimal
from datetime import datetime

class ProbMomentumLongOnly(Strategy):
    """
    Hypothesis: instruments with implied_prob_momentum_20 > threshold
    will continue appreciating for the next 24-48 hours.
    
    Rules:
    - Long when momentum > entry_threshold
    - Exit when momentum < exit_threshold or on resolution
    - Equal weight across positions
    - Max 10 concurrent positions
    """
    
    def __init__(self, entry_threshold: float = 0.02,
                 exit_threshold: float = -0.01,
                 max_positions: int = 10):
        self._entry = entry_threshold
        self._exit = exit_threshold
        self._max = max_positions
    
    @property
    def name(self) -> str:
        return f"prob_momentum_long_{self._entry}_{self._exit}"
    
    def on_init(self, universe: list[str]) -> None:
        self._universe = universe
    
    def on_data(self, timestamp: datetime, state: StrategyState) -> list[OrderIntent]:
        orders: list[OrderIntent] = []
        
        if not state.features:
            return orders
        
        current_positions = set(state.portfolio.positions.keys())
        
        # Exit signals
        for inst_id in list(current_positions):
            feat = state.features.get(inst_id, {})
            momentum = feat.get("implied_prob_momentum_20", 0.0)
            if momentum < self._exit:
                pos = state.portfolio.positions[inst_id]
                orders.append(OrderIntent(
                    instrument_id=inst_id,
                    side=Side.SHORT if pos.side == Side.LONG else Side.LONG,
                    size=pos.size,
                    order_type="market",
                ))
        
        # Entry signals
        if len(current_positions) < self._max:
            candidates = []
            for inst_id in state.universe:
                if inst_id in current_positions:
                    continue
                feat = state.features.get(inst_id, {})
                momentum = feat.get("implied_prob_momentum_20", 0.0)
                if momentum > self._entry:
                    candidates.append((inst_id, momentum))
            
            # Rank by momentum strength, take top N
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots = self._max - len(current_positions)
            
            for inst_id, _ in candidates[:slots]:
                # Equal-weight sizing
                size_usd = state.portfolio.equity / Decimal(str(self._max))
                price = state.latest_prices.get(inst_id, Decimal("0.50"))
                if price > 0:
                    contracts = size_usd / price
                    orders.append(OrderIntent(
                        instrument_id=inst_id,
                        side=Side.LONG,
                        size=contracts.quantize(Decimal("1")),
                        order_type="market",
                    ))
        
        return orders
    
    def on_resolution(self, instrument_id: str, resolved_price: Decimal) -> None:
        # Portfolio tracker handles the settlement automatically
        pass
```

### 5.3 Running the Backtest

```python
from apps.research.backtester.engine import EventBacktestEngine, EventBacktestConfig
from alpha_core.execution.models import FeeSchedule
from decimal import Decimal

config = EventBacktestConfig(
    dataset_id="exploration_v1",
    feature_set="pm_features_v1",
    initial_cash=Decimal("10000"),
    fee_schedule=FeeSchedule(
        taker_fee_bps=Decimal("7"),       # Kalshi-like
        per_contract_fee=Decimal("0.01"),
        resolution_fee_bps=Decimal("0"),
    ),
    slippage_model="fixed",
    slippage_params={"bps": 10},
)

engine = EventBacktestEngine(config)
strategy = ProbMomentumLongOnly(entry_threshold=0.02, exit_threshold=-0.01)

result = engine.run(strategy, dataset, features=feature_table)
print(f"Trades: {len(result.trades)}")
print(f"Final equity: {result.final_portfolio.equity}")
print(f"Total PnL: {result.final_portfolio.total_pnl}")
```

### 5.4 What to Check After a Backtest

After each validation run, ask these questions:

| Question | How to Check | Red Flag |
|---|---|---|
| Did it trade enough? | `len(result.trades)` | < 30 trades = too few for statistical significance |
| Is PnL driven by one trade? | Sort trades by PnL, check concentration | Top trade is > 50% of total PnL |
| Does it trade in all time periods? | Plot trade timestamps | All trades in one week = overfitting to that period |
| Does it handle resolutions? | Count resolution events vs total | Resolution PnL dominates = you're betting on outcomes, not trading |
| Are fills realistic? | Check slippage distribution | Average slippage > spread = unrealistic assumptions |
| Does it respect fees? | Compare gross vs net PnL | Profitable gross but unprofitable net = fee-sensitive signal |

### 5.5 Iterating on the Strategy

Based on backtest results, refine your strategy:

```python
# Try different thresholds
for entry in [0.01, 0.02, 0.03, 0.05]:
    for exit_th in [-0.005, -0.01, -0.02]:
        strategy = ProbMomentumLongOnly(entry_threshold=entry, exit_threshold=exit_th)
        result = engine.run(strategy, dataset, features=feature_table)
        print(f"entry={entry}, exit={exit_th}: "
              f"PnL={result.final_portfolio.total_pnl}, "
              f"trades={len(result.trades)}")
```

But **stop** — this manual loop is exactly what Phase 4 automates properly.

---

## 6. Phase 4 — Signal Iteration (Post-R4)

**Prerequisites:** R4 complete (vectorized backtester + parameter sweep)  
**Tools available:** Everything from Phase 3 + `VecBacktestEngine`, `ParameterSweepRunner`

### 6.1 When to Use Event vs Vectorized

| Use Event Engine (R3) | Use Vec Engine (R4) |
|---|---|
| Testing a **single signal** with precision | Sweeping **many parameter combinations** |
| Order book interaction matters | Cross-sectional (many instruments at once) |
| Need exact fill simulation | Speed over fill precision |
| Debugging strategy logic tick-by-tick | Screening signal variants |
| Final validation before promotion | Early-stage filtering |

### 6.2 Vectorized Signal Testing

The VecStrategy interface is designed for rapid signal iteration:

```python
from apps.research.backtester.vec_strategy import VecStrategy
import pandas as pd
from decimal import Decimal

class MomentumZScoreVec(VecStrategy):
    """Cross-sectional momentum z-score.
    Long instruments with momentum z-score > threshold.
    Short instruments with momentum z-score < -threshold.
    """
    
    def __init__(self, zscore_threshold: float = 1.5, window: int = 20):
        self._threshold = zscore_threshold
        self._window = window
    
    @property
    def name(self) -> str:
        return f"momentum_zscore_{self._threshold}_{self._window}"
    
    def generate_signals(self, features: pd.DataFrame,
                         universe: list[str]) -> pd.DataFrame:
        # Cross-sectional z-score of momentum
        momentum = features["implied_prob_momentum_20"]
        zscore = (momentum - momentum.mean()) / momentum.std()
        
        signals = pd.DataFrame({
            "instrument_id": features["instrument_id"],
            "signal": zscore.clip(-3, 3),  # Clip extremes
        })
        
        # Zero out below threshold
        signals.loc[signals["signal"].abs() < self._threshold, "signal"] = 0.0
        return signals
    
    def size_positions(self, signals: pd.DataFrame,
                       portfolio_value: Decimal,
                       max_positions: int) -> pd.DataFrame:
        active = signals[signals["signal"] != 0.0].copy()
        if len(active) == 0:
            return pd.DataFrame(columns=["instrument_id", "target_weight"])
        
        # Equal weight among active signals
        n = min(len(active), max_positions)
        top = active.nlargest(n, "signal", keep="first")
        top["target_weight"] = 1.0 / n
        return top[["instrument_id", "target_weight"]]
```

### 6.3 Parameter Sweeps

This is where R4 shines — automated, systematic signal variant testing:

```python
from apps.research.backtester.sweep import ParameterGrid, ParameterSweepRunner

# Define the grid
grid = ParameterGrid({
    "zscore_threshold": [0.5, 1.0, 1.5, 2.0, 2.5],
    "window": [5, 10, 20, 50],
})
print(f"Total combinations: {len(grid)}")  # 20

# Factory function — sweep runner needs this
def strategy_factory(params: dict) -> VecStrategy:
    return MomentumZScoreVec(**params)

# Run the sweep
sweep_runner = ParameterSweepRunner(
    engine=vec_engine,
    evaluator=evaluator,
    n_workers=1,
)

sweep_result = sweep_runner.run(
    strategy_factory=strategy_factory,
    param_grid=grid,
    dataset=dataset,
    features=feature_table,
    primary_metric="sharpe_ratio",
)

print(f"Best params: {sweep_result.best_params}")
print(f"Best Sharpe: {sweep_result.results[0][1].sharpe_ratio}")
```

### 6.4 Multi-Signal Combination Sweeps

Test combinations of signals, not just parameters of one signal:

```python
# Sweep: which feature combinations work best?
signal_combinations = [
    ["implied_prob_momentum_20"],
    ["implied_prob_momentum_20", "book_imbalance"],
    ["implied_prob_momentum_20", "book_imbalance", "time_to_resolution_decay"],
    ["cross_venue_spread"],
    ["volume_weighted_prob_50", "prob_acceleration"],
    ["implied_prob_momentum_5", "implied_prob_momentum_20"],  # Multi-timeframe
]

results = {}
for combo in signal_combinations:
    # Build a strategy that uses this feature combination
    strategy = MultiFeatureVecStrategy(feature_names=combo, threshold=1.5)
    result = vec_engine.run(strategy, dataset, feature_table)
    results[tuple(combo)] = result
    print(f"{combo}: PnL={result.final_portfolio.total_pnl}")
```

---

## 7. Phase 5 — Signal Evaluation & Selection (Post-R5)

**Prerequisites:** R5 complete (evaluation metrics + reporting)  
**Tools available:** Full stack + `BacktestEvaluator`, `PMMetrics`, `FinancialMetrics`, calibration

### 7.1 Which Metrics Matter for Prediction Market Signals

Standard financial metrics alone are **insufficient** for prediction markets. Here's the priority order:

| Priority | Metric | Why It Matters for PM |
|---|---|---|
| **1** | **Brier Score** | Are your probability estimates calibrated? This is the gold standard for PM forecasting. |
| **2** | **Sharpe Ratio** | Risk-adjusted PnL — same as traditional finance. Target > 1.0. |
| **3** | **Calibration Error (ECE)** | When you say "70% likely", does the event happen 70% of the time? |
| **4** | **Log-Loss** | Penalises confident wrong predictions heavily. Complementary to Brier. |
| **5** | **Resolution Accuracy** | What % of resolved positions were on the correct side? |
| **6** | **Max Drawdown** | Worst peak-to-trough — tells you how painful the journey is. |
| **7** | **Profit Factor** | Gross profit / gross loss — must be > 1.0 to be profitable net of fees. |
| **8** | **Win Rate** | % of profitable trades — less important than size of wins. |
| **9** | **Category Breakdown** | Does your signal work across politics, sports, crypto? Or just one domain? |

### 7.2 Evaluating a Signal Properly

```python
from alpha_core.evaluation.evaluator import BacktestEvaluator
from alpha_core.evaluation.financial import compute_financial_metrics
from alpha_core.evaluation.pm_metrics import compute_pm_metrics
from alpha_core.evaluation.calibration import calibration_curve, expected_calibration_error

evaluator = BacktestEvaluator()
report = evaluator.evaluate(result, dataset)

# --- Key numbers to examine ---
print("=== Financial Metrics ===")
print(f"Sharpe:       {report.financial.sharpe_ratio:.2f}")
print(f"Sortino:      {report.financial.sortino_ratio:.2f}")
print(f"Max Drawdown: {report.financial.max_drawdown:.2%}")
print(f"Profit Factor:{report.financial.profit_factor:.2f}")
print(f"Win Rate:     {report.financial.win_rate:.2%}")
print(f"Total Trades: {report.financial.total_trades}")

print("\n=== PM Metrics ===")
print(f"Brier Score:         {report.pm_specific.brier_score:.4f}")
print(f"Log-Loss:            {report.pm_specific.log_loss:.4f}")
print(f"Calibration Error:   {report.pm_specific.calibration_error:.4f}")
print(f"Resolution Accuracy: {report.pm_specific.resolution_accuracy:.2%}")
print(f"Resolution PnL:      {report.pm_specific.resolution_pnl}")

print("\n=== Category Breakdown ===")
for category, metrics in report.pm_specific.category_breakdown.items():
    print(f"  {category}: Sharpe={metrics['sharpe']:.2f}, Brier={metrics['brier']:.4f}, "
          f"Trades={metrics['trades']}")
```

### 7.3 The Signal Scorecard

Use this checklist to decide whether to **keep** or **kill** a signal:

```
SIGNAL SCORECARD: [Signal Name]
═══════════════════════════════════════════════════════════════

MUST PASS (any fail → kill):
  □ Sharpe > 0.5 (after fees)
  □ > 50 trades in backtest window
  □ Profit Factor > 1.0 (after fees)
  □ Not concentrated — top 5 trades < 50% of total PnL
  □ Trades across full time period (not clustered)
  □ Works on at least 2 venues
  □ Robust to ±50% parameter change (no cliff)

STRONG SIGNALS (differentiate good from great):
  □ Sharpe > 1.0
  □ Brier Score < 0.20 (better than naive)
  □ Calibration Error < 0.05
  □ Max Drawdown < 20%
  □ Resolution Accuracy > 55%
  □ Positive PnL in > 60% of months
  □ Signal works in bear + bull regimes

BONUS (nice to have):
  □ Signal has intuitive economic rationale
  □ Low correlation to other kept signals (diversification)
  □ Works across categories (politics, crypto, sports)
  □ Short holding period (capital efficient)
  □ Consistent Information Coefficient (IC) across time
```

### 7.4 Comparing Signals Side-by-Side

```python
# After evaluating multiple signals
reports = [report_momentum, report_arb, report_mean_reversion, report_combined]
comparison = evaluator.compare(reports)
print(comparison.to_string())

# Output something like:
#                          prob_momentum  cross_venue_arb  mean_reversion  combined
# sharpe_ratio                    1.23            0.87            0.65      1.45
# brier_score                     0.18            0.22            0.21      0.17
# max_drawdown                   -0.12           -0.08           -0.18     -0.10
# total_trades                     187              42             312       245
# resolution_accuracy              0.62            0.71            0.54      0.64
```

### 7.5 Walk-Forward Validation (When Available)

> **Note:** Full walk-forward and purged cross-validation are deferred to the Robustness stage (Stage 6). However, you can manually approximate walk-forward by splitting your gold dataset:

```python
# Manual walk-forward: train on first 60%, test on last 40%
from datetime import timedelta

split_point = dataset.date_range()[0] + (dataset.date_range()[1] - dataset.date_range()[0]) * 0.6

# Build two datasets
train_config = DatasetConfig(name="train", start=dataset.date_range()[0], end=split_point, ...)
test_config = DatasetConfig(name="test", start=split_point, end=dataset.date_range()[1], ...)

train_dataset = builder.build(train_config)
test_dataset = builder.build(test_config)

# Develop signal on train, validate on test
# Parameter tuning → only on train
# Final evaluation → only on test
# If Sharpe drops > 50% from train → test: signal is likely overfit
```

---

## 8. Phase 6 — Research Workflow Automation (Post-R6)

**Prerequisites:** R6 complete (CLI + example strategies + loader)  
**Tools available:** Full research CLI

### 8.1 The One-Command Research Pipeline

Once R6 is wired, your research loop becomes:

```bash
# 1. Build dataset
python -m apps.research.main build-dataset \
    --name "q1_2026_study" \
    --start 2026-01-01 --end 2026-03-01 \
    --venues kalshi polymarket \
    --require-quality

# 2. Compute features
python -m apps.research.main build-features \
    --dataset q1_2026_study \
    --feature-set "all_pm_features"

# 3. Backtest your signal
python -m apps.research.main backtest \
    --strategy apps.research.strategies.probability_momentum.ProbabilityMomentumStrategy \
    --dataset q1_2026_study \
    --features all_pm_features \
    --engine event \
    --fee-bps 7 --slippage-bps 5

# 4. Evaluate
python -m apps.research.main evaluate <backtest_id>

# 5. Compare with other signals
python -m apps.research.main report <id_1> <id_2> <id_3> --format table
```

### 8.2 Building a Research Habit

Set up a weekly research routine:

| Day | Activity | Time |
|---|---|---|
| **Monday** | Refresh gold datasets with latest silver data. Review last week's results. Update research journal. | 1h |
| **Tuesday** | Exploratory analysis. DuckDB queries on new data. Spot new patterns. | 2h |
| **Wednesday** | Feature engineering. Prototype 1–2 new signal ideas. Compute features. | 2h |
| **Thursday** | Backtesting. Run event-driven tests on new signals. Parameter sweep on promising ones. | 2h |
| **Friday** | Evaluation. Scorecard for this week's signals. Kill or promote. Update signal catalogue. | 1h |

### 8.3 Signal Versioning & Cataloguing

Keep a catalogue of every signal you test, whether it worked or not:

```
data/research_journal/
├── signals/
│   ├── SIG-001_prob_momentum.md         # PROMOTED
│   ├── SIG-002_cross_venue_arb.md       # PROMOTED
│   ├── SIG-003_volume_spike.md          # KILLED — fee-sensitive
│   ├── SIG-004_book_imbalance.md        # TESTING
│   ├── SIG-005_category_momentum.md     # KILLED — overfitting
│   └── SIG-006_ttr_decay.md             # TESTING
└── weekly/
    ├── 2026-W09.md                      # Week 9 research notes
    ├── 2026-W10.md
    └── 2026-W11.md
```

---

## 9. Signal Taxonomy for Prediction Markets

This taxonomy is restricted to strategies that are implementable in **event/tick time** and grouped by **microstructure mechanism** (not vague alpha labels).

### 9.1 Queue-Based Market Making (Inventory + Spread Capture)

Core idea: estimate short-horizon fair probability `p_hat_t` from order-flow state, then quote around it while controlling inventory.

Key state signals:

- Level-1 imbalance: `I1 = (V_bid - V_ask) / (V_bid + V_ask)`
- Microprice: `m_t = (P_ask * V_bid + P_bid * V_ask) / (V_bid + V_ask)`
- Queue position: expected time-to-fill conditional on market-order arrival intensity `lambda_market`

Prediction-market specifics:

- Spread is often sticky at 1-2 ticks.
- Depth is thin, so queue priority dominates.
- Prices are bounded in `[0, 1]`, which makes inventory convexity material near edges.

Short-horizon drift model:

`E[delta_p_(t->t+H) | state_t] = beta1 * I1 + beta2 * OFI + beta3 * cancel_rate + ...`

Execution control:

- Quote inside spread only when state predicts favorable drift.
- Inventory-skewed bid: `p_quote_bid = p_hat_t - s/2 - gamma * inventory`
- Inventory-skewed ask: `p_quote_ask = p_hat_t + s/2 + gamma * inventory`

Primary risks:

- Information shocks around major news/resolution updates
- Adverse selection during resolution cascades

### 9.2 Order Flow Imbalance (OFI) Predictive Models

Use Cont-de Larrard style OFI framing adapted to bounded contracts.

OFI in event time:

`OFI_t = deltaV_bid_plus - deltaV_bid_minus - (deltaV_ask_plus - deltaV_ask_minus)`

Where:

- `deltaV_plus`: new limit volume at best quote
- `deltaV_minus`: cancellations or market-order consumption at best quote

Empirical test:

`E[delta_p_(t->t+delta)] = alpha + beta * OFI_t`

In thin markets, `beta` is often large relative to spread due to lumpy retail flow.

Practical variants:

- Multi-level OFI (L1-L3)
- Decay-weighted OFI
- Signed trade imbalance with Hawkes intensity overlay

### 9.3 Latency-Sensitive Liquidity Taking

In prediction markets, retail meta-orders can sweep one side before the book re-equilibrates.

Signals:

- Rapid one-sided sweep
- Spike in trade intensity `lambda_trade(t)`
- High short-horizon impact elasticity

Strategy:

- Detect aggressive meta-order start.
- Cross immediately to join transient impact before reversion.
- Trade `delta_p ~= kappa * signed_volume - reversion`.

Requirements:

- Low-latency feed handling
- Calibrated impact decay model (often 5-30 seconds in thin venues)

### 9.4 Queue Position Arbitrage

If queue rank and fill probability are estimable, resting liquidity can have positive expected value.

Expected value of a resting order:

`EV = fill_prob * (spread - adverse_selection)`

Estimate `fill_prob` from:

- Poisson market-order arrivals
- Cancellation rate ahead in queue
- Queue depletion intensity

This is strongest in venues with slow cancellations but frequent retail market orders.

### 9.5 Mean Reversion Around Bounded Extremes (0 or 1)

Prediction contracts have hard bounds. Near `0.02` or `0.98`, microstructure often behaves like near-expiry optionality.

Observed behavior:

- Liquidity dries up
- Small trades cause exaggerated ticks
- Short-horizon overshoots become common

Strategy:

- Fit reversion probability when price enters extreme quantiles.
- Enter passive fades with strict inventory limits.
- Exit on 1-2 tick snapback.

Constraint:

- Hard cap tail risk when resolution probability shifts structurally.

### 9.6 Cross-Contract Statistical Arbitrage

Related outcome contracts satisfy simplex constraints:

`sum_i p_i = 1`

Tick-level inefficiencies appear during retail flow bursts.

Strategy:

- Monitor instantaneous mispricing vector `epsilon_t = sum_i p_i - 1`.
- Trade baskets to enforce simplex consistency.
- Use LP-based allocation to exploit best-bid/best-ask asymmetry.

Requirements:

- Full-depth visibility across outcomes
- Fee-aware basket execution

### 9.7 Resolution-Proximity Gamma Trading

As resolution approaches:

- Volatility spikes
- Depth collapses
- Order flow becomes one-sided

Approaches:

- Market make with aggressive inventory decay (higher `gamma`)
- Take convex directional bets when imbalance persistence is high

Model realized volatility as function of time-to-event `tau`:

`sigma_t ~= f(tau, information_intensity)`

Empirically, volatility often scales like `1 / sqrt(tau)` or faster near hard news.

### 9.8 Hawkes-Based Trade Intensity Forecasting

Fit marked Hawkes processes to:

- Market orders
- Cancellations
- Limit placements

If predicted `lambda_buy(t)` persistently exceeds `lambda_sell(t)`, short-horizon drift is often tradable.

Execution policy:

- Cross spread when predicted intensity imbalance exceeds threshold.
- Otherwise provide skewed liquidity.

### 9.9 Spread Dynamics Modeling

In many prediction markets, spread toggles between 1 and 2 ticks.

Depth asymmetry and cancellation pressure can predict spread transitions.

Model:

`P(spread_change | imbalance, cancel_rate, intensity_state)`

Use cases:

- Provide liquidity when spread likely to widen.
- Avoid being picked off when spread likely to compress.

### 9.10 Fee Structure Exploitation

Prediction venues can have:

- Outcome-based fees
- Maker/taker asymmetry (and sometimes rebates)
- Resolution-time fees

Edge comes from fee-adjusted microstructure EV, for example:

- Prefer maker side when rebate/asymmetry dominates expected adverse selection.
- Route taker flow only when expected impact-adjusted edge remains positive net fees.

### 9.11 Implementation Architecture (Practical)

To productionize these strategies you need:

- Event-time state representation: LOB snapshots, OFI features, queue state estimates, trade/cancel intensities.
- Short-horizon predictive model: linear/logistic baseline first, then tree models (for example LightGBM) after baseline parity.
- Execution simulator: queue-priority simulation, partial fills, latency model, fee model.
- Inventory-aware controller: Avellaneda-Stoikov style control adapted to bounded payoff contracts with `gamma` calibrated for resolution risk.

---

## 10. Signal Ideas — Starter Catalogue

Use these as first-pass implementations that map directly to the mechanism taxonomy above.

| Strategy | Mechanism | Entry/Action | Exit/Unwind | Main Risk | Earliest Stage |
|---|---|---|---|---|---|
| **S1: Inventory-Skewed Queue MM** | Queue-based market making | Quote around `p_hat_t` when `|I1|` and OFI support edge | Inventory or drift signal reverts | Adverse selection on news shocks | R3 |
| **S2: L1 OFI Drift Taker** | OFI predictive model | Cross when `OFI_t` exceeds threshold and spread is tight | Fixed horizon (`H`) or signal flip | Cost drag in noisy flow | R3 |
| **S3: L1-L3 OFI Weighted Model** | Multi-level OFI | Trade on weighted `OFI_L1..L3` score | Horizon end or weighted score mean reversion | Overfitting feature weights | R4 |
| **S4: Meta-Order Joiner** | Latency-sensitive taking | Detect one-sided sweep + intensity spike, cross immediately | Impact decay window (for example 5-30s) | Entering after impact peak | R3 |
| **S5: Queue Rank Capture** | Queue position arbitrage | Post only when `EV_rest > 0` from fill model | Cancel if queue EV drops below zero | Fill model misspecification | R3 |
| **S6: Extreme Fade (0/1 Boundaries)** | Bounded-extreme mean reversion | Passive fade near extreme quantiles (`p <= q_low` or `p >= q_high`) | 1-2 tick snapback or hard risk stop | Structural repricing near resolution | R3 |
| **S7: Simplex Basket Arb** | Cross-contract stat arb | Trade basket when `epsilon_t = sum_i p_i - 1` breaches bound | Close when simplex residual normalizes | Multi-leg execution slippage | R4 |
| **S8: Resolution Gamma MM** | Resolution-proximity gamma | MM with higher inventory decay as `tau` shrinks | Flatten aggressively near event boundary | One-sided flow into resolution | R5 |
| **S9: Hawkes Imbalance Hybrid** | Hawkes intensity forecast | Cross if predicted `lambda_buy - lambda_sell` exceeds threshold; otherwise skew maker quotes | Intensity imbalance reverts | Regime shift in excitation dynamics | R4 |
| **S10: Spread Regime + Fee Overlay** | Spread dynamics + fee exploitation | Quote/route only when spread-state and fee-adjusted EV are favorable | Exit when spread regime flips | Fee model assumptions stale | R5 |

Implementation guidance:

- Start with linear/logistic baselines before tree models.
- Use event-time features and strict no-look-ahead joins.
- Promote only strategies that stay positive after fees, latency, and queue simulation.

---

## 11. Research Anti-Patterns & Pitfalls

### Pitfall 1: Look-Ahead Bias

**What:** Using future information to make past decisions.

**How it sneaks in:**
- Using final resolution status to filter the training universe
- Computing features with a full-window average instead of rolling
- Centering z-scores with the full-sample mean/std
- Using `ts_event` instead of `ts_record` for as-of joins

**Prevention:**
- Always use `as_of_filter()` from R1
- The `DatasetBuilder` enforces point-in-time discipline
- In Phase 2, when computing `future_return_24h` for signal testing, **never** include this as a feature — it's the target variable, not an input
- Test: if your signal has an IC > 0.5, you probably have look-ahead bias

### Pitfall 2: Overfitting to Parameters

**What:** Tuning parameters until you find a profitable combination by chance.

**How it sneaks in:**
- Testing 1000 parameter combinations, picking the best one
- Brier score goes from 0.22 → 0.15 by changing `window` from 20 → 17
- Strategy works on Jan-Feb but fails on Mar data

**Prevention:**
- **Minimum requirements:** Signal should be profitable for ≥ 50% of reasonable parameter values (e.g., windows 10–50), not just one precise value
- **Sensitivity test:** Change each parameter by ±50%. If Sharpe drops by > 50%, the signal is fragile
- **Out-of-sample:** Always hold out the most recent 30–40% of data for final validation
- **Bonferroni correction:** If you test N parameter combos, divide your confidence threshold by N

### Pitfall 3: Survivorship Bias

**What:** Only analysing markets/instruments that survived to the end of your sample.

**How it sneaks in:**
- Building a universe of "currently active" markets and backtesting on historical data
- Excluding markets that resolved early  
- Only studying instruments with "enough data" (which excludes failed/halted markets)

**Prevention:**
- `UniverseManager.snapshot_at()` gives you the universe **as it was** at each point in time
- Include markets that resolved during your backtest window
- The event-driven backtester handles resolution events explicitly

### Pitfall 4: Transaction Cost Ignorance

**What:** Signal is profitable before fees/slippage but unprofitable after.

**How it sneaks in:**
- Testing with zero fees
- Assuming fills at mid-price
- Ignoring the bid-ask spread in PM order books (often 1–5¢)
- High-frequency signals where edge < spread

**Prevention:**
- **Always** backtest with realistic `FeeSchedule`:
  - Kalshi: ~7 bps taker fee + 1¢/contract
  - Polymarket: 0 bps trading fee, but wider spreads
- Use `BookDepthSlippage` instead of `FixedSlippage` when possible
- Rule of thumb: if your signal's average edge per trade is < 2× the cost per trade, it won't survive

### Pitfall 5: Resolution Event Contamination

**What:** Your PnL is driven entirely by resolution payoffs (0/1), not by trading alpha.

**How it sneaks in:**
- Buying cheap options (markets priced at 0.05) and winning big when they resolve YES
- The 1 big resolution win masks 20 small losing trades
- Your "trading strategy" is actually just event prediction

**Prevention:**
- Check `resolution_pnl` vs `trading_pnl` in evaluation
- If resolution PnL > 70% of total PnL, you're forecasting events, not trading markets
- This isn't necessarily bad — but be honest about what your signal is doing
- Separate evaluation: Brier score measures forecasting skill; Sharpe measures trading skill

### Pitfall 6: Signal Decay (Stale Features)

**What:** A feature that was predictive becomes useless as markets adapt or conditions change.

**How it sneaks in:**
- Signal worked in 2025 data but doesn't work on new 2026 data
- Obvious arbitrage signals (cross-venue spread) get competed away
- Market microstructure changes (exchange fee changes, new participants)

**Prevention:**
- Re-test signals on rolling windows (not just one big backtest)
- Monitor IC over time — if it's declining, the signal is decaying
- Prefer signals with an economic rationale (they're more likely to persist)
- Build signal monitoring into your weekly routine

### Pitfall 7: Small Sample Statistics

**What:** Drawing conclusions from too few trades or too short a time period.

**How it sneaks in:**
- "My signal has a Sharpe of 3.0!" (based on 12 trades in 2 weeks)
- Cross-venue arb with 5 opportunities per month
- Category momentum with only 3 categories

**Prevention:**
- **Minimum thresholds:**
  - ≥ 50 trades for any statistical conclusion
  - ≥ 3 months of data for Sharpe estimation
  - ≥ 10 resolution events for Brier score
- Use bootstrap confidence intervals on key metrics
- If your signal generates < 2 trades/week, consider it an insight, not a strtegy

---

## 12. Research Journal Template

Use this template for every signal you investigate. Store in `data/research_journal/signals/`:

```markdown
# Signal: SIG-XXX — [Name]

## Status: EXPLORING | TESTING | PROMOTED | KILLED

## Hypothesis
[One sentence: "I believe X predicts Y because Z"]

## Expected Mechanism  
[Why would this work? What economic/behavioural force drives it?]

## Feature(s)
- Primary: `FeatureName(param=value)`
- Secondary: `FeatureName2(param=value)` (if combined signal)

## Rules
- Entry: [condition]
- Exit: [condition]
- Sizing: [method]
- Max positions: N

## Phase 2 Results (Feature IC)
- IC vs 24h return: 
- IC vs 1h return: 
- IC stability (IC per month): 
- Distribution: [normal/skewed/bimodal?]

## Phase 3 Results (Event Backtest)
- Period: [start] → [end]
- Trades: N
- Sharpe: 
- Brier: 
- Max DD: 
- Resolution accuracy: 
- Profit factor: 
- Fee sensitivity: [profitable net of fees? Y/N]

## Phase 4 Results (Parameter Sweep)
- Parameters swept: {param: [values]}
- Best params: {param: value}
- Sharpe range across params: [min, max]
- Robust: [Yes if >50% of params are profitable]

## Phase 5 Results (Full Evaluation)
- Scorecard: PASS / FAIL (see checklist)
- Comparison vs benchmark: [better/worse/same]
- In-sample vs out-of-sample Sharpe: [in] vs [out]
- Unique alpha (low correlation to other signals): Y/N

## Decision
[KEEP: Why / KILL: Why / NEEDS MORE DATA]

## Next Steps
- [ ] ...
```

---

## 13. Microstructure Signals Implementation Track (R1→R6)

Use this as a practical build order for **microstructure signals** so you can start early and add fidelity as each research-plane stage lands.

### Stage-by-Stage Implementation Map

| Stage | What You Implement for Microstructure | Minimum Output | Convenient `.ipynb` Research Material |
|---|---|---|---|
| **R1** Dataset Builder | Build point-in-time trade + book research panels; verify quote/trade alignment quality; define candidate microstructure hypotheses (spread compression, imbalance drift, volume shock) | 2-5 written hypotheses + one reusable SQL query set | `apps/research/notebooks/r1_microstructure_eda.ipynb` |
| **R2** Feature Engine | Implement microstructure features in `pm_specific.py` (for example: spread bps, depth imbalance, microprice deviation, order-flow imbalance); register in `FeatureRegistry` | Feature definitions + feature QA summary (null rate, distribution, stability) | `apps/research/notebooks/r2_microstructure_feature_validation.ipynb` |
| **R3** Event Backtester | Convert one feature to a tradeable event-driven strategy with realistic fees/slippage; enforce execution constraints (max spread, min depth, cooldown) | One backtest result with trade log + fill diagnostics | `apps/research/notebooks/r3_microstructure_event_replay.ipynb` |
| **R4** Vectorized Backtester | Sweep parameters and feature combinations quickly; screen robust variants before expensive event reruns | Ranked parameter grid + robustness plot (not just top Sharpe) | `apps/research/notebooks/r4_microstructure_sweep_analysis.ipynb` |
| **R5** Evaluation | Evaluate net edge after costs using PM + microstructure diagnostics (Brier/Sharpe + turnover, slippage-to-edge ratio, adverse-selection) | Keep/kill scorecard with rationale | `apps/research/notebooks/r5_microstructure_scorecard.ipynb` |
| **R6** CLI Integration | Wire the microstructure pipeline into research CLI commands and repeatable run configs | Re-runnable end-to-end command sequence + persisted reports | `apps/research/notebooks/r6_microstructure_monitoring.ipynb` |

### R1 (Post-R1) — Start with Observable Microstructure States

Implement dataset-level fields you can query without a feature engine:
- Bid/ask spread in cents and bps
- Top-of-book imbalance
- Trade intensity (trades/minute) and size burstiness

Example exploratory query:

```sql
SELECT
  canonical_market_id,
  ts_event,
  (best_ask_price - best_bid_price) AS spread_cents,
  (best_bid_size - best_ask_size) / NULLIF(best_bid_size + best_ask_size, 0) AS top_book_imbalance
FROM books
WHERE venue IN ('kalshi', 'polymarket');
```

### R2 (Post-R2) — Promote Microstructure Ideas into Features

Move the best R1 findings into versioned features and registry entries:

```python
registry.register(BookImbalance(levels=3))
registry.register(VolumeWeightedProb(window=20))
# Example custom additions for microstructure research
registry.register(SpreadBps())
registry.register(OrderFlowImbalance(window=30))
registry.register(MicropriceDeviation(levels=3))
```

At this stage, use notebook material to validate:
- Feature distributions by venue/category
- Null/inf rates and warmup behavior
- IC drift over time windows

### R3 (Post-R3) — Trade the Signal with Realistic Execution

Implement your first microstructure strategy with execution guards:
- Enter only when `spread_bps <= threshold`
- Skip when top-book depth is too small
- Use short holding windows to match signal horizon

This stage is where many microstructure ideas fail after fees/slippage; capture fill-level diagnostics in your notebook and journal.

### R4 (Post-R4) — Search Robust Regions, Not a Single Peak

Sweep:
- Signal window lengths
- Entry/exit thresholds
- Liquidity filters (min depth, max spread)

Keep candidates only if performance is stable across neighboring settings, not just one best cell.

### R5 (Post-R5) — Score Microstructure Signal Quality

Evaluate with both PM metrics and microstructure economics:
- `net_edge_per_trade`
- `turnover`
- `slippage_to_gross_edge_ratio`
- `post_fill_adverse_move` (for example, 5-30 minute horizon)

Promote only signals that remain profitable after realistic costs and show stable calibration.

### R6 (Post-R6) — Operationalize Research, Keep Exploration in Notebooks

Use CLI for repeatable production-like runs, and notebooks for:
- Post-run diagnostics
- Feature drift and regime checks
- Signal failure forensics

By R6, every promoted microstructure signal should have: feature version, strategy version, evaluation report, and one notebook that explains why it was kept.

---

## 14. Notebook Placement for Alpha Research

For alpha research, `.ipynb` files are most useful for **exploration, diagnostics, and visual comparison**. Keep them structured so results are easy to revisit.

### Recommended Locations

```text
apps/research/notebooks/
  r1_exploration/
  r2_feature_validation/
  r3_event_replay/
  r4_parameter_sweeps/
  r5_evaluation/
  r6_monitoring/
data/research_journal/
  signals/
  weekly/
  notebook_exports/
```

### Naming Convention

Use a timestamp + signal id + stage, for example:
- `2026-03-01_SIG-012_r1_microstructure-eda.ipynb`
- `2026-03-04_SIG-012_r3_event-replay.ipynb`
- `2026-03-06_SIG-012_r5_scorecard.ipynb`

### What Goes Where

- Keep source notebooks in `apps/research/notebooks/...` (tracked research logic).
- Keep exported charts/tables and final snapshots in `data/research_journal/notebook_exports/`.
- Link every notebook to a journal entry in `data/research_journal/signals/` so decisions are auditable.
- If a notebook becomes a stable pipeline step, migrate the logic into Python modules/CLI and keep the notebook as a thin analysis layer.
- Use the migration workflow in `docs/guides/notebook-to-modules-cli-migration-guide.md` when promoting notebook logic.

---

## Quick Reference — Where to Do What

| "I want to..." | Phase | Step Required | Tool / Module |
|---|---|---|---|
| Explore raw data | 1 | R1 | `DuckDBAnalytics`, `GoldDataset.to_pandas()` |
| Check price distributions | 1 | R1 | DuckDB SQL, pandas `.describe()` |
| Find cross-venue divergences | 1 | R1 | DuckDB JOIN queries |
| Spot time-of-day patterns | 1 | R1 | DuckDB `EXTRACT(HOUR ...)` |
| Compute a signal/feature | 2 | R2 | `FeatureRegistry.compute_all()` |
| Test information coefficient | 2 | R2 | `df[signal].corr(df[future_return])` |
| Build a custom feature | 2 | R2 | Subclass `Feature`, register |
| Test with realistic execution | 3 | R3 | `EventBacktestEngine.run()` |
| Check fees eat the edge? | 3 | R3 | Compare gross vs net PnL |
| Sweep 20 parameter combos | 4 | R4 | `ParameterSweepRunner.run()` |
| Test cross-sectional strategy | 4 | R4 | `VecBacktestEngine.run()` |
| Get Sharpe, Brier, calibration | 5 | R5 | `BacktestEvaluator.evaluate()` |
| Compare 5 signals objectively | 5 | R5 | `evaluator.compare(reports)` |
| Automate full pipeline from CLI | 6 | R6 | `python -m apps.research.main ...` |
| Run everything end-to-end | 6 | R6 | CLI commands chained in bash |
