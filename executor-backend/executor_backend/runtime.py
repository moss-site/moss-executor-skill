from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import json
import os


DEFAULT_HOME = Path.home() / ".moss-hyper-agent"


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def short_agent_id(agent_address: str) -> str:
    address = (agent_address or "unknown").lower().removeprefix("0x")
    return address[:6] if address else "unknown"


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    agent_dir: Path
    config_env: Path
    service_pid: Path
    service_state: Path
    last_seen: Path
    operations: Path
    nav_snapshots: Path
    logs: Path
    executor_log: Path

    @classmethod
    def from_agent(cls, agent_address: str) -> "RuntimePaths":
        root = Path(os.getenv("MOSS_EXECUTOR_HOME", str(DEFAULT_HOME))).expanduser()
        agent_dir = root / "agents" / short_agent_id(agent_address)
        return cls(
            root=root,
            agent_dir=agent_dir,
            config_env=agent_dir / "config.env",
            service_pid=agent_dir / "service.pid",
            service_state=agent_dir / "service_state.json",
            last_seen=agent_dir / "last_seen.json",
            operations=agent_dir / "operations.jsonl",
            nav_snapshots=agent_dir / "nav_snapshots",
            logs=agent_dir / "logs",
            executor_log=agent_dir / "logs" / "executor.log",
        )

    def ensure(self) -> None:
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        self.nav_snapshots.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


def update_config_values(path: Path, values: dict[str, object], *, only_if_empty: bool = True) -> None:
    """Update simple KEY=value env files without touching secrets or comments."""
    existing = path.read_text().splitlines() if path.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    string_values = {key: "" if value is None else str(value) for key, value in values.items()}
    for line in existing:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue
        key, current = line.split("=", 1)
        if key in string_values:
            seen.add(key)
            if (not only_if_empty) or current == "":
                output.append(f"{key}={string_values[key]}")
            else:
                output.append(line)
        else:
            output.append(line)
    missing = [key for key in string_values if key not in seen]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# Resolved from Agent contract by agent-init.")
        for key in missing:
            output.append(f"{key}={string_values[key]}")
    path.write_text("\n".join(output) + "\n")


def write_config_template(paths: RuntimePaths, env: dict[str, str]) -> None:
    if paths.config_env.exists():
        return
    keys = [
        "NETWORK",
        "CHAIN_ID",
        "EVM_RPC_URL",
        "HYPERCORE_API_URL",
        "NAV_PERP_DEXS",
        "AGENT_ADDRESS",
        "EXECUTOR_ADDRESS",
        "ACCEPT_TOKEN",
        "CORE_DEPOSIT_WALLET",
        "USDC_TOKEN_INDEX",
        "USDC_SPOT_DESTINATION_DEX",
        "CORE_USDC_WEI_PER_ASSET_UNIT",
        "ENABLE_AUTO_NAV",
        "ENABLE_AUTO_CONFIRM_CORE_DEPOSIT",
        "ENABLE_AUTO_CONFIRM_CORE_WITHDRAWAL",
        "MAX_NAV_CHANGE_BPS",
        "REDEEM_LIQUIDITY_BUFFER_BPS",
    ]
    lines = [
        "# Hyperliquid Agent Executor runtime config.",
        "# Keep private keys outside git and avoid printing this file.",
    ]
    for key in keys:
        value = env.get(key, "")
        if key == "AGENT_ADDRESS" and not value:
            value = paths.agent_dir.name
        lines.append(f"{key}={value}")
    lines.append("# EXECUTOR_PRIVATE_KEY=0x...")
    paths.config_env.write_text("\n".join(lines) + "\n")


def dataclass_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return {"value": str(value)}
