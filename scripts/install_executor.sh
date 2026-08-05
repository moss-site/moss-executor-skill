#!/usr/bin/env bash
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_SRC="$SKILL_ROOT/executor-backend"
RUNTIME_ROOT="${MOSS_EXECUTOR_HOME:-$HOME/.moss-hyper-agent}"
INSTALL_ROOT="${MOSS_EXECUTOR_INSTALL_ROOT:-$RUNTIME_ROOT/executor-backend}"
INSTALL_DIR="$INSTALL_ROOT/current"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ ! -d "$BACKEND_SRC/executor_backend" || ! -f "$BACKEND_SRC/pyproject.toml" ]]; then
  echo "executor-backend source not found under $BACKEND_SRC" >&2
  exit 1
fi

mkdir -p "$INSTALL_ROOT" "$RUNTIME_ROOT/templates"
mkdir -p "$INSTALL_DIR"

# Copy the packaged backend into the user runtime so skill upgrades do not erase config/state.
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude='.venv' --exclude='.executor-runtime' --exclude='__pycache__' --exclude='*.pyc' --exclude='*.egg-info' \
    "$BACKEND_SRC/" "$INSTALL_DIR/"
else
  find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 ! -name '.venv' ! -name '.executor-runtime' -exec rm -rf {} +
  cp -R "$BACKEND_SRC/." "$INSTALL_DIR/"
  find "$INSTALL_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +
  find "$INSTALL_DIR" -name '*.pyc' -delete
  find "$INSTALL_DIR" -name '*.egg-info' -type d -prune -exec rm -rf {} +
fi

if [[ -f "$SKILL_ROOT/templates/env.testnet.example" ]]; then
  cp "$SKILL_ROOT/templates/env.testnet.example" "$RUNTIME_ROOT/templates/env.testnet.example"
fi
if [[ -f "$SKILL_ROOT/templates/env.mainnet.example" ]]; then
  cp "$SKILL_ROOT/templates/env.mainnet.example" "$RUNTIME_ROOT/templates/env.mainnet.example"
fi

if [[ ! -x "$INSTALL_DIR/.venv/bin/pip" ]]; then
  rm -rf "$INSTALL_DIR/.venv"
  "$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
fi
if [[ "${MOSS_EXECUTOR_SKIP_PIP_INSTALL:-}" == "1" ]]; then
  echo "Skipping pip install because MOSS_EXECUTOR_SKIP_PIP_INSTALL=1."
else
  if ! "$INSTALL_DIR/.venv/bin/python" -c 'import setuptools, wheel' >/dev/null 2>&1; then
    "$INSTALL_DIR/.venv/bin/pip" install -q setuptools wheel
  fi
  if ! "$INSTALL_DIR/.venv/bin/pip" install --no-build-isolation -q -e "$INSTALL_DIR"; then
    cat >&2 <<ERR
Failed to install executor-backend Python dependencies.
Check network access or preinstall dependencies from $INSTALL_DIR/pyproject.toml, then rerun this script.
For packaging smoke tests only, set MOSS_EXECUTOR_SKIP_PIP_INSTALL=1.
ERR
    exit 1
  fi
fi

cat <<OUT
Hyperliquid Agent Executor backend installed.
Runtime root:  $RUNTIME_ROOT
Backend dir:   $INSTALL_DIR
Python:        $INSTALL_DIR/.venv/bin/python
Testnet template: $RUNTIME_ROOT/templates/env.testnet.example
Mainnet template: $RUNTIME_ROOT/templates/env.mainnet.example

Next agent actions:
  1. Create $RUNTIME_ROOT/agents/<agent-id>/config.env from the matching network template.
  2. Fill Agent/RPC/executor settings without printing secrets.
  3. Run: $SKILL_ROOT/scripts/executorctl.sh --config $RUNTIME_ROOT/agents/<agent-id>/config.env agent-init
OUT
