---
name: hyper-agent-executor
description: Install and operate the Hyper Agent Executor backend from a packaged skill. Use when managing Hyper Agent local executor services, generating runtime config, starting/stopping the daemon, checking contract/HyperCore state, running NAV preview/settlement, reconcile, Core funding runbooks, or coordinating executor automation without requiring a full protocol repo checkout.
---

# Hyper Agent Executor

Use this skill to deploy and operate the local `executor-backend` runtime that manages a Hyper Agent's Executor actions.

## Operating Principles

- Keep user secrets and runtime state outside the skill directory under `~/.moss-hyper-agent/`.
- Never print private keys or full env files; redact `EXECUTOR_PRIVATE_KEY` in summaries.
- Default to dry-run / assisted mode. Use `--send` only after the user explicitly asks to broadcast.
- NAV input is accounted total assets. Use `accountedEvmUsdc`, never raw Agent token balance; do not subtract `pendingMintAssets` or `reservedRedeemAmount`, because the contract excludes them internally for active-share pricing.
- Do not settle NAV while `pendingCoreDeposits` or `pendingCoreWithdrawals` is non-zero. Verify both sides and confirm or repair accounting first.
- Do not overlap a NAV snapshot with explicit Core deposit, withdrawal, or spot/perp transfer operations; HyperCore spot and perp reads are separate API snapshots.
- For perp NAV, use HyperCore `marginSummary.accountValue`, not `withdrawable`, so open PnL and locked margin are included.
- Do not call `confirm-core-deposit` or `confirm-withdrawal` without observed HyperCore/HyperEVM evidence.
- Activate every new Agent HyperCore address from an external funder with `usd_transfer(2.0, AGENT_ADDRESS)`. The observed activation cost is about 1 USDC; leave the remaining approximately 1 USDC on HyperCore as a withdrawal/fee buffer.
- Before `deposit-core`, read `maxTradingBps` and current Core exposure. The contract default is `5000` (50%); tracked Core assets plus pending deposits, pending withdrawals, and the new amount must not exceed that limit.
- For executor key rotation, disable old contract permissions and verify Hyperliquid `extraAgents`; do not assume old API wallets are revoked by `setExecutor`.
- Treat `syncCoreAccounting` as owner-level manual repair, not normal Executor automation.
- For mainnet sends, restate network, Agent, Executor, target, action, and amount before sending, then set the process-only acknowledgement `ALLOW_MAINNET_SEND=true`.

## Installed Skill Layout

Packaged skill root:

```text
hyper-agent-executor-skill/
├── SKILL.md
├── executor-backend/
├── scripts/install_executor.sh
├── scripts/executorctl.sh
├── templates/env.testnet.example
├── templates/env.mainnet.example
└── references/
```

Runtime state:

```text
~/.moss-hyper-agent/
├── executor-backend/current/
├── templates/env.testnet.example
├── templates/env.mainnet.example
└── agents/<agent-id>/
    ├── config.env
    ├── service.pid
    ├── service_state.json
    ├── operations.jsonl
    ├── nav_snapshots/
    └── logs/
```

## First-Time Install

When the user asks to initialize or deploy the executor backend, locate the installed skill root and run the bundled installer from that directory:

```bash
./scripts/install_executor.sh
```

Do this as the operating agent; do not tell the user to run it manually unless the local environment or approval policy prevents execution. Then create an Agent config from the matching network template:

```bash
mkdir -p ~/.moss-hyper-agent/agents/<agent-id>
# Testnet:
cp ~/.moss-hyper-agent/templates/env.testnet.example ~/.moss-hyper-agent/agents/<agent-id>/config.env
# Mainnet instead:
cp ~/.moss-hyper-agent/templates/env.mainnet.example ~/.moss-hyper-agent/agents/<agent-id>/config.env
```

Edit `config.env` with at least:

```text
NETWORK
CHAIN_ID
EVM_RPC_URL
HYPERCORE_API_URL
AGENT_ADDRESS
EXECUTOR_ADDRESS
EXECUTOR_PRIVATE_KEY
ACCEPT_TOKEN
CORE_DEPOSIT_WALLET
MAX_NAV_CHANGE_BPS
```

Use `<agent-id>` as the first 6 lowercase hex characters of `AGENT_ADDRESS` without `0x`.

Before running operational commands, prefer the config-first flow in `references/config-requirements.md`: collect required fields, write the per-Agent `config.env`, run `agent-init`, then run read-only/dry-run checks.

## Command Wrapper

Use the bundled wrapper from the installed skill root instead of manually setting `PYTHONPATH`:

```bash
./scripts/executorctl.sh --config ~/.moss-hyper-agent/agents/<agent-id>/config.env <command>
```

Or pass the full Agent address:

```bash
./scripts/executorctl.sh --agent 0xAgent agent-chain-state --json
```

The wrapper sources `config.env`, uses the installed backend under `~/.moss-hyper-agent/executor-backend/current`, then runs:

```bash
python -m executor_backend.cli ...
```

Transaction-style commands emit structured JSON and append the same redacted record to `operations.jsonl`. For CoreWriter / Core deposit commands, treat the HyperEVM transaction as submitted only; run `hyper-state` and check HyperCore ledger/balances before any confirm command.

## Common Workflows

Initialize runtime and check status:

```bash
./scripts/executorctl.sh --agent 0xAgent agent-init
./scripts/executorctl.sh --agent 0xAgent service status
./scripts/executorctl.sh --agent 0xAgent service run-once --json
```

Read state:

```bash
./scripts/executorctl.sh --agent 0xAgent agent-chain-state --json
./scripts/executorctl.sh --agent 0xAgent hyper-state
```

NAV preview and settlement:

```bash
./scripts/executorctl.sh --agent 0xAgent nav-cycle --day <yyyymmdd>
./scripts/executorctl.sh --agent 0xAgent nav-cycle --day <yyyymmdd> --send
```

After one manual daily cycle has been reviewed and sent successfully, offer automatic daily NAV to the user. Set `ENABLE_AUTO_NAV=true` in that Agent's `config.env` and restart the service. The service then attempts at most one `nav-cycle --send` per UTC day and still blocks on pending Core accounting, the NAV-change guard, signer checks, and mainnet acknowledgement. Do not describe this as enabled until `service status` is running with the updated config.

Start/stop watcher:

```bash
./scripts/executorctl.sh --agent 0xAgent service start --interval 300
./scripts/executorctl.sh --agent 0xAgent service logs --lines 120
./scripts/executorctl.sh --agent 0xAgent service stop
```

## Reference Selection

- For the complete layered config field table and pre-operation checklist, read `references/config-requirements.md`.
- For first-time setup and the full operation sequence, read `references/quickstart.md`.
- For local runtime/service behavior, read `references/layer2-runtime.md`.
- For exact operational commands and safety checks, read `references/runbook.md`.
- For HyperCore unit conversions and testnet caveats, read `references/hypercore-units-and-caveats.md`.

Load only the reference needed for the user's request.
