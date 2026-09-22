# Provider requests for the frozen BTCUSDT sample

Prepared 2026-09-23 Asia/Singapore. **Archived, unsent drafts; proposed outreach
withdrawn.** The founder has clarified that Binance and Tardis are deprioritised.
These requests are not requirements or active next steps. Neither has been sent.
These requests disclose public source identifiers and local validation counts, not
the repository, strategy, private payloads or credentials. The supporting
[investigation](provider-records.md) records the public evidence already checked.

## Binance public-data maintainers

Suggested route: the official
[binance-public-data issue tracker](https://github.com/binance/binance-public-data/issues),
which the repository's README identifies for data questions. If the user prefers a
private channel, use their Binance support account and request routing to the spot
market-data/archive team. A GitHub issue would be public.

**Subject:** Historical evidence request: BTCUSDT spot, 2024-06-01 00:00–01:00 UTC

We are validating one hour of historical spot data for a reproducible research
backtest. Could the Binance spot market-data/archive team provide or point us to
the records below, or explicitly confirm which records cannot be supplied?

Scope:

- Binance spot BTCUSDT; 2024-06-01 00:00:00 inclusive to 01:00:00 exclusive, UTC.
- Public file:
  [BTCUSDT-trades-2024-06-01.zip](https://data.binance.vision/data/spot/daily/trades/BTCUSDT/BTCUSDT-trades-2024-06-01.zip).
- Retained ZIP SHA-256:
  `c9c333f58fe33faaa0a34d526c61b13f5648b908c4ad341dd6556e15c5bcc46a`.
- Our selection contains 27,480 rows, with observed trade IDs 3620989757 through
  3621017236 inclusive. These are observations to reconcile, not an assertion that
  the source is complete.

1. **Could the pair accept spot orders throughout the hour?** Please provide dated
   instrument/status records, including any halt, break or resumption, with effective
   times and when that information was published or available through the API.
   Please include base/quote units and the applicable trading rules/filters. A
   retrospective statement is useful if it identifies the historical records and
   information-availability times on which it is based.
2. **Does the file contain every applicable trade in the hour?** Please provide an
   interval-specific export/reconciliation record, expected count and boundary IDs,
   or an equivalent documented assurance. Identify any omitted, late, cancelled or
   otherwise excluded trades and any exchange/feed/export incident affecting the
   interval. Please distinguish exchange-level completeness from completeness of
   the public file relative to a feed that might itself omit events.
3. **Were any values changed after their first publication?** Please supply original
   records and every applicable revision, cancellation, insertion or archive
   replacement, with old/new values and publication/availability times. If none
   occurred, please explicitly confirm the scope and UTC cutoff through which that
   statement is complete. Include trade ID, event time, price, quantity, quote
   quantity, buyer-maker flag and best-match flag, and explain when archive-only
   fields became available. We need first-publication facts as well as any later
   ZIP replacement history.

The README's update table lists two 2022 bundles, while the updates directory also
contains `2022-10-04_aggregate_trade_updates.csv`. Please clarify where the complete
applicable update history is maintained; absence from that table alone is not enough
for our review.

Please identify the supporting record references, their issue/publication times,
applicable limitations and your team's authority to confirm the facts. A ticket
reply with attached records or a scoped attestation is acceptable for review; no
special software integration is required. If access has a cost, please describe it
before any order or subscription is started. Thank you.

## Tardis recording team

Suggested recipient: **help@tardis.dev**, published in the footer of the
[official Tardis site](https://tardis.dev/). The same site offers a contact form and
lists contact@tardis.dev. Use one route to avoid duplicate requests.

**Subject:** Historical recording evidence: Binance spot BTCUSDT, 2024-06-01 00:00–01:00 UTC

We are validating a single historical hour for a reproducible research backtest.
We retrieved your public first-of-month raw sample for exchange `binance`, channel
`trade`, symbol `btcusdt`, on 2024-06-01, including the 01:00 boundary. Could your
recording team supply or identify the following records, or say which are unavailable?

1. **Recording health for the whole hour.** For 00:00:00 inclusive to 01:00:00
   exclusive UTC, please supply recorder/subscription health, reconnect/restart,
   buffering/drop and export-completeness records. Our retained slices contain no
   disconnect marker, and the incident inventory has no overlapping report. Can you
   positively confirm complete capture for this instrument/channel and period?
   Please distinguish your recorder's coverage from any Binance upstream omissions
   you cannot rule out, and explain how expected counts or boundary IDs are checked.
2. **Original messages, timing and later changes.** Please confirm whether the raw
   replay is the originally received feed, how local receive timestamps are defined,
   and the known clock accuracy/limitations for that recorder. Supply any applicable
   replacement, correction or backfill history, with original/revised payloads and
   publication/availability times. If there were none, please state the scope and
   UTC cutoff through which that statement is complete. Distinguish changes to your
   stored feed from corrections Binance may have made outside that feed.
3. **Historical instrument/status records.** Do you retain a BTCUSDT reference/status
   snapshot and change history covering this exact hour, including when each fact
   was observed or available? We understand that current `active` metadata and
   best-effort metadata changes do not establish uninterrupted historical eligibility.
   If these records are not available, please say so rather than supplying only a
   current metadata response.

For reconciliation, the Binance daily individual-trade ZIP we retained has SHA-256
`c9c333f58fe33faaa0a34d526c61b13f5648b908c4ad341dd6556e15c5bcc46a`.
Our selected hour has 27,480 trades, IDs 3620989757–3621017236; all matched your saved
sample on ID, event time, price, quantity and buyer-maker flag. That comparison does
not independently verify Binance archive-only fields or unobserved omissions.
Three selected trades were received at or after 01:00, with the latest local receive
timestamp 01:00:00.005781 UTC, so the recording evidence must include the boundary.

Please identify supporting files or record references, their issue/publication
times, the scope of any assurance and any facts you cannot certify. A scoped support
reply with original attachments is suitable for review. Please describe any cost or
access requirement before starting an order or subscription. Thank you.
