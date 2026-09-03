# Dependency, License, and Approved-Registry Admission

## Status and authority

Dependency admission (`B07`) is **partial** on the `solo_bootstrap` track. The
machine-readable [admission policy](dependency-admission.toml) is authoritative
for repository-local decisions. It implements the blueprint's direct/transitive
locking, approved source, license, vulnerability, exploitability, maintenance,
platform, native-artifact, patch/EOL, emergency-override, and runtime-install
controls. It does not weaken the B02-B06 contracts that it migrates.

The change is R2: it changes a shared build and security boundary with a
compatibility-window rollback, but creates no production service, privileged
control, model/economic behavior, deployment, activation, market access, or
capital exposure. Its gates are QG01-QG06 and QG09-QG14. Institutional acceptance
requires the Platform Code Owner, an independent domain reviewer, and the SRE and
Security roles required by the affected platform-runtime paths.

## Admission boundary

The admitted dependency identity is the union of five immutable surfaces:

1. `uv.lock` for every direct and transitive Python distribution;
2. `requirements.bazel.txt` as the exact Bazel-runtime subset of that uv lock;
3. `MODULE.bazel.lock` for SHA-256-bound Bazel Central Registry inputs;
4. `flake.lock` for revision- and NAR-hash-bound Nix inputs; and
5. full Git commit pins for every GitHub Action in the current CI workflow.

Only `https://pypi.org/simple` is admitted for Python packages. Every one of the
61 external locked Python packages has an exact version, source-distribution
digest, wheel digests, an approved license disposition, and an explicit
native-artifact fact. The policy separately binds each complete lock surface by
its SHA-256 digest, so a semantically valid but unreviewed graph change still
fails admission. Dependencies may be added only by changing the owning
declaration, complete lock, B07 admission record, tests, and evidence together.
Unknown packages, sources, versions, dependencies, licenses, wheels, platforms,
digests, action refs, fields, or policy states fail closed.

The current supported build platforms are Darwin arm64 and Linux x86_64. A pure
Python dependency needs a platform-independent locked wheel. A dependency with
platform-specific artifacts needs both a Darwin arm64 wheel and a Linux x86_64
manylinux or musllinux wheel, in addition to the digest-bound source record. The
checker does not execute or trust wheel metadata. Target-platform installation
without source fallback remains external acceptance evidence.

Runtime package installation is prohibited. The `src` and `tools` runtime source
trees are scanned for `pip install`, `python -m pip install`, `uv pip install`, and
`uv add` execution. `uv sync --frozen` remains a declared developer/CI bootstrap
operation over the reviewed lock; it is not an application-runtime dependency
installer.

## License, maintenance, patch, and EOL decisions

The repository admits the current Python graph under exact SPDX-style
dispositions for Apache-2.0, Apache-2.0 OR BSD-2-Clause, BSD-2-Clause,
BSD-3-Clause, MIT, MPL-2.0, and PSF-2.0. A package cannot self-declare a new
license group: the policy parser rejects unrecognized expressions and any lock
package missing from the complete disposition set. The migrated Nix, Bazel,
quality-tool, scanner, and remote-service records retain their source, digest,
license, maintenance, platform/native, vulnerability-review, purpose, and
rollback fields.

All admission decisions are reviewed at least every 90 days; ordinary dependency
patch review is capped at 30 days. A new vulnerability, EOL announcement,
unsupported platform, missing wheel, mutable upstream, maintenance failure, or
license change blocks the next lock change until the owner upgrades, replaces,
or records a permitted time-bounded disposition. Qualified license-obligation and
independent Security review remain open findings; the repository-local license
mapping is not legal approval.

## Vulnerability and exploitability signals

