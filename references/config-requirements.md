# Executor Config Requirements

Use this document before running any executor command. The executor skill is simpler and safer when every required field is collected first, written to one per-Agent `config.env`, and then validated with dry-run/read-only checks.

This document only lists fields used by `executor-backend` or its bundled operational workflows. Do not copy unrelated trading-service-only fields into this config unless the executor backend explicitly supports them.

## 1. Config-First Workflow

1. Install the skill runtime so the template exists:

```bash
./scripts/install_executor.sh
```

2. Pick `<agent-id>` as the first 6 lowercase hex characters of `AGENT_ADDRESS` without `0x`. Example: `0x467f0f...` -> `467f0f`.

3. Create the per-Agent config path:

```bash
mkdir -p ~/.moss-hyper-agent/agents/<agent-id>
cp ~/.moss-hyper-agent/templates/env.testnet.example ~/.moss-hyper-agent/agents/<agent-id>/config.env
```

For mainnet, copy `~/.moss-hyper-agent/templates/env.mainnet.example` instead.

4. Fill `config.env` from the field tables below. Do not paste or print `EXECUTOR_PRIVATE_KEY` in chat or logs.

5. Run local initialization only after config is filled:

```bash
./scripts/executorctl.sh --config ~/.moss-hyper-agent/agents/<agent-id>/config.env agent-init
```

6. Run read-only checks before any `--send` command:

```bash
./scripts/executorctl.sh --config ~/.moss-hyper-agent/agents/<agent-id>/config.env agent-chain-state --json
./scripts/executorctl.sh --config ~/.moss-hyper-agent/agents/<agent-id>/config.env hyper-state
```


## 2. Simple User Template

For normal testnet setup, the user only needs to provide a few values. Everything else can keep the template defaults unless the operator explicitly enables custom RPC, mainnet, or automation.

```text
一、创建 executor 服务
请使用最新 executor skill/runtime 创建新的 executor 服务。

网络：Hyperliquid testnet
Agent 合约地址：<AGENT_ADDRESS>
Executor 地址：<EXECUTOR_ADDRESS>
运行模式：private_key

运行模式说明：
- dry_run：只生成 calldata / 做读取检查，不发交易。
- private_key：使用本地 EXECUTOR_PRIVATE_KEY 签名，允许发交易。

私钥稍后由用户写入本地 config.env；请告诉用户配置文件地址。

二、开始前检查
1. config.env 已创建。
2. 私钥由用户本地写入，未打印、未提交。
3. agent-init 已执行，并已从 AGENT_ADDRESS 自动读取 Agent/Core 配置。
4. agent-chain-state / hyper-state 检查通过。
5. isExecutor(EXECUTOR_ADDRESS) 为 true；如果不是 true，需要 owner 先设置。
6. authorize-approved 执行后，Hyperliquid userRole 显示 executor 是 Agent 的 agent wallet。
```

对应最小 `config.env` 只需要用户确认/修改这些行：

```env
NETWORK=testnet
AGENT_ADDRESS=<Agent proxy address>
EXECUTOR_ADDRESS=<Executor/API wallet address>
SIGNER_MODE=private_key
EXECUTOR_PRIVATE_KEY=
```

如果只是先检查、不准备发交易，可以临时使用：

```env
SIGNER_MODE=dry_run
EXECUTOR_PRIVATE_KEY=
```

Hyperliquid testnet 的网络默认值可以保留在模板里。Agent/Core 常量不需要用户填，`agent-init` 会从 `AGENT_ADDRESS` 读取并写回 `config.env`：

```env
CHAIN_ID=998
EVM_RPC_URL=https://rpc.hyperliquid-testnet.xyz/evm
HYPERCORE_API_URL=https://api.hyperliquid-testnet.xyz
ACCEPT_TOKEN=
CORE_DEPOSIT_WALLET=
USDC_TOKEN_INDEX=
USDC_SPOT_DESTINATION_DEX=
CORE_USDC_WEI_PER_ASSET_UNIT=
ENABLE_AUTO_NAV=false
ENABLE_AUTO_RECONCILE=false
ENABLE_AUTO_CORE_WITHDRAW=false
```

## 3. Required Field Table

### 3.1 Agent / Executor Identity

| Field | Required | Example | Meaning / Check |
| --- | --- | --- | --- |
| `AGENT_ADDRESS` | Yes | `0x467f0fdb95166a3248ed074f4c70aac7180f7b97` | Hyperliquid Agent contract proxy. This is also the Agent's HyperCore address/master account. |
| `EXECUTOR_ADDRESS` | Yes | `0x7419bf84a496b0Fa1C480c9F0Db71064a3543523` | Executor/API wallet address. Must match `EXECUTOR_PRIVATE_KEY` before sending. |

### 3.2 Network

