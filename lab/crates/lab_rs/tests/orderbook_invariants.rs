//! Invariant and unit tests for the L2 OrderBook.
//!
//! Spec-required tests:
//!   - test_apply_snapshot_sorted
//!   - test_apply_update_remove_level_when_size_zero
//!   - test_no_negative_sizes
//!   - test_no_crossed_book

use lab_rs::orderbook::{Level, OrderBook, Side};

// ══════════════════════════════════════════════════════════════════════════════
// §7.2 — Spec-required invariant tests
// ══════════════════════════════════════════════════════════════════════════════

#[test]
fn test_apply_snapshot_sorted() {
    let mut book = OrderBook::new();

    // Feed bids and asks in *random* order
    let bids = vec![(98.0, 5.0), (100.0, 10.0), (99.0, 7.0)];
    let asks = vec![(103.0, 3.0), (101.0, 8.0), (102.0, 4.0)];
    book.apply_snapshot(&bids, &asks);

    // Best bid must be the *highest* bid price
    assert_eq!(book.best_bid(), Some(100.0));
    // Best ask must be the *lowest* ask price
    assert_eq!(book.best_ask(), Some(101.0));

    // top_n_levels for bids: descending order (best first)
    let top_bids = book.top_n_levels(Side::Bid, 3);
    assert_eq!(top_bids.len(), 3);
    assert_eq!(top_bids[0].price, 100.0);
    assert_eq!(top_bids[1].price, 99.0);
    assert_eq!(top_bids[2].price, 98.0);

    // top_n_levels for asks: ascending order (best first)
    let top_asks = book.top_n_levels(Side::Ask, 3);
    assert_eq!(top_asks.len(), 3);
    assert_eq!(top_asks[0].price, 101.0);
    assert_eq!(top_asks[1].price, 102.0);
    assert_eq!(top_asks[2].price, 103.0);

    assert!(book.is_valid());
}

#[test]
fn test_apply_update_remove_level_when_size_zero() {
    let mut book = OrderBook::new();
    book.apply_snapshot(&[(99.0, 5.0), (100.0, 10.0)], &[(101.0, 8.0), (102.0, 4.0)]);
    assert_eq!(book.depth(Side::Bid), 2);

    // apply_update with size=0 should remove the level
    book.apply_update(Side::Bid, 100.0, 0.0);
    assert_eq!(book.depth(Side::Bid), 1);
    assert_eq!(book.best_bid(), Some(99.0));

    // Same for asks
    book.apply_update(Side::Ask, 101.0, 0.0);
    assert_eq!(book.depth(Side::Ask), 1);
    assert_eq!(book.best_ask(), Some(102.0));
}

#[test]
fn test_no_negative_sizes() {
    let mut book = OrderBook::new();

    // Negative size in snapshot should be silently ignored
    book.apply_snapshot(
        &[(100.0, -5.0), (99.0, 3.0)],
        &[(101.0, -1.0), (102.0, 2.0)],
    );
    assert_eq!(book.depth(Side::Bid), 1); // only 99.0 survived
    assert_eq!(book.best_bid(), Some(99.0));
    assert_eq!(book.depth(Side::Ask), 1); // only 102.0 survived
    assert_eq!(book.best_ask(), Some(102.0));

    // Negative size in apply_update should remove the level
    book.apply_update(Side::Bid, 99.0, -10.0);
    assert_eq!(book.depth(Side::Bid), 0);

    // Negative size via set_level should also remove
    book.set_level(Side::Ask, 102.0, -1.0);
    assert_eq!(book.depth(Side::Ask), 0);
}

#[test]
fn test_no_crossed_book() {
    let mut book = OrderBook::new();

    // Valid book: best bid < best ask
    book.apply_snapshot(&[(100.0, 10.0)], &[(101.0, 5.0)]);
    assert!(book.is_valid());

    // Crossed book: best bid ≥ best ask
    let mut crossed = OrderBook::new();
    crossed.apply_snapshot(&[(102.0, 10.0)], &[(101.0, 5.0)]);
    assert!(!crossed.is_valid(), "Crossed book must fail is_valid()");

    // Exact touch: best bid == best ask — also invalid (not strictly less)
    let mut touched = OrderBook::new();
    touched.apply_snapshot(&[(101.0, 10.0)], &[(101.0, 5.0)]);
    assert!(
        !touched.is_valid(),
        "Locked book (bid==ask) must fail is_valid()"
    );
}

// ══════════════════════════════════════════════════════════════════════════════
// Additional unit tests
// ══════════════════════════════════════════════════════════════════════════════

#[test]
fn empty_book_is_valid() {
    let book = OrderBook::new();
    assert!(book.is_valid());
    assert_eq!(book.best_bid(), None);
    assert_eq!(book.best_ask(), None);
    assert_eq!(book.midprice(), None);
    assert_eq!(book.microprice(), None);
    assert_eq!(book.spread(), None);
}

#[test]
fn single_bid_ask_valid() {
    let mut book = OrderBook::new();
    book.set_level(Side::Bid, 100.0, 10.0);
    book.set_level(Side::Ask, 101.0, 5.0);
    assert!(book.is_valid());
    assert_eq!(book.best_bid(), Some(100.0));
    assert_eq!(book.best_ask(), Some(101.0));
    assert_eq!(book.spread(), Some(1.0));
    assert_eq!(book.midprice(), Some(100.5));
}

