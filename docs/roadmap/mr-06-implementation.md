# MR 06: Resume the acquisition manifest

Owner: repository founder. Status: implemented and locally verified on 2026-09-15
on `codex/mr-06-acquisition-resume`. This record covers synthetic MR 06 acceptance;
MR 05's permitted-source and historical-evidence boundaries remain open.

## Problem / change

One-partition acquisition could leave published bytes without a saved completion.
[`acquire`](../../src/alpha_research/pipelines/acquisition.py) now validates a saved
manifest, verifies the entire completed prefix, selects remaining partitions
sequentially, and applies bounded backoff only to classified transient transport
failures. [`AcquisitionManifest`](../../src/alpha_research/data/manifests.py) owns
strict input/checkpoint validation and atomic durable file replacement. It persists
a receipt before raw publication; the pipeline appends a completion afterward.
A fresh process reuses pending published bytes and skips completed requests.
Missing or changed completed objects fail before another source access.

The [component contract](../../src/alpha_research/data/README.md#sequential-acquisition-and-resume)
owns caller inputs, state lifetime, retry classification and clock semantics.
The manifest retains the expected resolved job/catalog/code identity, an ordered
completion prefix and at most one pending receipt. Completed clocks remain fixed.
Recovery retains the original pending receipt time and records ingestion when it
reconfirms durability; provisional pending ingestion is not an acknowledged event.
`TransientFetchError` remains an `OSError` subtype; timeout callers now catch it
instead of only `TimeoutError`. Auth errors remain `PermissionError` and schema
errors remain `ValueError`. Retained tests and the NB 05 timeout example are migrated.

## Affected scope

Fetched `origin`; clean `main` equaled `origin/main` at `48bf9b7`, the MR 05 merge
in PR #26. Its history includes MR 04/PR #25 (`b136b36`), MR 03/PR #24 (`bf3fb99`)
and M0/PR #23 (`80b5bc6`). MR 06's prerequisite was merged before branch creation.
MR 08 has not delivered shared input validation; this slice reuses existing
`SourceRequest`, `ResolvedManifest`, `RawObject`, `RawStore` and `DomainCodec`.
No second acquisition wrapper, CLI, frame reader or dataset schema was introduced.

Against `48bf9b7`: **164 added production code-bearing lines, 3 deleted, total
167**. Manifest: 66/0; acquisition pipeline: 93/1; transport: 5/2. Counts include
imports, annotations, signatures and executable statements; exclude comments,
docstrings, blank lines, tests/fixtures and the worked notebook artifact. There
are **no dependency, lockfile, declarative configuration or maintained executable
tooling changes**. The 17-line overage keeps write-ahead receipt persistence,
verified publication, restart and retry with their first working consumer;
splitting would leave the publication/checkpoint failure boundary unhandled.
No validation or invariant was removed to meet the target.

`docs/research/p1-baseline.md` is unchanged, SHA-256
`a00d4a2e6bc4e5b31576abc3cbcc8d794b4da7b522f3d439fe0424374199b17a`.
The frozen lock remains
`1159199bc83be7a75b0ccd2df3a401f3239eda11e37892f5e32d3a88ecf5fc6d`.

## Validation result

CPython 3.14.7, macOS arm64. Commands ran from the checkout unless a `cd` is
shown. The final focused set passed **102 tests, 2 integration cases deselected**;
the explicit raw-store integration selection passed **2 tests, 12 deselected**.
No skips. Ruff lint/format, configured strict typing for all seven affected Python
files, the full engineering-source checker and focused Bandit pass. Local links
are checked under `docs/` and explicitly in the changed component/example guides.
No full local suite was run; the retained hosted complete lane remains a merge gate.

```sh
uv run --frozen --no-editable pytest -q \
  tests/unit/data/test_manifests.py tests/unit/pipelines/test_acquisition_resume.py \
  tests/unit/pipelines/test_acquisition.py tests/unit/data/test_raw_objects.py \
  tests/unit/data/test_raw_store.py
uv run --frozen --no-editable pytest -q -m integration tests/unit/data/test_raw_store.py
uv run --frozen --no-sync ruff check \
  src/alpha_research/data/manifests.py src/alpha_research/data/providers/tardis/transport.py \
  src/alpha_research/pipelines/acquisition.py tests/unit/data/test_manifests.py \
  tests/unit/pipelines/test_acquisition.py tests/unit/pipelines/test_acquisition_resume.py \
  tests/fixtures/mr06/acquire.py
uv run --frozen ruff format --check \
  src/alpha_research/data/manifests.py src/alpha_research/data/providers/tardis/transport.py \
  src/alpha_research/pipelines/acquisition.py tests/unit/data/test_manifests.py \
  tests/unit/pipelines/test_acquisition.py tests/unit/pipelines/test_acquisition_resume.py \
  tests/fixtures/mr06/acquire.py
uv run --frozen --no-sync mypy --strict \
  src/alpha_research/data/manifests.py src/alpha_research/data/providers/tardis/transport.py \
  src/alpha_research/pipelines/acquisition.py tests/unit/data/test_manifests.py \
  tests/unit/pipelines/test_acquisition.py tests/unit/pipelines/test_acquisition_resume.py \
  tests/fixtures/mr06/acquire.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml \
  src/alpha_research/data/manifests.py src/alpha_research/data/providers/tardis/transport.py \
  src/alpha_research/pipelines/acquisition.py
uv run --frozen --no-sync alpha-governance-architecture
uv run --frozen --no-sync python /private/tmp/mr06-verification/check_links.py
git diff --check 48bf9b7
```

The retained [process fixture](../../tests/fixtures/mr06/acquire.py) uses fake HTTP
and real atomic filesystem operations, with process exit 75 at the second partition.
The [resume tests](../../tests/unit/pipelines/test_acquisition_resume.py) compare
complete serialized manifests and preserved raw-object inodes across all four exits:

| Exit boundary | Completed before restart | Fetch offsets over interrupted + resumed runs | Outcome |
| --- | --- | --- | --- |
| Before second raw link | 1 | 0, 1, 1, 2 | Unpublished receipt is refetched; three unique completions. |
| After second raw link | 1 | 0, 1, 2 | Existing bytes verified, synchronized and reused. |
| Before second completion replacement | 1 | 0, 1, 2 | Pending publication recovered without source access. |
| After second completion replacement | 2 | 0, 1, 2 | Completed prefix verified and skipped. |

Every resumed document matches uninterrupted acquisition byte-for-byte with fixed
clocks; a repeated complete run performs no fetch. A separate recovery-clock case
retains an hour-earlier original receipt and records the new durability confirmation.
Other cases reject missing/mutated/truncated completed bytes, corrupt pending bytes,
foreign runs, unknown schemas/fields, duplicate/out-of-order descriptors, invalid
digests/clocks and truncated manifests. Injected staging sync/replacement failures
preserve the prior complete document. Disk failures do not retry. Transient source
failures consume exactly the declared delays and retain the completed prefix on
exhaustion; auth/schema/permanent errors stop immediately.

Initial test-harness failures in the added recovery-clock cases were a missing
`SourceRequest` import after lint removed it before those cases were added. Adding
that import resolved both failures. Initial strict typing required explicit typed
containers around heterogeneous mock responses and the completed descriptor tuple;
Bandit required replacing an internal assertion with an explicit failure. These
were corrected before final passing evidence. Sandbox cache/Git-reference writes
required authorized execution. No source endpoint was accessed.

### Installed candidate and notebook

The final wheel is installed with the existing `_InstalledWheelCheck.validate`
into a fresh environment outside the checkout: hash-locked runtime dependencies,
non-editable installation, isolated imports/round trips, absence of governance,
and `uv pip check`. The copied synthetic fixture and configuration/catalog then
exercise all four interruption boundaries and uninterrupted acquisition in fresh
`-I` processes. All five scenarios yield three completions and repeat without a
fetch; all five reject a subsequently missing completed object before source access.
The standalone scripts/results remain temporary local evidence, not a release archive.

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . \
  --out-dir /private/tmp/mr06-verification/wheels
uv run --frozen --no-editable python /private/tmp/mr06-verification/verify_installed.py
cd /private/tmp/mr06-verification/final-consumer
venv/bin/python -I consumer_check.py > installed-results.txt
mkdir -p committed/raw
venv/bin/python -I acquire.py committed run.json none
```

Final wheel SHA-256: `972ea4000b8ec640d84dadd21479ebfb778fe966fd7e9f8eeff784329456bc7a`.
Resolved synthetic run identity:
`6b91554304f13e957673c9744023a061e69432d20ed36fe41ba64bf4bc4422cd`;
implementation identity:
`bc1b3d15faf97b392f87b7b13a386ab54555d30e6d0bd602dfd71c18f76b72ed`.
The fixed-clock completed manifest digest is
`690c87448e5e300423d4723699574928713381032e6c9568a0de4b7660afae9c`.
These content identities identify the candidate beyond its base commit, including
the newly introduced manifest module. Final committed source retains these bytes;
the last command repeats the three-partition consumer after the implementation commit.

[Notebook section 14](../../examples/research-foundations.ipynb) completes NB 06
with the retained process fixture, intermediate prefix/pending/object tables,
resumed identities and the required failure examples. All **17 code cells** pass
in order in a fresh kernel, after exact installed/source runtime comparison.
Notebook tooling is separately pinned; runtime dependencies and `uv.lock` are unchanged.

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' \
  --with 'nbformat==5.10.4' python examples/run_notebook.py
```

All three notebook attempts passed. The first (`b2e075c4-1b32-40e1-a4f4-c5eb38696615`)
preceded the final assertion/tuple cleanup; the second
(`b2241927-db0c-472d-9109-8359cce975b4`) covered the final runtime. The final notebook
attempt, after adding the notebook helper's explicit return annotation, is
`54468d93-2368-4a07-a2d1-58c6768af4c3`. Its notebook source SHA-256 is
`8ef00fd90277208b03ae1726772c8ce19623d65b6127d624ca858a4540fad035`.
The maintained notebook retains small synthetic outputs and candidate/input identity;
separate attempt snapshots remain under ignored `examples/runs/`. Kernels close
after execution. Maintained `.ipynb`, `.py` and `.md` examples remain tracked;
only generated runs, temporary kernels, caches and checkpoints are ignored.
The packaged component guide was updated after the first wheel check; the final
wheel was rebuilt and its outside-checkout installation/consumer proof renewed.
Runtime source did not change, so the final notebook and focused tests still cover
its exact runtime implementation.

## Risks / reversal

One caller owns the manifest file and protects its directory/raw store from external
mutation. Whole-history JSON checkpoints use bounded-job memory and rewrite/validate
the prefix; no large-history performance or concurrent-writer claim is made.
Process exits and injected I/O failures do not prove physical power-loss behavior.
File/directory synchronization and atomic replacement must be supported; dead-writer
staging files remain ignored until safe cleanup. An absent manifest starts a new run,
so preserve the manifest with its objects. Unacknowledged ingestion clocks can differ
between recovery and uninterrupted runs; completed clocks and source receipt remain fixed.

HTTP/gzip integrity does not establish source framing, coverage, eligibility or
revision availability. No permitted source probe occurred, and MR 05's rights and
retention boundary remains open. QuantLib's existing release restriction is unchanged.
The installed acquisition CLI and expanded job telemetry remain MR 07 work; frame
iteration/validation and dataset publication remain with their owning later MRs.

Revert this isolated branch before dependent consumers merge, retaining raw objects,
manifest files and historical attempts. Unknown schema/run identities fail visibly;
no data deletion, service migration or trading activation is part of reversal.
**Next: MR 07 — Make acquisition usable and observable**, after MR 06 merges.
MR 07 was not started.
