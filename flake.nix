{
  description = "Clean-machine development environment";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { nixpkgs, ... }:
    let
      supportedSystems = [
        "aarch64-darwin"
        "x86_64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
      toolVersions = {
        bazel = "9.1.0";
        bazelisk = "1.29.0";
        git = "2.55.0";
        gnumake = "4.4.1";
        nix = "2.34.8";
        python = "3.12.14";
        uv = "0.12.7";
      };
      uvArtifacts = {
        aarch64-darwin = {
          archive = "uv-aarch64-apple-darwin.tar.gz";
          expectedVersionOutput = "uv 0.12.7 (61291a8ca 2026-08-27 aarch64-apple-darwin)";
          hash = "sha256-En692nrZU83xmOlktXDqV3G4VGfqk+t8ttb45vVUCPM=";
        };
        x86_64-linux = {
          archive = "uv-x86_64-unknown-linux-musl.tar.gz";
          expectedVersionOutput = "uv 0.12.7 (61291a8ca 2026-08-27 x86_64-unknown-linux-musl)";
          hash = "sha256-PWTUTtZ9p5CNx/XE1k67RLrTJvoX+KClL8mneTAXu+E=";
        };
      };
      bazelArtifacts = {
        aarch64-darwin = {
          binary = "bazel-9.1.0-darwin-arm64";
          hash = "sha256-CEoXhPqPDcrnf7Toj6oVBI2BSaNslHzhmFCL/7Bg4bs=";
        };
        x86_64-linux = {
          binary = "bazel-9.1.0-linux-x86_64";
          hash = "sha256-pmdFTz9PiHjfgZkTa4LBmfatqEd7M3+uOx74VPAeTi8=";
        };
      };
      toolchainFor =
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          uvArtifact = uvArtifacts.${system};
          bazelArtifact = bazelArtifacts.${system};
          exactUv = pkgs.stdenvNoCC.mkDerivation {
            pname = "uv";
            version = toolVersions.uv;
            src = pkgs.fetchurl {
              url = "https://github.com/astral-sh/uv/releases/download/${toolVersions.uv}/${uvArtifact.archive}";
              inherit (uvArtifact) hash;
            };
            sourceRoot = builtins.replaceStrings [ ".tar.gz" ] [ "" ] uvArtifact.archive;
            installPhase = ''
              runHook preInstall
              mkdir -p "$out/bin"
              install -m 0555 uv uvx "$out/bin/"
              runHook postInstall
            '';
          };
          exactBazel = pkgs.stdenvNoCC.mkDerivation {
            pname = "bazel";
            version = toolVersions.bazel;
            src = pkgs.fetchurl {
              url = "https://github.com/bazelbuild/bazel/releases/download/${toolVersions.bazel}/${bazelArtifact.binary}";
              inherit (bazelArtifact) hash;
            };
            dontUnpack = true;
            installPhase = ''
              runHook preInstall
              mkdir -p "$out/bin"
              install -m 0555 "$src" "$out/bin/bazel"
              runHook postInstall
            '';
          };
          bazelLauncher = pkgs.writeShellScriptBin "bazel" ''
            export USE_BAZEL_VERSION=${toolVersions.bazel}
            exec ${exactBazel}/bin/bazel "$@"
          '';
          versionAssertions =
            assert pkgs.bazelisk.version == toolVersions.bazelisk;
            assert pkgs.git.version == toolVersions.git;
            assert pkgs.gnumake.version == toolVersions.gnumake;
            assert pkgs.nix.version == toolVersions.nix;
            assert pkgs.python312.version == toolVersions.python;
            true;
        in
        assert versionAssertions;
        {
          inherit bazelLauncher exactBazel exactUv pkgs;
          packages = [
            bazelLauncher
            exactUv
            pkgs.bashInteractive
            pkgs.bazelisk
            pkgs.cacert
            pkgs.git
            pkgs.gnumake
            pkgs.nix
            pkgs.python312
          ];
        };
    in
    {
      devShells = forAllSystems (
        system:
        let
          toolchain = toolchainFor system;
        in
        {
          default = toolchain.pkgs.mkShellNoCC {
            packages = toolchain.packages;
            CLEAN_MACHINE_DEV_SHELL = "1";
            BAZELISK_SKIP_WRAPPER = "true";
            LANG = "C.UTF-8";
            LC_ALL = "C.UTF-8";
            PYTHONNOUSERSITE = "1";
            SOURCE_DATE_EPOCH = "1";
            TZ = "UTC";
            UV_PYTHON = "${toolchain.pkgs.python312}/bin/python3.12";
            UV_PYTHON_DOWNLOADS = "never";
          };
        }
      );

      checks = forAllSystems (
        system:
        let
          toolchain = toolchainFor system;
        in
        {
          toolchain-contract = toolchain.pkgs.runCommand "developer-environment-toolchain-contract" {
            nativeBuildInputs = toolchain.packages;
          } ''
            test "$(nix --version)" = "nix (Nix) ${toolVersions.nix}"
            test "$(uv --version)" = "${uvArtifacts.${system}.expectedVersionOutput}"
            test "$(python3.12 --version)" = "Python ${toolVersions.python}"
            test "$(bazel --version)" = "bazel ${toolVersions.bazel}"
            test "$(git --version)" = "git version ${toolVersions.git}"
            test "$(make --version | head -n 1)" = "GNU Make ${toolVersions.gnumake}"
            grep -F "USE_BAZEL_VERSION=${toolVersions.bazel}" "${toolchain.bazelLauncher}/bin/bazel"
            grep -F "${toolchain.exactBazel}/bin/bazel" "${toolchain.bazelLauncher}/bin/bazel"
            test "${toolchain.pkgs.bazelisk.version}" = "${toolVersions.bazelisk}"
            touch "$out"
          '';
        }
      );
    };
}
