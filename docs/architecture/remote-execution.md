# B06 remote cache, execution, sharding, and flake control (Retired)

This page records the retired B06 proposal and its original trust and evidence
contract. It remains reachable so historical provenance is not rewritten. The
repository no longer runs a remote cache, remote executor, deterministic shard
lane, or remote governance command; local `make check` is the active validation
path.

## Status and boundary

B06 was **partial** under the `solo_bootstrap` track. It selected BuildBuddy Cloud
through proposed [ADR 0009](decisions/0009-remote-execution-service.md) and described
the repository-owned client, policy, sharding, flake, budget, local-fallback, and CI
boundaries. No account, credential, quota, remote namespace, deployment, or service
admission was asserted. Those external facts remain historical open findings; the
proposal was retired before provisioning.

The former machine-readable source was `remote-execution.toml`; that retired
configuration is removed from the active checkout. The former
`alpha-governance-remote-execution` command no longer runs in the active path.

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
| Former `make remote-execution-policy-check` | Historical offline validation of the retired policy |
| Former `make remote-build` / `make remote-test` | Historical authenticated remote lanes; retired |
| Former `make remote-quarantine` | Historical diagnostic repeat lane; retired |
| `make check` | Active local source, policy, test, and package validation |

The former B05 full merged-result lane and optional B06 lane are retired. No repository
variable or protected key enables remote work.

## Evidence and governance

Exact classification, gate state and finding closure conditions were recorded in
the retired `remote-execution.toml` file. Gate definitions live in the
[operations runbook](../governance/operations.md); current state and
validation results are recorded in the [development workflow](../governance/workflow.md).

## Migration, rollback, monitoring, and evidence

Migration was opt-in: it would have provisioned a protected organization/key and quotas,
validated namespace and retention settings, and compared both shards with the same-revision
local B05 lane. The proposal was retired instead; its local `make check` replacement is
the active path and findings B06-F01 through B06-F03 remain historical.

Hosted evidence must retain revision, run, namespace, shard, seed, target set, cache-hit
and execution result, duration, retries, quarantine result, and local-equivalence links.
The retired lane would have alerted on authentication denial, namespace mismatch, download
verification failure, unexpected fallback, exhausted RPC retries, missing targets, shard
disagreement, flake, quarantine expiry, resource-budget breach, or local/remote mismatch.
Those remote signals are no longer active repository obligations.

The [development workflow](../governance/workflow.md) owns daily evidence. This
package creates no release, deployment, activation, runtime-service, credential,
market or capital authority.
