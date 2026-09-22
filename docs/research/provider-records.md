# Frozen sample: provider records investigation

Owner: repository founder. Investigated 2026-09-23 Asia/Singapore
(2026-09-22 UTC). Status: public-source investigation completed; follow-up deferred
and proposed outreach withdrawn after the founder clarified that Binance and
Tardis are deprioritised. Actual-source qualification remains unaccepted.

The existing software can admit reviewed evidence, but the additional public records
obtained in this investigation do **not** close the three factual gaps for Binance
spot BTCUSDT, **2024-06-01 [00:00, 01:00) UTC**. No historical eligibility,
completeness guarantee or correction availability was inferred to make admission pass.
The [frozen acceptance criteria](p1-baseline.md#qr-handoff-to-finish-mr-8)
and [admission implementation](source-qualification.md) remain unchanged.

## What was obtained and what it establishes

| Record or source checked | Result | Remaining limitation |
| --- | --- | --- |
| [Binance public archive README](https://github.com/binance/binance-public-data#updates), previously retained | Describes archive replacement checksums and next-day daily publication. Its update table contains two 2022 entries. | Archive publication is later than the simulated hour. This does not establish original intrahour availability or every applicable trade correction. |
| [Binance updates directory](https://github.com/binance/binance-public-data/tree/master/updates), newly retained through the GitHub API | Contains **three** files: the two listed ZIPs plus `2022-10-04_aggregate_trade_updates.csv`. | The directory includes an update absent from the README table. Neither inventory supplies a correction history for this exact 2024 individual-trade sample. |
| [Additional Binance correction record](https://github.com/binance/binance-public-data/blob/master/updates/2022-10-04_aggregate_trade_updates.csv), newly retained | **132** old/new checksum rows for aggregate-trade files in December 2017, January 2018 and March 2018. No BTCUSDT file or selected archive appears. | This is an actual publisher correction record, but it covers different data and dates. It cannot establish that the selected trades were never corrected. |
| [Tardis instrument metadata contract](https://docs.tardis.dev/api/instruments-metadata-api), reviewed against the retained document | `active` describes current exchange status; historical changes other than contract multipliers are best effort. | An API subscription by itself does not supply an exhaustive BTCUSDT status history or historical information-availability clocks. |
| [Tardis recording contract](https://docs.tardis.dev/faq/data), reviewed against the retained document | Raw exchange payloads are preserved, but gaps are possible and complete capture is not guaranteed. | The already saved tape and incident list do not certify full-interval completeness or exclude exchange-side omissions. |
| [Kaiko versioning contract](https://docs.kaiko.com/rest-api/general/getting-started/data-versioning), newly retained | Describes versioned datasets and explicit version selection. | This is a product-level contract, not records for the frozen Binance archive. No applicable historical export, status record, availability inventory or support confirmation was obtained. |

A search also located an indexed Binance H1 2024 uptime-report reference. Fetching
the official blog index returned **HTTP 202 with an empty body**. It is retained as
an unsuccessful retrieval, not admitted as an uptime record. The readable H2 2024
report covers the wrong half-year and was not substituted. Even service uptime
alone would not establish that every selected trade was captured.

The new evidence strengthens the explanation of the gap; it does not qualify the
source. The prior observed agreement of all **27,480** selected trades, with no
observed ID gaps or disconnect markers, remains useful corroboration within its
documented field and capture limits.

## Retained evidence and verification

Local response bodies and receipts are under
`data/notebooks/provider-records/2026-09-23/`, ignored by Git. Each receipt preserves
the URL, HTTP status, headers, actual UTC request/receipt times, byte count and
SHA-256. The four initial sandbox DNS failures remain in `public/`; the permitted
retry is in `public-retry/`; the additional correction file is in
`correction-record/`. Empty responses are never treated as documentary evidence.

| Retained body | Bytes | SHA-256 |
| --- | ---: | --- |
| `public-retry/binance-archive-updates.json` | 3,116 | `b8febaf11a36ac7a0ac119e4be6fe4c496dceac47766e2e30c615531cf1f1cee` |
| `correction-record/binance-2022-10-04-aggregate-updates.csv` | 28,558 | `7d2ff0915c472b4860d034daa02ee2cb30a764c428bd397cd23b325a5256ce90` |
| `public-retry/kaiko-data-versioning.md` | 2,844 | `707d0c61d98d908fd0d95a3e948997aabb21501f832f3b8a387ca5f78ef79131` |
| `public-retry/tardis-contact.html` | 377,428 | `b007d0fa9762eff19fe9eacdb30592da440d82f39756f40215ac090606f2be62` |

All retained response lengths and SHA-256 digests were rechecked. The additional
CSV also matches Git blob identity
`1877919385993a77614941aea355a575e6177755` from the independently retained directory
response. Its 132 rows were parsed and checked for applicability. Integrity checks
establish which bytes were inspected; they do not certify the provider's claims.
`investigation.json` records the outcome and response inventory.

Earlier archive/capture evidence and the completed notebook run remain at
`data/notebooks/p1-evidence/5ce14416-8b1c-41f2-83ee-0bb83a365729/`.
They were not replaced or rerun because none of the new records changes admission.
This continuation changes documentation only; no runtime or test result is claimed
for a newly qualified real source.

Validation: the architecture link check passed for 36 documents, the configured
secret scan passed for 475 governed paths, and `git diff --check` passed. The new
drafts were also inspected for private payloads and credentials. Runtime tests were
not repeated for this documentation and evidence-only continuation.

## Deferred follow-up

The founder's 2026-09-23 clarification supersedes the earlier recommendation to
contact these providers. The drafts below are retained as investigation history,
not required next actions. Preserving the frozen P1 case does not require pursuing
its acceptance now. Current work proceeds independently through the existing OKX
and Bitfinex workflows, with their own documented assumptions and limitations.

The [prepared provider requests](provider-requests.md) identify the exact hour,
archive digest, observed trade IDs and the records each provider is being asked to
supply. Binance owns the original exchange status, export and correction facts;
Tardis can address its recording health, capture clocks and any separately retained
historical reference information. Either can explicitly identify facts it cannot
certify. A reply containing only current status, matching checksums or an empty
incident list will leave the corresponding gap open.

No request has been sent. No provider account was accessed, subscription purchased,
alternative source substituted or acceptance criterion amended. Public documentation
does not establish that buying a plan would supply the missing records.

Only if this case is explicitly resumed and suitable records arrive, retain their
original bytes and attachments with source,
receipt and publication clocks. Review the precise instrument/window, supported
claims and correction-history cutoff, including whether the records establish
historical availability rather than only present-day knowledge. Only then encode
the reviewed `DatasetInput` and use the existing notebook admission path. P1 still
requires successful actual-source admission, both unchanged costed runs and their
accounting and restart checks. If a provider cannot supply a required fact, record
that refusal; changing the frozen acceptance standard requires a separate founder
decision.

The subsequent [MR8 scope amendment](saved-baseline-acceptance.md) authorizes a
separate saved-OKX simulation target. It does not accept P1 or reopen this deferred
investigation; the original records and no-outreach decision remain preserved.
