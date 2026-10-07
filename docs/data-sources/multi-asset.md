# Institutional multi-asset data delivery

**Status: source catalog updated 2026-09-16.** Rows distinguish earlier imports,
report candidates and primary-document checks. Access, depth and history remain
unverified unless the row states its evidence. See the
[evidence labels](overview.md#reading-the-records).

Tables order free access before conditional and paid routes.
Return to the [complete source index](overview.md#asset-class-guides).

## Institutional multi-asset delivery and raw packet archives

These rows cover delivery products spanning several tables above. They are not assertions that every covered venue has L3. A PCAP file preserves the native feed; it cannot add orders absent from that feed.

| Source | Free/Paid | Asset | Depth | Quality of Data | URL/API |
| --- | --- | --- | --- | --- | --- |
| Nasdaq Data Link — dataset marketplace / API | Free datasets / paid products; dataset-specific | Equities, macro, fundamentals and other publisher datasets | N/A / dataset-specific | **Report candidate; not rechecked.** Mixed publisher catalog. Select the named dataset, source and rights; a common API does not establish L3 or a release-time guarantee. | [API documentation](https://docs.data.nasdaq.com/) |
| LSEG Tick History — normalized / raw | Paid | Equities / futures / options / FX / fixed income | L1; L2; Trade only — feed-specific | **Imported; not rechecked.** Historical cross-asset archive; specify venue, raw versus normalized schema, corrections and timing. | [Tick History](https://www.lseg.com/en/data-analytics/market-data/data-feeds/tick-history) |
| LSEG Tick History — PCAP | Paid | Covered global exchange / venue instruments | Native L1/L2/L3 — feed-specific | **Imported; not rechecked.** Historical packet captures with capture-clock metadata; obtain precise feed/version and gap reports. | [PCAP product](https://www.lseg.com/en/data-analytics/market-data/data-feeds/tick-history/tick-history-pcap) |
| Pico — historical PCAP | Paid | Covered equities / options / futures venues | Native L1/L2/L3 — feed-specific | **Imported; not rechecked.** Historical native packets; request venue dates, A/B-channel handling and timestamp provenance. | [Historical market data](https://www.pico.net/products/market-services/market-data/historical-market-data/) |
| Databento — PCAP / normalized historical and live | Paid | Covered equities / futures / options venues | L1/L2/L3; Trade only — dataset-specific | **Imported; not rechecked.** Unified delivery with dataset-specific schemas; no universal MBO or spot-FX availability assumption. | [Databento](https://databento.com/) |
| BMLL — Data Feed / Data Lab | Paid | Covered equities / futures / options venues | L1/L2/L3 — dataset-specific | **Imported; not rechecked.** Historical/T+1 normalized data; research delivery is not a real-time production-feed replacement. | [Delivery FAQ](https://www.bmlltech.com/faqs) |
| LSEG — Real-Time consolidated feeds | Paid enterprise | Equities, derivatives, FX, fixed income and commodities | L1/L2 — source-dependent | **Report candidate; not rechecked.** Report identifies broad real-time distribution, including contributed/OTC prices. Distinct from native order feeds and Tick History. | [Data feeds](https://www.lseg.com/en/data-analytics/market-data/data-feeds) |
| LSEG — Real-Time Direct | Paid enterprise; exchange fees separate | Exchange-covered equities / derivatives / other markets | Native depth — source-dependent | **Documented 2026-09-16.** Managed direct exchange feeds with normalization. Exact depth and licensing are venue-specific; no measured latency or completeness evidence here. | [Direct service](https://www.lseg.com/en/data-analytics/market-data/data-feeds/direct-feeds) |
| Bloomberg — B-PIPE market-data feed | Paid enterprise | Equities, derivatives, FX, fixed income and commodities | L1/L2 — source-dependent | **Documented 2026-09-16.** Consolidated, normalized real-time distribution is documented. Specific source depth, entitlement and delivery performance remain untested. | [B-PIPE](https://professional.bloomberg.com/products/data/enterprise-catalog/real-time-data-feed/) |
| ICE — Consolidated Feed | Paid enterprise | Equities, derivatives, FX, fixed income and commodities | Source-dependent quotes / trades / depth | **Report candidate; not rechecked.** Broad enterprise distribution candidate; specify underlying feed, timing and depth. No universal L3 guarantee. | [Feed fact sheet](https://www.ice.com/publicdocs/ICE_Consolidated_Feed_FactSheet.pdf) |
