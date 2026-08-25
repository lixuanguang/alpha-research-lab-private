# Repository Charter and Monorepo Boundary

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A01 |
| Status | Proposed; acceptance evidence is incomplete |
| Accountable owner | Unassigned; required before approval |
| Change risk | R0 with package-specific QG12 and QG13 evidence |
| Machine-readable register | [System boundaries](system-boundaries.toml) |

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

The machine-readable register records the boundary disposition and authority on
each side. An external implementation may change only through a versioned,
owned, tested interface and the applicable later roadmap package.

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
  `MODULE.bazel`, `README.md`, `Makefile`, and `CODEOWNERS` retain their standard
  spelling.
- Names use the canonical domain vocabulary and include units or representation
  where ambiguity is unsafe. Unscoped names such as `utils`, `common`, `manager`,
  or `helper` do not define a public boundary.
- Canonical packages do not use vendor or venue names. Provider-specific names
  belong only inside the owning connector or adapter boundary.
- Implementation packages use `A01` through `L08`. Research stages use `R01`
  through `R16`; superseded implementation IDs must not label new work.
- Dataset, schema, service, model, strategy, and release identifier formats are
  deliberately deferred to their owning roadmap packages; this charter does not
  pre-empt A06, C01, or C08.

Language-specific symbols follow the applicable coding guide.

## Source governance policy

`main` is the protected integration branch. No direct push to `main` is allowed;
changes must arrive through a reviewed pull or merge request bound to an exact
commit and its required checks and approvals. Administrators and automation are
not implicit bypasses. Emergency access must be explicit, time-bounded, audited,
and reviewed under the later access-control packages.

This policy does not prove that the forge currently enforces it. A01 acceptance
requires independently inspectable branch-rule evidence showing direct pushes are
blocked. The current verification status is recorded as pending.

## Acceptance, rollout, and rollback

Acceptance requires platform, quantitative research, trading engineering, risk,
SRE, security, and compliance approval; an attested complete repository
inventory; a tracked authoritative blueprint; and verified protected-branch
enforcement. Pending evidence is explicit in the register and must not be treated
as a waiver or approval.

Adoption is a governance change only. It does not move code, alter a runtime, or
activate trading. Rollback is a reviewed revert of this charter and register; it
cannot be used to erase evidence or silently restore direct-push authority. No
runtime monitoring or runbook changes are introduced by A01.

## Non-goals

- Creating the target repository skeleton or moving historical source (B01).
- Defining the ADR/exception framework (A02), CODEOWNERS (A03), change classifier
  (A04), evidence bundles (A05), inventories (A06), or threat model (A07).
- Selecting build, schema, storage, transport, deployment, observability, or
  production-access technology.
- Configuring forge branch rules, contacting external systems, deploying
  artifacts, adding credentials, or authorizing trading.
