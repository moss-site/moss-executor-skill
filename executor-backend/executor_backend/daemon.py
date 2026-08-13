from __future__ import annotations

from datetime import UTC, datetime
import os
import signal
import subprocess
import sys
import time
from typing import Any

from executor_backend.chain.client import AgentContractClient
from executor_backend.chain.rpc import JsonRpcClient
from executor_backend.config import AppConfig
from executor_backend.hyper.client import HyperCoreClient
from executor_backend.runtime import (
    RuntimePaths,
    append_jsonl,
    dataclass_dict,
    read_json,
    update_config_values,
    utc_now_iso,
    write_config_template,
    write_json,
)


def init_agent_runtime(cfg: AppConfig) -> RuntimePaths:
    paths = RuntimePaths.from_agent(cfg.agent.agent_address)
    paths.ensure()
    write_config_template(paths, dict(os.environ))
    resolved_config: dict[str, Any] = {}
    resolve_error = None
    try:
        resolved_config = AgentContractClient(
            cfg.agent.agent_address,
            rpc=JsonRpcClient(cfg.network.evm_rpc_url),
            dry_run=True,
            core_deposit_wallet=cfg.agent.core_deposit_wallet,
            spot_destination_dex=cfg.agent.spot_destination_dex,
            usdc_token_index=cfg.agent.usdc_token_index,
            core_usdc_wei_per_asset_unit=cfg.agent.core_usdc_wei_per_asset_unit,
        ).resolve_runtime_config()
        update_config_values(
            paths.config_env,
            {
                "ACCEPT_TOKEN": resolved_config["accept_token"],
                "CORE_DEPOSIT_WALLET": resolved_config["core_deposit_wallet"],
                "USDC_TOKEN_INDEX": resolved_config["usdc_token_index"],
                "USDC_SPOT_DESTINATION_DEX": resolved_config["spot_destination_dex"],
                "CORE_USDC_WEI_PER_ASSET_UNIT": resolved_config["core_usdc_wei_per_asset_unit"],
            },
        )
    except Exception as exc:
        resolve_error = str(exc)
    write_json(
        paths.service_state,
        {
            "agent_address": cfg.agent.agent_address,
            "network": cfg.network.name,
            "status": "error" if resolve_error is not None else "initialized",
            "resolved_config": resolved_config,
            "resolve_error": resolve_error,
            "updated_at": utc_now_iso(),
        },
    )
    append_jsonl(
        paths.operations,
        {
            "type": "agent_init",
            "agent_address": cfg.agent.agent_address,
            "network": cfg.network.name,
            "resolved_config": resolved_config,
            "resolve_error": resolve_error,
            "created_at": utc_now_iso(),
        },
    )
    if resolve_error is not None:
        raise RuntimeError(f"agent-init failed to resolve on-chain Agent config: {resolve_error}")
    return paths


def run_once(cfg: AppConfig) -> dict[str, Any]:
    paths = RuntimePaths.from_agent(cfg.agent.agent_address)
    paths.ensure()
    previous = read_json(paths.last_seen)
    hyper = HyperCoreClient(cfg.network.hypercore_api_url, cfg.nav_perp_dexes)
    state = hyper.fetch_state(cfg.agent.agent_address)
    chain_state = None
    chain_error = None
    try:
        chain_state = AgentContractClient(
            cfg.agent.agent_address,
            rpc=JsonRpcClient(cfg.network.evm_rpc_url),
            dry_run=True,
        ).read_chain_state()
    except Exception as exc:  # keep watcher alive when RPC reads are temporarily unavailable
        chain_error = str(exc)
    suggested_actions = []
    auto_nav_result = None
    if cfg.auto_nav and chain_state is not None:
        auto_nav_result = run_auto_nav_if_due(
            cfg,
            chain_state,
            previous_result=previous.get("auto_nav_result"),
        )
    elif not cfg.auto_nav:
        suggested_actions.append(
            {
                "type": "enable_auto_nav",
                "message": (
                    "After reviewing a successful daily nav-cycle, set ENABLE_AUTO_NAV=true "
                    "and restart the service to submit one guarded NAV settlement per UTC day."
                ),
            }
        )
    if cfg.auto_reconcile and chain_state is not None:
        suggested_actions.append(
            {
                "type": "reconcile",
                "command": (
                    "PYTHONPATH=. python -m executor_backend.cli reconcile "
                    f"--agent-evm-usdc {chain_state.evm_idle_usdc} "
                    f"--tracked-core-usdc {chain_state.tracked_core_usdc} "
                    f"--pending-core-deposits {chain_state.pending_core_deposits} "
                    f"--pending-core-withdrawals {chain_state.pending_core_withdrawals}"
                ),
            }
        )
    hypercore_state = dataclass_dict(state)
    hypercore_state["total_perp_account_value"] = state.total_perp_account_value
    report = {
        "type": "run_once",
        "agent_address": cfg.agent.agent_address,
        "network": cfg.network.name,
        "automation_mode": "automatic" if cfg.auto_nav else "assisted",
        "auto_nav": cfg.auto_nav,
        "auto_nav_result": auto_nav_result,
        "auto_reconcile": cfg.auto_reconcile,
        "hypercore": hypercore_state,
        "agent_chain_state": chain_state.to_dict() if chain_state is not None else None,
        "agent_chain_state_error": chain_error,
        "suggested_actions": suggested_actions,
        "checked_at": utc_now_iso(),
    }
    report["previous_checked_at"] = previous.get("checked_at")
    write_json(paths.last_seen, report)
    write_json(
        paths.service_state,
        {
            "agent_address": cfg.agent.agent_address,
            "network": cfg.network.name,
            "status": "checked",
            "pid": os.getpid(),
            "updated_at": report["checked_at"],
        },
    )
    append_jsonl(paths.operations, report)
    return report


