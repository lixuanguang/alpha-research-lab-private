# Whole-Artifact Supply Chain

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | B08 |
| Operating track | Solo bootstrap |
| Package status | Partial |
| Accountable owner role | Platform |
| Dependencies | B07 and A07, provisionally ready with open external findings |
| Risk class | R2 shared sensitive, compatibility-window change |
| Applicable gates | QG01-QG06, QG09-QG15 |
| Required reviewers | Platform Code Owner plus one independent Data, Model, or Domain reviewer; independent Security review for the supply-chain control |
| Machine-readable policy | [Artifact supply-chain policy](artifact-supply-chain.toml) |
| Applicable ADRs | [Build and developer tooling](decisions/0001-build-and-developer-tooling.md), [deployment and activation](decisions/0006-deployment-and-activation.md) |

## Objective and boundary

B08 binds one complete artifact file to an SPDX 2.3 SBOM, SLSA v1 provenance,
test evidence, source commit, Bazel target, build platform, all build locks, the
locked toolchain, policy, and a Sigstore bundle over the canonical manifest.
Consumers must provide the exact `sha256:<digest>` of the artifact and repeat all
policy and signature checks. Unknown fields, missing evidence, mutable names,
symlinks, digest drift, untrusted signing context, or revoked identity fail closed.

The artifact input may be a binary or a deterministic archive produced by an
owning target. B08 does not define how a container, model, configuration bundle,
or later domain artifact is built. It secures that opaque, whole output. Archive
members whose names contain `.so`, `.so.`, `.dylib`, or `.dll` must also appear in
the SPDX file inventory, preventing native/shared libraries from disappearing
behind a Python or archive-level record.

## Build contract

`create` accepts one non-empty regular artifact, an allowed kind, an explicit
Bazel label, a full lowercase Git commit, and at least one non-empty test report.
It invokes the exact Nix-locked Syft 1.51.1 with file metadata enabled and update
checks disabled. B08 normalizes Syft's creation timestamp, namespace, name, and
array ordering, then emits canonical newline-terminated JSON. SLSA provenance
records the subject digest, source revision, builder and build-type identities,
external build parameters, four immutable lock digests, and the B03/B07-governed
toolchain digest. A staging directory is renamed only after every check succeeds;
failure removes the incomplete candidate.

Example lifecycle commands are deliberately separate:

```sh
uv run --frozen alpha-governance-artifacts create \
  dist/service.zip binary //platform/service:release "$GIT_COMMIT" \
  build/test-results.json build/candidate
uv run --frozen alpha-governance-artifacts sign \
  build/candidate github_protected_main
uv run --frozen alpha-governance-artifacts publish \
  build/candidate sha256:<artifact-digest> build/local-artifact-registry
uv run --frozen alpha-governance-artifacts verify \
  build/local-artifact-registry/sha256/<artifact-digest> sha256:<artifact-digest>
```

The first command creates an unsigned candidate, never a releasable artifact.

## Signing, publication, and consumption

`sign` invokes Cosign 3.1.3 `sign-blob` with a Sigstore bundle only when the
caller selects `github_protected_main`, GitHub reports a protected `main` ref,
and `GITHUB_SHA` equals provenance. The repository stores no key, token, signing
certificate, or credential. The external protected workflow identity, OIDC
permission, transparency service, and approval remain B08-F02 evidence and are
not activated by this package.

`publish` first performs complete consumer verification, then writes exactly once
below `sha256/<artifact-digest>`. This repository-local content store proves
immutability and rollback behavior; it is not the production artifact registry
owned by I01. A pre-existing digest is rejected rather than overwritten.

`verify` requires a non-revoked configured signer, a non-empty Sigstore bundle,
Cosign verification constrained to the exact workflow identity and OIDC issuer,
and exact artifact, manifest, SBOM, provenance, test, lock, toolchain, and policy
digests. It never resolves a tag or chooses a favorable fallback. Signature,
provenance, native-library, immutable-reference, and tamper failures stop
publication and consumption.

## Quality gates and evidence

The A04 facts classify B08 as R2: shared-domain blast radius, shared/candidate
materiality, shared-sensitive security effect, compatibility-window reversal,
and computational materiality, with no capital, economic, model, or trading
effect. A04 therefore requires QG01-QG06 and QG09-QG14. The blueprint adds QG15
for promotion and consumer admission. The synthetic partial evidence bundle at
[`b08-r2-partial`](../governance/evidence/examples/b08-r2-partial/manifest.toml)
records those exact gates and no approvals or waivers.

Repository tests cover deterministic success; archive/native coverage; missing,
malformed, duplicate, unknown, and unsafe input; tool absence/version/failure;
unsigned, tampered, mutable, and revoked-signer rejection; digest-only immutable
publication; and CLI failure. The real locked executables' version contracts are
also checked by Nix. Deterministic process doubles exercise the credential-free
local signing boundary; they are not evidence of a real cryptographic signature.

## Migration, rollout, rollback, monitoring, and runbook

Migration is additive: B08 admits Syft and Cosign through the existing locked Nix
and B07 records, adds an artifact target to the governed topology, and places its
offline policy check in Make, pre-commit, Bazel, and full CI. No existing artifact
is grandfathered. A later producer must create a new conforming bundle.

Rollout stops at repository-local validation. External rollout requires the
findings below to close on an exact commit before a registry or consumer may rely
on B08. Rollback is a reviewed revert of B08 and its two tool records; unpublished
candidates and the local test registry may be discarded. Already published
digests are never mutated or re-signed in place. Consumers remain fail closed
rather than accepting legacy unsigned output.

The policy command, failed lifecycle command, Cosign verification, and consumer
rejection are the current monitoring signals. On failure: retain the bundle and
logs; stop publish/consume; compare artifact, manifest, SBOM, provenance, lock,
toolchain, policy, and signature identities; revoke a suspected signer in policy;
rotate it externally; rebuild from reviewed source; and verify a new digest. Do
not overwrite or reactivate the rejected digest. There is no deployed alert,
registry, signing service, SLO, or on-call route in this package.

## Deferred findings

| Finding | Owner | Closure condition |
| --- | --- | --- |
| B08-F01 | Domain Architecture | Named Platform, Security, SRE, and independent domain reviewers resolve findings and approve the exact commit |
| B08-F02 | Platform CI | Protected builds prove supported-platform reproducibility, keyless identity and transparency inclusion, immutable registry retention, and real consumer rejection on the exact commit |
| B08-F03 | Security | Independent tamper, signer compromise/revocation/rotation/recovery, and target native/container completeness drills pass and are retained |

These findings are not waivers. B08 remains partial under solo bootstrap.

## Non-goals and successor

B08 does not implement I01's production registry or release manifest, K03's
organization-wide release enforcement, domain artifact builders, deployment,
activation, credentials, data infrastructure, models, accounts, venues, capital,
or risk authority. It does not implement C01. Once repository-local B08 evidence
passes, the next documented selector in the active adoption sequence is `C01`.
