//! # Order Book
//!
//! A minimal limit-order-book implementation for L2 snapshot reconstruction
//! and market-microstructure research.
//!
//! ## Invariants
//!
//! 1. Best bid < best ask (no crossed book).
//! 2. Bids sorted descending, asks sorted ascending.
//! 3. Prices are finite and strictly positive.
//! 4. Quantities are finite and strictly positive (non-positive removes).
//!
//! ## API surface
//!
//! | Method | Description |
//! |---|---|
//! | `new()` | Empty book |
//! | `apply_snapshot(bids, asks)` | Bulk-load from L2 snapshot |
//! | `apply_update(side, price, size)` | Incremental level update |
//! | `set_level(side, price, qty)` | Alias for `apply_update` |
//! | `remove_level(side, price)` | Remove a level |
//! | `best_bid()` / `best_ask()` | Top of book |
//! | `midprice()` / `microprice()` | Fair-value estimators |
//! | `spread()` | Best ask − best bid |
//! | `top_n_levels(side, n)` | Top-*n* levels from best |
//! | `is_valid()` | Invariant check |
//! | `depth(side)` | Level count |

use std::collections::BTreeMap;

/// A single price level in the order book.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Level {
    pub price: f64,
    pub quantity: f64,
}

/// Side of the book.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Side {
    Bid,
    Ask,
}

/// Ordered-float wrapper for use as BTreeMap key.
/// We assume prices are finite and non-NaN.
#[derive(Debug, Clone, Copy, PartialEq)]
struct OrdF64(f64);

impl Eq for OrdF64 {}

impl PartialOrd for OrdF64 {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for OrdF64 {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.0
            .partial_cmp(&other.0)
            .unwrap_or(std::cmp::Ordering::Equal)
    }
}

fn valid_price(price: f64) -> bool {
    price.is_finite() && price > 0.0
}

fn valid_quantity(qty: f64) -> bool {
    qty.is_finite() && qty > 0.0
}

/// A simple Level-2 order book (price → aggregated quantity).
#[derive(Debug, Clone)]
pub struct OrderBook {
    /// Bids keyed by price (BTreeMap: ascending order; best bid = last).
    bids: BTreeMap<OrdF64, f64>,
    /// Asks keyed by price (BTreeMap: ascending order; best ask = first).
    asks: BTreeMap<OrdF64, f64>,
}

impl OrderBook {
    /// Create an empty order book.
    pub fn new() -> Self {
        Self {
            bids: BTreeMap::new(),
            asks: BTreeMap::new(),
        }
    }

    // ── Snapshot / update ────────────────────────────────────────────────

    /// Bulk-load the book from an L2 snapshot.
    ///
    /// Replaces the entire bid and ask sides.  Each slice is
    /// `&[(price, quantity)]`.  Levels with `quantity <= 0` are silently
    /// ignored.
    pub fn apply_snapshot(&mut self, bids: &[(f64, f64)], asks: &[(f64, f64)]) {
        self.bids.clear();
        self.asks.clear();
        for &(price, qty) in bids {
            if valid_price(price) && valid_quantity(qty) {
                self.bids.insert(OrdF64(price), qty);
            }
        }
        for &(price, qty) in asks {
            if valid_price(price) && valid_quantity(qty) {
                self.asks.insert(OrdF64(price), qty);
            }
        }
    }

    /// Apply an incremental level update.
    ///
    /// If `size` is zero (or negative) the level is **removed**.
    pub fn apply_update(&mut self, side: Side, price: f64, size: f64) {
        self.set_level(side, price, size);
    }

    /// Add, update, or remove a price level.
    ///
    /// If `quantity` is zero the level is removed.
    pub fn set_level(&mut self, side: Side, price: f64, quantity: f64) {
        if !valid_price(price) {
            return;
        }
        let key = OrdF64(price);
        let book = match side {
            Side::Bid => &mut self.bids,
            Side::Ask => &mut self.asks,
        };
        if !valid_quantity(quantity) {
            book.remove(&key);
        } else {
            book.insert(key, quantity);
        }
    }

    /// Remove a price level entirely.
    pub fn remove_level(&mut self, side: Side, price: f64) {
        self.set_level(side, price, 0.0);
    }

    // ── Queries ──────────────────────────────────────────────────────────

    /// Best bid price, or `None` if the bid book is empty.
    pub fn best_bid(&self) -> Option<f64> {
        self.bids.keys().next_back().map(|k| k.0)
    }

    /// Best ask price, or `None` if the ask book is empty.
    pub fn best_ask(&self) -> Option<f64> {
        self.asks.keys().next().map(|k| k.0)
    }

    /// Best bid quantity, or `None` if the bid book is empty.
    pub fn best_bid_qty(&self) -> Option<f64> {
        self.bids.iter().next_back().map(|(_, &q)| q)
    }

    /// Best ask quantity, or `None` if the ask book is empty.
    pub fn best_ask_qty(&self) -> Option<f64> {
        self.asks.iter().next().map(|(_, &q)| q)
    }

    /// Mid price = (best_bid + best_ask) / 2.
    pub fn midprice(&self) -> Option<f64> {
        match (self.best_bid(), self.best_ask()) {
            (Some(b), Some(a)) => Some((b + a) / 2.0),
            _ => None,
        }
    }

    /// Backward-compat alias for [`midprice`].
    pub fn mid_price(&self) -> Option<f64> {
        self.midprice()
    }

    /// Microprice — size-weighted mid:
    ///
    /// ```text
    /// microprice = (best_ask_qty * best_bid + best_bid_qty * best_ask)
    ///            / (best_bid_qty + best_ask_qty)
    /// ```
    ///
    /// Returns `None` if either side is empty.
    pub fn microprice(&self) -> Option<f64> {
        match (
            self.best_bid(),
            self.best_ask(),
            self.best_bid_qty(),
            self.best_ask_qty(),
        ) {
            (Some(bp), Some(ap), Some(bq), Some(aq)) => {
                let total = bq + aq;
                if total == 0.0 {
                    return None;
                }
                Some((aq * bp + bq * ap) / total)
            }
            _ => None,
        }
    }

    /// Spread = best_ask − best_bid.
    pub fn spread(&self) -> Option<f64> {
        match (self.best_bid(), self.best_ask()) {
            (Some(b), Some(a)) => Some(a - b),
            _ => None,
        }
    }

    /// Return the top-*n* levels from best, as `Vec<Level>`.
    ///
    /// - **Bids**: descending by price (best first).
    /// - **Asks**: ascending by price (best first).
    pub fn top_n_levels(&self, side: Side, n: usize) -> Vec<Level> {
        match side {
            Side::Bid => self
                .bids
                .iter()
                .rev()
                .take(n)
                .map(|(k, &q)| Level {
                    price: k.0,
                    quantity: q,
                })
                .collect(),
            Side::Ask => self
                .asks
                .iter()
                .take(n)
                .map(|(k, &q)| Level {
                    price: k.0,
                    quantity: q,
                })
                .collect(),
        }
    }

    // ── Invariant checks ─────────────────────────────────────────────────

    /// Check the fundamental invariant: best_bid < best_ask (no crossed book).
    pub fn is_valid(&self) -> bool {
        match (self.best_bid(), self.best_ask()) {
            (Some(b), Some(a)) => b < a,
            _ => true, // empty or one-sided book is trivially valid
        }
    }

    /// Number of price levels on a given side.
    pub fn depth(&self, side: Side) -> usize {
        match side {
            Side::Bid => self.bids.len(),
            Side::Ask => self.asks.len(),
        }
    }
}

impl Default for OrderBook {
    fn default() -> Self {
        Self::new()
    }
}