The exact `pip-audit==2.10.1` command audits a generated exact requirement for
every package in the validated lock against the PyPI vulnerability service, with
dependency resolution disabled. This avoids silently omitting a platform-marked
package absent from the current host environment. The tool is a signal only: its
own documentation states that it audits dependency trees rather than application
code and cannot establish exploitability. B07 therefore parses its JSON
independently, requires exact coverage and versions for all 61 admitted external
packages, rejects a skip, duplicate, version mismatch, or omitted package, and
blocks every reported vulnerability without an exact repository-owned decision.
Scanner exit codes are not suppressed. See the
[official pip-audit documentation](https://github.com/pypa/pip-audit).

An exploitability decision binds the vulnerability ID, package and affected
version, owner, specific rationale, evidence URL, disposition, and expiry. Only
`not_exploitable` and `temporary_exception` are representable; both expire within
30 days so new advisory or usage evidence forces re-evaluation. There are no
active vulnerability decisions or emergency overrides. An emergency override
has a unique ID, exact component, owner, rationale, HTTPS evidence, and maximum
30-day expiry. It is audited policy state, never an implicit ignore, approval,
release waiver, or permission to bypass simulation, performance, or promotion
controls.

OpenSSF Scorecard 5.5.0 is likewise advisory. The importer requires a fresh
RFC-3339 timestamp, exact upstream repository and 40-hex commit, exact tool
version, and conclusive `License`, `Maintained`, `Pinned-Dependencies`, and
`Vulnerabilities` checks. It deliberately defines no aggregate-score admission
threshold: Scorecard itself describes low scores as heuristic signals, and B07
owns the resulting source, maintenance, vulnerability, and exploitability
decision. See the [official Scorecard project](https://github.com/ossf/scorecard).
Current upstream Scorecard execution requires external forge/API access and is
retained as B07-F03 rather than fabricated locally.

## B02-B06 migration

B07 consumes, validates, and retains the five predecessor records in dependency
order:

| Package | Migrated record | B07 disposition |
| --- | --- | --- |
| B02 | [Build-tool dependencies](build-tool-dependencies.toml) | Exact Bazel, rules, Buf, runtime manifest, and setup action records retained |
| B03 | [Developer toolchain](../../environments/dev/toolchain.toml) | Exact Nix, uv, CPython, Bazel, Git, Make, and B08-owned Syft/Cosign closure records retained |
| B04 | [Engineering-tool dependencies](engineering-tool-dependencies.toml) | Hypothesis and its transitive/native facts reconciled to `uv.lock` |
| B05 | [CI-tool dependencies](ci-tool-dependencies.toml) | The private-key scanner and transitive facts reconciled to `uv.lock` |
| B06 | [Remote-execution policy](remote-execution.toml) | The BuildBuddy service boundary remains guarded; provisioning and service drills stay external findings |

Migration changes admission ownership, not predecessor package status. B02-B06
remain partial until their own external and independent evidence closes. B07 does
not reclassify their evidence, rewrite their synthetic manifests, provision the
remote service, or claim target-environment acceptance.

## Interfaces and failure behavior

The canonical offline check is:

```sh
uv run --frozen alpha-governance-dependencies
make dependency-admission-check
```

The authoritative hosted merged-result lane also runs the live signal:

```sh
make dependency-audit
```

Reviewed external reports can be assessed without letting the producer own the
decision:

```sh
uv run --frozen alpha-governance-dependencies audit-report REPORT.json
uv run --frozen alpha-governance-dependencies \
  scorecard-report REPORT.json github.com/OWNER/REPOSITORY COMMIT_SHA
```

Invalid policy exits `1`; invalid command use exits `2`. Pre-commit uses only the
deterministic offline admission check. The authoritative hosted lane runs the live
vulnerability service after frozen synchronization and before the complete graph.
Network/service failure, partial output, a scanner skip, unknown result, or an
unresolved finding blocks rather than silently continuing.

## Quality-gate evidence

| Gate | Repository-local evidence |
| --- | --- |
| QG01 | Ruff, strict mypy, Bandit, immutable action pins, and runtime-install scanning cover the new code and integrations |
| QG02 | Complete uv/Bazel/Nix/action lock surfaces require immutable source and artifact digests; Bazel remains sandboxed |
| QG03 | Success, boundary, malformed, missing, stale, mismatch, scanner-failure, and CLI paths are deterministic tests |
| QG04 | Exact-set, uniqueness, transitive-closure, license-partition, and supported-wheel invariants are enforced; no numerical behavior changes |
| QG05-QG06 | No domain schema, dataset, PIT state, research result, feature, model, trial, or promotion behavior is introduced |
| QG09 | Installed command, Make, pre-commit, Bazel, frozen uv, and hosted merged-result interfaces consume the same policy |
| QG10 | Registry/lock scans are bounded by the current graph; no runtime-latency or target-host performance claim is made |
| QG11 | Missing sources, hashes, wheels, platforms, decisions, signals, locks, or tool output fail closed; Git rollback is retained |
| QG12 | Licenses, direct/transitive dependencies, vulnerabilities, exploitability, sources, native artifacts, runtime installs, and immutable refs are checked |
| QG13 | Scope, decisions, commands, migration, rollout, rollback, runbook, findings, non-goals, and successor are documented |
| QG14 | Checker and audit failures are the owned repository/CI signals; no deployed dashboard or alert route is claimed |

QG07-QG08 and QG15 are not applicable: B07 adds no cost/capacity model, risk
control, deployment, release, promotion, activation, or executable order path.

## Migration, rollout, rollback, monitoring, and runbook

This is an additive policy and lock migration. It adds `pip-audit` and its exact
transitives to the development lock but changes no runtime package, domain schema,
data, model, persisted state, service, credential, or external registry. Rollout
adds the offline check to Make, pre-commit, Bazel, and the retained uv path, then
adds live vulnerability scanning to the authoritative hosted merged-result lane.

Rollback is a reviewed unit revert of the policy, scanner pins and transitives,
command, tests, integrations, B07 evidence, and A06/A08 state. The last passing
B06 graph remains the rollback target. Do not hand-edit a lock, suppress a scanner
exit, remove a package from the report, or relax a source/license/wheel rule to
recover a failing build.

The runbook is: stop the merge; preserve the exact lock, report, and revision;
identify whether the failure is source/digest, license, vulnerability,
exploitability, maintenance/EOL, platform/wheel, registry, or scanner transport;
upgrade or replace the dependency, or add a complete expiring decision; rebuild
the lock from approved inputs; rerun offline admission, live audit, and the full
lane. No production monitor, page, alert route, on-call service, kill path, or
post-deploy window is created.

## Open findings

| Finding | Owner | Unavailable evidence | Closure condition |
| --- | --- | --- | --- |
| B07-F01 | Domain Architecture | Independent Platform Code Owner, domain, SRE, and Security review | Named reviewers resolve findings and approve the exact policy, graph, dispositions, integrations, rollback, and evidence commit |
| B07-F02 | Platform/CI | Protected exact-commit audit retention, Linux x86_64 wheel installation, approved-registry control, and blocking mutation exercises | Protected CI retains the audit, installs selected wheels without source fallback, and proves unapproved/mutable/unhashed/runtime-install states block |
| B07-F03 | Security | Qualified license review, upstream Scorecard signals, organization registry reconciliation, and independent exploitability review | Qualified and Security reviewers reconcile every component and current signal, resolve obligations/findings, and approve patch/EOL dispositions |

These findings are not approvals or waivers. B07 remains partial and authorizes no
release, promotion, deployment, activation, credential, market access, capital,
venue/account/instrument expansion, or increased risk authority.

## Explicit non-goals and successor

B07 does not emit or verify a whole-artifact SBOM, provenance, signature,
attestation, immutable publication, or consumer admission. Those belong to B08.
It does not implement K05's ongoing vulnerability operations, any analytical or
provider dependency from later packages, domain behavior, a production registry,
deployment, or activation.

The next documented selector is `B08`.
