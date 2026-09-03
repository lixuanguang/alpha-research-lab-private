#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'usage: %s [verify|check|rollback]\n' "$0" >&2
}

mode="${1:-check}"
if [[ $# -gt 1 ]]; then
  usage
  exit 64
fi
case "$mode" in
  verify | check | rollback) ;;
  *)
    usage
    exit 64
    ;;
esac

if [[ "${CLEAN_MACHINE_DEV_SHELL:-}" != "1" ]]; then
  printf 'clean-machine bootstrap must run inside: nix develop --no-write-lock-file\n' >&2
  exit 1
fi

repository_root="$(git rev-parse --show-toplevel)"
cd "$repository_root"

case "$(uname -s):$(uname -m)" in
  Darwin:arm64)
    expected_uv_version="uv 0.12.7 (61291a8ca 2026-08-27 aarch64-apple-darwin)"
    ;;
  Linux:x86_64)
    expected_uv_version="uv 0.12.7 (61291a8ca 2026-08-27 x86_64-unknown-linux-musl)"
    ;;
  *)
    printf 'unsupported clean-machine host platform: %s:%s\n' "$(uname -s)" "$(uname -m)" >&2
    exit 1
    ;;
esac

for tool in nix uv python3.12 bazel bazelisk cosign git make syft; do
  tool_path="$(command -v "$tool" || true)"
  if [[ "$tool_path" != /nix/store/* ]]; then
    printf '%s must resolve from the locked Nix store, got: %s\n' "$tool" "$tool_path" >&2
    exit 1
  fi
done

[[ "$(nix --version)" == "nix (Nix) 2.34.8" ]]
[[ "$(uv --version)" == "$expected_uv_version" ]]
[[ "$(python3.12 --version)" == "Python 3.12.14" ]]
[[ "$(bazel --version)" == "bazel 9.1.0" ]]
cosign version 2>&1 | grep -F "GitVersion:    v3.1.3" >/dev/null
[[ "$(git --version)" == "git version 2.55.0" ]]
[[ "$(make --version | head -n 1)" == "GNU Make 4.4.1" ]]
syft version 2>&1 | grep -F "Version:       1.51.1" >/dev/null
[[ "$UV_PYTHON" == /nix/store/*-python3-3.12.14/bin/python3.12 ]]
[[ "$UV_PYTHON_DOWNLOADS" == "never" ]]

if [[ "$mode" == "verify" ]]; then
  exit 0
fi

uv lock --check
uv sync --frozen

if [[ "$mode" == "rollback" ]]; then
  make BUILD_BACKEND=uv check
else
  bazel test --config=ci //:developer_environment_tests
  make check
fi
