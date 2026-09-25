# MR04 delivery and acceptance

[Roadmap and delivery dependencies](../README.md#delivery-order-and-dependencies).

Status: **complete for the declared local feature-store, workspace and job-service
scope**, 2026-09-24.
Owner: quant development. This is infrastructure MR04; no QR research result,
production deployment or capital authority is implied. The initial working tree
was clean and this delivery remains uncommitted for review.

Delivered through the existing functional owners:

- `research.features` owns exact versioned multi-field history, definition/entity/
  fitted-signature validation, source and dataset revision identities, causal
  historical reads, explicit missing/partial/future/stale/expired outcomes, and
  atomic vector/checkpoint commits. Incremental state is isolated by definition,
  materializer instance and entity. Changed source or dataset pins require a new
  instance and replay; a stored correction never rewrites earlier knowledge.
- `applications.explore.materialize_features` resumes committed work, prepares a
  named immutable version, publishes and verifies the isolated Feast generation,
  then conditionally activates the pointer. A concurrent newer activation cannot
  be overwritten by a stale publisher. Explicit rollback retains both versions.
  The independent Feast 0.66 lock and core pandas 3 environment remain unchanged.
- `run_served_decision` consumes the same admitted feature definition through real
  Feast online retrieval and existing pure `DecisionSession` policies. It preserves
  feature origin clocks while recording the consuming decision time, and pauses
  without policy-state advance on missing/expired/service-loss results. This is
  the bounded MR05/MR07 online-consumer prerequisite; candidate packaging,
  supervised live-input paper/OMS and order submission are not completed by it.
- `runtime.JobQueue` and bounded workers retain delayed scheduling, cancellation,
  progress, capped retry, immutable outputs and crash recovery. Jobs pin installed
  implementation, configuration, input and compatible-environment identities;
  secrets remain references. `StudyJobHandler` uses MR03 study components, shared
  family holdout history and optional stable job keys. A completed study survives
  lost acknowledgement without recomputation or duplicate publication.
- Workspace backup/restore fences job workers and nested attempt writers, captures
  mutable SQLite stores consistently, preserves immutable Feast generation bytes,
  and restores verified files into a fresh destination. Existing lakeFS pinned
  inputs and ClearML experiment/artifact publication remain authoritative remote
  integrations; their service volumes must be backed up as well.

The [feature guide](../../../src/research/features/README.md),
[runtime guide](../../../src/runtime/README.md) and
[scheduled study guide](../../../src/research/studies/README.md#scheduled-studies-and-reproducible-workspaces)
own supported APIs, producer quiescence, failure responses and recovery commands.
The installed [feature consumer](../../../tests/integration/consumers/research/feature_workspace.py)
and extended [study consumer](../../../tests/integration/consumers/research/decision_study.py)
are quant-development acceptance workloads. Their authored non-book signals and
spot quantities establish software behavior, not alpha or new venue qualification.
MR01's saved OKX/Bitfinex evidence remains valid: source adapters and their clocks
are unchanged. No new Binance/Tardis input or access is used.

Evidence is retained under ignored `logs/mr04/`. The separately locked real Feast
worker validates exact online values, missing/expired entities, late corrections,
retries, tamper rejection and relocation. The installed application workload also
checks stateful restart, two entities, rollback, online intents and service loss.
The extended study workload checks a lost acknowledgement after real completion,
one retained study across two job attempts, and clean queue/result restoration.
Local lakeFS/ClearML publication and stopped-volume restoration records qualify
the selected development services separately from fixtures:

| Boundary | Retained evidence | Result and limit |
| --- | --- | --- |
| Final local gate | `make-check-final.log` | 1,325 passed; one unselected real-Feast case skipped; three performance cases deselected; lint/format, strict typing/native stubs, ownership/docs, dependency/security checks and installed-wheel smoke passed |
| Real Feast SDK | `feast-serving-final.log` | Explicit separately locked worker test passed; exact rational online values, corrections, expiry, missingness, retry, relocation and tamper refusal |
| Installed feature workspace | `feature-workspace-final.log`, `feature-workspace-final/acceptance.json` | Two entities, exact offline/online parity, atomic incremental restart, retry, version rollback, intent-only serving and clean local restore |
| Installed study workspace | `study-workspace-final.log` | Fresh MR03 extensions remain executable; a lost completed-study acknowledgement produces two job attempts and one completed study; queue/history/results reopen after restore |
| Pinned lakeFS source/features | `lakefs-feature-version/feature-version.json`, `lakefs-features-reconciled.log`, `lakefs-after-restore.log` | Four exact named source/manifest/definition/history objects reopened from the same immutable commit, before and after actual service restore |
| ClearML experiment/artifact store | `clearml-publication-final.log`, `clearml-after-restore-fresh-cache.log` | Unique task/receipt recovery and exact remote artifacts, including fresh downloads after restore |
| Whole service recovery | `service-backups/manifest.json`, `service-backup-restore.log` | Five stopped lakeFS/ClearML volumes restored into separate projects under the same image pins and private credentials |

The final gate command is:

```sh
TMPDIR=/private/tmp PYTEST_ADDOPTS='--basetemp=/private/tmp/ar04-final-review' \
  make check > logs/mr04/make-check-final.log 2>&1
```

`wheel-sha256.txt` pins the retained final development wheel. The installed
acceptance interpreter was isolated from active workers; its owned runtime bytes
are compared with the retained wheel in `installed-runtime-parity.json`.
The initial virtual-environment symlink mistake, a relative credential-path
failure and a service-consumer tuple decoder error remain in their original logs.
The already-published ClearML attempts and lakeFS commit were reconciled after
those harness fixes; neither was relabelled as a fresh publication. The initial
installed runtime snapshot is retained separately, without rewriting old hashes.
Task-owned service containers are stopped after verification; backups and named
volumes remain as local-only evidence, not a portable shared-service deployment.

Scope and later ownership remain explicit. The supported topology is one trusted
local POSIX workspace, independently locked compatible Python environments and
loopback development services. It is not shared-host authentication, distributed
leases or arbitrary external exactly-once execution. Running study cancellation
is cooperative at a bounded computation boundary. Historical corrections require
an explicitly authored availability clock; source quality is not invented. MR06
still owns trusted deployable installation and the existing QuantLib source-to-wheel
release restriction. MR05/MR07 retain complete candidate/runtime/OMS acceptance;
MR15 owns launch capacity and latency budgets. G2–G5, QR onboarding, deployment,
live orders and capital activation are not accepted by this record.

Reversal preserves all retained stores and selects the prior feature generation
or prior compatible installed workspace. Restore to a new destination; do not
replace an active worker environment or edit a checkpoint to change its identity.
