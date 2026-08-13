# Executor Backend

Layer 2 service skeleton for the Hyperliquid Agent architecture.

Terminology:

- Hyperliquid chain: the overall chain/environment.
- HyperCore: the spot/perp trading, balances, ledger, CoreWriter, and API-wallet module.
- HyperEVM: the EVM contract module where Agent contracts and executor transactions live.

Responsibilities:

- Import/read Agent contracts created by an external frontend.
- Use the Executor signer for funding, NAV, self trading-wallet authorization, and withdrawal confirmation.
- Track HyperCore state and reconcile with contract accounting.
- Coordinate redeem liquidity by sending `DeleverageRequest` to the independent Layer 3 trading service.

Non-goals:

- No owner private key.
- No separate trading wallet private key in the default collapsed-role mode.
- No HyperCore order placement.
- No frontend implementation.
- No database in v1. Contract state and HyperCore state are authoritative; local files are only operational evidence.

Runtime model:

- CLI commands are the source of truth for Executor actions.
- The lightweight daemon is a watcher / scheduler that can run checks and NAV previews on a timer.
- By default the daemon should run in assisted mode: write reports and suggested commands, then wait for Executor confirmation before sending transactions.
- `confirm-core-deposit` and `confirm-withdrawal` must only be sent after HyperCore / HyperEVM balance evidence is observed.


## Packaged Skill Distribution

Build an installable skill bundle from the repo root:

```bash
./scripts/package_skill.sh
```

The generated `dist/hyper-agent-executor-skill/` bundle contains `SKILL.md`, the executor backend source, install/runtime wrapper scripts, references, and an env template. The generated archive is intentionally treated as a build artifact. Skill source files live under `skill/`.

Installed skill bootstrap flow, executed by the agent from the unpacked/installed skill directory:

```bash
./scripts/install_executor.sh
./scripts/executorctl.sh --help
```

The skill installer script copies backend code to `~/.moss-hyper-agent/executor-backend/current` and creates an isolated virtualenv. User Agent configs, private keys, snapshots, service state, and logs live under `~/.moss-hyper-agent/agents/<agent-id>/`, not in the skill directory.

Install dependencies:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

## Env Templates

The env templates serve different entry points but must keep the same supported
field set:

- `.env_excuter_testnet.example`: team/operator template for local testnet config.
- `.env_excuter_mainnet.example`: fail-closed mainnet template with signer fields empty.
- `skill/templates/env.testnet.example`: installed testnet runtime template copied to
  `~/.moss-hyper-agent/templates/env.testnet.example`.
- `skill/templates/env.mainnet.example`: fail-closed installed mainnet template.

When executor config fields change, update all four templates together. The
unit test suite checks that their key sets stay in sync.

Run a local config check:

```bash
set -a
source .env_excuter_testnet  # Use .env_excuter_mainnet for mainnet.
set +a
python -m executor_backend.cli config
```

Initialize a lightweight runtime directory:

```bash
PYTHONPATH=. AGENT_ADDRESS=0xAgentProxy python -m executor_backend.cli agent-init
```

Run a one-shot daemon check without sending transactions:

```bash
PYTHONPATH=. AGENT_ADDRESS=0xAgentProxy python -m executor_backend.cli service run-once
```

Read Agent contract accounting and run an assisted NAV cycle:

```bash
PYTHONPATH=. AGENT_ADDRESS=0xAgentProxy python -m executor_backend.cli agent-chain-state --json
PYTHONPATH=. AGENT_ADDRESS=0xAgentProxy python -m executor_backend.cli nav-cycle --day 20260611
```

`nav-cycle` reads raw, accounted, and unaccounted Agent HyperEVM USDC plus HyperCore spot and the configured perp account values (`NAV_PERP_DEXS=main,xyz` by default), writes a snapshot under `~/.moss-hyper-agent/agents/<agent-id>/nav_snapshots/`, and returns the `settleDailyNav` calldata. Settlement uses `accountedEvmUsdc`, not the raw token balance; raw/gross values remain diagnostic only. Each perp dex contributes its full `marginSummary.accountValue`, including margin and unrealized PnL. The contract subtracts `pendingMintAssets + reservedRedeemAmount` internally for active share pricing. NAV settlement is blocked while either Core deposit or withdrawal accounting is pending, because observed HyperCore balances cannot safely distinguish in-transit funds from already-applied or silently failed actions. Use `--send` only after reviewing the snapshot and NAV change guard.

