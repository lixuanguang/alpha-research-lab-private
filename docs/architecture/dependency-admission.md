# Dependency admission reference

This page owns the dependency admission contract, native allowance and supported
commands. The [architecture guide](README.md#dependency-and-release-boundaries)
summarizes its place in the system;
[`dependency-admission.toml`](dependency-admission.toml) is the machine-readable
policy consumed by the checker.

Schema version 4 binds the frozen `uv.lock` to exact package versions, artifact
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

## First deployment dependency decision

Status: planned R1 decision, 2026-09-14; the current release block is unchanged.
Before the [first trusted deployment consumer](../roadmap/capability-milestones.md#r1-trusted-artifact-before-first-deployment)
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
the decision and affected installed/import proof in R1; do not redesign packaging
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
