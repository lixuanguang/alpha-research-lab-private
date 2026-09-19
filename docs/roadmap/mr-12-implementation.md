# MR 12 — Select the universe as of a decision

Historical commands below retain paths from their tested revision. Current source links
and the [test layout](../../tests/README.md) use the reorganized locations.

Owner: repository founder. Historical validation: implemented and locally verified for review on
2026-09-16. Branch: `codex/mr-12-as-of-eligibility`. Base: updated `main` at
`5b10f78`, matching fetched `origin/main`. Prerequisite MR 11 merged in PR #35 at
that base. Runtime, fixture and consumer commit: `774cff9`.

## Problem / change

The assertion reader retained evidence but could not reconstruct membership for a
decision or admit an explicitly evidenced listing correction. `EligibilityAssertions`
now owns pure `select` and immutable `append` operations. Validity is half-open;
knowledge is inclusive and independent. Results retain the included/excluded
assertion, reason and evidence, or explicitly return unknown/unsupported. The
notebook's universe consumer admits only explicit inclusion.

Corrections name a retained predecessor by assertion content identity and require
the same instrument, later knowledge and distinct evidence. They replace the whole
prior assertion at the knowledge boundary, so removed valid dates do not fall back
to withdrawn history. Dangling/branched links and contradictions over overlapping
validity and knowledge lifetimes fail. Earlier decisions remain reconstructible.
Version-1 wire fields remain supported and unchanged; corrections require version 2,
which older readers reject. No existing file is rewritten or migrated automatically.