After one manual `nav-cycle --send` succeeds, set `ENABLE_AUTO_NAV=true` and restart the service to enable daily automatic reporting. The service attempts at most one settlement per UTC day and uses the same pending-Core, NAV-change, signer, and mainnet-send checks. A failed check is recorded and does not bypass the guard.

Mainnet broadcasts additionally require the exact process environment acknowledgement `ALLOW_MAINNET_SEND=true`. Unknown `NETWORK` values fail closed instead of defaulting to mainnet.

Keep local network configs separate: source `.env_excuter_testnet` for testnet and
`.env_excuter_mainnet` for mainnet. Never reuse the testnet executor key by copying
the whole file. The mainnet template starts in `dry_run`; switch to `private_key`
only after the deployed Agent, Executor permission, and derived signer address are verified.

Before using funding commands on a fresh Agent, have the operator/owner funder activate the Agent proxy on HyperCore with `usd_transfer(2.0, AgentProxy)`. Activation has been observed to consume about 1 USDC; leave the remaining approximately 1 USDC on HyperCore as a withdrawal/dynamic-fee buffer. This USDC is not HyperEVM gas in HYPE. The activation balance is external to contract accounting until HyperCore state is observed and the Owner intentionally syncs it with `syncCoreAccounting(...)`.

Start / stop the lightweight daemon:

```bash
PYTHONPATH=. AGENT_ADDRESS=0xAgentProxy python -m executor_backend.cli service start --interval 300
PYTHONPATH=. AGENT_ADDRESS=0xAgentProxy python -m executor_backend.cli service status
PYTHONPATH=. AGENT_ADDRESS=0xAgentProxy python -m executor_backend.cli service stop
```

Generate a NAV preview:

```bash
AGENT_ADDRESS=0x0000000000000000000000000000000000000001 \
python -m executor_backend.cli nav-preview --day 20260527 --evm-idle-usdc 1000000 --accounted-evm-usdc 1000000 --pending-core-deposits 0
```


Generate calldata without sending:

```bash
PYTHONPATH=. AGENT_ADDRESS=0x0000000000000000000000000000000000000001 python -m executor_backend.cli deposit-core --amount 1000000
```

`deposit-core` is for moving Agent HyperEVM USDC into an already activated HyperCore account on networks where the bridge-style deposit path is supported. It preflights the contract's trading limit and EVM liquidity. The default `maxTradingBps=5000` permits cumulative Core exposure up to 50% of `totalManagedAssets()`; tracked Core assets, pending deposits, pending withdrawals, and the requested amount all count. Exceeding the remaining capacity fails locally and would also revert in the contract. Mainnet keeps this as the intended contract-driven funding path. On testnet, do not expect `CoreDepositWallet.deposit(...)` to credit HyperCore; use native HyperCore `usd_transfer` / `spot_transfer` to fund real Core-balance tests. A HyperEVM receipt only proves the deposit wallet call succeeded; it does not prove HyperCore credited spot/perp balance. Never run `confirm-core-deposit` until HyperCore ledger or spot balance shows the funds.

Authorize the default collapsed-role trading wallet. When `--wallet` is omitted,
the CLI uses `EXECUTOR_ADDRESS`, which the Agent auto-approves through `setExecutor`:

```bash
PYTHONPATH=. AGENT_ADDRESS=0xAgentProxy EXECUTOR_ADDRESS=0xExecutor python -m executor_backend.cli authorize-approved --name executor
```

Broadcast with `EXECUTOR_PRIVATE_KEY`:

```bash
PYTHONPATH=. AGENT_ADDRESS=0xAgentProxy EXECUTOR_ADDRESS=0xExecutor EXECUTOR_PRIVATE_KEY=0x... python -m executor_backend.cli deposit-core --amount 1000000 --send
```

Confirm the deposit only after HyperCore ledger / spot balance shows the funds:

```bash
PYTHONPATH=. AGENT_ADDRESS=0xAgentProxy EXECUTOR_ADDRESS=0xExecutor EXECUTOR_PRIVATE_KEY=0x... python -m executor_backend.cli confirm-core-deposit --amount 1000000 --send
```

## Executor key rotation / leak response

See `skill/references/runbook.md` for the operational runbook. Contract `setExecutor(old, false)` disables Agent contract permissions but does not by itself remove the old HyperCore API wallet from `extraAgents`; always verify Hyperliquid `userRole` / `extraAgents` before considering a leaked key fully revoked.
