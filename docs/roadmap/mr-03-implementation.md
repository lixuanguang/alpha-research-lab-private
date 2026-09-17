# MR 03 implementation and local acceptance

Owner: repository founder. Historical validation: implemented and locally verified review
candidate, 2026-09-15 (Asia/Singapore). Branch:
`codex/mr-03-raw-object-verification`. The [roadmap](README.md#raw-inputs-and-acquisition)
remains the sole authority for ownership, dependencies and acceptance.

## Problem / change

A saved-file digest alone did not retain request attribution or original local
receipt/ingestion metadata, nor provide a callable integrity check. The immutable
[`RawObject`](../../src/alpha_research/data/raw_objects.py) now describes existing
bytes and verifies them against their descriptor and an independently supplied
`SourceRequest`. SHA-256 and size cover the exact stored representation, including
compression. Mutation, truncation, append and another request fail explicitly.

`from_file` is the descriptor's first useful consumer; `verify` reopens a saved
file without modifying bytes or metadata. Both read sequential one-MiB chunks.
The descriptor owns its invariants and bounded file operations; no pipeline or
forwarding wrapper is introduced. The existing request identity already binds
instrument/partition/source/catalog/code, and the existing `DomainCodec` supplies
strict serialization. The [component guide](../../src/alpha_research/data/README.md#saved-raw-object-verification)
owns the callable contract, errors and limits.

## Affected scope

Fetched `origin` and fast-forwarded `main` before creating the branch. The base
is `80b5bc64c91fc57f16e4bb19a163a930cc208946`, which merges PR #23 and MR 01's
configuration/request implementation (commit `17940b2`). MR 03 depends only on
MR 01; its prerequisite is merged.

Changes comprise one runtime module, its
[focused tests](../../tests/unit/data/test_raw_objects.py), component/roadmap
documentation and section 11 of the maintained
[foundation notebook](../../examples/research-foundations.ipynb).
Against this base: **84 added production code-bearing lines, 0 deleted, total 84**.
The count excludes blank lines, comments, docstrings, tests/fixtures and the worked
notebook artifact; includes imports, annotations, validators and executable method
bodies. No executable tooling, declarative configuration, dependency or lockfile
changes. The notebook runner is unchanged. No cohesive overage is needed.

State is limited to immutable descriptor values. File handles are scoped to one
operation; failure retains no mutable service state. Tests reuse M0's synthetic
configuration/catalog/frame and generate compressed/binary variants in temporary
directories. No new source data or fixture serialization contract is introduced.

## Validation result

On CPython 3.14.7 / macOS arm64, **63 focused tests passed, 0 failures, 0 skips,
0 deselections**. These include 33 raw-object cases plus existing request and exact
serialization regressions. Coverage includes the known `abc` SHA-256 vector,
immutable/round-trip metadata, original microsecond clocks, empty/multichunk binary
files, compressed-byte identity, wrong instrument/partition/policy, invalid schemas
and types, unsafe mutations, local I/O failure and recovery.

The final checks used a clean frozen non-editable install at
`/private/tmp/mr03-verification/project-venv`, created by the notebook command
below. The following exact invocations passed; the environment variable selects
that installed candidate, and `--no-sync` preserves it:

```sh
export UV_PROJECT_ENVIRONMENT=/private/tmp/mr03-verification/project-venv
uv run --frozen --no-sync pytest -q tests/unit/data/test_raw_objects.py \
  tests/unit/data/test_requests.py tests/unit/test_serialization.py
uv run --frozen --no-sync ruff check src/alpha_research/data/raw_objects.py \
  tests/unit/data/test_raw_objects.py
uv run --frozen --no-sync ruff format --check src/alpha_research/data/raw_objects.py \
  tests/unit/data/test_raw_objects.py
uv run --frozen --no-sync mypy --strict src/alpha_research/data/raw_objects.py \
  tests/unit/data/test_raw_objects.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/raw_objects.py
uv run --frozen --no-sync alpha-governance-architecture
git diff --check HEAD
```

Ruff lint/format and configured strict mypy pass for both changed Python files;
the engineering checker passes its full configured source scope. Bandit passes.
Local-link validation also explicitly includes the changed component and example
READMEs, which the standard `docs/**/*.md` discovery does not cover.
The first local typing/docstring checks found fixture-decorator overload typing
and missing fixture contract sections; both were fixed before final checks.
Some uv calls initially hit sandbox cache denials and succeeded with the required
permission; these were environment-access failures, not product failures.

### Installed consumer outside the checkout

Built the wheel and reused `_InstalledWheelCheck.validate` from the existing
wheel-smoke tool to create `/private/tmp/mr03-verification/consumer/venv`, install
hash-locked runtime dependencies and check isolated imports/round trips without
governance installed. `uv pip check` passed. Copied the M0 config, catalog
and synthetic frame needed by a local acceptance script. The final wheel includes
the updated component README; it was reinstalled and the six acceptance outcomes
renewed from the outside-checkout working directory with Python `-I`:

```sh
uv run --frozen --no-editable python /private/tmp/mr03-verification/verify_installed.py
UV_PROJECT_ENVIRONMENT=/private/tmp/mr03-verification/project-venv \
  uv run --frozen --no-sync uv build --no-build-isolation --wheel --no-sources . \
  --out-dir /private/tmp/mr03-verification/final-wheels
uv pip install --python /private/tmp/mr03-verification/consumer/venv/bin/python \
  --no-deps --reinstall \
  /private/tmp/mr03-verification/final-wheels/alpha_research_lab-0.1.0-py3-none-any.whl
cd /private/tmp/mr03-verification/consumer
venv/bin/python -I /private/tmp/mr03-verification/consumer_check.py
```

The first command prepared the initial wheel environment; its local script called
the existing wheel check with the initial wheel under `wheels/`. Scripts, both
wheel builds, copied inputs and `consumer/installed-results.json` remain local
under `/private/tmp/mr03-verification/`; they are temporary verification artifacts,
not a release archive. The maintained tests retain the reproducible API scenarios.

| Outside-checkout case | Result |
| --- | --- |
| Verify a 145-byte gzip object and round-trip descriptor JSON | Passed |
| Change a gzip header byte while preserving decompressed content | SHA-256 mismatch |
| Remove the final retained byte | Size mismatch: expected 145, got 144 |
| Supply another minute's request | Request identity mismatch |
| Supply another instrument's request | Request identity mismatch |
| Restore original bytes and verify again | Passed; original clocks/wire bytes unchanged |

### Notebook checkpoint and retained identities

Completed NB 03 in section 11; all **12 code cells** passed in a fresh kernel.
The notebook displays retained/compressed and decoded hashes, exact request
bounds/identity, retrieval reference, original clocks, JSON round trip, three
expected failures and successful recovery. The runner shut down the kernel.

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/mr03-verification/project-venv UV_LINK_MODE=copy \
  uv run --frozen --no-editable --with 'nbclient==0.10.4' \
  --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' python examples/run_notebook.py
git ls-files -- examples/
git check-ignore -v examples/runs/research-foundations/probe.ipynb \
  examples/.kernel-probe/kernel.json examples/.ipynb_checkpoints/probe.ipynb
```

Final attempt `7512daee-cd37-4665-8cab-f9379240c0af` verified 33 installed runtime
files against the checkout. Its request identity agrees with the isolated wheel
consumer. The kernel reports exactly nbclient 0.10.4, ipykernel 7.2.0 and nbformat
5.10.4. Its snapshot is retained under ignored `examples/runs/research-foundations/`.
Maintained `.ipynb`, `.py` and `.md` examples remain tracked; only the permitted
generated run/kernel/checkpoint paths above are ignored. Reviewed the maintained
code, metadata and small synthetic outputs; no credentials or restricted data.

The earlier attempt `36299df8-c7ca-4a01-bf10-5e7866ecefed` passed the scenarios but
used the existing `.venv`, which still contains renamed duplicate runtime files
from the previously recorded M0 environment issue. Those extras changed the
implementation/request identity and exposed ipykernel 7.3.0. That attempt is
retained but superseded as candidate evidence by the clean run. The existing
editor environment was not repaired as part of MR 03; use the clean command above.

| Candidate/input identity | SHA-256 |
| --- | --- |
| Raw-object runtime source | `067e756cd625e8d500085a46a041f5fb8a6b0b7e2a753aacce0126e2c1826e0c` |
| Final wheel | `3ef1f0dc60884c3ec8490a92ccac17c3a813494e8ac113ebee9970ad7f9dc3f9` |
| Installed implementation identity | `03e3f241eb34b9de1c4cff130f977ce89559d626283b01e459124bbec9237793` |
| Notebook source | `83bb8266fc2b961c27b2f486a20634e3b5899fa6af8ea9f53ca233f2783374f7` |
| Notebook runtime input diff against base | `5395ad5d24fed13016b307b89dff2229af68cfb144169868ecdf093cb2b5c42b` |
| Verified gzip bytes | `e4a81e816955ccd1884b30986a6fea04c10b8c0eafd14233d0341cc6a0b19d26` |
| Expected BTC minute request | `3fdd7890d4da087eff6c3e7156b4e2d4433fc99f1eab7c2de3793e222e0928c6` |
| Unchanged uv lock | `1159199bc83be7a75b0ccd2df3a401f3239eda11e37892f5e32d3a88ecf5fc6d` |
| Preserved P1 specification | `a00d4a2e6bc4e5b31576abc3cbcc8d794b4da7b522f3d439fe0424374199b17a` |

## Risks / reversal

MR 03 verifies existing bytes against trusted metadata at read time. Callers must
exclude concurrent writes. The factory records the caller's request/retrieval
attribution; it cannot authenticate a provider or establish transport completeness,
coverage, historical eligibility or dataset validity. Atomic publication, storage,
acquisition, manifests and resume are later MRs. No empirical P1 result is claimed.

The frozen P1 specification, configuration/catalog/fixture bytes, dependency lock,
financial/event contracts and notebook runner are unchanged. Native-adapter and
unrelated pipeline behavior reuse existing evidence; no new performance, external
source or release claim is made. Full local `make check` was not run for this
bounded slice; hosted complete merged-result CI remains required before merge.
The existing QuantLib release restriction remains in force.

Revert this MR's runtime module, tests, notebook section and documentation together
before downstream consumers merge; no stored objects or service state need removal.
