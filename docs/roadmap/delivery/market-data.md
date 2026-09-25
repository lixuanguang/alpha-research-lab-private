# MR01 delivery and acceptance

[Roadmap and delivery dependencies](../README.md#delivery-order-and-dependencies).

Status: **complete for the declared read-only data/reference scope**, 2026-09-23.
Owner: quant development. This record concerns the current infrastructure MR01,
not historical deliveries or any QR research milestone.

Delivered through the existing owners and installed applications:

- OKX/Bitfinex public spot trade backfill and bounded recent-trade polling,
  exact native bytes/units/IDs, checked source-specific pagination, retained
  pending receipts and restart without refetching acknowledged input.
- Source-observed, content-versioned venue rules with valid/knowledge-time
  resolution, explicit corrections and unknown history. Complete rules feed
  the existing spot order-grid boundary; incomplete rules refuse admission.
- Four independent universes, saved in public jobs and optional scoped native
  captures. Data/source/reference/calendar requirements fail before work;
  current readers enforce the selected collection/research/strategy boundaries.
- Public-trade publication through the existing `RawStore` / `SnapshotStore`,
  catalog discovery, pinned CLI reads, cutoff revision selection, typed replay
  cursors and causal named trade/book/non-book-reference assembly. Historical
  Binance/Tardis identities, native book formats and selected integrations remain.
- A configuration-only OKX ETH onboarding case and an installed reference
  consumer which creates pinned selections from completed inputs without a
  notebook-created manifest. Negative fixtures reject unsupported products and
  non-continuous calendars; existing C02 tests retain non-24/7 calendar evidence.

Dependencies are capability slices, not completed later milestones. MR16 owns
the shared typed admission/interface slice used here; broader package isolation,
registry enforcement and engineering migration remain MR16/MR06 work. MR08 owns
the reference-driven order-grid/minimum-size admission slice; independent account
risk, reservations and reconciliation remain open. Named input assembly belongs
to MR01; generalized features/models, study APIs and runtime promotion still
belong to MR02/MR03/MR05. G1 as a whole and G2–G5 are not accepted by this delivery.

The [data guide](../../../src/market_data/README.md#public-spot-data-plane) owns commands
and recovery. The [reference contract](../../data/contracts.md#versioned-venue-specifications-and-scoped-universes)
owns temporal facts and the four universes. Quant development's
[installed consumer](../../../tests/integration/consumers/datasets/public_data.py)
qualifies the integrated data boundary; it is not an alpha or execution workload.

Observed external evidence is retained locally under ignored `logs/mr01/`:

| Boundary | Observed evidence | Limit |
| --- | --- | --- |
| Both public reference endpoints | Exact OKX instrument and Bitfinex exchange-pair/configuration responses | Current observations only; no authenticated historical specification history |
| Both public historical-trade adapters | Maintained 2026-09-23 12:00:00–12:00:10 UTC job; five responses and 46,266 raw bytes; `public-backfill/acquisition.json` | Scoped endpoint responses, not an exhaustive venue tape or original availability |
| Both recent-trade polling adapters | Configured 45-second wall interval; eight responses and 71,116 raw bytes; `public-poll/acquisition.json` | Sampled REST observations; polling gaps/completeness remain unknown |
| OKX native L2 capture | 189 frames, one snapshot, 187 updates, 800 visible levels; no observed gaps; saved replay parity | 20-second `books` sample, 400 levels/side; no full-depth or fill-fidelity claim |
| Bitfinex native R0 capture | 1,104 frames, one snapshot, 1,099 updates, 50 visible orders; no observed gaps; saved replay parity | 20-second `len=25` sample; no event timestamp or matching-engine completeness claim |
| Integrated source reopening | `integrated-public-data-wheel/` publishes/reopens public trades, both books and venue specifications as four named inputs; 328 selected trades, 388 replayed observations and 60 repeated observations | Final wheel installed outside the checkout; book admission selects at most 1,000 raw positions and preserves unselected-prefix limits |

Raw capture IDs and response digests remain in their original manifests; no
historical hashes were rewritten. Failed editable invocation and the subsequent
non-editable command are retained separately. Live source bytes need no repeat
download when only reference validation, query projection or documentation changes;
final readers must re-decode and verify those retained bytes. These local-only
records are not distributed with Git; the commands and reference consumer reproduce
the workflow with new observations, not the same market sample.

Software evidence covers lost publication acknowledgement, pending-byte recovery,
backwards receipt/durable-clock rejection without invented timestamps,
malformed responses, changed resume configuration, source corruption, duplicate and
late versions, independent exact amounts, reference corrections/freshness, scoped
book exclusion, incompatible capabilities, configuration-only onboarding and an
isolated installed CLI/assembly/replay consumer. The complete local `make check`
gate covers source/style/typing/native contracts, ownership, dependencies/security,
unit/integration tests and an isolated wheel installation. The final command is:

```sh
TMPDIR=/private/tmp PYTEST_ADDOPTS='--basetemp=/private/tmp/ar-mr01-check' \
  make check > logs/mr01/make-check-final.log 2>&1
```

`make-check-final.log` retains the final results and installed-wheel location;
`wheel-sha256.txt` pins the copied wheel under `logs/mr01/wheels/`.
`integrated-public-data-wheel-command.log` records the final wheel's reopening of
the retained venue inputs. The earlier full gate remains in `make-check.log`;
its 1,272 passing tests preceded the final clock-regression test. Earlier focused
results and source attempts are retained, not replaced by the final run. The
existing QuantLib source-to-wheel restriction still blocks artifact release
outside its admitted development use; resolving it belongs to MR06.

Current source limitations are explicit acceptance boundaries, not empirical or
operating qualification. Current metadata cannot establish earlier tick/lot rules;
Bitfinex's selected public response does not supply fixed tick/quantity increments,
so order-rule admission remains closed there. There is no Bitfinex book backfill,
historical receipt reconstruction, continuous trade WebSocket service or proven
complete tape in this support declaration. Continuous services/scale, richer
candidate/runtime admission, venue execution qualification and deployment remain
with their owning future MRs. No strategy, QR onboarding, production deployment,
data purchase, live order or capital activation is accepted or authorized here.

Reversal is an uncommitted patch review/revert. Existing snapshot/request families
remain readable; newly authored public snapshots require the new reader family.
Retain their exact raw bytes and matching acquisition implementation for resume.
Do not migrate a checkpoint by editing its identity.
