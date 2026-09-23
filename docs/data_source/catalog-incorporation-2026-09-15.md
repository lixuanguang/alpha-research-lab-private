# Catalog incorporation — 2026-09-15

Historical import record. Counts and checks below describe 2026-09-15, before
later catalog additions; the [source index](README.md) owns the maintained inventory.

## Change and scope

The [source index](README.md) incorporates the supplied multi-asset catalog,
retains the earlier crypto survey, and adds Crypto.com native and vendor-recorded
products. Tables use the requested six columns and order free access before paid
access within each asset/data class. The research owner maintains these source
references with their future consumers.

The result contains **331 rows in 19 tables**: 133 crypto rows in the index and
198 rows across ten other asset/data guides. Counts include vendor bundles and
separate sample/paid routes; they are not counts of disjoint datasets or adapters.
The supplied list broadens coverage but does not enumerate every exchange.

This changes documentation only. No runtime, notebook, P1 specification,
dependency, admission policy or implementation roadmap changes are included.
Reversal restores the previous source index/crypto guide and removes the added
guides and this record; existing acquisition behavior remains available.

## Supplied inputs and incorporation

The three inputs were supplied from the user's local Downloads directory. Their
identities at incorporation were:

| Input | Bytes | SHA-256 |
| --- | ---: | --- |
| `catalog.json` | 131127 | `51b5984d6138d59b396c8564b231cc1f109cbbebd8f04c9a6baf2d097c831ace` |
| `README(20260915-133759).md` | 101645 | `f1f9d7eb2f3813c20cb9d76595b9f9dc97065a365d33f20fe9a5d9122f3c46b0` |
| `market-data-sources.html` | 127941 | `6730ae2592abcd95c5b3b275639e40797b487cf58eaf5cc8d7795504e0600523` |

All 283 JSON rows matched the supplied Markdown table text. Static HTML parsing
matched all 283 source/access/asset/depth rows; HTML scripts were not executed or
copied. The JSON supplied the tabular input, and Markdown tables are now the
maintained reference. The attachment's proposed acceptance checklist, ingestion
fields and operational instructions were not adopted as repository requirements.

Overlap handling preserved all 37 earlier rows, including their evidence text:

- Five spot entries matched the existing Binance individual/aggregate trades,
  Bybit trades, Kraken trades and OKX historical book entries.
- Two Binance futures execution bundles became four rows distinguishing
  individual and aggregate trades for USD-M and COIN-M contracts.
- Two Bybit futures trade entries matched the existing linear/inverse rows.
- One Bybit funding/OI bundle became the existing three funding, linear-OI and
  inverse-OI rows.

These ten supplied entries are represented by 14 earlier rows; the remaining
273 supplied entries and 23 earlier rows were retained. Adding 21 Crypto.com
entries gives `273 + 14 + 23 + 21 = 331`. Generic vendor bundles remain broader
than venue-specific rows and are not deduplicated into a claim of one dataset.

## Primary-document checks and evidence limits

The 21 Crypto.com entries cover four native products for each of spot and
perpetuals, three native derivatives metrics, and ten vendor sample/paid routes.
The [crypto guide](crypto/README.md#cryptocom-access-and-history) records the
meaning of those products and links their primary documents:

- [Crypto.com reference and market data](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/reference-and-market-data),
  its linked trade/book/candle/ticker/valuation references and
  [WebSocket documentation](https://exchange-developer.crypto.com/exchange/v1/docs/api/websocket-single-page/).
- [Tardis Crypto.com coverage and samples](https://docs.tardis.dev/historical-data-details/crypto-com).
- Three supplied rows were independently rechecked against
  [Kraken L3](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/level3),
  [Bitfinex raw books](https://docs.bitfinex.com/reference/ws-public-raw-books) and
  [Coinbase batched L2](https://docs.cdp.coinbase.com/exchange/websocket-feed/channels).

Thus **270 rows remain explicitly marked “Imported; not rechecked.”** Their
prices, depth labels, coverage and links are supplied claims, not new verification
results. The earlier 37 rows retain their previous evidence scope. The new 21
Crypto.com rows and three rechecked rows establish documentation support only.
No newly listed endpoint was exercised, market-data file downloaded, L2/L3 stream
replayed, entitlement tested or provider history audited during incorporation.

The previous [sample evidence](crypto/verification-2026-09-15.md) remains
unchanged. Crypto.com's query-window limit is not a proved retention boundary;
live feeds are not historical archives; sample days are not continuous backfills.
Current instrument schemas do not establish all historical product listings.

## Validation

Started from clean `main`, equal to `origin/main` after `git fetch origin`
(`git rev-list --left-right --count main...origin/main` returned `0 0`), then
created `codex/data-source-catalog-expansion`.

Commands run from the repository root:

- `python3 /private/tmp/verify_data_catalog.py`: passed. The temporary import
  audit counted 19 six-column tables and 331 rows, checked free-before-paid
  ordering and identical-row duplication, accounted for all 283 supplied entries
  and their URLs, and confirmed the 37 earlier entries retained their evidence
  and original links. It counted 21 Crypto.com entries and 270 unrechecked rows.
- `uv run --frozen --no-sync alpha-governance-architecture`: passed for 36
  documents, including every new asset guide. The check covers local Markdown
  links and heading fragments; it skips external URLs.
- `git diff --check`: passed.

Temporary import/audit scripts and the original attachments remain local-only;
the audit command requires those local inputs. The maintained tables and this
record retain the inventory and verification limits. No new runtime or
executable examples were added, so wheel/installed-consumer tests and a fresh
notebook run would not verify these catalog claims and were not rerun.
