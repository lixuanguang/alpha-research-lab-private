# MR 05: One bounded Tardis partition

Owner: repository founder. Status: implemented and locally verified with synthetic
responses on 2026-09-15, on `codex/mr-05-tardis-partition`. **Permitted-source
acceptance remains open:** no rights admission or protected retention location
was supplied, so no source-data request was made. This record covers MR 05 only.

## Problem / change

The existing request, descriptor and durable store did not have a fetch consumer.
[`fetch_partition`](../../src/alpha_research/pipelines/acquisition.py) now composes
an explicitly supplied HTTP connection and UTC clock with
[`TardisTransport`](../../src/alpha_research/data/providers/tardis/transport.py),
`RawObject` and `RawStore`. One selected instrument/minute produces exact retained
gzip bytes, an immutable descriptor, and run/partition progress. `stored` is emitted
only after verified durable publication. Failures emit their stage and error type;
HTTP bodies and credentials are excluded. Original source clocks remain in the raw
frames; local receipt and post-publication ingestion clocks are recorded separately.

The [component guide](../../src/alpha_research/data/README.md#one-partition-acquisition)
owns the callable inputs, HTTP/gzip checks, lifetime and failure semantics.
Configuration now admits the paired `historical` / `acquisition.fetch` capability
with its first consumer. Existing fixture jobs remain unchanged; the fixture
consumer explicitly rejects an acquisition selection. No new dependency, transport
framework, source fixture, acquisition CLI, manifest or retry mechanism is added.

## Affected scope

Fetched `origin`; clean `main` equaled `origin/main` at
`b136b36` (PR #25). Its history includes MR 01 in PR #23 (`80b5bc6`), MR 03
in PR #24 (`bf3fb99`), and MR 04 in PR #25 (`b136b36`). All selected prerequisites
were merged before creating the branch.

Against that base: **152 added production code-bearing lines, 6 deleted, total
158**. Breakdown: configuration 7/6, fixture consumer 2/0, transport 80/0,
acquisition pipeline 63/0. Counts include imports, signatures, annotations and
executable bodies, excluding blank lines, comments, docstrings, tests and the
worked notebook artifact. No executable-tooling, declarative configuration,
dependency or lockfile changes. The small cohesive overage keeps admission,
HTTP/gzip validation, safe failure reporting and durable publication together with
their first useful consumer; splitting would leave one half without this MR's
fetch-through-storage acceptance. No validation was removed to reduce the count.

Reusable transport behavior lives in its adapter class; workflow construction,
temporary-file I/O sequencing and reporting live in the pipeline. The transport
retains only the explicit connection and byte bound; invocation state and temporary
files are local. The returned descriptor/request remain caller-owned. Existing
`DomainCodec`, configuration/reference validation, gzip, HTTP and storage libraries
are reused. `docs/research/p1-baseline.md` is unchanged, SHA-256
`a00d4a2e6bc4e5b31576abc3cbcc8d794b4da7b522f3d439fe0424374199b17a`.

## Validation result

CPython 3.14.7, macOS arm64. Commands below ran from the checkout unless a `cd`
is shown. Focused regressions passed **110 tests, 3 integration cases deselected**.
After tightening only transport admission/header checks and adding a body-timeout
case, the complete affected acquisition file passed **24 tests**, no skips or
deselections. The unchanged 87 configuration/request/storage/fixture cases reuse
the first run. The affected installed fixture-command integration passed **1 test,
21 non-integration cases deselected**. No full local suite was run; hosted required
CI remains a merge gate.

```sh
uv run --frozen --no-editable pytest -q \
  tests/unit/pipelines/test_acquisition.py tests/unit/pipelines/test_dataset.py \
  tests/unit/data/test_raw_objects.py tests/unit/data/test_raw_store.py \
  tests/unit/data/test_requests.py tests/unit/test_configuration.py
uv run --frozen --no-editable pytest -q tests/unit/pipelines/test_acquisition.py
uv run --frozen --no-editable pytest -q -m integration tests/unit/pipelines/test_dataset.py
uv run --frozen ruff check src/alpha_research/configuration.py \
  src/alpha_research/pipelines/dataset.py src/alpha_research/pipelines/acquisition.py \
  src/alpha_research/data/providers/tardis/transport.py tests/unit/pipelines/test_acquisition.py
uv run --frozen ruff format --check src/alpha_research/configuration.py \
  src/alpha_research/pipelines/dataset.py src/alpha_research/pipelines/acquisition.py \
  src/alpha_research/data/providers/tardis/transport.py tests/unit/pipelines/test_acquisition.py
uv run --frozen mypy --strict src/alpha_research/configuration.py \
  src/alpha_research/pipelines/dataset.py src/alpha_research/pipelines/acquisition.py \
  src/alpha_research/data/providers/tardis/transport.py tests/unit/pipelines/test_acquisition.py
uv run --frozen alpha-governance-engineering-standards
uv run --frozen bandit -q -c pyproject.toml \
  src/alpha_research/data/providers/tardis/transport.py src/alpha_research/pipelines/acquisition.py
uv run --frozen alpha-governance-architecture
uv run --frozen python /private/tmp/mr05-verification/check_links.py
git diff --check HEAD
```

Ruff lint/format, configured strict typing, the full engineering-source checker
and Bandit pass. Link verification includes the changed component/example guides
in addition to the architecture checker's normal `docs/**/*.md` discovery.

The retained tests cover two configured instruments, fixed request origin/offset,
exact compressed-byte identity and descriptor round trips, original clocks,
progress, malformed/truncated gzip, HTTP length/encoding/slice mismatch, 401/403,
redirect/503 rejection, request and body timeouts, protocol truncation, both byte
caps, empty gzip, recovery after failure, missing destination, wrong consumer,
unsafe request mutation, admission markers and credential validation.

Initial test-harness failures were two successful-acquisition assertions using
`DomainCodec` with a generic dictionary target, plus a fake HTTP stream typing
mismatch. Tests now use msgspec's typed dictionary decoder and a buffered stream;
no runtime serialization API was broadened. An edit typo in the expected filter
string was fixed before the passing run. Some uv invocations hit sandbox cache
access errors and succeeded with authorized execution. The first outside-checkout
copy command used the wrong working directory; corrected setup then passed.

### Installed candidate and notebook

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . \
  --out-dir /private/tmp/mr05-verification/wheels
uv run --frozen --no-editable python /private/tmp/mr05-verification/verify_installed.py
cd /private/tmp/mr05-verification/final-consumer
venv/bin/python -I consumer_check.py > installed-results.txt
```

The local verification script calls the existing `_InstalledWheelCheck.validate`:
fresh outside-checkout venv, hash-locked runtime dependencies, non-editable wheel,
isolated imports/round trips, absence of governance, and `uv pip check`. A copied
NB 05 consumer uses only the installed runtime plus copied synthetic config,
catalog and frame. It reopens 145 gzip bytes, verifies the original capture
`2024-06-01T00:00:00.0041023Z`, price `67540.01000000`, quantity `0.00146000`, and
all four notebook failures. Scripts and outputs are temporary development evidence
under `/private/tmp/mr05-verification/`, not a release archive.

Final wheel SHA-256:
`55c3b49b44a5a2e5ddde353048ceb210aafbf15aa154bfa9475118f7f5305142`.
The [maintained notebook](../../examples/research-foundations.ipynb), section 13,
retains equivalent runnable evidence and small synthetic tables. All **15 code
cells** run in order in a fresh kernel against the installed candidate, with exact
installed/source byte comparison and runtime/source/input hashes in section 3:

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.2.0' \
  --with 'nbformat==5.10.4' python examples/run_notebook.py
```

The first attempt `aca504e8-6d59-42bd-9f37-66187b579049` failed in the new display
code by referring to a nonexistent provenance field. Using the retained event's
`original_capture_time` fixed it; attempt `36d4c297-9e2e-4da0-b652-9b72d2b36089`
passed. The final post-cleanup attempt is `9ee84bff-e14a-43c6-92bb-cd21a1e3fd39`;
its notebook source SHA-256 is `012837143ff7d1ba9d0406db5ea7708eeae48a151f95371660ab99bc3d3dc319`.
The maintained notebook and ignored attempt snapshot retain `research_execution`
metadata and the exact runtime content identity, including untracked candidate modules. Kernels close after
each attempt. Maintained `.ipynb`, `.py` and `.md` examples are tracked; generated
runs, temporary kernels and checkpoints remain ignored. No raw source data or
credentials were added.

### Source feasibility investigation — open acceptance boundary

Primary documentation was checked on 2026-09-15; no private/source endpoint was
probed and no credential was read. The frozen specification explicitly requires
rights evidence before source access. The user was asked for the dated admission
and protected location; neither was supplied during implementation.

| Claim | Available evidence and remaining gap |
| --- | --- |
| Endpoint and partition | [Tardis HTTP reference](https://docs.tardis.dev/api/http-api-reference) documents `/v1/data-feeds/binance`, fixed `from` plus minute offset, lowercase symbol filters, gzip and keyless first-of-month samples. A hypothetical probe is BTCUSDT at offset 0 of `2024-06-01T00:00:00Z`, `sliceSize=1`. Actual response headers, body and endpoint success remain unobserved. |
| Framing and clocks | The [Binance details](https://docs.tardis.dev/historical-data-details/binance) describe exchange-native payloads with capture prefixes. The [data FAQ](https://docs.tardis.dev/faq/data) describes 100 ns capture precision, row order and possible permanent gaps. Actual selected-sample Binance `T`/`E` millisecond units, exact framing and retained blank lines still need a permitted probe. Synthetic decoder success does not prove them. |
| Use and retention | Current [terms](https://docs.tardis.dev/legal/terms-of-service), clauses 9.1–9.5, describe internal-use/storage rights and continuing rights for compliant downloads, including samples, subject to restrictions. They also constrain disclosure and AI uses. These current terms are a potential evidence source, not supplied customer-specific admission. No agreed protected location or applicable licensor/entitlement record was established; no permission or indefinite retention is claimed here. |
| Historical eligibility | [Instrument metadata documentation](https://docs.tardis.dev/api/instruments-metadata-api) distinguishes current `active` status from availability and describes historical changes as best effort except tracked contract multipliers. Most requests require paid entitlement. No evidence-backed BTCUSDT trading eligibility interval with historical knowledge time was obtained; the 2026 authored catalog remains an assumption. |
| Revision availability | Raw-feed documentation and metadata change dates do not establish a complete correction/version history with first-availability times for the selected 2024 trades. No retrievable such evidence was obtained. MRs 10–12/17 retain reconciliation and selection ownership; unknown revisions cannot become a causal claim. |

Do not scale acquisition or mark source/P1 acceptance complete on this evidence.
A later permitted probe must retain request, descriptor, dated rights reference,
protected retrievable gzip bytes and safe framing/unit observations. This MR does
not substitute another provider, buy access, or modify the frozen experiment.

### Duplicate-file cleanup

During final verification four untracked ` 2` copies appeared in the checkout:
the MR 04 record, raw store, storage test and interruption fixture. Each matched
its original byte-for-byte. They were moved to
`/private/tmp/mr05-verification/duplicate-quarantine/`, preserving originals and
recording paths/digests in `manifest.json`. A further 35 such files in the local
installed `alpha_research` package were quarantined there: 32 identical and three
older/different copies, all preserved. Their origin was not established.

```sh
uv pip install --python .venv/bin/python --no-deps --reinstall --link-mode copy \
  /private/tmp/mr05-verification/wheels/alpha_research_lab-0.1.0-py3-none-any.whl
```

All 37 installed package files then matched the verified wheel; the wheel itself
contains no duplicate names. No duplicate remains in the owned checkout paths or
installed runtime package. The final notebook was refreshed after this cleanup.
The maintained example files remain tracked; generated snapshots and the
reversible duplicate quarantine are excluded from the implementation commit.

## Risks / reversal

Socket inactivity is bounded; total wall time and DNS resolution are not. This
small transport holds bounded compressed and expanded representations in memory.
HTTP/gzip integrity is not frame validity, completeness, eligibility or revision
acceptance. Storage/report/clock failures after publication may leave verified
bytes without acknowledgement; no durable acquisition checkpoint is claimed.
QuantLib's existing release restriction remains; this is development evidence.

Revert this isolated change before dependent consumers merge; keep existing raw
objects and historical notebook attempts. No service/schema migration or trading
activation is involved. **Next: MR 06 — acquisition manifest and resume**, after
MR 05 merges, retaining the source-evidence limits. MR 06/07/08 work was not started.