| Field | Required | Testnet Example | Mainnet Example | Meaning / Check |
| --- | --- | --- | --- | --- |
| `NETWORK` | Yes | `testnet` | `mainnet` | Selects default chain/API endpoints when explicit URLs are absent. |
| `CHAIN_ID` | Yes | `998` | `999` | HyperEVM chain id. Must match `EVM_RPC_URL`. |
| `EVM_RPC_URL` | Yes | `https://rpc.hyperliquid-testnet.xyz/evm` | `https://rpc.hyperliquid.xyz/evm` | EVM RPC used for Agent contract calls. |
| `HYPERCORE_API_URL` | Yes | `https://api.hyperliquid-testnet.xyz` | `https://api.hyperliquid.xyz` | HyperCore API used for balances, `userRole`, and `extraAgents` checks. |
| `NAV_PERP_DEXS` | Yes | `main,xyz` | `main,xyz` | Explicit perp dex whitelist included in NAV and reconciliation; `main` is required. |

### 3.3 Signing / Send Mode

| Field | Required | Example | Meaning / Check |
| --- | --- | --- | --- |
| `SIGNER_MODE` | Yes | `private_key` | `private_key` allows sends after the key is written locally; use `dry_run` only for no-send checks. |
| `EXECUTOR_PRIVATE_KEY` | Required for `--send` | `0x...` | Must derive `EXECUTOR_ADDRESS`. Never print it. Leave empty for dry-run/read-only setup. |
| `EXECUTOR_GAS_LIMIT` | Optional | empty | Optional manual gas limit override. Leave empty unless needed. |

### 3.4 Agent Contract / HyperCore Parameters

These values are normally read from the Agent contract during `agent-init`, then written back to `config.env`. Users should leave them empty unless debugging or intentionally overriding. Non-empty overrides are validated against chain values.

| Field | User Should Set? | Source | Meaning / Check |
| --- | --- | --- | --- |
| `ACCEPT_TOKEN` | No | `acceptToken()` | Agent accept token, normally USDC. |
| `CORE_DEPOSIT_WALLET` | No | `coreDepositWallet()` | Core deposit wallet used by Agent execute scope. |
| `USDC_TOKEN_INDEX` | No | `usdcTokenIndex()` | HyperCore USDC token index. |
| `USDC_SPOT_DESTINATION_DEX` | No | `spotDestinationDex()` | Spot destination dex used by deposit/core actions. |
| `USDC_PERP_DESTINATION_DEX` | Usually no | template default | Perp destination dex retained for class-transfer helpers. |
| `CORE_USDC_WEI_PER_ASSET_UNIT` | No | `coreUsdcWeiPerAssetUnit()` | Conversion between HyperCore USDC wei and EVM asset units. |

### 3.5 Deleverage / External Service Integration

These fields are only needed if using executor-backend's deleverage workflow against an external service. They are not required for normal chain state checks, authorization, NAV, deposit, withdraw, or reconcile commands.

| Field | Required | Example | Meaning / Check |
| --- | --- | --- | --- |
| `TRADING_SERVICE_URL` | Optional | `http://localhost:9000` | External service base URL for deleverage workflow. |
| `TRADING_SERVICE_API_KEY` | Optional / if service requires | empty | API key for that external service. Treat as secret. |
| `TRADING_SERVICE_DELEVERAGE_ENDPOINT` | Optional | `/deleverage` | Deleverage endpoint path. |
| `DELEVERAGE_REQUEST_TIMEOUT_SECONDS` | Optional | `3600` | Timeout for deleverage requests. |

### 3.6 Automation / Risk Switches

For first setup, keep automatic send-capable workflows disabled until read-only checks and manual dry-runs pass.

| Field | Required | Recommended Setup Value | Meaning / Check |
| --- | --- | --- | --- |
| `ENABLE_AUTO_NAV` | Yes | `false` until a manual send succeeds | When `true`, the running service attempts at most one guarded `nav-cycle --send` per UTC day. Restart after changing it. Mainnet still needs process-only `ALLOW_MAINNET_SEND=true`. |
| `ENABLE_AUTO_RECONCILE` | Yes | `false` first, then decide | Enables automatic reconcile workflow in the service loop. |
| `ENABLE_AUTO_CORE_WITHDRAW` | Yes | `false` | Core withdrawal automation should stay off unless explicitly approved. |
| `MAX_NAV_CHANGE_BPS` | Yes | `2000` | Guardrail for NAV movement; 2000 = 20%. |
| `REDEEM_LIQUIDITY_BUFFER_BPS` | Yes | `100` | Redeem liquidity buffer; 100 = 1%. |

### 3.7 Local Runtime

| Field | Required | Default | Meaning / Check |
| --- | --- | --- | --- |
| `DATABASE_URL` | Yes | `sqlite:///executor-testnet.db` / `sqlite:///executor-mainnet.db` | Network-specific local database path/URL. Never share one SQLite file across testnet and mainnet. |
| `MOSS_EXECUTOR_HOME` | Optional | `~/.moss-hyper-agent` | Runtime root override. Usually leave unset. |

