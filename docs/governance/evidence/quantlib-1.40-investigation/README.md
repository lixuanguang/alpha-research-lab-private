# QuantLib 1.40 prerequisite investigation

## Result and authority

**Historical investigation:** the blocked result below describes the policy at
the time of investigation. The subsequent
[bounded bootstrap policy revision](../../../architecture/README.md#dependency-and-release-boundaries)
permits a separate publication-evidence route with owned review, expiry and
artifact-release denial. QuantLib is still unadmitted; a complete record and
the owning package's local checks are required. The source-to-build gap remains.

**Blocked: QuantLib is not admitted and C03 remains unimplemented.** This
2026-09-04 investigation follows the request to try resolving C03's dependency
prerequisite. It records new observations against clean main
`c09d1f175c6709daab94faccfcf4121e594ce112`; that SHA identifies the investigation
base, not independent review or acceptance of this report.

The [current dependency and release boundary](../../../architecture/README.md#dependency-and-release-boundaries)
and [ADR 0012](../../../architecture/decisions/0012-wheel-only-source-admission.md)
remain unchanged. This is supplemental investigative evidence, not an A05
acceptance manifest, dependency admission, signature over a build claim, or
institutional approval. B07 remains partial on the solo-bootstrap track.

The subsequent [public-evidence recheck](public-evidence-recheck.md) extends the
inspection to all 42 wheels across 1.40 and 1.43 and prepares an unsent upstream
request. It found no SLSA build evidence and does not change the blocked result.

## Work completed

- Queried the official [PyPI 1.40 metadata](https://pypi.org/pypi/QuantLib/1.40/json):
  16 wheels, no source distribution. QuantLib remains absent from declarations,
  locks and admission records.
- Retrieved the public attestations for the Darwin arm64 and Linux x86_64
  CPython ABI3 wheels. Each contains a publication predicate with a null body,
  not SLSA build inputs. Repacked the existing signed bytes losslessly into
  Sigstore v0.3 bundles. The Darwin envelope and verification material exactly
  match the previously retained B07 fixture.
- Verified both publication signatures using Cosign 3.1.3, the exact upstream
  workflow identity, GitHub OIDC issuer, subject digest and retained public trust
  root. Both passed. For each wheel, a SLSA predicate requirement, wrong subject
  digest and wrong signer were rejected: two successes and six expected failures.
  All verification ran on Darwin; this is not Linux installation/build evidence.
- Queried the upstream GitHub attestation endpoint for both exact wheel subjects;
  each returned HTTP 404. The wheel repository's releases endpoint returned an
  empty list. These observations do not establish that no evidence exists
  anywhere or that an authenticated query would have the same result.
- Inspected the [release-pinned build workflow](https://github.com/lballabio/quantlib-wheels/blob/fa275d5ea06e13d0dd2f475a3ceb857b8f388443/.github/workflows/wheels.yml)
  and its Linux setup script. They contain no build-attestation step. The
  current workflow was also inspected; it supplies no such step. That moving
  snapshot is diagnostic only; it is not a proposed dependency input.
- Downloaded both source tarballs from the immutable wheel-repository commit.
  Their SHA-256 hashes match the official release asset metadata. Inspected their
  license texts and Python build recipe without running upstream code. Git release
  tags were resolved to commits; tag signatures and generated-tarball equivalence
  were not verified.

The raw signature bundle and exact observations, hashes, safe diagnostics and
source URLs are retained in [observations.json](observations.json) and
[linux-publish.sigstore.json](linux-publish.sigstore.json). Darwin's bundle and
the trust root are retained in this directory and the sibling
[`quantlib-1.43`](../quantlib-1.43/README.md) evidence directory, respectively, and are
hash-bound by the observations. Source archives are not vendored. Their verified
hashes are:

| Source archive | SHA-256 |
| --- | --- |
| QuantLib-1.40.tar.gz | `5d6b971b998b8b47e5694dfc4851e9c8809624ff24c620579efc7fedef9dc149` |
| QuantLib-SWIG-1.40.tar.gz | `768bc34191b67128c1bd01a01824e701e050130bf7232c77bf8a5129c3455a5e` |

## Why the missing evidence cannot be synthesized locally

The [PyPI publication predicate](https://docs.pypi.org/attestations/publish/v1/)
authenticates publication of exact bytes. Its signed statement does not name the
native-library, binding, Boost, compiler or build parameters. Adding those fields
would invalidate the existing signature. Downloading matching sources or signing
an investigator's own account of the upstream build cannot establish that the
upstream builder used those sources.

Copying the upstream recipe is not a governed reproducible build. The inspected
macOS job installs unpinned Homebrew Boost. Linux downloads Boost 1.89.0 without
checking its digest in the script. Action tags, compiler/SDK inputs, container
images and Python build tooling need explicit repository admission and pins.
The binding setup discovers `quantlib-config` on PATH. The source tarball includes
generated C++ bindings, so preserving that tarball avoids a new SWIG generation
step, but does not eliminate the native compiler and toolchain requirements.

A locally rebuilt wheel would be a new artifact with new evidence obligations.
There is also an artifact-source prerequisite: B07 currently allows only the
PyPI index and `files.pythonhosted.org` wheel URLs. A private wheel store, local
path, GitHub asset or Nix output is not an admitted replacement. B08's current
signed-manifest flow is not a B07 per-wheel SLSA attestation producer.

No source code, native compiler, dependency, workflow, signer, registry or
credential was added or activated. The local Docker client had no running daemon
socket; no Linux build was attempted. A workstation build alone would not close
the signed-build or artifact-source requirements.

## Concrete closure paths

| Path | Owner | Required deliverable and closure condition |
| --- | --- | --- |
| Obtain upstream build evidence | Platform with upstream builder; Security reviews trust | Authentic SLSA v1 evidence for every wheel selected into the eventual lock, with the exact subject, builder, parameters and complete native-library/binding/build-recipe materials; trusted signer and transparency verification pass the existing B07 profile |
| Produce repository-owned wheels | Platform/CI with Security and independent domain review | Admit and pin the complete native build inputs; define owned Darwin arm64 and Linux x86_64 build/test targets; retain clean-build digest comparisons, native-library/SBOM coverage and failure tests; produce honest signed per-wheel build evidence in an authorized protected builder; establish a reviewed immutable artifact source and its consumer checks before changing dependency locks |

The first path leaves the existing wheel source policy intact. The second needs a
separate reviewed native-build and artifact-source change. It must preserve source,
digest, signature, platform, registry and consumer checks, not relabel a local
output as a PyPI wheel or broaden URL acceptance without equivalent controls.
Publication, protected-workflow permissions, signing identity and external review
cannot be supplied by this report. No upstream message was sent.

An upstream evidence request can use the exact two subjects in `observations.json`
as the initial query, then expand to the complete eventual lock set. Request
builder-produced SLSA v1 DSSE bundles, exact source revisions and SHA-256s,
build parameters, builder identity, signer/issuer and transparency evidence.
Do not ask an upstream maintainer to retroactively assert unknown build inputs.
If original build inputs cannot be established, request a new governed rebuild.

After either path, run B07 admission, vulnerability/license/platform checks,
installed-package and native compatibility tests, the complete repository lane,
and independent review before resuming C03. New build evidence must not silently
reuse the publication-only fixtures as accepted build attestations.

## Reproduce signature checks

The following historical replay used Cosign 3.1.3 and retained local evidence;
it creates no signatures or external artifacts. Run it with the repository's
currently admitted Cosign 3.1.3 binary; no retired Nix setup is implied:

```sh
proof_dir=docs/governance/evidence/quantlib-1.40-investigation
evidence_dir=docs/governance/evidence/quantlib-1.43
cosign verify-blob-attestation --check-claims=true \
  --trusted-root "$evidence_dir/sigstore-trusted-root-2026-09-04.json" \
  --bundle "$proof_dir/linux-publish.sigstore.json" \
  --certificate-identity https://github.com/lballabio/quantlib-wheels/.github/workflows/wheels.yml@refs/heads/master \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --type https://docs.pypi.org/attestations/publish/v1 \
  --digest aca8d51be11a264a149cb41935082ea0a023ebcb82f634dc6ed5908257bd5ab3 \
  --digestAlg sha256
```

Expected: `Verified OK`. Repeat with the existing Darwin bundle
`$proof_dir/quantlib-1.40-publish.sigstore.json` and digest
`fefb04e34a4f6a529e8d3a0506de6cd443d52ba85fbc13b4c30b7865ce5fa4ce`.
For each, require a nonzero exit after changing `--type` to
`https://slsa.dev/provenance/v1`, the digest to 64 zeroes, or the identity to
`https://example.invalid/attacker`. Retain separate results; an expected failure
is not permission to ignore a positive verification failure.

## Repository validation

Historical repository validation (before the build-path cleanup) used `make check`
with Bazel, Nix, the former governance checks, and the former package layout. The
retained evidence hashes, verifier outcomes, and local documentation links were
checked at that time. Those results validate this report and the then-current
repository, not QuantLib admission or C03 behavior.

## Change classification and operating impact

This report changes documentation and supplemental evidence only. The A04 facts
are no capital, documentation-only blast radius, no data/model materiality or
security privilege, and immediate revert: R0, QG01 and QG13, Code Owner review,
source-governance-record retention. The underlying B07 controls and their R2
obligations remain unchanged. The publication replays supply additional QG12
diagnostics, not admission or approval.

No consumer, schema, data, deployment or runtime requires migration. Rollback is
removal of this report, its observations and new public bundle together. The
dependency contract's stop-and-reconcile runbook remains applicable. There is no
new monitoring, alert, production runbook or operational authority. B07-F01-F03
remain open; Platform/CI and Security retain the closure duties above. Nothing
authorizes release, promotion, deployment, activation, credentials, market access,
capital or expanded risk authority. C03 remains the blocked selector; C04 is not
unlocked.
