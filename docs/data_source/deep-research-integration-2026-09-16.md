# Deep-research source integration — 2026-09-16

## Change and scope

The [source index](README.md) incorporates the supplied deep-research report and
places its 17 source-selection recommendations in the
[highest-level README](README.md#source-selection-recommendations). The research
owner maintains these references with their eventual consumers. This record
identifies the import and its evidence limits; it is not an admission policy.

All **101 report source entries** are represented by new or existing catalog
rows. The change adds **52 rows** and updates the evidence of **five existing
rows**, producing **383 rows across 19 six-column tables**. Repeated enterprise
vendors are consolidated in the multi-asset guide; access routes, native feeds
and normalized products remain distinguishable. Row counts include overlapping
bundles and the CCXT integration library, not only independent datasets.

The [earlier incorporation record](catalog-incorporation-2026-09-15.md) remains
historical evidence for its 331-row revision. Runtime, notebook, configuration,
P1 specification and roadmap are unchanged. Reversal is a documentation revert
of this integration; it does not change acquisition behavior.

## Input and coverage

The user supplied `deep-research-report.md` from their local Downloads directory.
The report states a 2026-09-15 review date. Its bytes at incorporation were:

| Input | Bytes | SHA-256 |
| --- | ---: | --- |
| `deep-research-report.md` | 53556 | `0bcad08b3fdf240555cf64483645199aed4cfa31a5861ef35056d846823b7bbd` |

| Report section | Source entries | Maintained destination |
| --- | ---: | --- |
| Cryptocurrency spot | 13 | [Spot table](README.md#cryptocurrency--spot) |
| Crypto futures | 9 | [Futures table](README.md#cryptocurrency--perpetuals-and-dated-futures) |
| Crypto options | 7 | [Options table](README.md#cryptocurrency--options), [listed derivatives](listed-derivatives/README.md) |
| Traditional equities | 13 | [Equities](equities/README.md), [enterprise delivery](multi-asset/README.md) |
| Equity derivatives | 11 | [Listed derivatives](listed-derivatives/README.md), [enterprise delivery](multi-asset/README.md) |
| FX / FX spot | 8 | [FX](fx/README.md), [enterprise delivery](multi-asset/README.md) |
| FX derivatives | 6 | [FX](fx/README.md), [listed derivatives](listed-derivatives/README.md), [enterprise delivery](multi-asset/README.md) |
| Fixed income | 8 | [Fixed income](fixed-income/README.md), [enterprise delivery](multi-asset/README.md) |
| Commodities | 10 | [Physical series](commodities/README.md), [listed derivatives](listed-derivatives/README.md), [enterprise delivery](multi-asset/README.md) |
| Macro and economic data | 16 | [Macro](macro/README.md), [dataset marketplace](multi-asset/README.md) |
| **Total** | **101** | |

Existing rows retain their earlier provenance unless explicitly rechecked.
For example, the report's repeated Databento/CME entries map to the existing
asset-specific datasets, while new native CME rows distinguish direct delivery.
LMAX price-level data and disaggregated snapshots, IEX delayed/live feeds and
HIST, and BrokerTec full/conflated products are separate rows.

The report's opaque conversation citation tokens, subjective quality grades,
unverified exact prices and latency claims were not copied. Its source-selection
recommendations were adapted because the user requested them. Its other
checklists and operational instructions do not replace repository requirements.

## Primary-source checks and corrections

Documentation was inspected on 2026-09-15–16; newly checked rows carry the
2026-09-16 incorporation date. These checks establish documented interfaces or
commercial statements, not working acquisition or reconstructed books.

- **Crypto order identity and access:** the earlier verified
  [Kraken L3](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/level3)
  entry is retained despite the report's omission. Current
  [Coinbase authentication documentation](https://docs.cdp.coinbase.com/exchange/websocket-feed/authentication)
  confirms full/level3 authentication. A public protocol is not necessarily an
  unauthenticated feed or a historical archive.
- **IEX:** [DEEP+ and Options DEEP descriptions](https://www.iex.io/products/equities/market-data-connectivity)
  identify order-by-order feeds. The [fee schedule](https://www.iex.io/resources/trading/fee-schedule)
  lists delayed DEEP+ at no exchange fee and real-time DEEP+ at USD 3,500/month;
  delivery can cost extra. The [HIST portal](https://iextrading.com/trading/market-data/)
  did not establish a specific DEEP+ archive file. Published
  [specifications and samples](https://www.iex.io/resources/trading/market-data)
  are separate evidence from a usable Options feed or historical download.
- **CoinAPI:** its [L3 product description](https://www.coinapi.io/datasets/crypto-order-book-l3-data)
  describes source-dependent order IDs and an L2 fallback. Current snapshots and
  live delivery do not establish continuous historical L3 or options-venue
  coverage. Each crypto asset row retains those limits.
- **Native versus normalized derivatives:** [CME MDP 3.0 services](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457219613),
  [Databento MBO](https://databento.com/docs/schemas-and-data-formats/mbo) and
  [GLBX normalization](https://databento.com/docs/venues-and-datasets/glbx-mdp3)
  distinguish order events and event boundaries. The
  [ICE US normalization section](https://databento.com/docs/venues-and-datasets/ifus-impact)
  specifies price-level MBP-10 for options; futures MBO does not confer options
  L3. No selected contract's history or completeness was tested.
- **FX and Treasuries:** [LMAX](https://www.lmax.com/global/market-data-access)
  describes disaggregated snapshots; a full order lifecycle was not established.
  [BrokerTec Chicago](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/649592833)
  distinguishes premium full-order depth from top-ten-order, 50 ms conflated
  delivery. Conflated order records cannot recover every intervening queue event.
- **Consolidated feeds:** [OPRA](https://www.opraplan.com/) supplies quotations
  and last sales. [LSEG Direct](https://www.lseg.com/en/data-analytics/market-data/data-feeds/direct-feeds)
  and [Bloomberg B-PIPE](https://professional.bloomberg.com/products/data/enterprise-catalog/real-time-data-feed/)
  document different delivery products; source depth and measured performance
  remain separate questions.
- **Macro history:** [ALFRED parameters](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html)
  default to today and express date-level information sets. The
  [Macrobond Web API](https://help.macrobond.com/apis-feeds-connectors/the-macrobond-data-web-api-feed/)
  requires separate licensing; vintage coverage needs series-level checking.
  [Haver](https://www.haver.com/) documents archives, forecasts and REST delivery;
  advertised release speed is not a repository measurement.

Of the 52 additions, 18 carry documentation checks and 34 are explicitly
**Report candidate; not rechecked**. Five earlier imports are now documented:
Coinbase full/level3, Databento ICE US options, ALFRED, Macrobond and Haver.
The remaining 265 earlier imports retain **Imported; not rechecked**. Thus 299
catalog rows still carry an unverified-import label; the other 84 retain their
individual documented, observed or integrated evidence scope. No newly listed
data API, entitlement, download, live stream or replay was exercised here.

## Validation

Started from clean commit `26c52e3` on
`codex/data-source-catalog-expansion`, preserving the preceding catalog change
as a separate commit. Commands run from the repository root:

- `python3 /private/tmp/verify_source_report.py`: passed. The temporary audit
  matched the supplied report identity and all 101 source-entry mappings;
  counted 383 rows in 19 tables, 52 additions, five updated earlier rows and
  17 recommendations; checked index counts, duplicate complete rows,
  free-before-conditional/paid ordering and evidence-label counts. It compared
  earlier rows and historical evidence against `26c52e3`.
- `uv run --frozen --no-sync alpha-governance-architecture`: passed for 37
  documents. This covers local Markdown links and heading fragments, including
  the new recommendation links. External URLs are outside this check's scope.
- `git diff --check`: passed.
- `shasum -a 256 docs/research/p1-baseline.md`: unchanged at
  `7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.

The input report and temporary import/audit files remain local-only; the hash
identifies the supplied bytes but does not make them retrievable from Git.
Maintained Markdown contains the integrated inventory and recommendations.
Only source-catalog Markdown changed; wheel package source and executable
examples are unchanged. Runtime tests, wheel/installed-consumer verification
and notebook execution were not rerun; previous acquisition evidence is unchanged.
