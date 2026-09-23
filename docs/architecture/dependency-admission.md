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
[release boundary](../governance/workflow.md#build-a-release) blocks release use for the graph.
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
Before the [first trusted deployment consumer](../roadmap/README.md#delivery-order-and-dependencies)
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

The research-comparison change preserves CPython 3.14.7, pandas 3.0.5, NumPy 2.4.6
and Plotly 6.3.1. It adds Alphalens Reloaded 0.4.3, DuckDB 1.5.5, Polars 1.44.2,
Optuna 5.0.0 and marimo 0.24.2 for their first owned consumers. The resulting
core lock has 179 external packages; the complete unfiltered lock graph passes
the exact-version vulnerability audit. The separately locked Feast 0.66.0 worker
uses pandas 2.3.3 because its upstream metadata excludes pandas 3. Its 64-package
service-tool closure is audited independently, like the existing local ClearML
agent; it is not a release closure or a change to core runtime requirements.

New bundled-license records retain the actual distribution notices.
`LicenseRef-Docutils-Bundled` refers to Docutils 0.23's `COPYING.rst`, SHA-256
`6ab4f27c76c74f96e5e692da5944a6f82968f3bddaac5660a4aa723e70eb5d8f`:
public-domain dedication with the enumerated BSD-2/BSD-3 exceptions; the source
archive also identifies the separately licensed GPL-3-or-later Emacs `rst.el` tool.
Greenlet 3.5.6 retains MIT and PSF-2.0 for Stackless-derived platform files.
PyZMQ's wheel retains BSD-3-Clause, MPL-2.0, ISC and Apache-2.0 notices for its
bundled components. These are concrete notice reviews, not blanket approvals.

Evidently is **not admitted or installed**. Compatible Evidently 0.4.36 and latest
0.7.23 both depend unconditionally on NLTK. Its latest 3.10.3 release fails the
audit with PYSEC-2026-3740 / CVE-2026-81726, and the
[upstream advisory lists no patched release](https://github.com/advisories/GHSA-8mgp-746c-j5xp).
Removing that unused graph restores a clean audit; no finding is waived. The
[accepted MR 7 tool amendment](https://github.com/lixuanguang/alpha-research-lab-private/blob/31fcc842fa5a55daafe0764dd4d99912d082329c/docs/roadmap/history-mr1-to-mr9a.md#diagnostic-tool-requirement-amendment)
permits an admitted diagnostic implementation without Evidently. The subsequent
[direct SciPy consumer](#direct-scipy-diagnostic-consumer) supplies that capability;
MR 7 is now closed within its bounded offline scope.
The existing QuantLib allowance and release block remain unchanged.

Re-review on expiry, any dependency/policy change, or the first release consumer.
If the admission contract is defective, revert or correct the affected policy,
lock identity, checker, tests and documentation together. This allowance grants
no deployment, activation, credential, market or capital authority.

### Evidently prerequisite recheck

Evidently admission status: **blocked**, observed 2026-09-21 at 05:01 UTC, against main
`3ebd6a4bdb5722117e66dca830af28ee140b9f52`. This is a fresh review of
published artifacts and advisories, not admission of an additional dependency.
PyPI and upstream release records still identify Evidently **0.7.23** and NLTK
**3.10.3** as the latest stable releases. The downloaded wheel hashes matched
PyPI; their actual `METADATA` contains the following unconditional requirements:

| Candidate | Relevant wheel requirements | Observed result |
| --- | --- | --- |
| Evidently 0.4.36 | `nltk>=3.6.7`, `pandas[parquet]>=1.3.5`, `plotly>=5.10.0` | Disposable copy of the full project resolves on CPython 3.14.7 without changing any existing external version, including pandas 3.0.5, NumPy 2.4.6 and Plotly 6.3.1; vulnerability audit fails |
| Evidently 0.7.23 | `nltk>=3.6.7`, `pandas[parquet]>=1.3.5`, `plotly>=5.10.0,<6` | Resolver exits 1 because the core pins Plotly 6.3.1; a compatibility worker would still require vulnerable NLTK |
| NLTK 3.10.3 | Python `>=3.10` | Reviewed advisory affects `<=3.10.3`, has no patched version and is not withdrawn |

Evidence sources are the [Evidently release](https://pypi.org/project/evidently/0.7.23/),
[earlier resolver candidate](https://pypi.org/project/evidently/0.4.36/),
[NLTK release](https://pypi.org/project/nltk/3.10.3/),
[GitHub advisory](https://github.com/advisories/GHSA-8mgp-746c-j5xp) and
[PyPA advisory record](https://github.com/pypa/advisory-database/blob/main/vulns/nltk/PYSEC-2026-3740.yaml).
The GitHub, PyPA and OSV records agree on the unresolved prerequisite.

Resolution was attempted for both candidates with
`uv lock --project <disposable-copy> --refresh`; the real project manifest, lock
and admission policy were not modified.
The 0.4.36 candidate lock contains **216 external packages** (218 including the
two local projects). Exporting every registry package from that lock, without
platform filtering, and running pinned pip-audit 2.10.1 with
`--no-deps --disable-pip -r <exact-candidate-requirements> --format json` returned
**exit 1: 216 covered, one finding, no skips**. The finding is
`nltk==3.10.3: PYSEC-2026-3740`, aliases `CVE-2026-81726` and
`GHSA-8mgp-746c-j5xp`, with an empty fixed-version list. `--no-deps` here prevents
re-resolution of the already complete exact graph; it does not omit dependencies.
Successful resolution alone does not establish installed SDK compatibility.
No candidate was installed, imported or admitted.

Retained SHA-256 identities:

| Artifact | SHA-256 |
| --- | --- |
| Evidently 0.4.36 wheel | `332849bd2dd4b3e2ee551a9ece8f813cb32e90065e2f0e153d253f958a5df13f` |
| Evidently 0.7.23 wheel | `dbba5537a644f3401b8a393008cd126e304bcf939a070a7c4399bcc5b97061f6` |
| NLTK 3.10.3 wheel | `ff9598a8e20518ee0d557745890cc4435b9578489e2dcbc69c4f81fa060caf7c` |
| Rejected 0.4.36 candidate lock | `58c3e851a9d77c7a892b38587f82e267cdec2549e20c43be42242e8444e4af6e` |
| Complete candidate requirements | `49ea8cfb118d2a5989cb24bb1cdf547b40eebe994cf2db850711eb18a6653ea4` |
| Candidate audit JSON | `ed7a650606339cf4ad258cda8bd93f6b8f4d55a482c6d1e9e05511d02edd494a` |

Raw responses, wheel metadata/bytes, rejected resolver inputs/lock, commands and
audit output are retained in the primary checkout's ignored, owner-only
`logs/research-completion-prerequisite/2026-09-21/` directory. This is local
evidence, not a shared evidence service; preserve it before cleanup. The earlier
research-comparison acceptance archive remains intact.

There is **no admissible closure among the reviewed released candidates**.
For Evidently, the next feasible step is a published NLTK fix accepted by the
advisory/audit services, or a released Evidently distribution that genuinely removes the
mandatory vulnerable dependency, followed by complete admission and installed
SDK verification. If current Evidently still conflicts with the core pins, only
then consider a separately locked, fully audited compatibility worker. Isolation,
unused NLP features, older affected NLTK versions and `--no-deps` installation
cannot clear this blocker.

The founder subsequently authorized an explicit
[change to MR 7's tool requirement](https://github.com/lixuanguang/alpha-research-lab-private/blob/31fcc842fa5a55daafe0764dd4d99912d082329c/docs/roadmap/history-mr1-to-mr9a.md#diagnostic-tool-requirement-amendment)
on 2026-09-21. The required reference/current diagnostic capability may now use
admitted computation dependencies; Evidently is optional. The existing lock and
license records include SciPy 1.18.1, which provides an implementation candidate.
The amendment neither implements a diagnostic consumer nor changes package
admission. First direct use must declare its dependency in project metadata;
renew the full closure and installed-boundary proofs for any affected packaging.
The rejected candidates, advisory finding and historical attempts above remain
retained. No dependency is installed, removed, upgraded or exempted by this decision.

## Direct SciPy diagnostic consumer

The offline window consumer declares **SciPy 1.18.1** directly in project
metadata. It uses `scipy.stats.ks_2samp` for bounded two-sample CDF diagnostics;
exact financial ratios and predictive squared errors remain repository-owned
rational arithmetic. The 1,024-row bound is within the upstream exact method's
intended small-sample regime. Numerical warnings, including fallback to an
asymptotic calculation, fail the declared exact computation. Dependent temporal
observations and unadjusted p-values are explicitly descriptive, not inferential
or empirical acceptance.

The lock change adds only the direct project edge and requirement: **no external
package version or artifact changes**. CPython 3.14.7, pandas 3.0.5, NumPy 2.4.6
and Plotly 6.3.1 remain pinned. SciPy's existing source/wheel/native inventory and
bundled license notices above continue to apply. The complete updated 179-package
external lock graph passes the admission/audit wrapper with no vulnerability or
coverage gap. The updated lock digest is in the owning TOML policy; installed
boundary and report-consumer verification are recorded with MR 7 in the roadmap.

Evidently and NLTK remain absent from the admitted graph. Their rejected
candidate locks, advisories and failed evidence remain historical records.
No admission rule, dependency requirement, vulnerability finding or QuantLib
release restriction is weakened by the numerical consumer.

## Commands

```sh
uv run --frozen alpha-governance-dependencies
uv run --frozen alpha-governance-dependencies audit
uv run --frozen pip-audit --locked
uv run --frozen alpha-governance-artifacts release-check
```

The last command currently fails with the unresolved native dependency blocker.

## Economic research adapter admission

The first vectorbt consumer pins vectorbt 1.1.0 on CPython 3.14.7, NumPy 2.4.6,
pandas 3.0.5, Numba 0.67.0 and llvmlite 0.49.0. It explicitly selects Numba;
vectorbt-rust and optional trading/provider extras are not installed. The full
lock contains 131 external packages. Each added component has a digest-bound
PyPI source distribution, supported wheels and an exact license entry in the
existing policy. The native inventory includes the numerical, plotting and
widget dependencies required by vectorbt's distribution.

The initial installed import failed with Plotly 7.1.0 because vectorbt's template
still names `scattermapbox`. The lock constrains Plotly to the exercised 6.3.1;
this does not change the platform's Python or NumPy pin. The real installed
Numba backend is exercised without a mock or pure-Python fallback. The reference
ledger does not import that backend.

License records were checked against installed metadata and license files:
vectorbt's `licenses/LICENSE.md` is Apache 2.0 with Commons Clause 1.0, eligible
under the founder's explicit roadmap selection. Numba retains its BSD-2-Clause,
BSD-3-Clause and MIT notices; llvmlite and scikit-learn include LLVM runtime
notices/exceptions. SciPy's wheel also identifies OpenBLAS, LAPACK, GCC runtime
with its exception and libquadmath; the expression retains those bundled notices.
FontTools retains its font and bundled notices. The policy adds these concrete
expressions; source, wheel, vulnerability and release gates remain intact.

`LicenseRef-Matplotlib-Bundled` identifies the exact Matplotlib 3.11.2 wheel
`LICENSE` file (SHA-256 `822e8e528147569a41975592aee19c11992ab667ba50451cd929031d5fc74491`). It includes the Matplotlib agreement,
OFL fonts, BaKoMa font notice, Apache-2.0, Bitstream-Charter, FreeType's offered
FTL alternative, MIT variants, CC0-1.0, Qhull and the Yorick colormap notice.
It is a complete-notice reference, not a wildcard approval or an assertion that
every bundled component uses the main project license. Retain the exact locked
artifacts and their notices when reproducing this environment.

This admission serves the bounded development/research consumer. QuantLib's
pre-existing unresolved source-to-wheel binding still blocks release use of the
whole graph. No deployed service, executable venue dependency or trading
permission is introduced by the adapter.


## Configured-report dependency admission

The frozen runtime adds QuantStats 0.0.81 (Apache-2.0) and lakefs-sdk 1.86.0
(Apache-2.0) with 15 newly admitted transitive packages. QuantStats receives only
explicit retained returns and benchmark bytes; its transitive yfinance installation
is not a source-selection or automatic-download capability of this platform.

`MIT-0` identifies cffi 2.1.1. `LicenseRef-Lxml-Bundled` identifies the exact notices
in lxml 6.1.3's wheel `licenses/LICENSES.txt`, SHA-256
`388fa99f3bde4447cd5a4cbb114037be026854db6cfe89e112691c1d8abdcf3c`.
Those notices cover BSD/PSF/ElementTree and ISO/XSL resources, bundled zlib,
LGPL-2.1 iconv, and MIT libxml2/libxslt/libexslt; retain them with the wheel.
This names a concrete bundle rather than treating all its files as BSD.
The existing source, artifact hash, platform-wheel and vulnerability checks apply;
no new native wheel-only allowance is added. Peewee is a pure-Python wheel in
this lock. The independently locked local worker and synthetic service images are
recorded in their development guides, outside the runtime release graph.
