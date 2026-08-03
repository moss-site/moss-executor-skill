#!/usr/bin/env bash
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="${MOSS_EXECUTOR_HOME:-$HOME/.moss-hyper-agent}"
INSTALL_DIR="${MOSS_EXECUTOR_BACKEND_DIR:-${MOSS_EXECUTOR_INSTALL_ROOT:-$RUNTIME_ROOT/executor-backend}/current}"
PYTHON="$INSTALL_DIR/.venv/bin/python"
CONFIG_FILE=""
AGENT=""

usage() {
  cat <<'USAGE'
Usage: executorctl.sh [--config PATH | --agent ADDRESS] <executor-cli-args...>

Examples:
  executorctl.sh --config ~/.moss-hyper-agent/agents/bd0164/config.env agent-chain-state --json
  executorctl.sh --agent 0xBd0164eDaC67B701B3960551F86F336f5435C4e2 nav-cycle --day 20260720
  executorctl.sh service status
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG_FILE="$2"
      shift 2
      ;;
    --agent)
      AGENT="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

if [[ ! -x "$PYTHON" ]]; then
  echo "Executor backend is not installed at $INSTALL_DIR." >&2
  echo "Run: $SKILL_ROOT/scripts/install_executor.sh" >&2
  exit 1
fi

short_agent_id() {
  local a="${1#0x}"
  a="$(printf '%s' "$a" | tr '[:upper:]' '[:lower:]')"
  printf '%s' "${a:0:6}"
}

normalize_address() {
  local a="${1#0x}"
  a="$(printf '%s' "$a" | tr '[:upper:]' '[:lower:]')"
  printf '0x%s' "$a"
}

if [[ -z "$CONFIG_FILE" && -n "$AGENT" ]]; then
  CONFIG_FILE="$RUNTIME_ROOT/agents/$(short_agent_id "$AGENT")/config.env"
fi

if [[ -z "$CONFIG_FILE" && -n "${AGENT_ADDRESS:-}" ]]; then
  CONFIG_FILE="$RUNTIME_ROOT/agents/$(short_agent_id "$AGENT_ADDRESS")/config.env"
fi

if [[ -n "$CONFIG_FILE" ]]; then
  CONFIG_FILE="${CONFIG_FILE/#\~/$HOME}"
  if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Config file not found: $CONFIG_FILE" >&2
    echo "Create it from the matching network template:" >&2
    echo "  $RUNTIME_ROOT/templates/env.testnet.example" >&2
    echo "  $RUNTIME_ROOT/templates/env.mainnet.example" >&2
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
  set +a
  # Runtime state belongs under the wrapper-selected root, not under the backend install dir.
  export MOSS_EXECUTOR_HOME="$RUNTIME_ROOT"
  if [[ -n "$AGENT" && -n "${AGENT_ADDRESS:-}" ]]; then
    if [[ "$(normalize_address "$AGENT")" != "$(normalize_address "$AGENT_ADDRESS")" ]]; then
      echo "--agent $AGENT does not match AGENT_ADDRESS=$AGENT_ADDRESS in $CONFIG_FILE" >&2
      exit 1
    fi
  fi
fi

cd "$INSTALL_DIR"
exec "$PYTHON" -m executor_backend.cli "$@"
