# Institutional multi-asset data delivery

**Status: imported candidates, 2026-09-15.** These rows incorporate the supplied
catalog; their provider claims and access terms have not been independently
rechecked in this repository. No adapter or downloaded-data test is implied.
See [evidence labels and depth definitions](../README.md#reading-the-records)
and the [incorporation record](../catalog-incorporation-2026-09-15.md).

Use the six-column tables below to compare products within this asset/data class.
Free access precedes paid access in each table; qualifications remain attached.
Return to the [complete source index](../README.md#asset-class-guides).

## Institutional multi-asset delivery and raw packet archives

These rows cover delivery products spanning several tables above. They are not assertions that every covered venue has L3. A PCAP file preserves the native feed; it cannot add orders absent from that feed.

| Source | Free/Paid | Asset | Depth | Quality of Data | URL/API |
| --- | --- | --- | --- | --- | --- |
| LSEG Tick History — normalized / raw | Paid | Equities / futures / options / FX / fixed income | L1; L2; Trade only — feed-specific | **Imported; not rechecked.** Historical cross-asset archive; specify venue, raw versus normalized schema, corrections and timing. | [Tick History](https://www.lseg.com/en/data-analytics/market-data/data-feeds/tick-history) |
| LSEG Tick History — PCAP | Paid | Covered global exchange / venue instruments | Native L1/L2/L3 — feed-specific | **Imported; not rechecked.** Historical packet captures with capture-clock metadata; obtain precise feed/version and gap reports. | [PCAP product](https://www.lseg.com/en/data-analytics/market-data/data-feeds/tick-history/tick-history-pcap) |
| Pico — historical PCAP | Paid | Covered equities / options / futures venues | Native L1/L2/L3 — feed-specific | **Imported; not rechecked.** Historical native packets; request venue dates, A/B-channel handling and timestamp provenance. | [Historical market data](https://www.pico.net/products/market-services/market-data/historical-market-data/) |
| Databento — PCAP / normalized historical and live | Paid | Covered equities / futures / options venues | L1/L2/L3; Trade only — dataset-specific | **Imported; not rechecked.** Unified delivery with dataset-specific schemas; no universal MBO or spot-FX availability assumption. | [Databento](https://databento.com/) |
| BMLL — Data Feed / Data Lab | Paid | Covered equities / futures / options venues | L1/L2/L3 — dataset-specific | **Imported; not rechecked.** Historical/T+1 normalized data; research delivery is not a real-time production-feed replacement. | [Delivery FAQ](https://www.bmlltech.com/faqs) |
