# Dependency admission reference

This page owns the dependency admission contract, native allowance and supported
commands. The [architecture guide](README.md#dependency-and-release-boundaries)
summarizes its place in the system;
[`dependency-admission.toml`](dependency-admission.toml) is the machine-readable
policy consumed by the checker.

Schema version 5 binds the frozen `uv.lock` to exact package versions, artifact
hashes and URLs, the reviewed PyPI simple index, Darwin arm64 and Linux x86_64
wheel coverage, dependency edges, licenses, and vulnerability coverage. The
checker fixes the lock path and `src`/`tools` runtime scan roots directly.
`uv lock --check` separately ties that lock to the project manifest. The checker
rejects missing, duplicate, mutable or unsafe identities. Development tools
remain outside the runtime package. `pip-audit` must cover the complete admitted
package set, and every finding blocks admission; no vulnerability waivers exist.

## Wheel-only development allowance

An ordinary package must provide a digest-bound source distribution. A native
package without one requires an explicit `wheel_only_allowances` record matching
its admitted name and version. The record declares a rationale, isolated
development/CI usage, an **unverified** source-to-wheel binding, review date and
expiry. Its validity cannot exceed 30 days or extend beyond the policy review
deadline. Duplicate records and an allowance overriding source-distribution
metadata are rejected.

This allowance preserves lock, hash, source-origin, platform, license,
vulnerability and runtime-install checks. It does not authenticate publisher
signatures or establish source-to-wheel provenance. Archived native evidence,
its publication-attestation verifier and the Cosign CI installation have been
removed; historical records remain in Git.

## QuantLib restriction

QuantLib 1.43 is used by the C03 date-convention adapter. Its allowance applies
only to isolated development and CI from **2026-09-04 through 2026-10-04**.
The source-to-wheel binding remains unverified, so the
[artifact boundary](artifact-supply-chain.md) blocks release use for the graph.
Removing the allowance alone does not clear the block: ordinary admission still
rejects its missing source distribution.

Resolve the source-binding requirement with an enforceable admission contract,
or remove the dependency, imports, lock entries and affected tests together,
before enabling release use. Native adapter conformance tests and exact domain
goldens remain behavioral checks, not provenance verification.

## Verified upstream source archives

Status: **implemented**, 2026-09-20, following the founder's explicit approval.
ClearML SDK 2.1.12 has no PyPI source distribution. Schema 5 adds an alternative
for this pure Python package: `source_archives` binds its exact admitted version,
locked wheel URL/SHA-256, upstream commit and source archive SHA-256. The only
accepted upstream archive origin is `clearml/clearml` on GitHub, addressed by a
40-character commit. It cannot replace an existing sdist, authorize a native
package, change the locked wheel, or create an implicit wheel-only exception.
An absent binding restores the ordinary source-distribution requirement.

`validate_repository` invokes the owned `SourceArchiveVerifier` before returning
success, so the existing dependency command, audit and `make check` all enforce
the comparison. On a cold cache it downloads the reviewed archives over HTTPS,
with no redirects, a 32 MiB transfer limit, 15-second socket timeouts and a
60-second elapsed transfer budget checked between reads. Network failures block
admission. The ignored repository-local `.dependency-cache/` contains actual
content-addressed archive bytes, never an authorization marker; each invocation
rehashes and rechecks both archives. A valid cache permits offline verification.
A corrupt entry fails visibly; remove that expendable entry to fetch it again.

The verifier reads archives in memory without extracting or executing upstream
code. It bounds expanded content to 64 MiB and 4,096 members, rejects unsafe or
duplicate paths and special runtime files, and compares the complete `clearml/`
file inventory and bytes, including `.conf` and typing resources. Unselected
upstream documentation/examples are not executed or extracted; their symlinks are
not followed. The wheel may contain only that runtime plus six known dist-info
files. Checks cover name/version, pure-Python tags, the upstream license,
top-level package, entry points parsed from source without execution, and the
complete RECORD inventory/hashes/sizes. Unexpected installation hooks fail.

The actual locked artifacts matched **283 runtime files**. Source commit:
`559467f550c0d23dc3506ee551386c3b59e6b091` (release tag `v2.1.12`). Source SHA-256:
`56fabf73b333d28c6bd6cf031215aa8ae387746b7088f08f5a54b89a4c98f7fa`.
The exact wheel identity remains in the policy and frozen lock. This establishes
runtime byte correspondence to the reviewed source archive; it is not a signed
publisher identity or reproducible-build attestation. New versions require fresh
source/wheel pins, comparison and review. License, platform, lock, vulnerability
and runtime-install checks remain enforced. QuantLib's separate release block
and existing allowance expiry remain unchanged.

## First deployment dependency decision

Status: planned deployment dependency decision, 2026-09-14; the current release block is unchanged.
Before the [first trusted deployment consumer](../roadmap/README.md#trusted-deployment-artifact)
needs an artifact, choose the smallest enforceable path for its actual graph:

- Admit the required QuantLib build/source provenance under an implemented,
  tested policy; or
- Separate pure financial values from the optional date-convention adapter into
  genuinely distinct runtime dependency closures, if the selected spot/collector
  consumer does not use conventions. This requires packaging metadata, public
  import boundaries, dependency policy and tests to agree, including a fresh
  installation of the selected artifact without QuantLib and retained adapter
  conformance in its own closure.

A closure split is a future code/packaging change, not permission to exempt the
current graph. Lazy imports, deleting an allowance or omitting a scan do not
resolve admission. The present policy scans the whole graph; any selected-closure
admission must be implemented and tested before it can permit release. Record
the decision and affected installed/import proof in artifact verification; do not redesign packaging
merely to run synthetic research. Review the existing 2026-10-04 allowance expiry
on its actual deadline even if deployment is later.

## Review and reversal

Re-review on expiry, any dependency/policy change, or the first release consumer.
If the admission contract is defective, revert or correct the affected policy,
lock identity, checker, tests and documentation together. This allowance grants
no deployment, activation, credential, market or capital authority.

## Commands

```sh
uv run --frozen alpha-governance-dependencies
uv run --frozen alpha-governance-dependencies audit
uv run --frozen pip-audit --locked
uv run --frozen alpha-governance-artifacts release-check
```

The last command currently fails with the unresolved native dependency blocker.
