# ADR 0012: Wheel-only source admission

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A02 |
| Status | Proposed |
| Decision owner | Platform |
| Decision date | 2026-09-04 |
| Review date | 2026-12-03 |
| Supersedes | None |
| Approval evidence | Pending; B07-F01 |

## Context

C03's QuantLib candidate publishes hashed native wheels but no PyPI source
distribution for surveyed 1.40 or current 1.43. B07 required every Python package
to carry a hashed `sdist` in `uv.lock`; it could not express equivalent upstream
source evidence. The roadmap does not exempt candidates from admission. This
change repairs B07 and does not install QuantLib or implement C03.

## Decision drivers

- Preserve exact source and binary identity, complete lock coverage, native
  platform availability, license decisions, and fail-closed admission.
- Authenticate build claims without implementing cryptography or trusting a
  producer's Boolean verification result.
- Keep offline checks independent of network availability and mutable trust caches.
- Preserve every existing admission without a policy migration.

## Considered alternatives

- **Remove the source requirement:** loses a control and is rejected.
- **Record source URLs and publication attestations:** publication identifies the
  uploader, not the build inputs; it cannot establish the required relationship.
- **Build repository-owned QuantLib wheels:** requires separate native build,
  reproducibility, platform, and publication work outside this fix.
- **Explicit authenticated upstream-source alternative:** selected; requires a
  stronger source-to-artifact link than a standalone source-archive hash.

## Decision

Add optional `wheel_source_admissions` to B07 policy version 1. Absence preserves
the sdist requirement. Each record matches an exact admitted native package and
covers every locked wheel. An alternative cannot replace an existing `sdist`
key, including a malformed one.

The [dependency contract](../dependency-admission.md#wheel-only-source-evidence)
defines immutable source archives, approved licenses, exact builder/build type,
build parameters, signer and issuer, and digest-bound local trust roots and
per-wheel Sigstore v0.3 bundles. Require in-toto v1 SLSA provenance v1 matching the
exact wheel subject and complete ordered source-material list. Use already
admitted Cosign 3.1.3 with claims, certificate transparency, and transparency-log
verification enabled. Reject publication-only evidence and insecure options.
No B07 import of dependent B08 code or new dependency is introduced.

## Consequences

Existing admissions need no changes or Cosign invocation. Wheel-only packages
gain an admission route, but must supply adequate signed build evidence. No
wheel-source records are activated here. In particular, QuantLib's PyPI publish
attestations alone do not admit it. Source completeness, including native-library,
binding, and build-recipe inputs, remains an explicit Platform/Security review duty.

Evidence reads are bounded and reject noncanonical paths, missing files and
symlinks. Verification uses private copies of checked bytes, exact argv, a
restricted environment, bounded diagnostics, and a 60-second per-command deadline.
Missing tools and unverifiable evidence block admission.

## Migration and rollout

The optional field preserves existing version-1 policies and current locks. The
existing checker, Make, pre-commit, and CI paths share enforcement. No root command,
CI lane, resource inventory, or A08 readiness change is needed. Future admissions
must retain evidence files as declared build inputs and update locks, reviews,
source records and evidence together. Nothing is deployed or activated.

## Reversal plan

Revert implementation and documentation together on a semantic or verifier defect.
There are no current wheel-only consumers to migrate. Once one exists, remove or
replace its dependency and lock/admission record before reverting support. Preserve
failure and source evidence throughout the shared-contract compatibility lifecycle.

## Review and evidence

This is R2: no capital, shared domain/materiality, shared-sensitive security,
compatibility-window rollback, and no economic/model/trading trigger. Gates are
QG01-QG06 and QG09-QG14. Require Code Owner, independent domain, Platform/SRE and
Security review under B07 ownership. No independent acceptance is claimed.

The change exceeds the preferred 400 lines because parser, enforcement, failure
tests and policy documentation must ship together. Review the model/parser, then
verifier/lock integration, then tests/evidence as one coherent change; these are
review areas, not new roadmap selectors. Synthetic runner success is not
cryptographic evidence. Retain B07-F01 (independent review), B07-F02 (protected
Linux and real target evidence), and B07-F03 (qualified source/license/security
review). Review again on the stated date or any verifier, trust, profile, platform,
or first-consumer change. B07 remains partial and grants no release, promotion,
deployment, activation, credentials, market access, capital, or expanded risk authority.

Primary references: [PyPI publish predicate](https://docs.pypi.org/attestations/publish/v1/),
[SLSA provenance v1](https://slsa.dev/spec/v1.1/provenance),
[Cosign 3.1.3 verifier](https://github.com/sigstore/cosign/blob/v3.1.3/cmd/cosign/cli/verify/verify_blob_attestation.go),
[QuantLib 1.40](https://pypi.org/project/QuantLib/1.40/#files), and
[QuantLib 1.43](https://pypi.org/project/QuantLib/1.43/#files).
