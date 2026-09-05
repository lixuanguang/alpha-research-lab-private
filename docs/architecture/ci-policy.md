# Affected and Full Continuous Integration

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | B05 |
| Parent package | B05 (no delivery slice) |
| Objective | Fast affected/reverse-dependency CI plus authoritative full merged-result validation |
| Operating track | Solo bootstrap |
| Package status | Partial |
| Repository-local status | Provisionally implemented |
| Accountable owner role | Platform |
| Change risk | R2 shared build and security policy |
| Applicable gates | QG01-QG06, QG09-QG14 |
| Machine-readable policy | [CI policy](ci-policy.toml) |
| Provisional dependency | [CI tool dependency](ci-tool-dependencies.toml) |
| Evidence | [B05 partial evidence](../governance/evidence/examples/b05-r2-partial/manifest.toml) |

## Objective and delivery boundary

B05 adds two governed lanes over the B01-B04 repository. The non-authoritative
fast lane validates pull-request head changes by path, asks Bazel for the direct
source owners, expands through reverse dependencies, and builds and tests the
result. A foundational, deleted, malformed, excessive, or unowned change broadens
to `//...`; it never narrows by guesswork. The authoritative full lane runs source
hygiene, every registered schema module, the complete Bazel graph, and the full
frozen-uv compatibility path.

The full lane runs on the GitHub pull-request merge commit and on `main` pushes.
The merge-identity check requires exactly the declared base and head parents, so a
head-only result cannot masquerade as merged-result evidence. The fast lane is a
latency aid only. Its success cannot override a failed, absent, or stale full-lane
result.

ADR 0001 already selects the pinned Bazel graph, declarative environment, affected
analysis, and merged-result direction. B05 uses that decision without changing
the build system, toolchain, language boundary, remote-execution model, or domain
schema authority.

The delivery exceeds the preferred 400-line change guideline because B05 owns
five required, independently tested surfaces: policy validation, affected-target
selection, secret detection, lane execution/events, and hosted/root integration.
The implementation separates those responsibilities into modules and keeps one
canonical runner; splitting a second execution path would create policy drift
rather than a smaller coherent change.

## Selection and safe broadening

`alpha-governance-ci select --base-ref BASE --head-ref HEAD` resolves both refs to
exact commits, parses NUL-delimited Git name-status output, and reads Bazel XML
query output. Direct `srcs` owners are the only source-to-target mapping; B05 does
not maintain a second dependency graph. A Bazel `rdeps(//..., set(...))` query
then selects every reverse-dependent rule, and `tests(...)` selects affected test
targets.

The selector retains old and new rename paths, caps a change at 1,000 paths, and
rejects malformed paths, refs, XML, labels, and query failures. These conditions
force the full graph:

- a foundational build, lock, CI, or governance-tool path changes;
- a changed or deleted path has no current Bazel owner; or
- safe ownership cannot otherwise be demonstrated.

An empty diff produces an empty fast selection. A deterministic 1,000-path
selection stays inside the one-second repository-local computation budget. This
is not the blueprint's target-host median fast-lane evidence: the numeric target
still requires owner approval and representative protected-CI observations.

## Hygiene, secrets, generated artifacts, and drift

Fast CI runs pre-commit over the exact ref range; full CI runs every hook over all
files. The B05 hook and root checker validate the same policy, dependency record,
schema roots, evidence profile, root commands, Bazel inputs, and hosted lanes.
Unknown fields or a weakened fast/full relationship fail closed.

Generated build artifacts under `bazel-bin/`, `bazel-out/`, `bazel-testlogs/`,
`build/`, or `dist/` cannot enter a source diff or tracked-source set. B04 still
owns generated source admission and generator metadata; B05 enforces separation
at the CI boundary and creates no generated source root.

