# Pre-B01 toolchain refresh evidence

## Scope and status

This record covers only the mandatory existing-tool refresh that precedes B01a.
It does not implement B01-B04, complete B04, alter the package graph, or close any
A01-A08 external finding. All current package statuses remain `partial`.

Evidence date: 2026-08-30. Target platform: macOS arm64. Required runtime:
CPython 3.12.14 with `requires-python = "==3.12.*"`. Pydantic remains exactly
2.13.5.

## Clean baseline and rollback point

The clean tool baseline was uv 0.12.5, Hatchling 1.27.0, pytest 8.3.4,
pytest-cov 6.0.0, Ruff 0.8.6, mypy 1.14.1, Bandit 1.8.0, pre-commit 4.0.1,
and pre-commit-hooks 5.0.0 on CPython 3.12.14. The source rollback point is
commit `d8c2cbcffaee7a9f5df3e43d86676d69e424a889`; its `pyproject.toml` and
`uv.lock` SHA-256 digests are respectively
`d4c9ccffe782d02dd73c89480af91cd651e8256a70c76830ee5afe975a398410` and
`9acdb8e6a3c8f59880fb79dcb4fe2a8d123a80eb2012239442a42dd0c01c1d7c`.

Before any pin changed, `uv lock --check`, `make check`, and
`uv run --frozen pre-commit run --all-files` passed. The test baseline was 201
passing tests. Governance summaries remained `partial`: 8 ADRs, 12 ownership
domains, 8 resources of 8 kinds, 12 threats, 12 controls, 4 jurisdictions, 96
roadmap packages, and 7 KPI definitions. Public default and JSON CLI outputs were
captured byte-for-byte for final comparison.

The baseline wheel and sdist were built with `uv build --no-sources`. Their
SHA-256 digests were
`8bf781a60968ad235e3e4d0c97f278b4dd52eceaa234d3d748d4107859f3e52c` and
`9582292b7c0e22238256a0595332faefce2470108f6ad2ac5a46f42b0c221f81`.
Both used core metadata 2.4, required Python `==3.12.*`, and declared only
`pydantic==2.13.5` at runtime.

## Release and compatibility review

Only final, non-yanked releases compatible with Python 3.12 and the target
platform were selected. The review used upstream release histories and PyPI
package metadata across every version gap:

