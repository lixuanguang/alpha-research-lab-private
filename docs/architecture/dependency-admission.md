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
74 external locked Python packages has an exact version, wheel digests,
an approved license disposition and an explicit native-artifact fact. The 73
ordinary packages have source-distribution digests; C03 QuantLib 1.43 uses the
explicit bounded bootstrap source/publication profile below. The policy separately
binds each complete lock surface by its SHA-256 digest, so a semantically valid but unreviewed graph change still
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

### Wheel-only source evidence

[ADR 0012](decisions/0012-wheel-only-source-admission.md) adds an explicit alternate
source path for native packages published without a PyPI sdist. All 73 ordinary
packages retain their existing sdist records. C03 activates one bounded bootstrap
admission for QuantLib 1.43 through 2026-10-04. Two explicit evidence profiles are
available: authenticated SLSA build evidence and bounded bootstrap publication evidence. Neither is an
automatic exemption. The first consumer is recorded in the [C03 contract](financial-units.md).

The optional root `wheel_source_admissions` array contains strict records with
the fields below. Omitting it preserves the existing behavior. An entry must match
an exact native package already declared in the license and native-package policy.
Duplicate or stale entries fail. A present `sdist` key, even malformed, cannot be
overridden. All wheel hashes, approved registries, platform, transitive, license,
vulnerability, review-expiry and complete-lock checks remain in force.
This profile continues to require signed build evidence; it never falls back to
publication evidence when a signature, material or subject check fails.

| Field | Required evidence |
| --- | --- |
| `name`, `version`, `owner_role`, `rationale` | Exact admitted native package, `platform` owner, and 40-2000 character source-path justification |
| `sources` | 1-100 ordered source records: credential-free HTTPS `uri` containing its exact 40-hex `revision` as a path segment, lowercase SHA-256 `sha256`, and admitted `license_expression` |
| `builder_id`, `build_type` | Exact HTTPS SLSA builder and build-type identities |
| `build_parameters_sha256` | SHA-256 of UTF-8 JSON containing `externalParameters` and `internalParameters`, with sorted keys, compact separators, ASCII escaping, and no trailing newline or non-finite values |
| `certificate_identity`, `oidc_issuer` | Exact credential-free HTTPS identity and issuer; no regular-expression matching |
| `trusted_root` | Repository-relative `path` and SHA-256 of retained Sigstore trusted-root JSON |
| `wheels` | 1-100 records containing exact package/version wheel `filename`, `sha256`, and a `bundle` with repository-relative `path` and SHA-256 |

Each bundle must use `application/vnd.dev.sigstore.bundle.v0.3+json` and a DSSE
`application/vnd.in-toto+json` payload. The statement is in-toto v1 with SLSA
provenance v1, a single exact wheel subject, and a predicate with `buildDefinition`
and `runDetails`. The build definition has exactly `buildType`,
`externalParameters`, `internalParameters`, and `resolvedDependencies`. The two
parameter fields are JSON objects. Materials must exactly equal the ordered
source list projected to `{"uri": URI, "digest": {"sha256": SHA256, "gitCommit": REVISION}}`.
The run details require `builder: {"id": BUILDER_ID}` and may carry standard
`metadata` and `byproducts`. Unknown fields outside those metadata objects,
duplicate JSON keys, unsupported profiles, or mismatched identities fail closed.

Cosign 3.1.3 authenticates the same checked bundle bytes using the retained trust
root, exact signer/issuer, SLSA type and locked SHA-256, with claims and transparency
checks enabled. The command uses the pinned Nix developer environment when Cosign
is not on the host PATH. Its explicit `--trusted-root` and local bundle avoid
mutable trust-cache/network resolution. Missing/incompatible tools, nonzero exits,
or 60-second timeouts block admission. Evidence reads are capped at 5,000,000 bytes,
reject symlinks at every path component, and verify hashes before copying inputs
to a private temporary directory. No archive is executed or extracted.

The signed materials bind asserted build inputs to exact wheel bytes. This is not
a claim of reproducible native builds, a particular SLSA assurance level, safe
source code, or independent approval. Platform/Security must review that sources
include the complete native-library, Python-binding and build-recipe inputs, that
the builder/signer is appropriate, and that retained trust roots are authentic.
Archive bytes are digest-identified as with existing sdist records; admission does
not fetch them. Each newly locked wheel, source correction, signer change, trust
rotation or build-parameter change requires a new reviewed record and replay.

### Bounded solo-bootstrap publication evidence

The optional root `bootstrap_wheel_admissions` array permits an exact native
package without a PyPI sdist to be evaluated for isolated development and CI.
It explicitly accepts an unverified source-to-wheel relationship; publication
signatures do not become build provenance. A package cannot appear in both
profiles. Unknown, stale, duplicate or conflicting records fail closed.

Each record shares `name`, `version`, `owner_role`, `rationale`, `sources`,
`certificate_identity`, `oidc_issuer`, `trusted_root` and `wheels` with the build
profile. All corresponding source, license, path, digest, registry and complete
wheel-set checks still apply. It additionally requires:

