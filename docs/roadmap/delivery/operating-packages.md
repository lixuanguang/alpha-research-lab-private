# MR06 delivery and acceptance

[Roadmap and delivery dependencies](../README.md#delivery-order-and-dependencies).

Status: **complete for independent operating packages and trusted local
installation**, 2026-09-24.
Owner: quant development. This is current infrastructure MR06, not a historical
milestone or QR research deliverable. The initial working tree was clean. All
changes remain uncommitted for founder review.

The delivery follows the existing MR04 trusted local POSIX development profile:
Darwin arm64, standard-GIL CPython 3.14.7, local retained registry and clean
operating virtual environments. It adds shared-contract, collector and execution
distributions with independent collector/execution locks. Exact financial values
are separate from the optional QuantLib convention adapter. The complete research
environment and independently locked Feast/ClearML workers remain supported.

The existing administrative artifact command now composes actual build,
Ed25519 signing, trusted-origin/builder verification, offline installation and
compatible rollback. Signed releases bind source bytes/base commit/dirty state,
build commands, root and selected locks, admission policy, fresh complete audit,
wheel inventory, configuration and state. Installation rejects unsafe archives,
unknown/missing records, signature/source/dependency mismatches, expiry and
incompatible targets/schemas. Quiescence, immutable installation slots, an atomic
active pointer and preserved current state define local recovery.

The execution package consumes typed spot limit intents, scoped credential
references, the capability registry and existing exact reference/risk checks.
Research, paper and shadow modes suppress submission; production-mode requests
and credential/environment mismatches fail before any submission. This is an
executable reference application for the package boundary, not the later durable
OMS or venue-adapter acceptance. The collector retains existing public capture
and saved replay interfaces for the declared OKX/Bitfinex spot scope.

Dependency ownership remains bounded. MR16 owns the package/import-contract slice;
its broader ownership migration remains open. MR07 owns the intent-admission
reference application's execution slice; supervised events and durable OMS were
open at MR06 acceptance and are now addressed under MR07. MR13 owns
credential/mode separation and compatible-state refusal pulled
forward here; bounded activation, venue reconciliation and operational recovery
remain open. MR11 still owns both venues' private account/execution conformance.
MR04 owns workspace/data/feature/job restore; installation does not redefine those
schemas or rewind external order/fill state.

The [release workflow](../../governance/workflow.md#build-a-release),
[dependency guide](../../architecture/dependency-admission.md#first-deployment-dependency-decision)
and [operating runbook](../../governance/operations.md#trusted-local-installation)
own interfaces, commands and limitations. Acceptance artifacts and logs are
retained under ignored `logs/mr06/`. Actual release builds used the pinned tools
and fresh pip-audit reports covering all 179 admitted external dependencies;
each reported no known vulnerabilities. The retained signed registry contains:

| Artifact | Signed release SHA-256 | Installed closure |
| --- | --- | --- |
| Execution, initial shadow configuration | `c6d92722f352928aeecdf9e48e6f9b657d9702c37f9cbdc06a01b6ba19a62527` | 8 distributions, including shared contracts |
| Execution, changed quantity limit | `1fae2b481550d3ef5912f0ad0920b4a645a2ea6b5d49a65105f54771ae92e67d` | Same pinned code/closure, separately signed configuration |
| Collector | `3563efb023e0bd0c86e31ebc199ef2d7ea469efd2db9d4b586ac3a6c10dc5266` | 14 distributions, including shared contracts |

The [maintained installation consumer](../../../tests/integration/consumers/deployment/trusted_installation.py)
runs with the installed governance interpreter outside the checkout. It installs
the two real execution releases, checks actual isolated distribution metadata,
suppresses admitted intents, rejects production requests, and restores the prior
configuration while preserving current mutable state. The upgrade changes the
maximum quantity from 0.001 to 0.002; it is a configuration upgrade with unchanged
code, not a claim of a new application version or schema migration.

The installed collector's `replay` command reopens the retained MR02 native
100-message OKX BTC-USDT and Bitfinex tBTCUSD captures. Both finish synchronized
with no gaps in the saved prefix; terminal quality remains unavailable because
the finite recordings ended. `collector-okx-replay.json` and
`collector-bitfinex-replay.json` retain their book/trace identities. This reuses
the original public observations and renews installed decoder/package evidence;
it does not assert fresh acquisition, historical completeness or private venue
execution conformance. `collector-installed.json` records exact distribution and
runtime identities. Neither operating environment exposes unrelated research,
notebook, training or reporting modules, including QuantLib.

`trusted-installation-reviewed.json` records the completed configuration-change
consumer against the installed final governance artifact. It includes signed
configuration/request hashes, rejected → suppressed → rejected admission for the
larger intent, production-request refusal, and the unchanged mutable-state digest.
`actual-provenance-refusals.json` records real correctly signed invalid bundles:
source/wheel mismatch, selected-lock drift, omitted audit coverage and wrong
configuration mode. Each passes authentication and fails the installed semantic
verifier. Focused engineering tests additionally exercise entrypoint/RECORD and
dependency mismatch, unsafe files, stale/revoked trust, target/schema refusal,
fencing, staged failure, interrupted initial installation and local byte drift.

The full local gate passes, including strict typing/native stubs, ownership and
documentation checks, dependency/advisory admission, security/secret scans,
installed tests and the complete research-wheel smoke test. The independently
locked Feast 0.66.0/pandas 2.3.3 worker is also selected for the final gate; its
candidate/serving cases exercise compatibility with the pandas 3.0.5 core without
resolving either environment into the other. The final command and log are:

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/ar06-env TMPDIR=/private/tmp \
  ALPHA_FEAST_WORKER_PYTHON=/private/tmp/ar06-feast/bin/python \
  PYTEST_ADDOPTS='--basetemp=/private/tmp/ar06-check' \
  make check > logs/mr06/make-check-final.log 2>&1
```

`operating-source-parity.log` confirms every local file in the retained operating
wheels matches final source. Full-research import corrections are renewed by the
full wheel gate. The task's test signing identity is local acceptance evidence;
its retained public policy expires and is not production key provisioning.

The research graph's QuantLib source-to-wheel binding remains unverified and its
release block/2026-10-04 allowance deadline remain in force. Only genuinely
independent operating closures can be admitted. Linux, remote deployment,
production key provisioning, live orders, capital activation, empirical strategy
acceptance and QR onboarding are not qualified by this local delivery.

Reversal is patch review/revert plus selection of a previously verified compatible
release. Retain the current mutable state, all registry bytes and independent
worker environments. Never edit a signed manifest, dependency digest or checkpoint
to make an incompatible artifact appear acceptable.
