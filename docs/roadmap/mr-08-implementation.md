# MR 08 — Read saved raw frames with explicit gaps

Owner: repository founder. Status: implemented and locally verified on 2026-09-16;
review candidate on `codex/mr-08-saved-archive-rows`. M1 and P1 remain incomplete.
The [roadmap row](README.md#raw-inputs-and-acquisition) owns scope and acceptance.

## Problem / change

Saved Binance daily archives could be acquired and verified but their reusable
row reader was missing. `BinanceArchiveRows.from_manifest` now selects the expected
partitions, reuses `AcquisitionManifest` validation and streams their verified
ZIP/UTF-8 CSV records. Frozen rows retain exact source bytes, zero-based position,
raw-object provenance and half-open research selection bounds. Equal timestamps
do not reorder rows. `columns()` parses text without interpreting event values.

Missing completion/object, empty CSV and unknown recorder completeness are
separate outcomes. Malformed UTF-8/CSV, truncated or corrupt ZIP, wrong member,
byte-limit violations, foreign bindings and mutated storage fail visibly. Pending
receipts never become completed inputs. The reader creates no decoder, disconnect,
capture clock, knowledge clock, padded price or canonical dataset.

## Affected scope

Started from fetched, clean `main` at
`a5d86a91e94b70b0e78deff44031834ceef0a294` (equal to `origin/main`). Before branching,
`git merge-base --is-ancestor <commit> main` passed for MR 01/M0 `80b5bc64`,
MR 03 `bf3fb991`, and reused MR 06 manifest validation `0e35496d`. No missing
prerequisite or later-MR implementation was introduced.

- [Reader and raw records](../../src/alpha_research/data/providers/binance/rows.py):
  validated immutable declarations together with their streaming consumer.
- [Focused regressions](../../tests/unit/data/providers/binance/test_rows.py) and
  [installed consumer fixture](../../tests/fixtures/mr08/read_saved.py).
- [Component API documentation](../../src/alpha_research/data/README.md#saved-binance-archive-rows),
  [maintained notebook](../../examples/research-foundations.ipynb), examples guide
  and roadmap status.

The notebook consumes the installed reader in section 5 and shows NB 08 boundary
outputs in section 7. Existing exploratory timestamp/financial previews remain
notebook-local. The persisted dataset pipeline and individual-trade event decoding
belong to MR 09. Existing configuration, manifests, storage, serialized event
fixtures, Tardis decoder/gap semantics and P1 specification are unchanged.

Review size against the actual MR base above: **110 added + 0 deleted = 110
production code-bearing physical lines**. Imports, annotations, validators and
method bodies count; blank lines, comments/docstrings, tests/fixtures and notebook
teaching examples do not. No executable tooling changes. Declarative configuration
changes: **0**. Dependency/lock changes: **0**. No cohesive overage.

## Validation result

CPython 3.14.7 on macOS arm64. Commands below ran from the checkout unless a
working directory is specified. The tested runtime is identified independently
of notebook output timestamps:

| Identity | SHA-256 |
| --- | --- |
| New `rows.py` | `163d60379667b6f02ae80ab6711d48046c445923f58daff463a26203f6d23b79` |
| All 59 runtime Python/JSON/type-marker files, notebook's path/content digest | `a85cf8273c3d5cb6ea016f5616c8603041ea6f0a3b94816b0b12500ef23a28c6` |
| Built runtime wheel | `2a19ccc45c51a3a27e1a8853cb71a4e261f6e0fcf4d626d4d61892408c06876a` |
| `uv.lock` | `e6cd3a169ff4b6850bcb5b09e38c44e1179b0dc1fb7c6a9bd95d2c4a058595e4` |
| Preserved `docs/research/p1-baseline.md` | `7feb8039724001889060dfeb79138fb4bc78764dcca6683297bc64fb2bd0192d` |

### Focused checks

```sh
uv run --frozen --no-editable pytest -q \
  tests/unit/data/providers/binance/test_rows.py \
  tests/unit/data/test_manifests.py \
  tests/unit/data/providers/tardis/test_tardis_decoder.py \
  tests/unit/data/providers/tardis/test_tardis_binance.py \
  tests/unit/pipelines/test_binance_archive.py

uv run --frozen --no-sync ruff check \
  src/alpha_research/data/providers/binance/rows.py \
  tests/unit/data/providers/binance/test_rows.py \
  tests/fixtures/mr08/read_saved.py examples/research-foundations.ipynb
uv run --frozen --no-sync ruff format --check \
  src/alpha_research/data/providers/binance/rows.py \
  tests/unit/data/providers/binance/test_rows.py \
  tests/fixtures/mr08/read_saved.py examples/research-foundations.ipynb
uv run --frozen --no-sync mypy --strict \
  src/alpha_research/data/providers/binance/rows.py \
  tests/unit/data/providers/binance/test_rows.py tests/fixtures/mr08/read_saved.py
uv run --frozen --no-sync alpha-governance-engineering-standards
uv run --frozen --no-sync bandit -q -c pyproject.toml \
  src/alpha_research/data/providers/binance/rows.py
uv run --frozen --no-sync alpha-governance-architecture
```

Focused tests: **62 passed**, no skips or deselections. Changed-path Ruff/format,
strict mypy (three files), engineering standards, Bandit and local documentation
links passed. Component and examples README links were also checked explicitly
because the architecture command discovers only `docs/**/*.md`.

Initial local checks exposed a generator annotation that did not advertise
`.close()`, an overlong fixture output string and a missing fixture `Raises:`
section. These were corrected before final validation. No runtime acceptance
failure was hidden or test weakened. Existing unaffected storage interruption
and acquisition retry evidence is reused; this MR does not change those paths.
No full local suite or hosted CI result is claimed. Hosted merged-result checks
remain required before merge.

### Installed wheel outside the checkout

```sh
uv run --frozen --no-editable uv build --no-build-isolation --wheel --no-sources . \
  --out-dir /private/tmp/mr08-validation/dist
mkdir -p /private/tmp/mr08-validation/inputs
cp configs/data-jobs/binance-archive.json \
  configs/reference/binance-archive-spot.json tests/fixtures/mr08/read_saved.py \
  /private/tmp/mr08-validation/inputs/
uv run --frozen --no-sync python /private/tmp/mr08-validation/install.py
cd /private/tmp/mr08-validation
./venv/bin/python -I inputs/read_saved.py inputs
```

The temporary `install.py` reused the repository's existing smoke implementation:

```python
from pathlib import Path
from alpha_research_governance.wheel_smoke import _InstalledWheelCheck

root = Path('/Users/lxg/Documents/GitHub/Alpha Research/alpha-research-lab-private')
validation = Path('/private/tmp/mr08-validation')
_InstalledWheelCheck.validate(
    root, validation, validation / 'dist/alpha_research_lab-0.1.0-py3-none-any.whl'
)
```

This creates an isolated runtime environment, exports frozen runtime requirements,
installs them with `--require-hashes --only-binary=:all:`, installs the candidate
wheel with `--no-deps`, runs dependency compatibility and the retained installed
import/codec smoke. All passed. The copied consumer then passed exact equal-time
bytes/order, origins/bounds, raw-row codec, empty CSV, invalid UTF-8/CSV and both
absence cases. Imports resolved under the external environment's `site-packages`,
with `-I` and no checkout path injection. No governance package is installed there.
The final wheel was rebuilt after its packaged component README changed, installed
with `uv pip install --python /private/tmp/mr08-validation/venv/bin/python --no-deps
--reinstall /private/tmp/mr08-validation/dist/alpha_research_lab-0.1.0-py3-none-any.whl`,
and the outside-checkout consumer passed again. Runtime Python/JSON/type-marker
bytes were unchanged. The wheel/environment are local development evidence,
not a release artifact.

### Fresh-kernel NB 08

```sh
uv run --frozen --no-editable --with 'nbclient==0.10.4' \
  --with 'ipykernel==7.2.0' --with 'nbformat==5.10.4' \
  python examples/run_notebook.py examples/research-foundations.ipynb
```

All **22 cells / 11 code cells** passed from a fresh kernel. The notebook verified
all 59 installed runtime files against source before using them; no `sys.path`
patch was used. Observed tooling metadata was nbclient 0.10.4, nbformat 5.10.4 and
ipykernel 7.3.0 (the kernel's observed version, despite the requested overlay).
Successful attempt `ee11fc43-8a05-4515-bcf9-32519f84675e` is preserved under ignored
`examples/runs/research-foundations/`; notebook source digest:
`2f07cfdda2c24025e50c6f766d8a5c1c727eb5ffc0c28954dee10b97ea5be9c9`.

The initial cache-only attempt `294def8b-57d3-4906-a8d3-0f8b8023b60a` failed
explicitly at missing completion: adding the reader changes the runtime-bound
run identity. It is retained. The next run used the notebook's existing permitted
public acquisition path; no old manifest was rewritten. The actual ZIP digest
still matches the earlier source sample, while this candidate has its own run:

- Run: `6b564380af76ea0ad0d268f983020cf4d602617d77fe103f3d1886cf5f2ba0cd`.
- ZIP: `c9c333f58fe33faaa0a34d526c61b13f5648b908c4ad341dd6556e15c5bcc46a`,
  **7,308,819 bytes**; **638,484 rows**, **27,480** in the unchanged selected hour.
- NB 08: equal-time trade IDs `12, 11` retain positions `0, 1` and exact CRLF/LF;
  empty CSV yields zero rows; invalid UTF-8/CSV, truncated ZIP, absent daily
  completion and missing stored ZIP show distinct controlled outcomes. All report
  unknown recorder coverage. Existing financial previews and copy/checksum
  rejections also pass.

Raw bytes are locally retrievable at `data/binance-archives/raw/<ZIP digest>`;
configuration, catalog, acquisition attempts and manifest remain together under
`data/binance-archives/runs/<run identity>/`. This is ignored local working storage,
not a backed-up archive. The maintained notebook contains only small reviewed
previews and synthetic outputs. Its aggregate runtime hash identifies the added
module; the first run's Git diff hash alone did not include then-untracked source.
The runner closed its execution kernel and removed temporary kernel files.
Maintained `.ipynb`, `.py` and `.md` examples remain tracked; generated runs,
checkpoints, kernel files and downloaded data remain ignored under unchanged policy.

## Risks / reversal

The bounded reader supports the existing single-day Binance individual-trade
selection and seven-column single-line CSV, with explicit compressed/expanded and
row caps. A complete final record need not end in a newline. Header, numeric/time,
instrument and event semantics remain for MR 09 and later quality checks. A
consumer must exhaust an iterator for full CRC/CSV validation and close it after
an abandoned prefix; a prefix cannot establish dataset acceptance.

Archive presence and row counts establish neither recorder coverage nor historical
eligibility, revision availability or point-in-time knowledge. Empty content is
not accepted quiet-market evidence. No M1/P1 completion, empirical strategy result,
deployment or release qualification is claimed; the existing QuantLib release
restriction remains in force.

Revert this branch before dependent consumers merge. It changes no stored schema,
configuration, dependency or existing decoder and migrates no data. Retain raw
objects, manifests and execution attempts. After MR 09 consumes the API, revert
or select compatible dependent code together.

**Next: MR 09 — Bind decoded events to raw occurrences**, after MR 08 merges.
MR 09 has not been started.
