# A05 Unprotected Forge Exercise

## Control metadata

| Field | Value |
| --- | --- |
| Roadmap package | A05 |
| Operating track | Solo bootstrap |
| Exercise date | 2026-08-30 |
| Accountable owner role | Platform |
| Result | Supplemental evidence only |
| Protected target | No |

## Purpose and limitation

This record retains the hosted positive and negative pull-request-body exercises
performed before A05 was merged to `main`. The repository was private and its
GitHub plan did not enforce branch protection. These results prove that the
hosted workflow executed the A05 validator, but they do not prove that a direct
push, administrator bypass, or merge without the required check was blocked.

Accordingly, this evidence does not close A05-F01 or A05-F02. A05 remains
`partial`; this record is not approval, release, promotion, deployment, or
activation evidence.

## Retained exercises

| Exercise | Pull request | Head commit | Source tree | Hosted job | Result |
| --- | --- | --- | --- | --- | --- |
| Complete 29-field body | [PR #7](https://github.com/lixuanguang/alpha-research-lab-private/pull/7) | `ee0b19da1f726f9ea33be37ba8d881f8a7adc3c2` | `af088857cb65b9cd79547f9ef6fc6f4b24dcdcf3` | [successful job, attempt 2](https://github.com/lixuanguang/alpha-research-lab-private/actions/runs/33287675126/job/99200359862?pr=7) | Passed the complete package job, including `Lint pull-request body` |
| Missing `Accountable owner` body | [PR #8](https://github.com/lixuanguang/alpha-research-lab-private/pull/8) | `9756004f6e6c3d1bbce47e6860f78fd2b6c041fd` | `af088857cb65b9cd79547f9ef6fc6f4b24dcdcf3` | [blocking job](https://github.com/lixuanguang/alpha-research-lab-private/actions/runs/33290072572/job/99200047293?pr=8) | Failed at `Lint pull-request body`; PR closed unmerged and disposable branch deleted |

The positive and negative commits deliberately have the same source tree. The
negative exercise uses a distinct empty commit so the PR event receives a unique
check identity without changing the implementation under test.

## Check-identity observation

The first negative PR run reused the positive head commit
`ee0b19da1f726f9ea33be37ba8d881f8a7adc3c2`. GitHub then surfaced the invalid
body's failed `Bootstrap package` context on the positive PR because check
contexts are commit-bound. The [colliding failed
job](https://github.com/lixuanguang/alpha-research-lab-private/actions/runs/33290042363/job/99199969771?pr=7)
is retained as failure-mode evidence.

Future event-body exercises must use distinct head commits even when their source
trees are identical. This prevents a negative PR's expected failure from being
mistaken for the status of a positive PR at the same commit.

## Closure conditions that remain open

- Platform/CI repeats the complete and missing-field exercises on protected
  `main`, proves required-check enforcement and bypass prevention, and retains the
  exact-commit pass/block jobs.
- A named, non-author Platform Code Owner resolves findings and approves the exact
  A05 evidence commit.
