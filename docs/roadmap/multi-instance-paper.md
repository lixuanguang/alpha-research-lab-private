# Supervised multi-instance paper operation

Owner: quant development. Status: complete for the declared bounded local scope
on 2026-09-27. Scope: MR14 and the remaining in-scope local MR10 service drills,
from main `2b4b5a4` on
`codex/mr14-multi-instance-paper`. The starting tracked worktree was clean.
The [engineering guide](../coding_standards/README.md) governs implementation
and documentation; no applicable repository `AGENTS.md` was present.

Signed local account services and a supervised source/policy runtime now operate
different reference strategies across shared and isolated accounts. The qualified
workload has two accounts, two native sources and three initial policy instances,
with a fourth added by selecting a provisioned definition through configuration.
Both OKX and Bitfinex paper paths pass; a representative shared/isolated shadow
deployment preserves zero fills through retained-journal owner replacement.

The [runbook](../governance/operations.md#supervised-multi-instance-paper-services)
and [service guide](../../src/applications/paper/README.md#supervised-local-deployments)
own runnable startup, inspection, selective controls, shutdown and recovery commands.
The joint MR10 evidence index is `logs/mr10/multi-instance-paper.json`; it hashes
accepted service, receiver, native-source, artifact and final stopped-state records.
Services are stopped. MR15 capacity, MR16 ownership/enforcement and MR17 onboarding
remain open; private execution, live trading and real capital remain KIV.

## Bounded implementation plan

An operator installs and separately authorizes and activates a bounded local
paper/shadow deployment. Independently selected native inputs, reference policies
and instruments run under supervision. Shared and isolated account services retain
exact ownership, reservations, checkpoints, costs and valuation through selective
worker/source failure and account-owner replacement. Qualify OKX and Bitfinex
separately; engineering economics, not profitability, determine acceptance.

1. Correct reduction admission first: sample current UTC inside the serialized
   transaction and check operational quote, book and reconciliation freshness there,
   retaining request-time causal checks and original idempotent results. Regress
   a ten-second limit with request age nine and input age eighteen seconds.
2. Extend the existing disabled deployment envelope only enough to bind multiple
   explicit venue/instrument/input routes and paper/shadow mode. Keep existing
   deployment identities. Keep authorization, installation and owner claims distinct.
3. Add a bounded signed account-owner service consuming the existing typed account
   command protocol. Its fixed installed configuration, journal and release are
   authoritative. Reuse `PaperAccount` through a local socket adapter, with no
   automatic retry after uncertain execution. Duplicate service starts and replaced
   generations must be fenced.
4. Compose typed source and instance definitions, active selections, existing
   strategy bindings, book registry and portfolio runtime into supervised local
   processes. One account service serializes a shared account; isolated accounts
   have separate signed targets. Separate journal budgets are not one atomic firm
   budget. USD and USDT never consolidate without explicit FX, which is out of scope.
5. Supply startup, inspection, selective stop/restart, shutdown and recovery commands.
   Distinguish process heartbeat, source freshness and economic progress. Project
   account/instance authority, reservations, reconciliation and exact cost/P&L while
   running. Diagnostic/alert failure cannot retry execution or disable controls.
6. Qualify installed artifacts with independent economics and actual process loss,
   source loss/restoration, owner replacement and receiver observations. Renew both
   public source routes, update owning guides/runbook/roadmap, and run `make check`.
   Leave all qualification services stopped. Do not push or merge.

The configuration addition example activates a previously inactive, explicitly
provisioned instance from the immutable installed definitions/budget envelope.
Only the active scheduling selection changes at controlled restart. Existing
definition, account configuration and checkpoint identities remain exact. Adding
an instrument or budget outside that envelope requires a new compatible signed
configuration and is not silently admitted by this procedure. Hot reload is not
required. Old active selections cannot silently overwrite a newer retained revision.

New owners have concrete consumers: the local socket service hosts installed
account commands; its adapter implements `PaperAccount`; typed scheduling records
feed the deployment application; supervision owns child lifetime and routing.
Retain existing strategy sessions, account journal, risk, allocation, matching,
book/source adapters and telemetry implementations. No new matching engine,
distributed infrastructure, implicit FX or capital authority is introduced.

## Declared qualification budgets and failure policy

The retained preparation files declare three initial instances:
`shared-fixed-btc`, `shared-liquidity-btc` and `isolated-fixed-btc`. A successor
selection adds the provisioned `shared-fixed-eth`, preserving all definitions and
journals. `fixed_clip` requests two base units; `liquidity_clip` requests half
displayed ask size, capped at two and rounded to the one-unit reference lot. The
later fixture size of two therefore distinguishes their decisions. BTC and ETH
share USDT on OKX and USD on Bitfinex, with explicit distinct instrument identities.

Each account opens with 100,000 quote units. Each instance limit is 5,000, account
limit 10,000, and the independent journal's firm limit 10,000. Maximum order
notional is 1,000, price deviation 500 basis points and account state age 120
seconds. Separate grants permit at most eighty orders and cumulative buy quantity
100 per instrument for one hour. These are authored engineering limits, not
recommended trading limits. Separate journals do not provide one atomic combined
firm budget. Shadow reserves the same scoped exposure but never fills.

Before trials: local macOS arm64 / pinned CPython; two different reference policies
sharing one account and instrument, a second same-currency instrument, plus an
isolated account. Repeat venue-specific native routing for OKX/USDT and Bitfinex/USD.
Each signed service invocation is bounded to 120 seconds (within the existing
180-second launcher ceiling); trial source capture is bounded by time/bytes/messages.
Use an authored 30-second source/account freshness envelope for signed local command
round trips. Observe process heartbeat at most every 0.2 seconds; detect dead children
within two seconds, terminate dependent workers before recovery, and target bounded
local restoration within 30 seconds after explicit operator reconciliation/claim.
These are small operational trial budgets, not MR15 capacity or venue latency claims.
That original restoration target was missed. The accepted confirmation uses the
subsequently predeclared forty-second clock from the first actual claim request
to all-instance progress, including preparation of the second account, as detailed
below. Earlier misses and their original assumptions remain retained.

Before candidate 9: retain every native book in order, but select economic books
at an explicit three-second interval bound into each input/deployment identity.
The first eligible book is selected immediately; intermediate books update source
state and freshness without matching orders or advancing strategy checkpoints.
Invalid/disconnected input remains an immediate control boundary. Recorded delivery
selection makes replay exact. With two-second fixture arrivals this selects every
four seconds. Fixture capture is bounded to 60 seconds/25 frames; the supervisor
runs for at most 45 seconds and each account service for 100 seconds. The first
three valid fixture books retain the initial touch, followed by nonmarketable books.

Policy/source/owner process-loss response remains two seconds. Request-storage
failure rejects each attempted operation before effects; dependent-worker fencing
is budgeted at six seconds from injection, including one economic scheduling period
and fixture arrival quantization. Measure actual worker disappearance separately
from status latency. Condition waits for unaffected/restarted economic progress are
six seconds within the thirty-second restoration budget. These declared changes
address scheduling and observation latency without relaxing any freshness/risk guard.

Worker loss stops that instance without transferring its ownership. Source loss
blocks affected account admission conservatively; an isolated account may continue.
Account-owner loss stops every dependent worker; no timeout is treated as rejection.
Reopen retained state, reconcile independent facts, then explicitly claim a replacement
before reissuing residuals. Economic/delivery persistence failure prevents further
effects; telemetry and receiver failure remain diagnostic and cannot clear controls.
Retain initial failures and changed assumptions before a justified bounded rerun.

## Verification and evidence reuse

Use targeted causal/freshness, currency/scope, budget, fencing, shadow, configuration
compatibility and economic fault tests. Installed process trials establish service
behavior; deterministic native-frame fixtures establish independent exact economics;
fresh public observations establish each venue's new routing boundary. Keep these
three evidence classes separate. Retain receiver-observed alerts separately from
socket acceptance. Run relevant installed consumers plus repository-required gates.

Reuse MR09 allocation/conflict/residual arithmetic and MR11 deterministic matching,
fees/slippage/gas and reconciliation proofs where those algorithms are unchanged.
Reuse MR12 metric/query/retention and receiver primitives; renew their operating
composition. Reuse MR13 signing, quarantine, compatible rollback and owner-generation
proofs; renew changed deployment scope and freshness boundaries. MR04 service evidence
remains limited to its original services. New bytes need artifact verification.

MR10 closes only after its remaining local integrated service drills pass. MR15
capacity, MR16 ownership/enforcement and MR17 fresh onboarding remain distinct.
Remote/distributed operation, host-volume disaster recovery, private venue execution,
live capital and calibrated execution fidelity are outside this local paper scope.

## Implementation and qualification record

Implementation and bounded installed qualification are complete. This record
is not an activation grant. Initial attempts are retained under
`logs/multi-instance-paper/`:

- A concurrent-tooling attempt replaced files in the shared Python environment.
  Later validation and operating environments are independent immutable installs.
- Initial candidate builds preceded typed heartbeat/owner-file decoder corrections;
  those candidates are not acceptance artifacts.
- The first process trial failed to pickle a test fixture's cached JSON encoder.
  All services stopped without orders or checkpoints. The maintained fixture now
  tests process serialization and both real native book adapters.
- The next trial admitted initial decisions but guarded stale queued input before
  any fill. Repeated response/monitor snapshots were the immediate composition
  cost. Read-only responses and monitoring now share single consistent snapshots;
  authority and economic transaction checks are unchanged. The selected capture
  has a five-second idle limit, which imposes a stricter effective input age than
  the thirty-second account/input envelope. Neither limit was relaxed.
  Distinct invalid inputs also exposed a reused fault-control identity; each now
  binds its retained input, preserving exact retries.
- The full gate's initial test run passed 1,773 tests but three existing AF_UNIX
  tests exceeded Darwin's pathname limit under its long default temporary path.
  The final gate uses `TMPDIR=/private/tmp`; the failed log is retained.
- Candidate 3's signed installed OKX initial trial reached the authored first
  economics: two attributed shared fills and independent monitoring net P&L of
  -3.201 USDT for the shared account (-1.6005 for each policy), with the isolated
  account at -3.201 USDT. A duplicate installed account launch was fenced. Initial
  activation took 18.83 seconds; the observed worker-loss and owner-loss responses
  took 0.466 and 0.237 seconds. These are observations from a failed qualification,
  not accepted recovery or capacity measurements. The selective `stop_instance`
  request supplied an owner outside that action's guarded typed field and was
  rejected. The supervisor then faulted the whole shared account, so the surviving
  shared policy did not continue independently. The original harness
  `logs/multi-instance-paper/candidate-3/trial-okx/initial/summary.json` reported
  `passed: true`; its retained `qualification-review.json` supersedes that result
  with `qualified: false` and the precise selective-stop failure. A stronger signed
  rerun must retain the unaffected shared policy's checkpoint and prove same-owner
  selective restart only after the terminal parent outcome and reconciliation.
- Candidate 3's first OKX public attempt stopped at the explicit recovery claim,
  before starting services or public sources. The authored later ask of 105 against
  a retained bid of 98 exceeded the unchanged 500-basis-point price-deviation
  guard. The corrected fixture uses ask 103 and size 2, still nonmarketable against
  the initial buy limit of 102; the risk limit was not relaxed.
- The corrected fixture's OKX public attempt retained usable BTC and ETH markets
  through separate native source processes in
  `logs/multi-instance-paper/candidate-3/trial-okx/public-attempt-2/summary.json`.
  BTC forwarding backpressure then stalled its heartbeat; both dependent accounts
  were guarded, two receiver alerts were observed and all services exited. This is
  bounded routing and safe-stall evidence, not a sustained-rate or MR15 capacity
  pass. The separate Bitfinex public observation in
  `logs/multi-instance-paper/candidate-3/trial-bitfinex/public/summary.json` retained
  usable BTC and ETH markets with all selected workers and sources active and no
  fault at observation, followed by shutdown. These source-routing observations
  may be reused after the narrow selective-stop owner-token validator correction:
  it does not change native source, policy or matching behavior. The corrected
  signed service and selective-stop/restart qualification still require a new trial.
- Candidate 4's signed OKX trial corrected the owner token: selective stop kept
  the other shared policy and isolated policy active, and their checkpoints
  advanced. Its separate socket reconciliation followed by a CLI restart raced
  the next source cohort and residual reissue, so the journal correctly rejected
  restart with `instance_restart_requires_reconciliation`. The interrupted
  attempt remains in `logs/multi-instance-paper/candidate-4/trial-okx-initial.log`;
  it does not qualify selective restoration. The next trial carries the independent
  observation in the typed supervisor restart control, so reconciliation and the
  restart request run before the next supervised source cohort.

- Candidate 5's in-flight policy termination occurred after the liveness check,
  inside pure policy evaluation. The conservative generic exception path faulted
  the whole account. `PolicyProcessFailure` now identifies only failure of the
  isolated policy process before cohort admission; its PID selects the affected
  instance. Unknown failures and any account-command uncertainty still fault all
  dependent workers. The focused policy/supervisor/monitor suite passes 13 tests.
- Candidate 6's first trial retained the expected economics, a 1.209-second
  selective response and continuing shared/isolated checkpoints. Its restarted
  worker was healthy, but the harness checked its checkpoint after a fixed 1.4
  seconds, before the next committed cohort. The journal retained subsequent
  progress about three seconds after restart and no account fault. The failed
  assertion and qualification review remain under `candidate-6/trial-okx/initial/`.
  The rerun uses a five-second condition wait within the unchanged thirty-second
  recovery budget, with explicit reconciliation/new owner claims on the same
  journal and nonmarketable subsequent inputs. No implementation changed for this
  harness correction, and the original first-touch economics are not replayed.

- Candidate 6's retained-state rerun faulted on stale queued books before its
  selective-stop assertion. Nineteen shared decisions were enough to expose the
  repeated complete-response cost: a checkpoint query decoded the complete
  journal twice and returned a 106,682-byte account response. An unprofiled local
  read took about 0.14 seconds before socket retention and owner checks; a source
  cohort performs several such operations. The recorded 2.499-second inactivity
  observation is not a selective-stop pass. Both journals remain retained/stopped.
  The correction reuses the opened journal handle with exact request/configuration/
  owner checks and requests typed narrow projections for internal reads and
  operation receipts. Each authority/admission transaction still reads current
  state; there is no state cache or execution retry. Full operator inspection
  remains complete. New account and supervisor artifacts must qualify the changed
  response boundary; freshness, source cadence and response budgets are unchanged.

- Candidate 7 passed its installed initial drill, including selective restart
  and owner loss with the receiver down. Its addition harness reported a pass,
  but final review found pre-existing freshness faults before the injected source
  loss. `trial-okx/addition/qualification-review.json` supersedes that pass; it is
  not accepted source-restoration evidence. The final harness requires healthy
  accounts before injection, the matching failure reason, fresh source recovery,
  and exactly the expected final active/faulted account sets. Restoration with two instruments
  still lagged after 29 shared decisions and 23 child orders; the unchanged source
  freshness guard faulted the accounts before the progress assertion. The remaining
  cost was repeated deep decoding of identical SQLite state within a cohort.
  The next correction retains one validated immutable decode and reuses it only
  when freshly read configuration and payload bytes match exactly. Every load still
  reads SQLite, changed bytes are validated, and each transaction still evaluates
  current authority, time and exposure. Rollback and external-writer regressions
  qualify this bounded decode optimization; it is not MR15 capacity acceptance.

- Candidate 8's initial and addition trials pass the stronger health checks,
  including actual ETH source resynchronization. Its first storage-failure
  restoration retained an isolated-account failure event about 0.167 seconds after
  injection, but the status query returned after 3.244 seconds and the shared
  account subsequently guarded stale queued inputs. That attempt is not accepted.
  The remaining recovery, Bitfinex and shadow trials declare a two-second native
  fixture cadence (0.5 updates/second/source), replacing the original 1.25-second
  assumption for retained two-instrument recovery. The original OKX initial/addition
  observations retain their faster workload. Effective source freshness stays five
  seconds, account freshness thirty seconds and hard-stop response two seconds.
  The storage drill measures actual dependent-worker PID disappearance separately
  from status-query latency. Current journals, economic facts and checkpoints are
  retained across this explicit recovery; no code, risk limit or journal is reset.
  Broader arrival-rate, retention and sustained native-feed capacity remain MR15.

- Candidate 8's two-second restoration retry also guarded stale queued books before
  the storage injection. Its source lag grew to the unchanged five-second limit;
  `trial-okx/restoration-retry/qualification-review.json` records nonqualification.
  Per-book account operations still consumed about 3.3 seconds for the retained
  two-instrument cohort. Candidate 9 therefore qualifies an explicit economic
  sampling interval, rather than assuming every native feed update can trigger a
  decision. All native records remain retained and validated. The interval is part
  of exact signed input identity, and each selected/nonselected delivery is retained
  for exact replay. This new boundary requires renewed public evidence for each venue.

Candidate 8 rebuilt and verified all six signed account artifacts and the
separate installed research supervisor after the response correction. Its trials
use preserved state between configuration addition and owner/source/storage
recovery. The request-storage drill renames the isolated target's
`service-requests` directory aside and temporarily places a regular file there;
this forces actual request-retention failure without changing economic code.
The original directory is restored before explicit reconciliation and replacement.
The selected invocation remains 25 seconds within a 100-second account service
lifetime. These service observations are separate from native-frame fixture
inputs and from real public-source captures.

Failed deployments, requests and checkpoints remain retained and stopped. New
corrected artifacts are qualified in separately provisioned targets; an existing
journal is never reset to manufacture a clean continuation. The successful
configuration-addition and recovery drills must preserve their own current state.
The authored first-touch oracle uses ask 100, bid 99, size 4, take fraction 0.5,
adverse price 0.50 and fee 0.001. The corrected later nonmarketable interests use
ask 103 and size 2 to distinguish fixed-size from liquidity-scaled decisions. Gas
is explicitly inapplicable to this off-chain reference spot model.

## Candidate 8 installed artifact set (superseded for qualification)

Candidate 8 ran on macOS 27.0 arm64 with pinned CPython 3.14.7 and
local Unix sockets. Its non-editable research distribution is installed at
`/private/tmp/mr14-research-v8`; `research-identity.json` records module paths and
hashes outside the checkout. Complete installed implementation identity:
`ebd9b6dca052fe1766c96034b97c5f4bd2bcdeef068613024394edb32e702575`.

Fresh builds, dependency audits, signature verification and independent offline
installation are retained in `logs/multi-instance-paper/candidate-8/`:

| Target | Signed release |
| --- | --- |
| bitfinex-isolated | `6c68d191fd9e35da90d6c6087925cef4a36e0fb3aa191cf1855d6449eaeb94df` |
| bitfinex-shared | `4eb53f638b074c827cef128f672bcaa656b6e0b95affc23fae32a65c4ecea72b` |
| okx-isolated | `ead2ccb79c07d2ed2daa69d03f0cccd23ca8e0c7084217420424bc59c7be4269` |
| okx-shadow-isolated | `d814695e255be7c1412e38916bdd2203cf8b7b32ab8f2493c67f32b4a52d55ac` |
| okx-shadow-shared | `168e4ec3f29fe8577c00b21c91d45ac78430c8eddb1c8fd620fbc624a15a749e` |
| okx-shared | `e434c68739d97a8c81f7254c3ec10b5486e11c9144afb0b118a76c8a449c877c` |

The source/policy supervisor uses the full research distribution. Each signed
account target uses its independently admitted execution/contracts closure.
Separate disabled deployments, grants, observations and owner claims are retained;
installation itself supplies no paper authority. Earlier artifact sets remain
retained with their failed qualification records.

## Candidate 9 installed artifact set

The corrected scheduling boundary is independently installed at
`/private/tmp/mr14-research-v9` on the same declared macOS arm64 / CPython 3.14.7
profile. Research implementation identity is
`92b7515129875f014cc113b4f865b8382f9b2e86a830d47a2f0fcdbd8d1806d0`.
`logs/multi-instance-paper/candidate-9/research-identity.json` retains installed
module paths and hashes. Fresh dependency audits, signed builds, verification and
offline installation completed for all six account targets:

| Target | Signed release |
| --- | --- |
| bitfinex-isolated | `030707983e91349c161d919a3422c6a7e90668def43106c5878c3f3fd68edb90` |
| bitfinex-shared | `51892031d5e2187bef4057de98a6e0bba17babeacdfda771992eff2a03c0df09` |
| okx-isolated | `f4491f3b6de12d5edf7f3bd2600a3a3cac9f5de2273d89bc201256f7d14e00f3` |
| okx-shadow-isolated | `e84aca3244afcf68552d7c956341bbb6a1e49c270a4cd1c81215741f8c02462e` |
| okx-shadow-shared | `75e39957cb6b6158f17682591611a937bd9c99583682251e3d442ea1aba37236` |
| okx-shared | `fa1e1084c83781490ee30c23d17640089c25e877fa1050c38133019ce8c79a4f` |

The first candidate-9 full gate passed lint, format, strict typing and stub checks,
then found three documentation-summary violations in the new test helper. The
failed log is retained as `make-check-candidate9-attempt1.log`; those test-only
summaries are corrected before the final gate. Operating trials remain the
acceptance boundary; artifact installation alone does not establish recovery.

Candidate 9 initial OKX qualification passed. The first addition attempt timed out
waiting for a monitoring sample: existing BTC fills satisfied the generic initial
condition before the new ETH source had reached its first fill. Retained deliveries
and the journal confirm exactly two ETH units filled on the selected third low
book, with no account fault. The retry first waits explicitly for that new fill
(up to twelve seconds, covering subscription, selection and account completion),
then checks monitoring. It retains the same configuration revision, journal,
checkpoints and artifact bytes; the failed attempt is not a source-recovery pass.

Before candidate-9 public trials: after both native sources expose usable markets
(within twenty seconds), observe six more seconds, spanning the three-second
economic interval, and require all selected instances/accounts to remain healthy.
Retain native captures and selection flags separately from fixture economics;
this bounded window is not a sustained-rate or latency-distribution claim.

Recovery timing audit: `after_first_claim_seconds` in the earlier trial records
actually started after that account's post-claim verification. It is not an exact
claim-to-progress measurement. Retained first `claim_paper` request timestamps
show 30.981 and 32.687 seconds for OKX restoration and 32.037 seconds for Bitfinex,
including preparation of the second account. These miss the original thirty-second
target; safe recovery and exact economics passed, but those results do not pass
that latency target. The corrected harness records the actual first claim request.
Before explicit `restoration-budget-confirmation` trials on both retained journals,
declare forty seconds from that request through remaining-account preparation,
service startup and committed checkpoint progress for every selected instance.
This budget includes sequential signed operator commands; freshness and two-second
process-loss budgets are unchanged. Total operator workflow time remains separately
reported. No source, artifact, state or economic assumption changes for these reruns.

### Independent fixture economics

Each instrument contributes exactly two account units bought at 100.50 and valued
at the bid of 99. The shared BTC allocation gives one unit to each policy; the
isolated policy owns two. ETH addition contributes two units owned only by
`shared-fixed-eth`, leaving existing BTC attribution unchanged. Opening cash is
100,000 per account. The independently authored expected totals are:

| Venue/currency | Account state | Cash | Fees | Net P&L at bid 99 |
| --- | --- | ---: | ---: | ---: |
| OKX / USDT | Initial shared or isolated BTC | 99,798.799 | 0.201 | -3.201 |
| OKX / USDT | Shared BTC + ETH | 99,597.598 | 0.402 | -6.402 |
| Bitfinex / USD | Initial shared or isolated BTC | 99,798.80 | 0.20 | -3.20 |
| Bitfinex / USD | Shared BTC + ETH | 99,597.60 | 0.40 | -6.40 |
| Shadow / USDT | Initial and restored accounts | 100,000 | 0 | 0 |

Each initial shared BTC policy owns fee 0.1005 and P&L -1.6005 USDT, or fee 0.10
and P&L -1.60 USD. Slippage is one quote unit per instrument/account, already
included in fill price and never subtracted twice. The bid mark determines the
remaining loss. Half-even currency fee rounding explains the USD/USDT difference;
no conversion or aggregation across those currencies is performed. Gas is
explicitly inapplicable to off-chain spot. Recovery preserves fill identities,
cost postings and checkpoints before new progress; it does not replay the
first-touch economics.

Candidate 9 shadow initial observation failed because the monitor still held its
pre-admission sample with no reservations. While preparing a same-journal retry,
a real recovery limitation became visible: shadow never invokes paper matching,
but managed manual events were also prohibited, leaving unaccepted shadow intents
without a terminal operation before owner replacement. The failed target is kept
stopped with its reservations; it is not reset or claimed as accepted recovery.
The bounded correction permits only an explicit local rejection of unsent,
never-accepted, zero-filled shadow physical intents while the account is stopped,
through the current fenced owner. Existing allocation atomically closes child
interests. Paper manual events and shadow fills stay prohibited. Exact retries
remain idempotent; a complete independent reconciliation still precedes a new claim.
This is a local no-submission fact, not an exchange observation. New shadow
artifacts must qualify initial operation and retained-state owner replacement.

The second candidate-9 full gate passed 1,793 tests with two skips, but failed two
supervisor test cases whose fake fixed PID no longer met the new liveness check.
The test harness now uses its actual live PID and snapshots a set before removing
items. All seven focused supervisor tests pass. The failed full-gate log remains
`make-check-candidate9-attempt2.log`; the final gate follows the shadow correction.

Before final candidate-10 public observations, the independently signed source
definition permits at most 2,000 messages and 32 MB per source over sixty seconds
(maximum single frame 8 MB, queue capacity 1,024). The earlier eighty-message
fixture envelope could end a native feed before the declared six-second observation
window. The reference fixture still emits at most twenty-five book frames at two-second
intervals, plus acknowledgements/control records; no fixture rate or authority/order budget changes. The new capture bound
changes input identity, so candidate 10 is separately provisioned and signed.
Candidate-9 paper service/fault economics remain reusable for their smaller workload;
actual final public routing and shadow recovery use the new artifacts.

The first forty-second confirmation reached execution after the original one-hour
grant expired. The installed claim correctly rejected
`paper_authorization_expired_or_not_yet_valid`, before services launched. The
failed attempt and stopped journal remain retained. The next confirmation performs
an explicit fresh one-hour grant with the same limits only after stopping, settling
physical outcomes and independently reconciling, then claims a new generation.
This is an operator qualification action; the running service never renews grants.
The original forty-second measurement still starts at the actual claim request.

## Candidate-10 shadow artifact set

The final source adds only the protected shadow-intent rejection path after
candidate 9's paper service qualification. Managed paper manual-event behavior,
matching, scheduling, authority, account state and risk algorithms are unchanged;
31 adjacent activation/netting/scope tests pass. Candidate-9 exact paper economics
and actual worker/source/owner/storage drills are retained with the strengthened
`posthoc-harness-review.json`; its two `restoration-budget-renewed` trials use the
correct first-claim clock and pass at 38.779 seconds (OKX) and 38.063 seconds
(Bitfinex), under the predeclared forty-second budget. Both verified cleanup.
They retain the original thirty-second misses and expired-grant refusal.

Candidate 10 rebuilds, audits, verifies and independently installs all six signed
account artifacts and the non-editable research distribution at
`/private/tmp/mr14-research-v10`. Its implementation identity is
`d375a716ef6243d938e915ed6e7051a2c73d2815f31868f0c1cca04bf179f68e`.
Installed module hashes, fresh dependency audits and release verification are
under `logs/multi-instance-paper/candidate-10/`.

| Target | Signed release |
| --- | --- |
| bitfinex-isolated | `41688d0bd3b5f7f8f6316b517a0a4344a11dfe302cf2f7f6a39d1d985c278d84` |
| bitfinex-shared | `676f263edb8ad2b3e1ad26117325e37860c8acde17ab98429accc8fb07bc3861` |
| okx-isolated | `1df7f524c934eb1ce7030f89d8c062081751f1851e81305c248ba2a50373435e` |
| okx-shadow-isolated | `53214ccefb4b503a199040495b6d98363d525fe71b8b20eb593769795c9d5caa` |
| okx-shadow-shared | `dafc8637f462f1ef2c9983869eba1b634058b005d64378619af79cd3a7038cce` |
| okx-shared | `0f7f7a4534ac8a9abe2161e4ef49d83d04d0c44cd0f7e1413a072de975e2e723` |

Candidate-10 native public routing used these paper artifacts with the newly declared
2,000-message capture envelope. Initial shadow operation and owner replacement
use these shadow artifacts on the same retained candidate-10 journals. The earlier
failed shadow target remains stopped and retained; it is not upgraded through an
incompatible immutable deployment release allowlist or reset to manufacture recovery.

The final shadow replacement trial declares the same forty-second budget from
first actual claim request to committed progress of every selected instance. Its
explicit stop/rejection/reconciliation work before that first claim is retained
and reported separately. It must retain zero fills, fees and net P&L throughout,
while initial shadow operation must expose nonzero pending reservations.

Final candidate-10 shadow initial operation passed with pending reservations and
zero economics. The first restoration attempt correctly refused
`instance_restart_requires_reconciliation`: its owner claim advanced the account
control clock beyond the pre-claim observation. No service launched during that
failed restoration. The retained attempt is not a recovery pass. The corrected
operator sequence supplies a fresh complete observation after the claim and
before each instance restart, since each restart also advances that clock. The
same journal and checkpoints continue under unchanged artifacts and budgets.

The corrected candidate-10 shadow restoration passed at 39.239 seconds from the
first actual claim to progress in all four instances. Both journals stopped with
zero fills, fees and net P&L. Candidate-10 OKX public routing passed its six-second
healthy window. Bitfinex public routing safely faulted both dependent accounts on
a valid native heartbeat: R0 sequence advancement changes the exact book-state
identity, but the live projection required that identity to stay unchanged to
carry the last market through a heartbeat. The two receiver-observed alerts and
stopped journals are retained; this is a failed healthy-routing qualification.

Before candidate 11, retain all prior budgets and additionally require a valid
post-snapshot native heartbeat from each Bitfinex source while every instance and
account stays healthy. After the six-second minimum window, allow at most twenty
seconds for those heartbeat observations. The correction must preserve original
market age and exact state/sequence verification, with no heartbeat-triggered fills
or strategy checkpoints. New implementation identity requires separately bound
deployments; failed or accepted older journals are not relabeled or reset.

The candidate-11 correction is confined to `LiveBookDecisionSource`. It rebuilds
the retained L3 state through the existing `VisibleBook` identity implementation
and requires both the original market hash and the new control hash to match.
Heartbeat sequence must advance by one; a later nonmarket control keeps the last
sequence. Epoch, validated quality and original market clocks remain unchanged.
Changed hashes and actual native sequence gaps still invalidate the source.
The quote-only registry remains conservative at that control boundary; the
supervised observer schedules only subsequent eligible market rows and does not
query it to execute on a heartbeat. No schema, deployment check, account economics
or scheduling cadence changes. The eighteen focused source/runtime tests pass.

Candidate-9 fixture/service economics remain valid because their native fixture
workload has no post-snapshot Bitfinex heartbeat. Candidate-10 shadow uses OKX;
its no-fill and unsent-intent settlement paths are untouched. Final public trials
renew the corrected native boundary and bind the new implementation explicitly.

## Retained service observations

The following are actual installed processes, Unix-socket requests and receiver
observations. Their market inputs are separately identified native-message
fixtures; they do not represent exchange fills. Candidate-9 successful initial,
addition and restoration directories retain requests, observed events, periodic
economic projections and checkpoint assertions. `posthoc-harness-review.json`
records the independent review of the earlier harness, including its limits.

| Drill | OKX | Bitfinex | Declared bound / protected behavior |
| --- | ---: | ---: | --- |
| Policy process killed | 0.368 s | 0.297 s | 2 s; only affected instance stops, other shared and isolated checkpoints advance |
| Isolated account owner killed, receiver down | 0.267 s | 0.280 s | 2 s; dependent policies stop; shared account continues under its own controls |
| ETH source killed after configuration addition | 0.261 s | 0.279 s | 2 s; shared account protects, isolated BTC continues |
| Restarted ETH source usable | 4.759 s | 6.606 s | 8 s; new source PID and market, account stays protected until explicit recovery |
| First actual claim to all-instance recovery progress | 38.779 s | 38.063 s | 40 s; identical prior fills/costs/checkpoints, stale owners rejected |
| Request-retention failure fences isolated worker | 1.602 s | Common service path reused | 6 s; no admitted effect/retry, shared account continues |

The storage fault replaces the request directory with a regular file, forcing an
actual retention error. Restoration of the original directory does not execute
anything automatically. Its status observation arrived at 2.755 seconds; that is
distinct from worker disappearance. Five alert datagrams were independently
observed across the accepted candidate-9 initial/addition/storage trials. The
deliberately unavailable receiver during owner loss did not prevent protection.
No human acknowledgement is claimed.

The forty-second recovery clock includes sequential preparation of the second
account after the first claim. Total renewed operator workflows, including earlier
stop/settlement/reconciliation and final cleanup, took 62.769 seconds for OKX and
57.684 seconds for Bitfinex. Original thirty-second misses remain failed timing
observations. Both renewed trials verify stopped journals and exited processes.

Candidate-10 shadow initial and `restoration-shadow-reconciled` qualify the common
shadow path, including existing reservations, local unsent-intent settlement,
fresh observations between controls, owner replacement and configuration selection
of the fourth instance. Recovery took 39.239 seconds under the same forty-second
clock. Zero economics and original checkpoints were independently checked before
new progress; both final journals and all child processes stopped. The preceding
failed attempt is retained. Repeating every fault for shadow would add no distinct
execution/account effect: it shares supervision, ownership and reservations while
its separate no-fill/settlement boundary is qualified directly.

## Final candidate-11 public artifact set

The corrected research distribution is independently installed at
`/private/tmp/mr14-research-v11`, with implementation identity
`81c4584db810ef3090b10150849296efe508c52763497f26fe1efea6c32ceba7`.
Its installed live-source module hash equals the current source. Fresh signed
paper builds, dependency audits, signature verification and independent offline
installation passed for all four targets:

| Target | Signed release |
| --- | --- |
| okx-shared | `9f57fcf645b9910a1952d80a8583ad80a6bca7273d8a0783863e88fa909adf96` |
| okx-isolated | `5ab818dd9b48bee15d637ba3e2dfeb1f5e0fbf5c9e9637f5696bff318bfd9bdb` |
| bitfinex-shared | `e4713d96d28ddc97568da6979e3871b6543cdfd4ae0c0e8e6e98bc9164585d86` |
| bitfinex-isolated | `64f9db05e545d2ed7a78532ae3fce436bd4e32cbc599b9f40d19a4c9ce736027` |

`logs/multi-instance-paper/candidate-11/` retains the installed module inventory,
preparation, separately disabled deployments/grants, audit/build/verify/install
logs and signed releases. Each deployment's exact policy identity binds this
research implementation; no older journal is silently migrated to it.

Both final native public trials passed with all four instances active and no
account fault after the declared observation window. Their actual native source
records and economic selection are retained separately from fixtures:

| Venue | Source / account observer | Delivery records | Selected economic books | Books retained without economic effects | Post-snapshot heartbeats |
| --- | --- | ---: | ---: | ---: | ---: |
| OKX | BTC / shared and isolated, each | 63 | 3 | 58 | 0 |
| OKX | ETH / shared | 68 | 3 | 63 | 0 |
| Bitfinex | BTC / shared and isolated, each | 94 | 3 | 86 | 1 |
| Bitfinex | ETH / shared | 155 | 4 | 146 | 1 |

The other delivery records are session/subscription/control boundaries. Every
retained heartbeat has no decision inputs or coordination time. Native public
routing uses current venue prices under the authored engineering risk limits;
it is not the fixed-price economic oracle or a calibrated fill model. Each trial
verified shutdown and stopped account journals. No alert was expected or observed
in these healthy windows; actual receiver success and loss are qualified by the
separate fault trials above.

## Final verification and limits

`UV_PROJECT_ENVIRONMENT=/private/tmp/mr14-validation TMPDIR=/private/tmp make check`
passed, with 1,800 tests, two skips and three performance tests deselected, plus
Ruff, formatting, strict typing/stub checks, engineering/dependency/architecture
checks, security and vulnerability/secret scans. The installed research-wheel
smoke passed its APIs, resources, historical snapshot and OKX book command.
`logs/multi-instance-paper/make-check-final.log` retains the final gate; previous
failed and passing candidates remain separately recorded.

The final read-only audit inspected 54 installation journals. All 32 activated
journals were stopped; the remaining installations had never received authority.
All 314 retained direct service PIDs were absent at that later audit. Final trial
cleanup records independently retain immediate process exits, child checks and
stopped account phases. No bounded qualification service remains running.

MR10 closes by combining these actual local service drills with valid earlier
backup/restore, signed rollback, matching, allocation and monitoring evidence under
the impact explanation above and the joint evidence index. This accepts trusted
single-user local invocations bounded to 1–120 seconds, and addition of provisioned
inactive instances. Arbitrary definition/budget/state migration, indefinite daemon
operation, remote/distributed or hostile-user isolation, host-volume disaster
recovery, cross-journal atomic firm limits and implicit FX are not qualified.
MR15 still owns sustained rates, retention, concurrency and latency distributions;
MR16 and MR17 retain their separate delivery and fresh-entry obligations.