| Field | Required value or evidence |
| --- | --- |
| `usage` | Exactly `isolated_development_and_ci` |
| `source_to_wheel_binding` | Exactly `unverified`; no claimed build assurance |
| `finding_id` | Unique `B07-DEP-NNN` identity for the residual evidence gap |
| `reviewed_on`, `expires_on` | A positive window of at most 30 days, starting no earlier than the policy date and ending by its review deadline |
| `residual_risk`, `closure_condition` | 40-2000 character explanation of the accepted binary/source risk and how to close it |
| `source_review` | Digest-bound retained review of source revisions, archive hashes, source completeness and license disposition |
| `security_review` | Digest-bound retained vulnerability, maintenance, publisher/trust and permitted-use assessment |
| `native_inventory` | Digest-bound retained inventory of native and bundled components, with known coverage gaps stated |
| `compatibility_report` | Digest-bound retained installation and compatibility results with platform, version and test identities; unavailable target evidence stays explicit |

The owner must be `platform`. Every report is required, bounded, nonempty and
hash-checked using the same safe file reader. Report presence does not establish
independent approval or the truth/completeness of its content. The owner must
review the actual evidence; unresolved local defects cannot be deferred as
external findings. Target-platform and qualified review obligations remain
B07-F02/F03. Isolated execution is an environment obligation, not a claim that
this metadata parser sandboxes imported Python/native code.

The validator accepts only in-toto v1 PyPI publish statements, an exact wheel
subject, and a null or empty-object predicate body. The same pinned Cosign, exact
signer/issuer, trusted-root, claims, certificate-transparency and transparency-log
checks apply. No insecure verifier flag, synthetic approval, source-hash-only
fallback or runtime package installation is permitted. The record must be in
effect on the validation date, inclusive of its expiry date. Expired and
not-yet-effective records block repository validation; there is no automatic
renewal. CLI success lists each bootstrap package, owner, expiry and open finding.

**Artifact boundary:** B08 calls `require_release_admission()` before artifact
creation, before signing, and during consumer verification (including publication).
Any bootstrap record blocks the entire current dependency graph at those
boundaries, even if expired. There is no target-specific exemption because the
current graph cannot prove a package is excluded from a particular artifact.
Removing the record alone also fails: B08 rechecks the dependency policy, Python
source/wheel graph, review deadline and admitted lock hashes. Replace the record
with complete build evidence, or remove/replace the dependency and update its
declarations, locks and admissions together. Ordinary sdist admissions retain
their existing evidence contract. No new B08 CLI, signing permissions or registry
is introduced.

This is a development admission tier, not SLSA certification or a production
waiver. B08's own artifact provenance, signatures and release controls remain
mandatory. The blueprint's B07 source/lock/license controls and B08 artifact
controls apply at their respective boundaries; its institutional milestones are
not completed by this tier.

C03 admits QuantLib 1.43 for isolated development/CI with all 10 locked wheel
publication bundles, immutable source records, local review/compatibility/native
evidence and an expiry of 2026-10-04. Source-to-wheel binding remains unverified
under Platform-owned B07-DEP-001; all graph artifact release is denied. The
signed-build route remains available. See the [C03 evidence](../governance/evidence/examples/c03-r2-partial/manifest.toml).

The [QuantLib prerequisite investigation](../governance/evidence/quantlib-1.40-investigation/README.md)
retains real Darwin/Linux publication-signature checks, immutable source hashes,
observed upstream evidence gaps, and the native-build and artifact-source closure
requirements for the stronger profile. Those historical observations remain valid;
the bootstrap policy revision changes the permitted scope of use.

The existing command enforces this profile automatically. On failure, stop the
dependency update, retain package/version, wheel digest, bundle and verifier
diagnostic, reconcile sources/provenance with Platform and Security, then rerun
admission and full checks. Do not disable claims, SCT or transparency-log checks.
Rollback is a reviewed revert together with removal/replacement of any dependent
wheel-only package and its lock entries. Reverting the active QuantLib admission
also requires removing or replacing the C03 adapter and its declared dependency.
Existing B07-F01-F03 retain independent, protected-CI and qualified-review closure.

Runtime package installation is prohibited. The `src` and `tools` runtime source
trees are scanned for `pip install`, `python -m pip install`, `uv pip install`, and
`uv add` execution. `uv sync --frozen` remains a declared developer/CI bootstrap
operation over the reviewed lock; it is not an application-runtime dependency
installer.

## License, maintenance, patch, and EOL decisions

The repository admits the current Python graph under exact SPDX-style
dispositions for Apache-2.0, the admitted Apache/BSD alternatives, BSD-2-Clause,
BSD-3-Clause, ISC, MIT, MPL-2.0, PSF-2.0, and NumPy's exact composite SPDX
expression. A package cannot self-declare a new
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
independently, requires exact coverage and versions for all 73 admitted external
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

C02 extends the admitted graph with exact `exchange-calendars==4.13.2` and its
eight transitives. NumPy and pandas are recorded as native-wheel packages for both
supported platforms, and NumPy is constrained to 2.4.6 for the documented
warnings-as-errors compatibility boundary. This record does not make the calendar
source authoritative or close B07's qualified and target-platform findings.

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

## Evidence policy

Gate definitions live in the [quality-gate catalog](operations.md#quality-gate-catalog).
Exact B07 classification, gate state, dependency finding and closure conditions
live in [dependency-admission.toml](dependency-admission.toml); current package
state and finding IDs are rendered in the
[program status](../governance/program-status.md).

## Migration, rollout, rollback, monitoring, and runbook

This is an additive policy and lock migration. B07 originally added `pip-audit`
and its exact transitives; C02 now adds the admitted calendar graph without
changing B07's partial status. It changes no persisted state, service, credential,
or external registry. Rollout
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

## Governance references

The [development workflow](../governance/workflow.md) owns daily evidence. B07
admits development dependencies but grants no artifact release, deployment,
activation, credential, market or capital authority.