- [uv releases](https://github.com/astral-sh/uv/releases) and
  [PyPI metadata](https://pypi.org/project/uv/)
- [Hatchling history](https://hatch.pypa.io/latest/history/hatchling/) and
  [PyPI metadata](https://pypi.org/project/hatchling/)
- [pytest changelog](https://docs.pytest.org/en/latest/changelog.html) and
  [PyPI metadata](https://pypi.org/project/pytest/)
- [pytest-cov changelog](https://pytest-cov.readthedocs.io/en/latest/changelog.html)
  and [PyPI metadata](https://pypi.org/project/pytest-cov/)
- [Ruff changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md) and
  [PyPI metadata](https://pypi.org/project/ruff/)
- [mypy changelog](https://mypy.readthedocs.io/en/stable/changelog.html) and
  [PyPI metadata](https://pypi.org/project/mypy/)
- [Bandit releases](https://github.com/PyCQA/bandit/releases) and
  [PyPI metadata](https://pypi.org/project/bandit/)
- [pre-commit changelog](https://github.com/pre-commit/pre-commit/blob/main/CHANGELOG.md)
  and [PyPI metadata](https://pypi.org/project/pre-commit/)
- [pre-commit-hooks releases](https://github.com/pre-commit/pre-commit-hooks/releases)
  and [PyPI metadata](https://pypi.org/project/pre-commit-hooks/)

## Cluster results

### 1. uv 0.12.5 to 0.12.7

The patch gap adds managed-Python replacement, cross-platform resolution targets,
and earlier source-archive hash rejection. The intervening 0.12.6 release also
refreshes bundled CPython OpenSSL/libffi inputs, adds PGO to supported binaries,
and fixes extras, version-constraint, Git-pin, and build behavior. Human-readable
byte-size output and Rust source-build requirements changed; neither is a public
repository contract. The official macOS arm64 binary is native and requires no
Python dependency. Its published checksum was verified before use. No repository
configuration change beyond the exact pin and matching CI installer pin was
required. `uv lock` reproduced the baseline lock byte-for-byte, and
`uv lock --check`, the five exact-pin/package contract tests, and
`uv build --no-sources` passed under uv 0.12.7. No lock dependency changed.

### 2. Hatchling 1.27.0 to 1.32.0

The full gap drops Python 3.9, fixes reproducible timestamps and shared-script
shebangs, excludes Git worktree metadata, adds SBOM and static-version editing
features, and hardens readme path handling. Hatchling 1.30.0 was yanked after
prematurely defaulting to core metadata 2.5; 1.30.1 restored 2.4. Hatchling 1.32.0
now deliberately defaults to core metadata 2.5 and adds `tomlkit` as a pure-Python
runtime dependency. The backend otherwise remains a pure-Python wheel supporting
Python 3.12. Both the build-system and development pins were changed together.
The lock changed only from Hatchling 1.27.0 to 1.32.0 and added pure-Python
`tomlkit==0.15.1`. `uv lock --check`, the five exact-pin/package contract tests,
and `uv build --no-sources` passed. At this cluster checkpoint, wheel package
paths and all packaged Python bytes matched the baseline. Expected artifact
metadata changes are
`Metadata-Version: 2.4` to `2.5` and the WHEEL generator version; name, version,
Python requirement, pure-wheel tag, and sole runtime dependency are unchanged.
At this checkpoint, the sdist added only this refresh evidence document to the
baseline path set.

### 3. pytest 8.3.4 to 9.1.1 and pytest-cov 6.0.0 to 7.1.0

The pytest gap drops Python 3.8 and then 3.9, turns unsupported async tests and
non-`None` test returns into errors, introduces native TOML configuration and
strict-mode improvements, makes Pygments required, changes several terminal and
traceback details, and fixes fixture-scope, assertion, collection, and plugin
regressions through 9.1.1. The existing `[tool.pytest.ini_options]`, strict
configuration, and strict-marker settings remain supported. pytest-cov changes
terminal width/precision and warning filters, then removes its legacy implicit
subprocess `.pth` hook in 7.0 and requires coverage 7.10.6 or newer. This
repository has no subprocess coverage setup or coverage threshold, so adding
`[run] patch = subprocess` would be unnecessary. pytest-cov is the only pytest
plugin in the lock. Both selected packages are pure Python and support Python
3.12. The lock changed only the two direct versions and added dependency edges
from pytest to the already-locked Pygments 2.21.0 and from pytest-cov to the
already-locked Pluggy 1.6.0; coverage remained 7.15.4. `uv lock --check` and all
201 tests passed with the repository's local `PYTHONPATH=src` interface. A
diagnostic pytest-cov run also passed all 201 tests and reported 87% total
coverage; no threshold was added or lowered. The progress/count output remained
semantically identical apart from elapsed time. No test or product code changed.

### 4. Ruff 0.8.6 to 0.16.5

Across 0.9-0.16, Ruff introduced 2025 and 2026 formatter style revisions,
stabilized and split rules, removed deprecated UP038, changed first-party module
resolution, expanded suppression handling and output detail, and expanded the
default lint set from 59 to 413 rules in 0.16. It also defaults unspecified target
versions toward newer Python releases and discovers/formats Markdown by default.
Those defaults do not broaden this repository: `target-version = "py312"`,
`src = ["src", "tests"]`, explicit lint families `E`, `F`, `I`, `W`, `UP`, and
`RUF`, and explicit Python paths remain in force. Ruff is a native executable;
the selected macOS arm64 wheel supports the target and adds no Python transitive
dependency. No formatter or lint setting was changed. The existing rule selection
surfaced UP042, RUF005, and RUF043 diagnostics. Compatibility edits were limited
to two equivalent tuple constructions, six raw regex literals in tests, and three
formatter line joins. One line-scoped UP042 annotation preserves the existing
`RiskClass(str, Enum)` string semantics that `StrEnum` would change; no rule family
or file was excluded. `uv lock --check`, lint, format check, and all 201 tests
passed. Lint output remains `All checks passed!`; formatter output remains 42
formatted files. The lock changed only Ruff's version and native wheel set.

### 5. mypy 1.14.1 to 2.3.1

The gap improves control-flow narrowing, attribute and protocol resolution,
configuration discovery, line locations, cache formats, performance, and support
for newer typing PEPs. Python 3.8 and then 3.9 targeting were removed. Mypy 2.0
turns `local_partial_types` and `strict_bytes` on by default and changes flexible
variable-redefinition semantics; later releases refine those behaviors and add
experimental parallel/native parser work that is not enabled here. Diagnostic
locations and wording can therefore change even when results do not. The
repository continues to target Python 3.12 with strict mode and has no third-party
mypy plugin. The selected CPython 3.12 macOS arm64 mypyc wheel is native. The new
lock adds native `ast-serialize==0.8.0` and `librt==0.15.0`; Pathspec was already
locked through Hatchling. Mypy 2.3.1 reported two redundant casts after its
improved narrowing. Removing only those casts required no runtime or configuration
change. `uv lock --check`, strict checking of all 42 source files, Ruff, and 48
focused change-risk/Pydantic tests passed. The successful mypy output remains
`Success: no issues found in 42 source files`.

### 6. Bandit 1.8.0 to 1.9.4

The gap drops Python 3.9, adds Python 3.14 support, expands B311 random-function
coverage, adds MarkupSafe XSS and Hugging Face revision checks, refines Torch
deserialization, SQL `VALUES(`, hardcoded-password, timeout, cipher, and line
reporting behavior, removes obsolete lxml blacklist checks, and fixes several
false positives and crashes. These are rule/default changes within the existing
recursive source scan. Bandit and its selected TOML extra remain pure Python and
support Python 3.12. No Bandit configuration or suppression was changed.
`uv lock --check`, the quiet recursive source scan, and the five exact-pin/package
contract tests passed. The security scan still emits no findings or output. The
lock changed only Bandit's direct version and artifact hashes; all transitive
versions were already compatible and remained unchanged.

### 7. pre-commit 4.0.1 to 4.6.2 and pre-commit-hooks 5.0.0 to 6.0.0

The pre-commit gap adds Julia support, improved default Python discovery,
rootless/Docker-in-Docker handling, an explicit `--fail-fast` run option,
unsupported-language aliases, Git 2.54 hook handling, and Node/npm compatibility
fixes through npm 12. It also improves pre-push and all-files conflict handling.
None changes the current `repo: local`, `language: system` configuration.
pre-commit-hooks 6.0.0 requires Python 3.9 or newer, improves shebang diagnostics,
removes two hooks not used here, and disallows a `file-contents-sorter` option
combination not used here. The current trailing-whitespace, EOF, YAML, TOML, and
large-file console scripts remain available. Both packages are pure Python and
support Python 3.12. `uv lock --check`, all 15 configured hooks over all tracked
files, explicit hygiene hooks over this new evidence file, and the five exact-pin
package contract tests passed. The lock changed only the two direct versions and
artifact hashes; all transitive versions remained unchanged. Hook names, order,
scope, and successful output are unchanged.

## Final pins and lock

| Component | Final exact version | Declaration |
| --- | --- | --- |
| CPython | 3.12.14 | `.python-version` |
| Pydantic | 2.13.5 | Runtime dependency; intentionally unchanged |
| uv | 0.12.7 | `[tool.uv]` and CI installer |
| Hatchling | 1.32.0 | `[build-system]` and development group |
| pytest / pytest-cov | 9.1.1 / 7.1.0 | Development group |
| Ruff | 0.16.5 | Development group |
| mypy | 2.3.1 | Development group |
| Bandit | 1.9.4 | Development group with TOML extra |
| pre-commit / pre-commit-hooks | 4.6.2 / 6.0.0 | Development group |

The final lock contains 40 packages and has SHA-256
`53f7842c7c3b3c3d4fb5c0d6009fc26ba0f2ff4d5b6bab3c59dc9c50189da357`.
The only newly locked packages are `tomlkit==0.15.1`,
`ast-serialize==0.8.0`, and `librt==0.15.0`. Pydantic and all runtime metadata
remain unchanged.

## Rollback checkpoints

Each checkpoint is the lock immediately before applying the named cluster. A
rollback restores the listed prior direct pin or pins, the corresponding exact-
pin tests and documentation, and regenerates a lock matching the recorded digest.
The original files are also available from the source rollback commit above.

| Cluster | Prior direct pin or pins | Prior-lock SHA-256 |
| --- | --- | --- |
| uv | 0.12.5 | `9acdb8e6a3c8f59880fb79dcb4fe2a8d123a80eb2012239442a42dd0c01c1d7c` |
| Hatchling | 1.27.0 | `9acdb8e6a3c8f59880fb79dcb4fe2a8d123a80eb2012239442a42dd0c01c1d7c` |
| pytest / pytest-cov | 8.3.4 / 6.0.0 | `1be50de558866ea9cf7c16e0d83e670b6a22ec54b1b9a7e596b8837d9cfd9575` |
| Ruff | 0.8.6 | `b6942a901c3b55f951ae32706efe9749d80f61756daa7876c5702125ec3f0355` |
| mypy | 1.14.1 | `1bf844d14a8e1991e1ec9e91f676b8ebf4f2eba90840feb28163adf26a17dd4a` |
| Bandit | 1.8.0 | `8d8bc853ec6976c6c3883fa4d489b57b24acd5f43c9b5cd621ef679494b13558` |
| pre-commit / pre-commit-hooks | 4.0.1 / 5.0.0 | `6f9e03e409528852e834a36cf677cd06575f743e3fef918adb4c6f8ea4444900` |

## Final repository and artifact validation

The final `make check` passed under uv 0.12.7: lock resolution contained 40
packages; Ruff and formatting passed; mypy found no issues in 42 files; every
A01-A08 repository-local governance command passed with package status `partial`;
Bandit emitted no finding; all 201 tests passed; smoke import and package build
passed. `uv run --frozen pre-commit run --all-files` passed all 15 hooks. A
separate diagnostic pytest-cov run passed and reported 87% without creating a
threshold.

All four default governance summaries and all three public governance JSON
outputs are byte-identical to the baseline. Ruff, formatter, mypy, and Bandit
success outputs are byte-identical; pytest progress and pass count are identical
after normalizing the nondeterministic elapsed time.

The final wheel has the same 34-path set as the baseline. Five packaged Python
files differ only because of the documented Ruff/mypy compatibility edits. The
remaining wheel differences are METADATA, WHEEL, and their RECORD hashes:
Hatchling now emits core metadata 2.5 and identifies generator 1.32.0, while the
development-environment prose names uv 0.12.7. Distribution name and version,
`==3.12.*`, pure-Python tag, and sole runtime requirement `pydantic==2.13.5` are
unchanged. The final sdist has 113 files versus 112 at baseline; the sole new path
is this evidence document, and every other changed path is an exact pin, lock,
CI/documentation, test, or narrow compatibility edit listed above.

CI still installs the same exact uv required by `pyproject.toml`. Its lock, lint,
format, type, seven governance, security, test, and build commands use the same
tools and options as the corresponding Make targets; CI additionally performs
Python installation, frozen synchronization, and pull-request-body validation,
while Make adds the local smoke import and supplies `PYTHONPATH=src` explicitly.

## Gate result and remaining findings

The pre-B01 toolchain refresh gate passed completely on the evidenced local
macOS arm64/Python 3.12 baseline. There are no unresolved toolchain-refresh
blockers. Existing A01-A08 organization, protected-forge, target-control-plane,
independent-review, and applicability findings remain open and every affected
package remains `partial`. This result does not implement or complete B01, B04,
or any later package and does not authorize deployment, activation, credentials,
market access, or capital exposure.
