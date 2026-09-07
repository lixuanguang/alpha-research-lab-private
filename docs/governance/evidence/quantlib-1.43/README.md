# QuantLib 1.43 retained admission evidence

This directory contains the byte-preserved native evidence consumed by the
bounded QuantLib development/CI admission in
[`dependency-admission.toml`](../../../architecture/dependency-admission.toml).
The source-to-wheel binding remains unverified, and artifact release, signing,
publication, and consumer verification remain blocked. The current boundary is
described in the [architecture overview](../../../architecture/README.md#dependency-and-release-boundaries).

The machine-readable admission record consumes the trust root, four review
reports, and the ten exact locked-wheel Sigstore bundles here. The retained
native observations, publication verification results, compatibility record,
and locked vulnerability report support those reviews. Their bytes were moved
from the retired synthetic C03/B07 evidence envelopes without rewriting them.
These records are historical observations from 2026-09-04. Current admission
and wheel-source tests verify their paths, hashes, and claims, but do not turn
historical results into a new review or resolve the unverified build binding.
The admission record was reviewed on 2026-09-04 and expires on 2026-10-04;
isolated development and CI remain permitted only through that date.

The retained records are [the trust root](sigstore-trusted-root-2026-09-04.json),
[the source review](source-review.txt), [the security review](security-review.txt),
[the native inventory](native-inventory.txt), [the compatibility report](compatibility.txt),
[the native observations](native-observations.json), [the locked vulnerability
report](pip-audit.json), [the publication verification results](verification.json),
and [the historical integration report](integration-security-performance.txt).

For historical byte references, the former
`docs/governance/evidence/examples/c03-r2-partial/reports/` prefix maps to this
directory. Its former `reports/quantlib-1.43/*.whl.sigstore.json` paths map to
`wheels/*.whl.sigstore.json`; the former
`reports/quantlib-1.43/verification.json` path maps to `verification.json` at
this directory's root. The former
`docs/governance/evidence/examples/b07-r2-partial/reports/sigstore-trusted-root-2026-09-04.json`
path maps to the trust-root file here. The 1.40 Darwin publication bundle moved
to `../quantlib-1.40-investigation/quantlib-1.40-publish.sigstore.json`.
Historical `observations.json` keeps its original repository-path fields so its
recorded bytes remain unchanged; use these mappings when resolving them.

The three domain golden datasets remain under `tests/golden/` and are consumed by
their domain unit tests. They are separate calculation oracles and are not
QuantLib admission evidence.