## 4. Minimal Testnet Config Example

Suggested config path for the current test Agent:

```text
~/.moss-hyper-agent/agents/467f0f/config.env
```

Config values:

```text
NETWORK=testnet
CHAIN_ID=998
EVM_RPC_URL=https://rpc.hyperliquid-testnet.xyz/evm
HYPERCORE_API_URL=https://api.hyperliquid-testnet.xyz

AGENT_ADDRESS=0x467f0fdb95166a3248ed074f4c70aac7180f7b97
EXECUTOR_ADDRESS=0x7419bf84a496b0Fa1C480c9F0Db71064a3543523
SIGNER_MODE=private_key
EXECUTOR_GAS_LIMIT=
EXECUTOR_PRIVATE_KEY=

ACCEPT_TOKEN=
CORE_DEPOSIT_WALLET=
USDC_TOKEN_INDEX=
USDC_SPOT_DESTINATION_DEX=
USDC_PERP_DESTINATION_DEX=0
CORE_USDC_WEI_PER_ASSET_UNIT=

TRADING_SERVICE_URL=http://localhost:9000
TRADING_SERVICE_API_KEY=
TRADING_SERVICE_DELEVERAGE_ENDPOINT=/deleverage
DELEVERAGE_REQUEST_TIMEOUT_SECONDS=3600

DATABASE_URL=sqlite:///executor-testnet.db
ENABLE_AUTO_NAV=false
ENABLE_AUTO_RECONCILE=false
ENABLE_AUTO_CORE_WITHDRAW=false
MAX_NAV_CHANGE_BPS=2000
REDEEM_LIQUIDITY_BUFFER_BPS=100
```

The user writes `EXECUTOR_PRIVATE_KEY` locally before any `--send` operation. Leave it empty for config creation and read-only checks.

## 5. Minimal Mainnet Config Example

Keep mainnet in a separate config file and start with all send-capable automation disabled:

```env
NETWORK=mainnet
CHAIN_ID=999
EVM_RPC_URL=https://rpc.hyperliquid.xyz/evm
HYPERCORE_API_URL=https://api.hyperliquid.xyz

AGENT_ADDRESS=<mainnet Agent proxy>
EXECUTOR_ADDRESS=<mainnet Executor address>
SIGNER_MODE=dry_run
EXECUTOR_PRIVATE_KEY=

ACCEPT_TOKEN=
CORE_DEPOSIT_WALLET=
USDC_TOKEN_INDEX=
USDC_SPOT_DESTINATION_DEX=
USDC_PERP_DESTINATION_DEX=0
CORE_USDC_WEI_PER_ASSET_UNIT=

ENABLE_AUTO_NAV=false
ENABLE_AUTO_RECONCILE=false
ENABLE_AUTO_CORE_WITHDRAW=false
ENABLE_AUTO_CONFIRM_CORE_DEPOSIT=false
ENABLE_AUTO_CONFIRM_CORE_WITHDRAWAL=false
MAX_NAV_CHANGE_BPS=2000
DATABASE_URL=sqlite:///executor-mainnet.db
```

Run `agent-init` and read-only checks before adding the key or changing
`SIGNER_MODE=private_key`. Every mainnet broadcast also requires the exact
process-only acknowledgement `ALLOW_MAINNET_SEND=true`; do not persist that
acknowledgement in `config.env`.

## 6. Pre-Operation Checklist

Before running any operation beyond `agent-init` and read-only checks:

1. `AGENT_ADDRESS` is the expected Hyperliquid Agent proxy.
2. `EXECUTOR_ADDRESS` is the intended Executor/API wallet.
3. `EXECUTOR_PRIVATE_KEY`, if present, derives exactly `EXECUTOR_ADDRESS`.
4. `NETWORK`, `CHAIN_ID`, `EVM_RPC_URL`, and `HYPERCORE_API_URL` point to the same environment.
5. Agent contract `acceptToken()` and `coreDepositWallet()` match config.
6. `isExecutor(EXECUTOR_ADDRESS) == true`; if false, owner must run `setExecutor(EXECUTOR_ADDRESS, true)` first.
7. Hyperliquid `userRole(EXECUTOR_ADDRESS)` shows agent role for `AGENT_ADDRESS` after `authorize-approved`.
8. An external funder activated the Agent HyperCore address with `usd_transfer(2.0, Agent)` and approximately 1 USDC remains as a withdrawal/fee buffer.
9. Before `deposit-core`, verify the CLI preflight. Default `maxTradingBps=5000` permits cumulative Core exposure up to 50% of `totalManagedAssets()`, not 50% of the raw EVM wallet balance.
10. Testnet caveat: a successful HyperEVM deposit receipt may still produce no HyperCore credit; fund directly for testing and never confirm without ledger/balance evidence.
11. `--send` is used only after dry-run output and balances/permissions are reviewed.
