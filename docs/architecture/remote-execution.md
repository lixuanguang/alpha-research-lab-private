# B06 remote cache, execution, sharding, and flake control

## Status and boundary

B06 is **partial** under the `solo_bootstrap` track. It selects BuildBuddy Cloud
through proposed [ADR 0009](decisions/0009-remote-execution-service.md) and implements
the repository-owned client, policy, sharding, flake, budget, local-fallback, and CI
boundaries. No account, credential, quota, remote namespace, deployment, or service
admission is asserted. Those external facts remain open, and B07 owns final dependency
admission.

The machine-readable source of truth is [remote-execution.toml](remote-execution.toml).
`alpha-governance-remote-execution` validates it fail closed before any remote command.

## Trust and cache integrity

Remote cache reads, writes, and execution use REAPI v2 over `grpcs` and one instance
name isolated by repository, trusted lane, Bazel version, Python version, platform, and
contract version. Only a clean `refs/heads/main` push whose `GITHUB_SHA` equals checked
out `HEAD` may receive the protected API key or upload results. Pull requests and local
developer contexts are untrusted and remain remote-disabled.

The key is never stored in workspace Bazel configuration. The runner accepts it only
from `BUILDBUDDY_API_KEY`, creates a mode-0600 temporary Bazel rc, removes the variable
from the child environment, and deletes the temporary file after Bazel exits. Workspace
credential helpers are prohibited. Bazel download verification is mandatory, concurrent
source changes are blocked, the disk cache is disabled in the remote lane, and remote
failure never silently falls back within that lane. These controls limit cross-context
poisoning; target-service poisoning and tenant-isolation drills remain finding B06-F03.

## Deterministic sharding and flakes

The runner queries the complete Bazel test graph and assigns each unique sorted label to
one of exactly two shards using the first 64 bits of
`SHA256(seed + NUL + label) modulo shard_count`. The committed seed makes assignment
independent of query order. Duplicate, malformed, empty, oversized, or out-of-range
inputs block. Empty individual shards succeed, but an empty complete graph blocks.

Normal tests run once: no whole-test retry can turn a flaky result green. Bazel's two
retries apply only to remote RPC infrastructure. A quarantine is diagnostic, owner- and
expiry-bounded by policy, repeats each listed target five times with every run required
to pass,
and never removes it from the authoritative normal shards. There are no active
quarantines.

## Resource budgets and interfaces

The remote lane is capped at 25 jobs, two shards, 1,000 test targets, two RPC retries,
three seconds maximum retry delay, and 60 seconds remote timeout. The verified local
fallback disables remote cache, executor, and uploads and caps local work at four jobs,
four CPUs, and 4,096 MiB.

| Command | Behavior |
| --- | --- |
| `make remote-execution-policy-check` | Offline validation of policy, integrations, evidence, and trust invariants |
| `make remote-build REMOTE_CONTEXT=github_main_push` | Authenticated remote build after clean-main trust checks |
| `make remote-test REMOTE_CONTEXT=github_main_push REMOTE_SHARD_INDEX=0` | One deterministic remote test shard |
| `make remote-quarantine REMOTE_CONTEXT=github_main_push` | Diagnostic repeat lane for active quarantines only |
| `make remote-local-fallback-check` | Complete explicitly remote-disabled local build and test |

The existing B05 full merged-result lane remains authoritative. The optional B06 lane is
enabled only on a main push when repository variable `REMOTE_EXECUTION_ENABLED` is
exactly `true`; protected CI must supply the key. It cannot run for pull-request code.

## Risk and quality gates

The A04 facts are: no capital at risk; shared-domain blast radius; shared/candidate
data-model materiality; shared-sensitive credential privilege; compatibility-window
reversal; computational materiality; and no economic/risk, model, or trading relevance.
They classify B06 as R2. The applicable set is QG01-QG06 and QG09-QG14; the blueprint's
explicit QG02, QG03, and QG11 requirements are contained in that stricter R2 set. QG07,
QG08, and QG15 are not added because B06 changes no economic/risk model and does not
deploy or activate a service.

Required review is one Platform Code Owner and one independent affected-domain reviewer.
Because the boundary handles a shared credential and external execution, SRE and Security
must also review the exact trust, namespace, retention, resource, poisoning, rotation,
revocation, outage, and rollback controls before acceptance. Solo-bootstrap work records
these roles as unavailable findings rather than approvals.

## Migration, rollback, monitoring, and evidence

Migration is opt-in: provision the protected organization/key and quotas, validate the
namespace and retention settings, enable the repository variable, then compare both
shards with the same-revision local B05 full lane. Roll back by disabling that variable;
`make remote-local-fallback-check` is the preserved path. Do not switch B05 authority
until findings B06-F01 through B06-F03 close.

Hosted evidence must retain revision, run, namespace, shard, seed, target set, cache-hit
and execution result, duration, retries, quarantine result, and local-equivalence links.
Alert on authentication denial, namespace mismatch, download verification failure,
unexpected fallback, exhausted RPC retries, missing targets, shard disagreement, flake,
quarantine expiry, resource-budget breach, or local/remote mismatch. On any such signal,
disable the remote lane, run the local fallback, preserve logs without secrets, rotate
or revoke credentials if applicable, and escalate to Platform CI and Security.

Open findings are B06-F01 (independent approval), B06-F02 (protected provisioning and
equivalence), and B06-F03 (security drills and B07 admission).

This package creates no release, deployment, activation, runtime service, credentials,
market access, capital allocation, or expanded risk authority. The documented successor
is B07.
