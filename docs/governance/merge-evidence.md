# PR evidence and implementation acceptance

## Current workflow

Use the [default template](../../.github/pull_request_template.md) with four sections:

- **Problem / change:** the concrete problem and resulting behavior.
- **Affected scope:** the affected code, contracts or documentation and relevant impacts.
- **Validation result:** commands, results and any pending checks; CI retains the run
  and revision. A written assertion of success does not replace the automated checks.
- **Risks / reversal:** material limitations and how to undo the change.

The [founder example](evidence/examples/founder-pr.md) needs no package-specific
manifest, invented findings or external signatures. Ordinary documentation changes
use this same path. The [operating policy](domain-ownership.md#current-operating-policy)
separates engineering completion from any scoped team handover.

Add these level-two sections only when applicable:

| Section | Trigger and content |
| --- | --- |
| Migration / compatibility | Changed schema/migration paths, `.proto`, `.avsc` or `.sql` files, a declared compatibility window, or a semantic migration. Explain old/new behavior, migration and reversal. |
| Benchmark | Benchmark/performance paths or computationally material work. Record the relevant baseline, result and threshold. |
| Operational plan | Deployment/infrastructure paths, R3/R4 impact, or an institutional acceptance, release or activation operation. Record rollout, stop/rollback, monitoring, runbook and observation checks relevant to the operation. |

Documentation mentioning these topics does not activate a section by filename
alone. Declare semantic impacts not visible in the diff using one optional comment:

```html
<!-- evidence-context: {"migration":true,"benchmark":true} -->
```

The context accepts `migration`, `benchmark`, `operation` (default `implementation`;
also `institutional_acceptance`, `release`, `activation`) and an optional `change`
object containing the [A04 classification facts](change-risk-classification.md).
Unknown fields, invalid types and duplicate declarations fail. Explicit false
flags cannot turn off a trigger detected in the actual changed paths.

CI generates the exact base/head SHAs, changed paths, operation, required extras
and classification source in its log. It uses the merge-base diff, including
removed paths and both sides of renames. Prose-only `.md`/`.rst` changes infer R0.
Other changes report `risk_class: null` until semantic facts are supplied; filenames
cannot establish capital exposure, privilege or model materiality. This is not a
risk exemption: describe those impacts in Affected scope and supply A04 facts for
changes relying on a risk-class decision. Supplied facts are recomputed, a declared
downgrade is rejected, and R3/R4 facts require the operational section.

## Policy and commands

The [version-2 evidence policy](merge-evidence-policy.toml) owns the ordered four
fields, conditional fields, preserved institutional fields and example paths.
`make evidence-check` validates the policy, template and both examples, including
the historical bundle and every referenced artifact. The hosted workflow uses:

```sh
uv run --frozen alpha-governance-evidence --github-event "$GITHUB_EVENT_PATH"
```

The event must contain full lowercase base and head SHAs available in the fetched
Git history. The CLI validates the actual diff and body together. PR body edits
also trigger CI. A missing, duplicated, empty or placeholder-only required section
fails; headings inside comments or code examples do not count.

Local body linting does not infer a Git diff:

```sh
uv run --frozen alpha-governance-evidence --mr-body path/to/pr.md
uv run --frozen alpha-governance-evidence \
  --manifest path/to/manifest.toml --expected-commit-sha FULL_HEAD_SHA
```

A manifest is required only by a capability's artifact/evidence contract, not by
every PR. Both the canonical `alpha-governance-evidence` command and the existing
`alpha_research.evidence` Python facade use the same readers.

## Acceptance meanings and artifact integrity

Version-1 manifests remain unchanged. `accepted` continues to mean institutional
acceptance: required class/package gates passed, no findings remain, and full
commit-bound A04 approvals are present. `partial` still records unresolved gates
and findings. The historical [A05 bundle](evidence/examples/a05-valid/manifest.toml)
and institutional PR profile retain those meanings; the policy's `package_status`
and findings refer to that historical fixture, not current implementation progress.

Version-2 manifests have the distinct status `implementation_accepted`. They retain
all version-1 artifact, change, gate and finding fields and add:

```toml
schema_version = 2
bundle_status = "implementation_accepted"
operating_domain = "repository_platform"
accepted_by = "@lixuanguang"
accepted_on = "2026-09-05"
```

The reader requires the recorded founder to be active in the named domain at
acceptance, passing required technical evidence, and no technical findings, failed
or deferred gates, institutional approvals or waivers. Gates in this format record
the technical portion of the control; they do not claim an independent human
review. Team handover remains separately resolved from actual role assignments.
Package consumers can select `implementation_complete` explicitly; existing
`validated` profiles still require institutional `accepted` evidence.

Every manifest retains exact source-SHA binding, risk and retention recomputation,
required gates, bundle-contained paths and SHA-256 verification. Passed gates must
reference verified artifacts. Existing technical failures cannot be recast as
missing staffing. Founder acceptance requires the ownership operating model;
it fails if supplied to `--operation release`, `activation` or
`institutional_acceptance`. Successful body linting or engineering acceptance
cannot authorize those operations or replace their existing approval controls.

## Historical evidence and reversal

A05-F01 (protected-forge exercise) and A05-F02 (Code Owner signature) remain in the
historical policy and bundle. The [unprotected forge exercise](evidence/a05-unprotected-forge-exercise.md)
is retained without claiming those obligations passed. Current implementation
status is owned by the [program register](program-governance.toml).

Version-1 policy reading remains available for existing consumers. Revert this
migration's template, policy, readers and workflow together if needed, retaining
the prior records. Never relabel founder evidence as historical institutional
approval. The delivery-graph migration is a separate step.