The [data contract](../data/contracts.md#decision-time-selection-and-corrections-mr-12)
and [component example](../../src/market_data/README.md#select-membership-at-a-decision)
record the exact semantics. The reader's existing catalog/units, evidence-clock,
strict-codec and immutable-record contracts remain in force.

## Affected scope

`data/eligibility.py` owns validation and selection; notebook, retained isolated
consumer and focused tests are its current callers. Inputs are explicit immutable
history, member ID and two UTC clocks. Results are an existing assertion or a named
unavailable outcome. Appends return a new history; queries keep no mutable state.
The pipeline, configuration resolver, acquisition, quality and publication are unchanged.
No new abstraction, public export, dependency or operational telemetry is needed for
this pure operation.

Against base `5b10f78`, production code-bearing changes are **79 additions +
9 deletions = 88 lines**, including imports, annotations, validators and codec setup.
Blank lines, comments, docstrings, tests/fixtures and notebook acceptance examples
are excluded under the roadmap rule. There are **zero declarative runtime
configuration/dependency changes and zero executable-tooling changes**. No overage
or split is needed. The synthetic JSON adds a retained correction, not a live config.

## Validation result

CPython 3.14.7 on macOS arm64. Commands run from the checkout unless specified.
An initial focused selection passed 93 tests. The final affected selection passed
**112 tests, no skips or deselections**:

```sh
uv run --frozen --no-editable pytest -q tests/unit/data/test_eligibility.py tests/unit/data/test_eligibility_selection.py tests/unit/test_reference_data.py tests/unit/test_configuration.py tests/unit/test_serialization.py
uv run --frozen --no-sync ruff check src/alpha_research/data/eligibility.py tests/unit/data/test_eligibility_selection.py tests/fixtures/mr12/select_eligibility.py examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check src/alpha_research/data/eligibility.py src/alpha_research/data/README.md tests/unit/data/test_eligibility_selection.py tests/fixtures/mr12/select_eligibility.py examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict src/alpha_research/data/eligibility.py tests/unit/data/test_eligibility_selection.py tests/fixtures/mr12/select_eligibility.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml src/alpha_research/data/eligibility.py
```

All passed. Tests cover before/at/after both clocks, future perturbations through
the actual selector, full-predecessor retirement after interval corrections,
multiple correction generations, excluded members beyond catalog validity,
unknown versus unsupported, late authored assumptions, empty history, deterministic
agreement, file reordering, constructor/decoder parity, unsafe nested inputs,
legacy wire fields, unknown versions, malformed/dangling/cross-member/branched links,
same-time or reused-evidence corrections, conflicting assertions and failure recovery.
The existing reader/catalog/serialization tests retain their original contracts.
No affected network/process integration test or performance claim applies here.

Initial static findings were a `reversed` overload yielding an imprecise test type,
a long consumer output string and a missing notebook import. These were corrected
without suppressions. Sandbox uv-cache denials used the required escalation path.
The documentation skill's referenced `docs/coding_standards/documentation.md` is
absent; the actual engineering guide's Documentation section was followed.

### Installed wheel outside the checkout

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . --out-dir /private/tmp/mr12-validation/dist
mkdir -p /private/tmp/mr12-validation/inputs
cp configs/reference/binance-archive-spot.json tests/fixtures/mr12/eligibility.json tests/fixtures/mr12/select_eligibility.py /private/tmp/mr12-validation/inputs/
uv run --frozen --no-sync python /private/tmp/mr12-validation/install.py
cd /private/tmp/mr12-validation
./venv/bin/python -I inputs/select_eligibility.py inputs
```

The temporary installation script calls the existing
`alpha_research_governance.wheel_smoke._InstalledWheelCheck.validate` with the
checkout, external directory and built wheel. It installs frozen requirements
with hashes and binary-only dependencies, installs the wheel with `--no-deps`,
checks dependencies, imports and exact codecs, and confirms governance tooling is
absent from the runtime. All passed.

The [retained consumer](../../tests/integration/consumers/eligibility/select_eligibility.py) then ran with
`-I` from the external directory against copied inputs and external `site-packages`.
It verified prior and corrected decisions, both clocks, half-open endpoints,
unknown/unsupported, retained exclusions, exact round trip, rejected unlinked and
dangling corrections, and recovered on the valid append. The packaged README's
membership example also returned `['ETHUSDT']` during final review.

Wheel SHA-256: `b32e7f1509b52977fa74423c52589b71294f3e14fab9074350fd6cb9b002b125`.
Frozen lock SHA-256: `e6cd3a169ff4b6850bcb5b09e38c44e1179b0dc1fb7c6a9bd95d2c4a058595e4`.
Synthetic fixture SHA-256: `805010ed176f759785de3a0f441b56411edf6ba11d527a85269f28cbd467a27a`.
The wheel and external installation match all 64 packaged source files in the
committed candidate. These local artifacts are development evidence, not a durable
release archive.

### Fresh-kernel NB 12

```sh
ALPHA_OKX_ARCHIVE_DIRECTORY=data/okx/history/802967bb-05eb-4b7b-9c90-2c964f22e41f ALPHA_BITFINEX_CAPTURE_DIRECTORY=data/bitfinex/a5116c5a-b7d6-4e2b-9ee6-c79839c80f43 uv run --frozen --no-sync --with 'nbclient==0.10.4' --with 'ipykernel==7.3.0' --with 'nbformat==5.10.4' python examples/run_notebook.py examples/research-foundations.ipynb
```

All **44 cells / 19 code cells** passed in a fresh kernel, after comparing all
**63 installed runtime files** with commit `774cff9`; the runtime input diff was
empty. The existing 17 code cells are unchanged and used the same pinned saved
OKX/Bitfinex inputs. No new source observations or network acquisition were needed.
Actual tooling: nbclient 0.10.4, nbformat 5.10.4 and ipykernel 7.3.0. The runner closed
the kernel and removed its temporary kernel directory.

Successful attempt: `7f380ad8-81cd-4437-9b40-bb5e594805b8`, retained under ignored
`examples/runs/research-foundations/`. Notebook source SHA-256:
`08a76ead2fbabbbca0c6a7f6f007580efc7f140222e845137c4b110ddc056d9a`.
Runtime SHA-256: `2076d38563e55d06e17bee5539bbea56ffcc316a7cfc2660a24704746d6080e7`.

NB 12 displays 12 boundary rows, the earlier BTC+ETH universe versus ETH after the
noon correction, four required failures, and unknown versus unsupported. Its
initial attempt `7382a37f-9ac2-4104-8dd8-74cc06f39d9a` is also retained: the notebook
mistakenly appended an unlinked exclusion to an already-corrected history, where
it was valid agreeing evidence. The failure example was corrected to use the
pre-correction history, matching the existing passing regression and isolated
consumer; the full notebook was then rerun. No runtime fix or evidence overwrite
was needed.

Final review commands:

```sh
uv run --frozen --no-sync --with 'nbformat==5.10.4' python /private/tmp/mr12-validation/validate.py
python3 /private/tmp/mr12-validation/review.py
uv run --frozen --no-sync alpha-governance-architecture
git diff --check
git ls-files -- examples/
git check-ignore examples/runs/research-foundations/7f380ad8-81cd-4437-9b40-bb5e594805b8.ipynb examples/.kernel-probe/connection.json examples/.ipynb_checkpoints/checkpoint.ipynb
```

Temporary review scripts check notebook schema, syntax, completed sequential
execution, source identity, unchanged earlier code cells, selected local links,
wheel/source/external-install parity, the component example and unchanged P1 bytes.
All passed, including six selected Markdown/notebook inputs and the architecture
check's 45 documents. Ruff lint and formatting were renewed after notebook execution.
Maintained notebook, Python and Markdown examples remain tracked. Only existing
run snapshots, checkpoints and kernel artifacts are ignored; ignore policy is
unchanged. Small notebook outputs and metadata were reviewed for unintended data.
No new repository validation tool was introduced.

## Risks / reversal

This is bounded in-memory reference selection, without large-history performance
qualification. Evidence identities and clocks remain supplied attestations;
source authentication and actual historical P1 membership remain unresolved.
No quality acceptance, snapshot publication or M1/P1 completion is claimed.
Existing acquisition/storage/decoder evidence is reused because those behaviors
are unchanged. The full local suite and hosted CI were not run for this handoff;
the complete hosted lane remains required before merge. The existing QuantLib
release restriction remains unchanged.

The frozen [P1 specification](../research/p1-baseline.md) is byte-identical to base:
SHA-256 `7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d`.
Revert this MR before dependent consumers merge. Preserve version-2 histories;
older code rejects them, so select compatible code and version-1 inputs together
if reverting a consumer. No stored data deletion or service migration is needed.
