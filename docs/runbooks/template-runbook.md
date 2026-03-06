# {Topic} Runbook

> **Type:** Operator procedure  
> **Category:** `docs/runbooks/` — see ADR 004 for documentation placement rules  
> **Last updated:** YYYY-MM-DD  
> **Owner:** (team or individual responsible)

---

## Purpose

One or two sentences describing what operation this runbook covers and when
an operator would reach for it.

---

## Prerequisites

- Required access, credentials, or environment setup before starting.
- List each prerequisite as a bullet.
- Example: `conda activate py311` with all deps installed.

---

## Steps

### 1. {First step title}

```bash
# example command
```

Expected output:

```
# what success looks like
```

### 2. {Second step title}

Describe the action.  Include commands where relevant.

### 3. Verify

How to confirm the operation completed successfully.

---

## Rollback

If the operation needs to be undone, describe how.

---

## Known issues

| Symptom | Likely cause | Fix |
|---|---|---|
| (describe symptom) | (likely cause) | (resolution or escalation path) |

---

## Related

- Link to relevant implementation plan in `docs/implementation/`
- Link to relevant ADR in `docs/adr/`
- Link to relevant guide in `docs/guides/`