Secret scanning covers the affected existing files in fast CI and every tracked
file in full CI. The already locked `pre-commit-hooks==6.0.0`
`detect-private-key` command is provisionally reused as the external scanner. Closed
repository-owned patterns supplement its intentionally narrow role for assigned
credentials and high-confidence AWS, GitHub, Slack, and Stripe tokens. Matches
report only pattern identifiers and paths, never secret contents. Symlinks,
non-regular paths, scanner failures, and files over the one-megabyte scan bound
block. The empty values in `secrets/.secrets.example` remain valid; no live secret,
allowlist, credential, or external secret system is introduced.

## Schema compatibility

Every tracked `.proto` file must be inside a policy-registered module containing
`buf.yaml`. The only current module is B02's test-only toolchain fixture under
`tests/build/fixtures/proto`; B05 does not create a canonical or production
schema. Fast CI checks changed modules, while full CI checks every module. The
pinned Buf 1.72.0 tool lints the working module and runs `buf breaking` against
the exact base commit when the module exists there. A new module has no false
baseline claim and must lint; deletion, relocation outside a module, invalid
configuration, or an incompatible existing module blocks.

The sandboxed compatibility target proves an additive field passes and removal
of an existing field fails under the module's `FILE` policy. C05 still owns
canonical market/reference/lifecycle schemas, and C08 owns registry policy,
consumer migrations, compatibility windows, generated-client digests, and domain
rollback.

## Evidence events and interfaces

Build and test phases write newline-delimited JSON events under ignored
`build/ci/`. Each event records the full source revision, run identity, UTC start
and end, environment, outcome, and fast/full target. Hosted fast and full jobs
retain separate event streams for 30 days through the pinned artifact action; each
stream carries the run URL needed by A08's observation contract. A non-local lane
rejects a dirty checkout so revision identity remains exact. Local events keep an
empty evidence URL and remain unretained execution output. A new log is truncated
before preflight so a failed rerun cannot leave a stale passing event behind.

The supported interfaces are:

```sh
make ci-policy-check
make ci-secrets-check
make ci-schema-check CI_BASE_REF=HEAD
make ci-fast CI_BASE_REF=BASE CI_HEAD_REF=HEAD
make ci-full CI_BASE_REF=BASE
```

With the Bazel backend, `make check` is the full B05 lane. The explicit
`make BUILD_BACKEND=uv check` path remains the pre-Bazel rollback and cannot claim
full-lane authority. The `alpha_research.ci_policy` API and module command are
compatibility facades; the canonical implementation is
`alpha_research_governance.ci_policy`.

## Classification and evidence

B05 is R2 because it changes shared build, compatibility and source-security
behavior with a compatibility-window reversal. Applicable gate definitions live in
the [quality-gate catalog](operations.md#quality-gate-catalog); exact gate state and
finding closure conditions live in [ci-policy.toml](ci-policy.toml). The
[generated program status](../governance/program-status.md) reports current
implementation, governance and retained findings.

## Migration, rollout, rollback, monitoring, and runbook

The change is additive and has no data, model, persisted-state, runtime-service,
or domain-schema migration. Rollout makes the existing GitHub workflow expose a
head fast lane and an authoritative merged-result/full lane, while local and root
commands use the same implementation. It neither protects the branch nor grants
the workflow any write permission.

Rollback is a reviewed revert of the CI policy, scanner invocation, Buf
compatibility target, fast/full workflow, events, dependency record, evidence,
inventory/readiness state, and compatibility facade together. The prior B04
`make BUILD_BACKEND=uv check` path is retained and tested as the rollback target;
it is not a substitute for B05 while B05 remains active.

Operational signals are nonzero lane phases, named secret/schema/drift findings,
and the emitted build/test outcome events. The runbook is: stop the merge, inspect
the first named failing phase without exposing sensitive contents, broaden to the
full lane when ownership is uncertain, restore the last passing policy/lock/schema
combination or revert B05 as a unit, and rerun the full lane. There is no deployed
monitor, alert route, on-call service, kill path, or post-deploy window.

## Governance references

The [development workflow](../governance/workflow.md) owns daily validation and
evidence shape. Current status, findings and the active queue are generated in the
[program status](../governance/program-status.md). B05 creates no deployment,
activation, credential, executable-order or capital authority.
