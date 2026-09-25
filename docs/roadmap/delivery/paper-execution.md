# MR07 delivery and acceptance

[Roadmap and delivery dependencies](../README.md#delivery-order-and-dependencies).

Status: **complete for local dedicated-account paper/shadow operation**, accepted
2026-09-25. Owner: quant development. The acceptance envelope is
local paper/shadow, one cash-funded spot instrument and instance per dedicated
account. The initial native inputs remain OKX `books` L2 and Bitfinex `R0` L3.
Generalized candidate, named-source, feature and target/order/quote contracts are
preserved; unsupported product economics still fail admission.

Delivered behavior:

- `runtime.PaperCandidateRuntime` supervises the existing candidate feature/model/
  policy components with start/recovery, market, timer, order, account, stop and
  fault events. Candidate state, decision inputs/results and order admission are
  committed together. Durable event cursors replay the then-current account
  balance without delivering a later fill early. Stale input, serving loss,
  changed versions, unknown orders and account breaks suppress new decisions.
- `execution.PaperOrderJournal` owns stable child IDs, exact portable order records,
  SQLite transactions, one POSIX-fenced owner and persisted epochs. Request
  acknowledgment, accepted state, cancel acknowledgment and confirmed terminal
  outcomes remain distinct. Duplicate retries reopen saved results; conflicting
  bytes fail. Partial fills post exactly once. Unknown outcomes preserve
  reservations and require explicit reconciliation before retry. Replacement
  requires the old order to be terminal and retains its lineage.
- `PaperMatcher` consumes finite displayed bid/ask liquidity shared by orders,
  later-than-decision market events, resting post-only admission, IOC residual
  cancellation and exact fees. Paper fills are modeled observations; shadow never
  matches. Neither path has an executable submit interface.
- `applications.paper.run_paper` composes source or `CandidateFeatureFeed` with
  these same owners. `run_live_paper` injects native transport/book adapters into
  the reusable neutral collector and supervises a real UTC scheduler alongside it.
  The callback occurs after durable capture/reconstruction. Original receipt and
  actual local delivery clocks are both retained, allowing saved-live replay
  without inventing earlier availability. A fresh recording starts with a fresh
  synchronized book while candidate/order state survives process restart.
- The independent `alpha-execute paper` application accepts durable steps,
  normalized events, modeled markets, cancellation, confirmed replacement and
  inspection without importing research, simulation, training, notebooks or
  QuantLib. Candidate supervision remains in the complete research distribution.

Owning contracts and usage are in the [runtime guide](../../../src/runtime/README.md#paper-candidate-supervision),
[execution guide](../../../src/execution/README.md), [paper application](../../../src/applications/paper/README.md),
[execute command](../../../src/applications/execute/README.md) and
[test guide](../../../tests/README.md#paper-and-live-input-acceptance).

Acceptance evidence is retained under ignored `logs/mr07/`:

| Boundary | Evidence and outcome |
| --- | --- |
| OMS lifecycle and independent limits | `independent-execution-pytest-final.log`: 21 focused execution/risk cases, including uncertain outcomes, partial fill/fee reservations, cancel/fill races, terminal contradiction, atomic quotes and replacement |
| Candidate clocks and hard controls | `runtime-focused.log`: 11 candidate/runtime cases, including paper/shadow parity, restored callbacks, stale quotes, clock regression, account break and a faulting callback unable to undo an independent block |
| Interrupted matching and independent stop | `runtime-final.log`: 13 runtime cases after review fixes, including completing a claimed quote before advancing the recovery clock, no duplicate fill/account callback, and preserving operator stop across both failed and successful reconciliation |
| Installed candidate and real serving | `installed-candidates-rerun.log`: both installed integration tests pass; `installed-candidates-source/` and `installed-candidates-feast/` retain actual candidate bundles, studies, paper traces and summaries. Rule-order and learned-target candidates preserve intent/feature parity and independently expected exact fill/fee/cash values; real Feast service loss and version change pause the OMS |
| Independent execution installation | `independent-execution-claim/README.md`: final admitted eight-wheel closure, clean offline install/pip check, all 58 owned source files matched, outside-checkout CLI partial fill, shadow refusal, confirmed replacement and restart parity; changed quote bytes rejected after interrupted matching while exact retry preserves liquidity/effects. Its focused execution/runtime run passes 28 cases |
| Independent collector installation | `collector-boundary/`: admitted 14-wheel closure with 16 edges, fresh offline installation/pip check, outside-checkout recovery consumer and `alpha-collect replay`; source parity and absence of research/simulation/execution verified |
| Earlier partial-fill installed proof | `independent-execution/`: retained original artifact demonstrates partial quantity 1 of 2, cash 899.90, holding 1, remaining reservation 100.90, duplicate/restart parity and shadow fill refusal |
| Actual OKX public input | `live-okx/summary.json` and `live-okx.log`: 8-second `books` L2 recording, 74 frames, one snapshot, 72 updates, no gaps, raw replay parity; seven decided cutoffs/orders from eight timer ticks |
| Actual Bitfinex public input | `live-bitfinex/summary.json` and `live-bitfinex.log`: 8-second `R0` L3 recording, 250 frames, one snapshot, 246 updates, no gaps, raw replay parity; seven decided cutoffs/orders from eight timer ticks |
| Same-component saved-live replay and restart | Both native output trees retain paper/shadow replay journals: all original paper `StepRecord` bytes, orders and ledger equal; shadow status/features/intents equal and no fills; a fresh recording preserves source binding, reopens the account and retries the saved timer without duplicate effects |
| Source identity of live acceptance | `live-installed-source-parity.json`: all 272 installed runtime/source/resource files match current source; installed source identity `8a8c059e42807b7f5f25392a095fa3c4fc6d3d9413979b0b1e6932b6e8b3dce9` |
| Complete local gate | `make-check.log`: complete `make check`, 1,502 tests passed, three performance tests deselected, real Feast enabled, strict mypy/stubtest, lint/format, engineering/dependency/link checks, security/audit/secret scan and isolated wheel APIs/resources/OKX book command. Short pytest base `/private/tmp/mr07-check` avoids macOS socket path limits |

`final-wheel/` retains the final research wheel, locked runtime requirements,
smoke inputs/results and a 272-file source-parity manifest. Its wheel SHA-256 is
`106aec1bec9ef1f754100de2bba2eb0bd53e19154078e4fdbb00c9ca1745d415`.
`final-candidates-source/` and `final-candidates-feast/` preserve the installed
consumer outputs from the final complete gate. Earlier snapshots remain separate.

The native runs used the installed core interpreter with `-I` and the three
maintained consumer scripts copied outside the checkout to
`/private/tmp/mr07-live-consumer/`. Exact script copies and bounded configs remain
in `live-consumer/` and `live-configs/`. The command for each venue was:

```sh
/private/tmp/ar07-core/bin/python -I /private/tmp/mr07-live-consumer/live_paper.py \
  --config /absolute/repository/logs/mr07/live-configs/okx.json \
  --output /absolute/repository/logs/mr07/live-okx
```

Use `bitfinex` in the config/output paths for its run. Capture duration was eight
seconds with zero retries. Each run retained actual source timestamps, receipt,
delivery and cadence clocks; no clock was shifted to force availability. The
passive engineering reference bid did not fill in either live-input run.
The summary's `canonical_parity=false` means optional persisted canonical batch
publication was not selected; raw native replay and the complete saved-delivery
paper replay both passed. Modeled fill semantics are established separately by
the exact controlled matching and installed OMS proofs.

The complete local command used an isolated task environment, preserving active
worker environments:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/ar07-gate TMPDIR=/private/tmp \
  ALPHA_FEAST_WORKER_PYTHON=/private/tmp/ar07-feast/bin/python \
  PYTEST_ADDOPTS=--basetemp=/private/tmp/mr07-check \
  make check > logs/mr07/make-check.log 2>&1
```

The initial gate's single failure was an installed recovery consumer still
patching the old collector module after extraction; its log is retained as
`make-check-before-recovery-fixes.log`. The mock now targets the functional owner,
and the installed recovery consumer plus complete gate pass. Review also added
regressions for immutable quote claims, interrupted matching recovery, equal-time
book delivery and preserving independent stops during reconciliation. Changed
operating wheels were rebuilt and requalified; old proof hashes remain intact.

The final independent execution wheel SHA-256 is
`fd05a2d8d489f1f642f10b10f795bdcc7eb36f5086a6dccd8ab5813ad043fc59`;
its contracts wheel is
`1e661e802fb2c4f6f86d6e0ed589de6a74f69c7ac0d3b8fd9505e6ee244c6194`.
The earlier partial-fill proof retains its original wheel hash rather than being
relabeled as a later artifact. These are installed software proofs, not a signed
production deployment. The complete research graph's existing QuantLib
source-to-wheel release restriction is unchanged.

Prerequisite ownership is explicit. MR08 owns the delivered dedicated-account
cash/inventory/fee reservation and local reconciliation slice. Account/firm
budgets across instances, transfers, rebates, correction posting and physical
venue reconciliation were left open by MR07. The
[MR08 account increment](account-risk.md#mr08-delivery-and-acceptance) now supplies their local
software path; physical venue proof remains open. MR11 owns authenticated execution, private
streams, venue rules/throttles and external uncertainty resolution for **both**
venues. MR10 owns broader failure/recovery drills; MR12 owns alert/dashboard
integration; MR13 owns deployment authority and safe activation; MR09/MR14 own
shared accounts and multiple active instances. None is closed by this slice.

A fill contradicting an already confirmed terminal cancellation saves a durable
`late_terminal_fill` block and raises without rewriting the ledger. Local matching
of a paper snapshot cannot clear this contradiction; the owning correction and
physical reconciliation increment must resolve it. Paper touch matching models
neither queue position nor market impact. Declared authored grids/fees are not
current venue-rule qualification. Native observations prove the data-to-runtime
boundary only, and completed engineering studies are not empirical strategy
evidence. Capacity, production operation and MR17/G5 remain open; formal QR work
has not started.

Reversal is patch review/revert plus selection of a compatible retained wheel and
its exact candidate/configuration/journal. Keep captured input and OMS bytes.
Never edit checkpoint identities or erase fills to force an older artifact to
accept newer state. Local acceptance does not authorize deployment or live trading.
