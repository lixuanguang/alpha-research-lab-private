# MR 04: Durable raw-byte publication

Owner: repository founder. Historical validation: implemented and locally verified on 2026-09-15
for review on `codex/mr-04-durable-raw-store`. This record covers MR 04 only;
acquisition, manifests and dataset validity remain planned.

## Problem / change

MR 03 can verify saved bytes but cannot publish an immutable object safely.
[`RawStore`](../../src/alpha_research/data/raw_store.py) now stages a saved file on
the destination filesystem, verifies its exact bytes with `RawObject.verify`,
and publishes its SHA-256 name through an atomic, no-overwrite hard link. File
and directory synchronization must succeed before the method acknowledges
completion. Readers verify the complete published object before receiving a
read-only stream. Repeated publication reuses the existing inode, even when the
original source is gone; conflicts remain unchanged and fail explicitly.

The first consumers are the storage acceptance cases and section 12 of the
[foundation notebook](../../examples/research-foundations.ipynb). The library owns
bounded file operations and immutable publication; no pipeline or forwarding
wrapper is introduced. The [component guide](../../src/alpha_research/data/README.md#durable-raw-byte-store)
owns the callable contract, filesystem prerequisites, errors and recovery steps.

## Affected scope

Fetched `origin`; `main` already equaled updated `origin/main` at
`bf3fb991bdf13889ef116e9111106317224fc6b7`. This merge of PR #24 contains MR 03
implementation `1236da5`; ancestry was checked before creating the MR 04 branch.
MR 04's sole prerequisite is merged.

Against that base: **51 added production code-bearing lines, 0 deleted, total 51**.
This includes imports, declarations, annotations and executable method bodies;
excludes blanks, comments, docstrings, tests/fixtures and the worked notebook
artifact. The new interruption script is a test fixture shared by retained tests
and NB 04, not runtime tooling. No executable tooling, configuration, dependency,
lockfile or public re-export changes. No overage is needed.

`RawStore` retains only its explicit directory path. Each call owns its temporary
file and handles; caller-owned immutable descriptors retain their original clocks.
The store never persists descriptors or advances acquisition checkpoints. Existing
configuration, catalog, M0 synthetic frames and `DomainCodec` serialization are
reused unchanged. There is no new source-data fixture.

## Validation result

On CPython 3.14.7 / macOS 26.6.2 arm64: **77 focused tests passed**, with no
failures, skips or deselections. This comprises 14 storage cases and 63 existing
raw-object/request/serialization regressions. The storage cases include empty and
multichunk files, compressed-byte changes/truncation, repeated publication without
the source, unsafe descriptor/request changes, symlinks/directories, competing
publishers, file/directory synchronization failures and abrupt process exit before
and after the atomic link.

The final checks use the clean frozen non-editable environment created by the
notebook command below. After correcting only the interruption fixture's argument
typing/docstring, its two process cases were renewed: **2 passed, 12 deselected**.
The unchanged runtime and other behavioral cases reuse the 77-test run.

```sh
/private/tmp/mr04-verification/project-venv/bin/python -m pytest -q -m 'not performance' \
  tests/unit/data/test_raw_store.py tests/unit/data/test_raw_objects.py \
  tests/unit/data/test_requests.py tests/unit/test_serialization.py
/private/tmp/mr04-verification/project-venv/bin/python -m pytest -q -m integration \
  tests/unit/data/test_raw_store.py
/private/tmp/mr04-verification/project-venv/bin/ruff check \
  src/alpha_research/data/raw_store.py tests/unit/data/test_raw_store.py \
  tests/fixtures/mr04/interrupt_publish.py
/private/tmp/mr04-verification/project-venv/bin/ruff format --check \
  src/alpha_research/data/raw_store.py tests/unit/data/test_raw_store.py \
  tests/fixtures/mr04/interrupt_publish.py
/private/tmp/mr04-verification/project-venv/bin/mypy --strict \
  src/alpha_research/data/raw_store.py tests/unit/data/test_raw_store.py \
  tests/fixtures/mr04/interrupt_publish.py
/private/tmp/mr04-verification/project-venv/bin/alpha-governance-engineering-standards
/private/tmp/mr04-verification/project-venv/bin/bandit -q -c pyproject.toml \
  src/alpha_research/data/raw_store.py
/private/tmp/mr04-verification/project-venv/bin/alpha-governance-architecture
git diff --check HEAD
```

Ruff lint/format, strict mypy, full configured engineering-source checks, Bandit
and repository-local links pass. Link validation explicitly includes the changed
component/example READMEs, beyond the architecture command's `docs/**/*.md` scope.
The first typing check found argparse's inferred `Any` fields in the test fixture;
a typed namespace and complete fixture docstring resolved it without suppression.
An initial test command used `uv --no-sync --python ...`, which selected the old
project environment instead of the clean environment and failed collection on the
new import. The explicit candidate interpreter above fixed that harness error.
Some uv calls hit sandbox cache denials; their authorized retries succeeded.

### Installed consumer outside the checkout

Built one wheel using Hatchling from the frozen environment, then reused the
existing `_InstalledWheelCheck.validate` to install hash-locked runtime dependencies
and the wheel into `/private/tmp/mr04-verification/consumer/venv`. Its isolated
imports, exact round trips, absence of governance and `uv pip check` passed.
Copied only the existing synthetic configuration/catalog/frame and the maintained
[interruption fixture](../../tests/fixtures/mr04/interrupt_publish.py) for the
additional storage consumer. No checkout source or editable imports were used.

```sh
/private/tmp/mr04-verification/project-venv/bin/python -m hatchling build -t wheel \
  -d /private/tmp/mr04-verification/wheels
/private/tmp/mr04-verification/project-venv/bin/python \
  /private/tmp/mr04-verification/verify_installed.py
cd /private/tmp/mr04-verification/consumer
venv/bin/python -I consumer_check.py
```

The local scripts invoke the existing wheel check and the same public API
scenarios retained in the tests. Scripts, copied inputs, wheel and
`consumer/installed-results.json` remain under `/private/tmp/mr04-verification/`;
these are temporary development evidence, not a release archive.

| Isolated wheel outcome | Result |
| --- | --- |
| Exit before link | Verified staging orphan remains; reader reports missing object |
| Retry before link | Publishes from saved source; repeat reuses inode; orphan cleanup preserves object |
| Exit after link | Reader sees all 145 verified gzip bytes; staging and published names share an inode |
| Retry after link without original source | Verifies/resynchronizes existing object; repeat reuses inode |
| Wrong request minute | Rejected before reading |
| Corrupt published object: read | SHA-256 mismatch |
| Corrupt published object: publish | SHA-256 mismatch; existing bytes remain unchanged |

The descriptor survives JSON round trip and all failures with its original
retrieval reference and UTC receipt/ingestion clocks unchanged.

### Notebook checkpoint and retained identities

NB 04 is complete in section 12. All **13 code cells** passed in a fresh kernel,
with 34 installed runtime files verified against the candidate. The outputs show
staging/published state at both abrupt exits, two reconciled retries, inode reuse
and two corrupt-object rejections. The runner shut down its kernel. The notebook
tooling reports nbclient 0.10.4, ipykernel 7.2.0 and nbformat 5.10.4 separately from
the runtime environment.

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/mr04-verification/project-venv UV_LINK_MODE=copy \
  uv run --frozen --no-editable --with 'nbclient==0.10.4' \
  --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py
git ls-files -- examples/
git check-ignore -v examples/runs/research-foundations/probe.ipynb \
  examples/.kernel-probe/kernel.json examples/.ipynb_checkpoints/probe.ipynb
```

Attempt `57c11987-7d3f-4cb7-9760-6734d0d7795c` is retained under ignored
`examples/runs/research-foundations/`. The maintained notebook was subsequently
written with a new-cell `ModuleNotFoundError` output, while the archived fresh
execution remained successful. Cell sources were identical; the later output was
preserved as `mr04-external-output-observed.ipynb` in the ignored run directory and
verified outputs restored. Its origin was not established. The pre-existing editor
environment issue remains separate; the explicit clean command above and isolated
wheel imports pass. No notebook runner change or runtime path patch was needed.

Maintained `.ipynb`, `.py` and `.md` examples remain tracked. Only the policy's
generated run/kernel/checkpoint paths are ignored. Reviewed source, metadata and
small synthetic outputs; no credentials or restricted data are retained.

| Candidate/input identity | SHA-256 |
| --- | --- |
| Raw-store runtime source | `1a3f60551a2dcd4cf869a69d1e9259766abb19a391c9034963406994586845f0` |
| Candidate wheel | `0d780b2020ff17c4607adf2b00b1eda01dcbe372c363c72081f1748641d73538` |
| Installed implementation identity | `9b3c12b399518923604777e0c232f56587ba9727f9d6f0eb1554b77aea81de5d` |
| Notebook source | `8a3e0ba5c3950a045ee2576046564ccd7142ab6c5f7257787ff889d04237b006` |
| Notebook runtime input diff against base | `11411356e904ae83e9b412a2b996a0708d7a07c84a15b2b2500c78e8bed5a284` |
| Interrupted-publisher fixture | `19e44f521ce1ca3e2177e672fef9e8fe78cd6a87eade56da218f210f82777448` |
| Verified gzip bytes | `e4a81e816955ccd1884b30986a6fea04c10b8c0eafd14233d0341cc6a0b19d26` |
| Expected minute request | `fd7117d2a1d5dc7d3e2d477bbb07fe7d316e607fc1d0f3f5b50a9f5adf67e7bc` |
| Unchanged uv lock | `1159199bc83be7a75b0ccd2df3a401f3239eda11e37892f5e32d3a88ecf5fc6d` |
| Preserved P1 specification | `a00d4a2e6bc4e5b31576abc3cbcc8d794b4da7b522f3d439fe0424374199b17a` |

### Editor environment repair before merge

On 2026-09-15 the editor installation lacked `data/raw_store.py`, despite the
successful clean-environment run. The failed output remains at local ignored
`examples/runs/research-foundations/mr04-editor-missing-raw-store.ipynb`.
Rebuilding with Hatchling 1.32.0 reproduced wheel SHA-256
`0d780b2020ff17c4607adf2b00b1eda01dcbe372c363c72081f1748641d73538`.
Reinstallation with `--no-deps --reinstall --link-mode copy` restored all 34 files;
20 renamed duplicates were retained in
`/private/tmp/mr04-notebook-repair/duplicate-runtime-files/`, indexed by
`quarantined-files.json`. Their origin was not established.

Attempt `92d41cf8-f517-4ff3-969e-f28790bd138c` passed 13 code cells via
`examples/run_notebook.py --kernel-python .venv/bin/python`, on CPython 3.14.7 /
macOS 27.0 arm64 with ipykernel 7.3.0. Notebook source SHA-256 remained
`8a3e0ba5c3950a045ee2576046564ccd7142ab6c5f7257787ff889d04237b006`;
runtime was unchanged from `caec320`. Current repair instructions belong in the
[notebook operations guide](../../examples/notebook-operations.md).

## Risks / reversal

The store requires a durably provisioned, caller-controlled local directory and
filesystem/device support for atomic hard links and file/directory synchronization.
It excludes external mutation/removal during verification and subsequent reads;
read-only mode is not protection from the owner. Orphan staging is ignored and
must only be removed when no active writer owns it. Physical power loss, network
filesystems and object stores were not tested. No provider authenticity, transport
completeness, persisted manifest, dataset validity or empirical P1 result is claimed.

The P1 specification, existing configuration/fixtures, dependency lock and financial,
event and descriptor wire contracts are unchanged. Full local `make check` was not
run for this slice; the complete hosted merged-result lane remains required before
merge. QuantLib's existing release restriction remains in force.

Revert this module, tests, NB 04 and documentation together before dependent
consumers merge. Existing raw files can be retained and verified by MR 03; this
slice adds no service or acquisition state requiring migration.