def run_auto_nav_if_due(
    cfg: AppConfig,
    chain_state,
    *,
    day: int | None = None,
    previous_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit at most one guarded NAV settlement for each UTC calendar day."""
    target_day = day or int(datetime.now(UTC).strftime("%Y%m%d"))
    if chain_state.last_settled_day == 0:
        return {
            "status": "blocked",
            "day": target_day,
            "error": "initial NAV settlement must be reviewed and sent manually",
        }
    if chain_state.last_settled_day == target_day:
        return {"status": "already_settled", "day": target_day}
    if (
        previous_result
        and previous_result.get("day") == target_day
        and previous_result.get("status")
        in {"submitted", "unknown", "awaiting_chain_confirmation"}
    ):
        return {
            "status": "awaiting_chain_confirmation",
            "day": target_day,
            "previous_status": previous_result["status"],
        }
    if chain_state.last_settled_day > target_day:
        return {
            "status": "blocked",
            "day": target_day,
            "error": f"lastSettledDay {chain_state.last_settled_day} is ahead of UTC day",
        }

    cmd = [
        sys.executable,
        "-m",
        "executor_backend.cli",
        "nav-cycle",
        "--day",
        str(target_day),
        "--send",
    ]
    try:
        completed = subprocess.run(
            cmd,
            cwd=os.getcwd(),
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "unknown",
            "day": target_day,
            "error": "nav-cycle timed out; verify chain state manually before retrying",
        }
    if completed.returncode != 0:
        return {
            "status": "failed",
            "day": target_day,
            "exit_code": completed.returncode,
            "error": (completed.stderr or completed.stdout).strip()[-2000:],
        }
    return {
        "status": "submitted",
        "day": target_day,
        "output": completed.stdout.strip()[-4000:],
    }


def loop(cfg: AppConfig, interval: int) -> None:
    paths = RuntimePaths.from_agent(cfg.agent.agent_address)
    paths.ensure()
    write_json(
        paths.service_state,
        {
            "agent_address": cfg.agent.agent_address,
            "network": cfg.network.name,
            "status": "running",
            "pid": os.getpid(),
            "updated_at": utc_now_iso(),
        },
    )
    while True:
        try:
            run_once(cfg)
        except Exception as exc:  # daemon should keep observing after transient API issues
            append_jsonl(
                paths.operations,
                {
                    "type": "run_once_error",
                    "agent_address": cfg.agent.agent_address,
                    "error": str(exc),
                    "created_at": utc_now_iso(),
                },
            )
            write_json(
                paths.service_state,
                {
                    "agent_address": cfg.agent.agent_address,
                    "network": cfg.network.name,
                    "status": "error",
                    "pid": os.getpid(),
                    "error": str(exc),
                    "updated_at": utc_now_iso(),
                },
            )
        time.sleep(interval)


def start_service(cfg: AppConfig, interval: int) -> dict[str, Any]:
    paths = RuntimePaths.from_agent(cfg.agent.agent_address)
    paths.ensure()
    current = service_status(cfg)
    if current["running"]:
        return current

    cmd = [
        sys.executable,
        "-m",
        "executor_backend.cli",
        "service",
        "loop",
        "--interval",
        str(interval),
    ]
    log_fh = paths.executor_log.open("a")
    proc = subprocess.Popen(  # noqa: S603 - command is fixed and uses current Python module
        cmd,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        cwd=os.getcwd(),
        env=os.environ.copy(),
        start_new_session=True,
    )
    paths.service_pid.write_text(str(proc.pid) + "\n")
    payload = {
        "agent_address": cfg.agent.agent_address,
        "network": cfg.network.name,
        "status": "running",
        "pid": proc.pid,
        "log": str(paths.executor_log),
        "updated_at": utc_now_iso(),
    }
    write_json(paths.service_state, payload)
    append_jsonl(paths.operations, {"type": "service_start", **payload})
    return {"running": True, **payload}


def stop_service(cfg: AppConfig) -> dict[str, Any]:
    paths = RuntimePaths.from_agent(cfg.agent.agent_address)
    pid = _read_pid(paths)
    if pid is None:
        return {"running": False, "status": "not_running"}
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    if paths.service_pid.exists():
        paths.service_pid.unlink()
    payload = {
        "agent_address": cfg.agent.agent_address,
        "network": cfg.network.name,
        "status": "stopped",
        "pid": pid,
        "updated_at": utc_now_iso(),
    }
    write_json(paths.service_state, payload)
    append_jsonl(paths.operations, {"type": "service_stop", **payload})
    return {"running": False, **payload}


def service_status(cfg: AppConfig) -> dict[str, Any]:
    paths = RuntimePaths.from_agent(cfg.agent.agent_address)
    state = read_json(paths.service_state)
    pid = _read_pid(paths)
    running = _pid_running(pid) if pid is not None else False
    return {
        "agent_address": cfg.agent.agent_address,
        "network": cfg.network.name,
        "running": running,
        "pid": pid,
        "runtime_dir": str(paths.agent_dir),
        "log": str(paths.executor_log),
        "state": state,
    }


def tail_log(cfg: AppConfig, lines: int) -> str:
    path = RuntimePaths.from_agent(cfg.agent.agent_address).executor_log
    if not path.exists():
        return ""
    data = path.read_text(errors="replace").splitlines()
    return "\n".join(data[-lines:])


def _read_pid(paths: RuntimePaths) -> int | None:
    try:
        return int(paths.service_pid.read_text().strip())
    except Exception:
        return None


def _pid_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
