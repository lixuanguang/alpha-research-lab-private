# Repository Charter and Monorepo Boundary

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A01 |
| Operating track | Solo bootstrap |
| Charter status | Proposed |
| Package status | Partial |
| Accountable owner role | Platform |
| Change risk | R0 with package-specific QG12 and QG13 evidence |
| Current workflow | [Development and release workflow](workflow.md) |

This charter defines the source and governance boundary for the Alpha Research
Platform. It is subordinate to the root blueprint and the architecture,
operations, contracts, roadmap, and coding standards under `docs/`.

## Charter

The monorepo is the authoritative source for reviewed code, contracts, lineage
definitions, ownership, build and release definitions, policy, and small
reviewable evidence fixtures. It is a source and governance boundary, not one
deployable, runtime, security zone, latency profile, release cadence, failure
domain, database, or grant of operational authority.

Source visibility does not grant data entitlement, credential access, artifact
promotion, deployment permission, venue access, or capital authority. Deployment
and activation remain separate governed actions.

## Scope

The target boundary includes:

- Domain-first production and research source with one authoritative strategy
  kernel across research, replay, paper, shadow, canary, and live modes.
- Versioned schemas, small golden fixtures, generated sources approved for
  tracking, build definitions, dependency locks, and environment definitions.
- Architecture decisions, contracts, ownership, control policies, runbooks, and
  machine-verifiable evidence definitions.
- Asset and strategy packages that depend on canonical contracts and pass their
  independent certification gates.
- Migration adapters and compatibility definitions needed to move or bridge a
  classified existing repository without copying its authority ambiguously.

The boundary is domain-first. Reusable economic logic belongs to its owning
domain; application entrypoints compose targets; venue, provider, storage, and
runtime details stay behind owned adapters.

## Systems outside the monorepo

The following remain outside Git even when their schemas, adapters, manifests, or
policies are reviewed here:

- Mutable forge state, user identities, branch rules, CI workers, and approval
  decisions.
- Secrets, private keys, credentials, identity-provider state, and key material.
- Vendor, venue, broker, exchange, clearing, custody, and regulatory systems.
- Bulk market data, experiment output, model binaries, compiler output,
  deployment artifacts, databases, queues, caches, and telemetry stores.
- Runtime compute, schedulers, networks, hosts, clusters, and operator sessions.
- Developer workstations, notebooks, and local caches as sources of convenience,
  never as production or deterministic authority.

External systems may change only through a versioned, tested interface. The
selected data or broker adapter owns the boundary when an actual integration is
implemented.

## Repository disposition rules

Every existing repository must have exactly one reviewed disposition:

- `migrate`: canonical source and governance move into this monorepo through an
  explicit compatibility, cutover, and rollback plan.
- `bridge`: the repository remains separately released for a bounded reason and
  communicates through a versioned contract with named owners on both sides.
- `retain`: the repository remains independently governed and is not a source
  dependency of this monorepo; only approved artifacts or service contracts may
  cross the boundary.

An unclassified repository blocks A01 acceptance. The current register covers
only repositories discoverable from this checkout and documentation. A platform
owner must attest the organization-wide inventory before `inventory_complete`
may become true.

## Naming conventions

- Repository IDs use lower-kebab-case; the target ID is
  `alpha-research-lab-private`.
- New domain directories, packages, modules, and non-conventional files use
  lower_snake_case. Conventional build and governance names such as
  `.python-version`, `README.md`, `Makefile`, and `CODEOWNERS` retain their
  standard spelling.
- Names use the canonical domain vocabulary and include units or representation
  where ambiguity is unsafe. Unscoped names such as `utils`, `common`, `manager`,
  or `helper` do not define a public boundary.
- Canonical packages do not use vendor or venue names. Provider-specific names
  belong only inside the owning connector or adapter boundary.
- A short backlog identifies the next actual data, strategy, or operating task.
- Dataset, schema, service, model, strategy, and release identifiers are chosen
  by the capability that needs them and recorded with that capability.

Language-specific symbols follow the applicable coding guide.

## Source governance policy

The [development and release workflow](workflow.md) governs solo implementation.
The founder may review and merge changes after applicable technical checks.
Keep source revisions, focused test results, and the CI result. This policy does
not change forge settings.

For institutional acceptance, `main` requires protected integration, exact-commit
reviews and controls against direct pushes and implicit administrator bypasses.
The register retains those requirements and their pending external evidence for
the shared-team handover.

## Acceptance, rollout, and rollback

Repository checks complete the engineering change. A real release and activation
remain separate founder decisions with the artifact identity, limits, stop path,
and operating checks described in the [operations runbook](operations.md).

Adoption is a governance change only. It does not move code, alter a runtime, or
activate trading. Rollback is a reviewed revert of this charter and register; it
cannot be used to erase evidence or silently restore direct-push authority. No
runtime monitoring or runbook changes are introduced by A01.

## Governance references

The [development workflow](workflow.md) owns daily implementation records and
the [operations runbook](operations.md) owns deployment and activation behavior.
This charter grants no deployment, credential, market, capital, or trading
authority.
