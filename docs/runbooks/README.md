# Runbooks

Operator procedures for running, deploying, troubleshooting, and operating
the alpha research platform.

**Documentation rule (ADR 004):** This directory contains *how-to-operate*
content only.  Architecture decisions belong in `docs/adr/`.  Migration
instructions belong in `docs/guides/`.  Stage design belongs in
`docs/implementation/`.

---

## Index

| Runbook | Topic |
|---|---|
| [template-runbook.md](template-runbook.md) | Blank template — copy this when creating a new runbook |

---

## When to write a runbook

Write a runbook when you need to document:

- How to start, stop, or restart a service or pipeline
- How to perform a routine operational task (backfill, data validation, key rotation)
- How to respond to a known failure mode (incident response)
- Environment setup steps for a specific deployment target
- Manual verification steps before or after a deploy
