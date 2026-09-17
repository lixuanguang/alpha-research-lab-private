# MR 13 — Validate a canonical partition

Owner: repository founder. Historical validation: implemented and locally verified for review on
2026-09-16. Branch: `codex/mr-13-partition-quality`. Base: updated `main` at
`210db65`, matching freshly fetched `origin/main`. Prerequisites are merged:
MR 09 / PR #33 (`a66b49a`), MR 10 / PR #34 (`d88ba11`), MR 11 / PR #35
(`5b10f78`) and MR 12 / PR #36 (`210db65`). Runtime, contract, fixture and test
commit: `071321e`.

## Problem / change

Decoded and revision-admitted trades previously had no joint partition quality
gate. `QualityPolicy.validate` now checks one exact request's original occurrences,
source ordering, schema, instrument/units, timestamps, positive trade quantities,
authored price ticks, revisions, observed gaps and decision-time eligibility.
`validate_saved_partition` composes the existing verified archive reader with this
operation. It returns invalid/gap/duplicate counts and retained reasons before
allowing any canonical bytes to leave the gate.

Accepted bytes are deterministic and explicitly `exploratory_degraded`; they retain
the policy, request/catalog, complete eligibility and revision histories, exclusions,
reasons and binding-scoped controls. Structural failures and unresolved economic
conflicts return no canonical prefix. `QualityReport.require_canonical()` refuses
publication on rejection. A terminal decoder/read failure records the observed
failure and explicitly marks the unread remainder unvalidated. Raw inputs survive.

The current archive and captured-fixture contracts cannot establish complete
recorder coverage, so causal use fails even with zero observed gaps. Exploratory
use can retain evidence limitations and exclusions with explicit annotations;
it never upgrades them to valid historical data. No caller-supplied completeness
flag, backfilled clock, zero fill or forward fill is introduced. Original source
re-decoding rejects altered canonical capture clocks or values. Trade quantity
zero is invalid here; existing depth deletion quantity zero remains supported.
Publisher quote amounts remain exact source values without an invented rounding
or product-equality rule.

