# Source Validation and CI

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | B05 |
| Objective | Run one reproducible source, policy, test, and package validation path |
| Operating track | Solo bootstrap |
| Package status | Partial |
| Repository-local status | Provisionally implemented |
| Accountable owner role | Platform |
| Change risk | R2 shared source and security policy |
| Evidence | [B05 partial evidence](../governance/evidence/examples/b05-r2-partial/manifest.toml) |

## Current validation path

The active repository check is `make check`. It runs the frozen lock check,
configured Python formatting and linting, strict typing and stub checks,
repository governance validators, security checks, the admitted dependency audit,
tracked-source secret scanning, the default pytest suite, and the installed wheel
smoke. The root command uses Python 3.12.14 and the non-editable package paths
recorded in `uv.lock`; it does not depend on a caller `PYTHONPATH`.

The hosted workflow installs the frozen environment and pinned Cosign 3.1.3,
runs `make source-check` on Linux, and then runs the installed wheel smoke on
Linux and macOS. A pull-request merged-result identity check remains an explicit
hosted check. The workflow file is repository-local evidence; protected branch
and exact-commit retention remain external findings.

## Secret scanning

`make ci-secrets-check` runs the retained `alpha-governance-ci scan-secrets
--all` command. The scanner uses bounded repository-owned patterns together with
the locked `detect-private-key` hook. It reports only pattern identifiers and
paths, never matching contents. Missing scanners, unsafe paths, unreadable files,
oversized files, scanner failures, and detected credentials fail closed.

## Retired policy surfaces

The former affected-target selector, Bazel owner and reverse-dependency queries,
fast/full custom scheduler, schema lane, and CI event-log retention were retired
when the single frozen-uv source path became authoritative. Their implementation
and configuration remain historical evidence where retained, but they add no
current setup, topology, inventory, or merge prerequisite. The historical
affected-target and remote-execution pages remain reachable from the architecture
index for provenance.

## Scope and evidence

Focused commands such as `make topology-check`, `make inventory-check`, and
`make engineering-standards-check` support local iteration. They do not replace
`make check` before merge. Record the exact command, selected test paths, skips,
and unavailable hosted observations in the validation result. Historical migration
results and synthetic evidence packs do not claim current execution.

The [development workflow](../governance/workflow.md) owns daily validation and
evidence shape. Current state and findings are generated in the
[program status](../governance/program-status.md). B05 creates no deployment,
activation, credential, executable-order, or capital authority.