#[test]
fn best_bid_is_highest() {
    let mut book = OrderBook::new();
    book.set_level(Side::Bid, 99.0, 1.0);
    book.set_level(Side::Bid, 100.0, 2.0);
    book.set_level(Side::Bid, 98.0, 3.0);
    assert_eq!(book.best_bid(), Some(100.0));
}

#[test]
fn best_ask_is_lowest() {
    let mut book = OrderBook::new();
    book.set_level(Side::Ask, 103.0, 1.0);
    book.set_level(Side::Ask, 101.0, 2.0);
    book.set_level(Side::Ask, 102.0, 3.0);
    assert_eq!(book.best_ask(), Some(101.0));
}

#[test]
fn zero_quantity_removes_level() {
    let mut book = OrderBook::new();
    book.set_level(Side::Bid, 100.0, 10.0);
    assert_eq!(book.depth(Side::Bid), 1);
    book.set_level(Side::Bid, 100.0, 0.0);
    assert_eq!(book.depth(Side::Bid), 0);
    assert_eq!(book.best_bid(), None);
}

#[test]
fn remove_level_works() {
    let mut book = OrderBook::new();
    book.set_level(Side::Ask, 101.0, 5.0);
    book.set_level(Side::Ask, 102.0, 3.0);
    assert_eq!(book.depth(Side::Ask), 2);
    book.remove_level(Side::Ask, 101.0);
    assert_eq!(book.depth(Side::Ask), 1);
    assert_eq!(book.best_ask(), Some(102.0));
}

#[test]
fn update_quantity_in_place() {
    let mut book = OrderBook::new();
    book.set_level(Side::Bid, 100.0, 10.0);
    book.set_level(Side::Bid, 100.0, 20.0);
    assert_eq!(book.depth(Side::Bid), 1);
}

#[test]
fn depth_counts_levels() {
    let mut book = OrderBook::new();
    for i in 0..5 {
        book.set_level(Side::Bid, 100.0 - i as f64, 1.0);
        book.set_level(Side::Ask, 101.0 + i as f64, 1.0);
    }
    assert_eq!(book.depth(Side::Bid), 5);
    assert_eq!(book.depth(Side::Ask), 5);
}

// ── Snapshot ────────────────────────────────────────────────────────────────

#[test]
fn snapshot_replaces_previous_state() {
    let mut book = OrderBook::new();
    book.apply_snapshot(&[(100.0, 10.0)], &[(101.0, 5.0)]);
    assert_eq!(book.depth(Side::Bid), 1);

    // Second snapshot should fully replace the first
    book.apply_snapshot(&[(98.0, 1.0), (99.0, 2.0)], &[(102.0, 3.0)]);
    assert_eq!(book.depth(Side::Bid), 2);
    assert_eq!(book.best_bid(), Some(99.0));
    assert_eq!(book.best_ask(), Some(102.0));
}

// ── Microprice ──────────────────────────────────────────────────────────────

#[test]
fn microprice_size_weighted() {
    let mut book = OrderBook::new();
    // bid 100 @ qty 10, ask 102 @ qty 30
    book.apply_snapshot(&[(100.0, 10.0)], &[(102.0, 30.0)]);

    // microprice = (30*100 + 10*102) / (10+30) = (3000 + 1020) / 40 = 100.5
    let mp = book.microprice().unwrap();
    assert!((mp - 100.5).abs() < 1e-9);

    // Contrast with midprice = (100 + 102)/2 = 101
    assert!((book.midprice().unwrap() - 101.0).abs() < 1e-9);

    // Microprice should be closer to the side with *less* quantity
    // (ask qty > bid qty → microprice pulled toward bid)
    assert!(mp < book.midprice().unwrap());
}

#[test]
fn microprice_equal_sizes_equals_midprice() {
    let mut book = OrderBook::new();
    book.apply_snapshot(&[(100.0, 5.0)], &[(102.0, 5.0)]);
    let mid = book.midprice().unwrap();
    let micro = book.microprice().unwrap();
    assert!(
        (mid - micro).abs() < 1e-12,
        "Equal sizes → microprice == midprice"
    );
}

// ── top_n_levels ────────────────────────────────────────────────────────────

#[test]
fn top_n_levels_clamped() {
    let mut book = OrderBook::new();
    book.apply_snapshot(&[(99.0, 1.0), (100.0, 2.0)], &[(101.0, 3.0)]);
    // Ask for more levels than exist
    let bids = book.top_n_levels(Side::Bid, 10);
    assert_eq!(bids.len(), 2);
    assert_eq!(
        bids[0],
        Level {
            price: 100.0,
            quantity: 2.0
        }
    );
    assert_eq!(
        bids[1],
        Level {
            price: 99.0,
            quantity: 1.0
        }
    );
}

// ── apply_update incremental ────────────────────────────────────────────────

#[test]
fn apply_update_adds_new_level() {
    let mut book = OrderBook::new();
    book.apply_snapshot(&[(100.0, 10.0)], &[(101.0, 5.0)]);

    // Add a new bid level
    book.apply_update(Side::Bid, 99.5, 3.0);
    assert_eq!(book.depth(Side::Bid), 2);
    assert_eq!(book.best_bid(), Some(100.0)); // unchanged
}

#[test]
fn apply_update_modifies_existing_level() {
    let mut book = OrderBook::new();
    book.apply_snapshot(&[(100.0, 10.0)], &[(101.0, 5.0)]);

    // Update existing bid quantity
    book.apply_update(Side::Bid, 100.0, 20.0);
    assert_eq!(book.depth(Side::Bid), 1); // still one level
    let top = book.top_n_levels(Side::Bid, 1);
    assert_eq!(top[0].quantity, 20.0);
}
