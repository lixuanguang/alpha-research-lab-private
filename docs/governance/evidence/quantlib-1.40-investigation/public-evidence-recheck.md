# QuantLib public build-evidence recheck

## Result and scope

This is a historical observation under the earlier policy. The later
[current dependency boundary](../../../architecture/README.md#dependency-and-release-boundaries)
adds a bounded development admission route. It does not alter the observed
publication statements, supply build provenance or admit QuantLib automatically.

On 2026-09-04, clean `main` at
`6b5f18a10e7c048adc848111d49ba0506e302deb` was rechecked after a request to resolve
the C03 prerequisite. **The prerequisite remains blocked.** This supplements the
[original investigation](README.md); it is neither an admission nor an acceptance
manifest. No policy, dependency, signer, registry or credential was changed.

The original investigation checked two wheel subjects. This recheck inspected
the PyPI provenance response for every published wheel of both the roadmap
baseline and current release, including the newer upstream publishing repository.

| Release | PyPI wheels | PyPI sdists | Publication-only responses | SLSA build responses |
| --- | --- | --- | --- | --- |
| 1.40 | 16 | 0 | 16 | 0 |
| 1.43 | 26 | 0 | 26 | 0 |

All 42 provenance requests returned HTTP 200 and contained one publication
statement with a null predicate. The 1.40 publisher is
`lballabio/quantlib-wheels`; 1.43 uses `lballabio/QuantLib-SWIG`. Release metadata,
exact subjects, response hashes, URLs and predicate observations are recorded in
[public-evidence-recheck.json](public-evidence-recheck.json).

GitHub's unauthenticated attestation endpoints returned HTTP 404 for six
subjects: the Darwin arm64 and manylinux x86_64 CPython ABI3 wheels in each
release, plus the two corresponding 1.43 free-threaded CPython 3.14 wheels.
The latter are diagnostic only and are not compatible candidates for this
repository's CPython 3.12 lane. These responses do not prove global absence or
predict authenticated access.

Issue searches for `provenance` and `attestation` across both publishing
repositories returned no results. The
[1.43 release workflow](https://github.com/lballabio/QuantLib-SWIG/blob/bb5a63b376008e4482d11600ff7a1434284558e1/.github/workflows/wheels.yml)
builds wheels and publishes through PyPI, but contains no SLSA build-attestation
step. The newer release therefore supplies no observed resolution to this
specific evidence gap; it is not proposed as a dependency upgrade.

## Evidence limits and next action

This recheck decoded public statements but did not rerun cryptographic
verification. It preserves observation hashes and URLs, not new accepted signature
bundles. The original two publication-verification results remain separately
retained. Mutable endpoints can change; response hashes identify the observed
bytes and do not authenticate their provenance.

The repository's CI currently grants `contents: read`, has no native wheel build
or signing job, and has no admitted replacement wheel source. The local Docker
client could not connect because its daemon socket did not exist. No Linux build
or external workflow was run. A local rebuild would still need complete native
input admission, both supported-platform results, protected builder signatures,
and an approved immutable artifact source before consumption.

The concrete next step is the prepared
[upstream build-evidence request](upstream-build-evidence-request.md). Sending it
requires explicit authorization for external communication. Platform owns the
request and exact-subject reconciliation; Security owns signer/material review.
Closure still requires the original investigation's complete upstream-evidence or
repository-owned-build path. No reply or attestation is assumed to exist.

## Validation

Historical repository validation (before the build-path cleanup) used
`uv lock --check` and `make check` with Bazel, all-files pre-commit, the former
governance checks, package import and sdist/wheel build. Observation counts,
response hashes, exact subjects and all four request digests were checked against
the downloaded metadata. These checks validate the report and the then-current
repository; they do not validate QuantLib admission or C03.

## Change classification and operations

This update has no capital, a documentation-only blast radius, no data/model or
security-privilege effect, and immediate-revert reversibility: A04 R0, QG01 and
QG13, Code Owner review and source/governance-record retention. B07's underlying
R2 requirements and B07-F01-F03 remain unchanged and open. No independent approval
is claimed.

There is no migration, deployment, activation, new monitoring or production
runbook. Rollback removes this supplement and draft together with their link from
the original report. C03 remains unimplemented and C04 is not unlocked. B07
remains partial on the solo-bootstrap track and authorizes no release, promotion,
deployment, activation, credentials, market access, capital or expanded risk
authority.
