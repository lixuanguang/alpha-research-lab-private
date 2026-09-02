# ADR 0009: Remote execution service

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A02 |
| Status | Proposed |
| Decision owner | Platform |
| Decision date | 2026-09-02 |
| Review date | 2026-12-01 |
| Supersedes | None |
| Approval evidence | Pending; B06-F01 |

## Context

B06 requires authenticated Bazel remote caching and execution with isolated trust,
deterministic sharding, non-masking flake controls, resource budgets, and a verified
local fallback. The repository has no admitted or provisioned remote execution service.

## Decision drivers

- Authenticate every remote request without committing credentials.
- Isolate cache writes by repository, trust context, toolchain, platform, and policy version.
- Preserve deterministic full-suite equivalence and a remote-disabled local fallback.
- Bound concurrency, retries, timeouts, test population, and quarantine duration.
- Prevent infrastructure retry or quarantine from masking a failing or flaky test.

## Considered alternatives

- **Self-hosted BuildBuddy:** preserves protocol compatibility but adds an unimplemented
  operational service and capacity boundary.
- **EngFlow or another REAPI provider:** viable but not selected because it would add a
  second unresolved provider contract.
- **Cache-only HTTP storage:** does not meet the remote execution objective.
- **Unauthenticated or shared-namespace cache:** rejected because it cannot satisfy the
  trust and poisoning restrictions.

## Decision

Select BuildBuddy Cloud as the proposed B06 REAPI v2 cache and executor. Use only TLS
`grpcs` endpoints, an isolated versioned instance name, a protected API-key header
injected outside workspace configuration, verified downloads, bounded infrastructure
retries, and clean main-push uploads. Keep the B05 local full lane authoritative until
the external and independent-review findings close. B07 must complete final dependency
admission before this decision can become accepted.

## Consequences

The repository gains one explicit provider contract and deterministic clients without
claiming that an account or credential exists. The provider is an external availability,
security, cost, and retention dependency. Disabling the guarded CI variable restores the
remote-disabled local path; there is no automatic remote-to-local fallback that could
hide remote failures.

## Migration and rollout

Provision a protected BuildBuddy organization, least-privilege main-push key, namespace,
retention settings, quotas, and evidence retention only after review. First keep the B05
full local lane authoritative, enable the B06 variable for protected main pushes, and
compare the complete two-shard union with the same-revision local suite using the fixed
seed. Promotion of the remote lane to authority is outside B06 and prohibited while any
finding remains open.

## Reversal plan

Disable `REMOTE_EXECUTION_ENABLED`, revoke the key when compromise is suspected, and
run `make remote-local-fallback-check`. The local configuration explicitly clears remote
cache and executor endpoints and disables uploads. Preserve failure evidence without
credentials, then revert the reviewed client/configuration change if local equivalence
or repository checks do not recover.

## Review and evidence

Repository tests mutate authentication, namespace, shard, retry, flake, budget, and
fallback controls and verify complete non-overlapping shard assignment. Target-service
poisoning, tenant isolation, credential rotation/revocation, outage, performance, and
same-revision local/remote equivalence remain retained-evidence requirements. Roll back
by disabling `REMOTE_EXECUTION_ENABLED`, revoking the key, and running
`make remote-local-fallback-check`.

## Evidence and open questions

Evidence is governed in `docs/governance/evidence/examples/b06-r2-partial`. Repository
tests mutate authentication, namespace, shard, retry, flake, budget, and fallback controls
and verify complete non-overlapping shard assignment. Target-service poisoning, tenant
isolation, credential rotation/revocation, outage, performance, and same-revision
local/remote equivalence remain retained-evidence requirements. Open findings B06-F01
through B06-F03 cover independent approval, protected service provisioning/equivalence,
poisoning and credential drills, and B07 admission.

Protocol and provider behavior must be checked against the official
[Bazel remote execution](https://bazel.build/remote/rbe),
[Bazel remote caching](https://bazel.build/remote/caching),
[BuildBuddy RBE setup](https://www.buildbuddy.io/docs/rbe-setup/), and
[BuildBuddy authentication](https://www.buildbuddy.io/docs/guide-auth/) documentation
at review and on provider or Bazel changes.
