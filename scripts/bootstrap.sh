#!/usr/bin/env bash
# bootstrap.sh — One-command dev environment setup
# Usage: bash scripts/bootstrap.sh
set -euo pipefail

CONDA_ENV="py311"
PYTHON_VERSION="3.11"

echo "=== Alpha Research Lab — Bootstrap ==="

# ── Ensure conda is available ────────────────────────────────────────────────
if ! command -v conda &>/dev/null; then
    echo "ERROR: conda not found. Install Miniforge/Miniconda first."
    exit 1
fi

# ── Create or reuse conda env ────────────────────────────────────────────────
if conda info --envs | grep -qw "$CONDA_ENV"; then
    echo "Conda env '$CONDA_ENV' already exists — activating."
else
    echo "Creating conda env '$CONDA_ENV' (Python $PYTHON_VERSION)..."
    conda create -y -n "$CONDA_ENV" python="$PYTHON_VERSION"
fi

# Activate (works inside scripts via conda run)
eval "$(conda shell.bash hook)"
conda activate "$CONDA_ENV"

# ── Install project in editable mode with dev extras ─────────────────────────
echo "Installing alpha-research-lab[dev] in editable mode..."
pip install -e ".[dev]"

# ── Install pre-commit hooks ─────────────────────────────────────────────────
echo "Installing pre-commit hooks..."
pre-commit install

# ── Validate ─────────────────────────────────────────────────────────────────
echo "Running environment validation..."
python scripts/validate_env.py

echo ""
echo "=== Bootstrap complete. Run: conda activate $CONDA_ENV ==="
