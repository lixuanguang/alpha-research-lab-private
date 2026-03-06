# ADR 004: Documentation Modularity Rule

- **Status:** Accepted
- **Date:** 2026-03-06
- **Supersedes:** none
- **Related:** Foundation Stage §13.4, `README.LEAN_ADOPTION.md §12.5`

---

## Context

As the platform grows across Foundation, Data Plane, Research Plane, and Live
Plane stages, documentation has accumulated in a small number of large files
(primarily `docs/implementation/foundation-stage.md`).  This creates several
problems:

- A single file becomes the source of truth for unrelated concerns
  (architecture decisions, operator procedures, migration instructions, and
  stage status).
- Stage updates keep appending to already-large documents, making it hard to
  find the right information quickly.
- Breaking changes have no authoritative home, so they get buried in update
  notes inside implementation plans.

---

## Decision

Adopt a strict four-category split for all documentation written from this
point forward:

| Category | Location | What goes here |
|---|---|---|
| **Architecture contracts** | `docs/implementation/` | Stage implementation plans, scope definitions, module-level design decisions, acceptance criteria, API surface descriptions |
| **Operator procedures** | `docs/runbooks/` | Step-by-step instructions for running, deploying, troubleshooting, and operating the platform; environment setup; incident response |
| **Migration mappings** | `docs/guides/` | How to move from one pattern/API/workflow to another; upgrade instructions; before/after examples |
| **Breaking changes** | `docs/adr/` | Formal records of significant architectural decisions, especially those that break backward compatibility or constrain future choices |

### Naming conventions

- **ADRs:** `docs/adr/{NNN}-{kebab-slug}.md` — sequential number, short
  lowercase slug describing the decision.
- **Runbooks:** `docs/runbooks/{topic}-runbook.md` — named after the operation
  or system component they cover.
- **Guides:** `docs/guides/{topic}-guide.md` — named after the migration or
  workflow being explained.
- **Implementation plans:** `docs/implementation/{stage-name}.md` — one file
  per development stage.

### Enforcement rule

When writing new documentation, ask:

1. Does this describe *what the system is* or *why a design was chosen*? → `docs/implementation/` or `docs/adr/`
2. Does this describe *how to operate or run* something? → `docs/runbooks/`
3. Does this explain *how to move from A to B*? → `docs/guides/`
4. Does this record a *decision that constrains future choices*? → `docs/adr/`

Content that spans categories must be split into appropriately placed files
cross-referenced by relative links.  Avoid adding operational instructions to
implementation plans and avoid adding architecture descriptions to runbooks.

---

## Consequences

**Positive:**
- Readers can navigate to the right document type immediately without
  scanning large mixed-content files.
- Stage implementation plans stay focused on contracts and scope; they do not
  accumulate operational cruft.
- Breaking changes have a permanent, numbered, authoritative record in
  `docs/adr/`.

**Negative / Trade-offs:**
- Cross-references between files must be maintained when documents move.
- Authors must make a conscious category choice for each new document.
- Short status updates and addenda that previously lived inline in
  implementation plans must now be filed in the correct location.

**Out of scope:**
- This ADR does not retroactively reorganise existing documents.  Existing
  mixed-content files are grandfathered; new content added to them must
  follow the split rule.