The [quality contract](../data/contracts.md#canonical-partition-quality-mr-13) owns
semantics; the [component guide](../../src/alpha_research/data/README.md#validate-a-canonical-partition-mr-13)
and [researcher guide](../../examples/README.md) explain the current callers.

## Affected scope

`data/quality.py` owns the declared-use policy and scoped result; the dataset
pipeline owns verified saved-input iteration and closes its generator after use.
Inputs and reports are immutable; each validation keeps only local bounded-batch
state. No new dependency, export layer, service, configuration format or command
is added. Dataset manifest identity, atomic snapshot publication and the installed
dataset command remain MRs 14, 15 and 16 respectively.

Against base `210db65`, production code-bearing changes are **253 additions +
0 deletions = 253 lines**: 235 in `data/quality.py` and 18 in the pipeline.
Blank lines, comments, docstrings, tests/fixtures and notebook acceptance examples
are excluded according to the roadmap. There are **zero declarative runtime
configuration/dependency changes and zero executable-tooling changes**.

This exceeds the preferred review size by 103 lines. The cohesive overage keeps
strict policy/report validation, original-source checks (including clock-rewrite
refusal), interval/eligibility/revision composition and its working saved-input
consumer together. Splitting off declarations would have no useful consumer;
splitting off required checks would leave an incomplete quality gate. The source
scope is two files, reusing the existing codecs, source decoders, request/catalog,
revision admission and eligibility selection. No later-MR behavior is included to
justify the overage.

## Validation result

CPython 3.14.7, macOS arm64. Commands below ran from the checkout unless stated.
The initial new tests required two collection fixes (pytest's reserved `request`
fixture name and the resulting import rename typo). Focused test/static findings
also corrected the retained RawStore test path, generic decoder annotation,
`pairwise` iteration, and a nested test generator's docstring. No suppressions or
weakened assertions were added. Sandbox uv-cache denials followed the required
escalation path. The documentation skill's referenced
`docs/coding_standards/documentation.md` is absent; the actual engineering guide's
Documentation section was followed.

```sh
uv run --frozen --no-editable pytest -q tests/unit/data/test_quality.py tests/unit/data/test_revisions.py tests/unit/data/test_normalization.py tests/unit/data/test_eligibility.py tests/unit/data/test_eligibility_selection.py tests/unit/data/providers/binance/test_trades.py tests/unit/data/venues/binance/test_binance_events.py tests/unit/pipelines/test_occurrences.py tests/unit/pipelines/test_dataset.py tests/unit/test_serialization.py
uv run --frozen --no-editable pytest -q -m integration tests/unit/pipelines/test_dataset.py
uv run --frozen --no-sync ruff check src/alpha_research/data/quality.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_quality.py tests/unit/pipelines/test_occurrences.py tests/fixtures/mr13/validate_partition.py examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/quality.py src/alpha_research/pipelines/dataset.py src/alpha_research/data/README.md tests/unit/data/test_quality.py tests/unit/pipelines/test_occurrences.py tests/fixtures/mr13/validate_partition.py examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/data/quality.py src/alpha_research/pipelines/dataset.py tests/unit/data/test_quality.py tests/unit/pipelines/test_occurrences.py tests/fixtures/mr13/validate_partition.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/quality.py src/alpha_research/pipelines/dataset.py
```

All passed. The main selection ran **200 tests, 1 deselected, no skips**. The
separate integration selection ran **1 test, 21 deselected, no skips**. It renews
the existing installed fixture entry point after the pipeline import change.
The new pure gate and saved-input tests account for 20 tests within that selection.

Coverage includes deterministic duplicate/retry disposition and complete lineage;
leading/internal/trailing gaps and their exact tolerance boundary; empty/missing
and mutated raw input; invalid records after a valid prefix; malformed/nonfinite,
negative/zero prices, tick mismatch and zero trade quantities; wrong instruments,
unsafe schemas, altered payloads, source position/time regressions and raw identity
collisions; explicit/dangling/conflicting corrections and preserved prior knowledge;
interval exclusions without trades, unknown membership and future perturbations;
changed catalog linkage; clock-rewrite refusal and retained disconnect scope; strict
policy/report wire round trips and publication refusal. Existing depth-event tests
retain stream-specific zero-quantity semantics. No performance claim is made.

### Installed wheel outside the checkout

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr13-validation/dist
mkdir -p /private/tmp/mr13-validation/inputs
cp configs/data-jobs/binance-archive.json configs/reference/binance-archive-spot.json tests/fixtures/mr12/eligibility.json tests/fixtures/mr13/validate_partition.py /private/tmp/mr13-validation/inputs/
uv run --frozen --no-sync python /private/tmp/mr13-validation/install.py
cd /private/tmp/mr13-validation
./venv/bin/python -I inputs/validate_partition.py inputs
```

The temporary `install.py` invokes the existing
`alpha_research_governance.wheel_smoke._InstalledWheelCheck.validate` with
`Path.cwd()` (checkout), `Path('/private/tmp/mr13-validation')` and the wheel under
its `dist/` directory. That operation creates the external venv, installs frozen
hash-verified binary-only runtime requirements, installs the candidate wheel with
`--no-deps`, checks dependency compatibility, exercises public imports/exact codecs
and verifies that governance tooling is absent. All passed.

The [retained isolated consumer](../../tests/fixtures/mr13/validate_partition.py)
then runs through saved acquisition manifests and verified raw objects with `-I`
and external `site-packages`. It reproduced canonical bytes twice, retained one
duplicate and two observed gaps, refused causal scope, rejected NaN price, zero
trade quantity, conflicting correction and missing input, and round-tripped every
report. No checkout imports, network source access or notebook state are used.
Canonical SHA-256 for its accepted synthetic fixture:
`db9b7ef693605c7197c2acbbeedb4a78c78a47cb0a32117f9ceb4a4b0e546df3`.

Wheel SHA-256: `3502cfe4c3521363997991308d78ca112cf21e96f56805936a9ac99cf845f1f8`.
Frozen lock SHA-256: `e6cd3a169ff4b6850bcb5b09e38c44e1179b0dc1fb7c6a9bd95d2c4a058595e4`.
Eligibility fixture SHA-256: `805010ed176f759785de3a0f441b56411edf6ba11d527a85269f28cbd467a27a`.
All **65 packaged files** match the committed source, wheel and external installation.
These local artifacts are development evidence, not a durable release archive.

### Fresh-kernel NB 13

```sh
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-editable --with 'nbclient==0.10.4' --with 'ipykernel==7.3.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
```

The first notebook attempt passed **49 cells / 21 code cells**, including the
unchanged source of all earlier 44 cells. Before interpreting outputs it verified
all **64 runtime files** against installed `site-packages`, pinned Python 3.14.7,
commit `071321e` and an empty runtime-input diff. The independently built wheel
contains the same runtime bytes. Notebook tooling was separately identified as
nbclient 0.10.4, nbformat 5.10.4 and ipykernel 7.3.0. The kernel shut down and its
temporary kernel directory was removed.

Successful attempt: `63abc105-2bb1-4a5d-8328-24c90e1788b9`, retained under ignored
`examples/runs/research-foundations/`. Notebook source SHA-256:
`80dab5f60df284f5dded1553b37c4e17404b619e4042e687956991d97e777eac`.
Runtime SHA-256: `a8e4e5e325d8cec55ce2186c99465fc135378e2cd1f5305a352d8a247daea2a6`.

NB 13 displays exploratory versus causal disposition (0 invalid, 1 gap, 1 duplicate),
the evidence limitations, **11,939 canonical bytes**, and seven required refusal
examples: required coverage/gap, wrong instrument, conflicting correction, future
whole-sample knowledge shift, NaN price, zero price and zero trade quantity.
The original captured availability stays unchanged. The canonical SHA-256 is
`27f7aed135bab006402b7c46b61a40b165994bbc04b278800de3adf1ea7aa1ab`.
Earlier book sections reuse the same pinned saved OKX/Bitfinex inputs; no new
acquisition or empirical source acceptance occurred.

Final review commands:

```sh
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr13-validation/review.py
uv run --frozen --no-sync alpha-governance-architecture
python3 /private/tmp/mr13-validation/count.py
git diff --check
git ls-files -- examples/
git check-ignore examples/runs/research-foundations/63abc105-2bb1-4a5d-8328-24c90e1788b9.ipynb examples/.kernel-probe/connection.json examples/.ipynb_checkpoints/checkpoint.ipynb
```

The temporary review script checks notebook schema, sequential completed execution,
source identity, earlier cell-source preservation, changed local documentation links,
wheel/source/external-install parity and preserved P1 bytes. All passed: five changed
Markdown documents plus notebook links, and the architecture check's 46 documents.
The first temporary review asserted that no historical kernel directories existed;
the check was corrected to this attempt's creation interval, preserving four older
directories. This did not require a notebook or runtime rerun. Ruff lint and formatting
are renewed after execution. Maintained `.ipynb`, `.py` and `.md` examples remain
tracked; only existing generated run snapshots, checkpoints and kernel artifacts
are ignored. Ignore policy and the notebook runner are unchanged. Small outputs and
metadata were reviewed; no new repository verification tooling was added.

## Risks / reversal

The gate is a bounded in-memory reference operation with synthetic acceptance.
It does not establish empirical coverage, historical membership/source authenticity,
large-input performance, a published dataset, M1 completion or a P1 result. Invalid
counts are observed counts after terminal reader failures; conflicts are separately
identified by their revision reasons. Stored raw inputs and complete histories are
retained. Future query consumers must honor scope and revision effective knowledge.
Existing raw acquisition/storage and decoder evidence is reused because their
implementations are unchanged; the new composition is verified above.

The complete local suite and hosted CI were not run for this handoff. The retained
full hosted lane remains required before merge. The QuantLib release restriction
is unchanged. No release, deployment or source-access authority is implied.

The frozen [P1 specification](../research/p1-baseline.md) is byte-identical to base:
SHA-256 `7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
Revert this MR before dependent consumers merge; preserve any canonical bytes as
schema-versioned exploratory artifacts and select compatible code if reopening
them. No stored data deletion, service migration or operational rollback is needed.
