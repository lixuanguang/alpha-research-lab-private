# MR 20 — Replay with shared event stepping

Owner: repository founder. Status: implementation under local verification on
2026-09-17. Branch: `codex/mr-20-event-stepping`. Base: fetched `main` at
`f37c07d`; MR 19, the sole prerequisite, merged at `0898d0a` through PR #44 and
is an ancestor of the base. Scope follows the
[MR 20 roadmap row](README.md#m2-research-data-access-and-replay).

## Problem / change

The reference history query retains revisions in partition/head order. `Replay`
expands that history at effective availability and reuses the admitted economic
ordering rule. Its shared `step` operation advances to the next source, consumer
wakeup or inclusive terminal, delivering every equal-time source before expiry,
fill, decision and mark callbacks. Read-ahead does not advance the clock.
Unknown original archive availability is never inferred. Membership and quality
remain explicit evidence for the consumer's cutoff-aware selection.

A frozen, codec-serializable `ReplayCursor` binds the query, consumer configuration
and ordering/phase version to a completed clock and logical source position.
Resume works across query batch sizes and rejects mismatched or incomplete source
positions. Callback errors propagate and prevent further use or checkpointing of
the partial instance; restore the last completed cursor with matching consumer
state. Callback payloads and exposed cursors/evidence are isolated from mutation.

## Affected scope

Runtime changes are confined to `data/replay.py`: ordered reference construction,
clock, phase delivery and completed-step cursor. Its first consumers are focused
regressions, the [installed fixture](../../tests/fixtures/mr20/replay_consumer.py)
and [NB 20 section 10](../../examples/research-foundations.ipynb). The existing
query, selector, configuration, canonical/revision serialization, publication and
live/book implementations are reused unchanged. The
[API guide](../../src/alpha_research/data/README.md#chronological-event-stepping-mr-20)
documents arguments, memory, progress, failure and recovery contracts.

Against `f37c07d`, production code-bearing changes are **147 additions + 0 deletions
= 147 lines**, including imports, annotations, validators and codec use. Blank
lines, docstrings/comments, tests/fixtures and notebook exercises are excluded
under the roadmap rule. No declarative configuration, dependency, lock, public
export or executable-tooling changes. The cursor and phase declarations ship
with the operation that consumes them; no later runner or schema is scaffolded.

## Validation result

Initial focused validation on CPython 3.14.7 passed **45 tests**, with no skips or
deselections, covering replay, query and as-of selection. Strict mypy passed all
five affected source/test/fixture files; source Bandit and engineering standards
passed. Final installed-wheel, notebook and focused-check evidence will be recorded
below after execution against the committed candidate.

An initial resume-test assertion compared a fully drained resumed cursor with
its starting cursor; the assertion was corrected, and the next run passed.
Initial mypy/lint findings in test annotations, imports and notebook documentation
were corrected before final acceptance. No failed run is counted as acceptance.

## Risks / reversal

This is a bounded in-memory reference over trade/control canonical history.
The canonical-byte cap bounds retained input, not process RSS or one-batch memory;
selected revisions and their sorted index remain resident. Existing MR 18 query
measurements are historical, verified against the unchanged measured runtime
files, and make no claim about new replay performance. No replay benchmark or
large-scale latency claim is made.

Consumers own observations, outstanding schedules, pending intents, applied fills
and ledger state; the source cursor cannot certify unsupplied economic state.
The scheduler fixes phase order, while E1/MR 44 will prove the earlier-fill/later-gap,
exact-expiry and resumed-economics contracts using their actual libraries.
L2/L3 shared publication/adapters, atomic book application and accepted-snapshot /
recovery-epoch checkpoints remain with their later consumers. The current canonical
trade boundary does not accept those book records. No research outcome, deployment
or release acceptance is claimed; existing release restrictions remain.

Revert this MR before dependent consumers merge; existing datasets and cursor-free
query APIs require no migration. Preserve the frozen P1 specification. Hosted full
CI remains required before merge. **Next: MR 21**, after this MR merges; it is not
implemented here.
