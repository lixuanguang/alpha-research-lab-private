# Draft upstream request: signed build provenance for QuantLib wheels

Status: prepared locally, **not sent**. Proposed destination:
[QuantLib-SWIG issues](https://github.com/lballabio/QuantLib-SWIG/issues), which
owns the 1.43 wheel workflow. The maintainer can redirect the historical 1.40
question to `quantlib-wheels`. Only the title and body below are intended for
external communication. They contain public package information only.

The later bootstrap policy revision makes this an optional request for stronger
build evidence; sending it is no longer the only path to development admission.

## Title

Availability of signed build provenance for Python wheels

## Body

Hello, thank you for maintaining QuantLib and its Python wheels.

Is builder-produced SLSA v1 provenance available for the published wheels, beyond
the PyPI publication attestations? I checked the PyPI provenance responses for
1.40 and 1.43 on 2026-09-04. All 42 wheel responses contained only
`https://docs.pypi.org/attestations/publish/v1`, with a null predicate. The public
GitHub attestation endpoints I checked for the following four wheel hashes
returned 404; I understand that this does not prove evidence is unavailable
elsewhere.

The initial use case is CPython 3.12 on macOS arm64 and Linux x86_64. Exact wheel
subjects are:

| Release | Wheel filename | SHA-256 |
| --- | --- | --- |
| 1.40 | `quantlib-1.40-cp38-abi3-macosx_11_0_arm64.whl` | `fefb04e34a4f6a529e8d3a0506de6cd443d52ba85fbc13b4c30b7865ce5fa4ce` |
| 1.40 | `quantlib-1.40-cp38-abi3-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl` | `aca8d51be11a264a149cb41935082ea0a023ebcb82f634dc6ed5908257bd5ab3` |
| 1.43 | `quantlib-1.43-cp39-abi3-macosx_11_0_arm64.whl` | `85d70b28778afca84b9b6ae74ef05a1069b2dca00e80fc74aa8ddf438259dc0c` |
| 1.43 | `quantlib-1.43-cp39-abi3-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl` | `35cd2c178aa9a30c3b7a9ca050536037c3185afd6728e6a1cf2085adef54464e` |

The needed evidence connects exact wheel bytes to their actual build inputs:

- QuantLib and QuantLib-SWIG source revisions and archive SHA-256s, including
  generated binding sources and the build recipe;
- Boost and relevant compiler, SDK, container and Python build-tool identities;
- builder identity, build type, parameters and resolved dependencies;
- the exact wheel subject digest, signed in an in-toto SLSA v1 statement with
  its verification bundle, signer/issuer and transparency evidence.

PyPI's publication identity is useful, but its statement does not itself attest
to these build inputs. A link to existing signed evidence would be sufficient
to start verification; there is no request to change previously published bytes.

If such evidence was not retained, would you consider emitting it during a
future governed build? Unknown historical inputs should not be retroactively
asserted. A newly built artifact with its own identity and honest provenance is
also a useful path. Please let me know if another venue is better for this
question.

## Internal acceptance notes

An upstream answer or newly available bundle does not automatically admit a
dependency. Platform/Security must reconcile the complete eventual lock set,
sources, native materials, signer and B07's exact supported SLSA profile, then
run cryptographic verification, admission and compatibility checks. These four
subjects are an initial query, not a declaration of the eventual lock contents.
Changing to 1.43 requires its own owning-package compatibility and admission work.
