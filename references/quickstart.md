# Executor Quickstart

Use this document for first-time setup and the normal operation sequence. Run commands from the installed skill root, for example `dist/hyper-agent-executor-skill/` or the unpacked skill directory.

Terminology used by this skill:

- Hyperliquid chain is the overall environment.
- HyperCore is the spot/perp trading, balances, ledger, CoreWriter, and API-wallet module.
- HyperEVM is the EVM contract module for Agent contracts and executor transactions.

## 0. Safety Rules

1. Start with dry-run commands. Add `--send` only after checking addresses, balances, permissions, and generated calldata.
2. Never print `EXECUTOR_PRIVATE_KEY` or paste a full `config.env` into chat/logs.
3. Executor commands can only perform Executor-authorized actions. Owner actions such as `setExecutor(...)`, pause/unpause, upgrades, and `syncCoreAccounting(...)` are outside this CLI and require the owner key.
4. Do not run `confirm-core-deposit` or `confirm-withdrawal` until there is independent HyperCore/HyperEVM evidence.
5. NAV uses accounted total assets. Use `accountedEvmUsdc()`, never raw `balanceOf(agent)`, for the EVM component. Do not subtract `pendingMintAssets` or `reservedRedeemAmount`; the contract handles active-share pricing internally.

## 1. Install the Skill Runtime

```bash
./scripts/install_executor.sh
```

This copies the packaged backend to:

```text
~/.moss-hyper-agent/executor-backend/current
```

It also creates:

```text
~/.moss-hyper-agent/templates/env.testnet.example
~/.moss-hyper-agent/templates/env.mainnet.example
```

If installation fails in a fresh Python venv with `setuptools.build_meta` missing, install/upgrade the build tools in that runtime venv and rerun the installer:

```bash
~/.moss-hyper-agent/executor-backend/current/.venv/bin/python -m pip install -U setuptools wheel
```

## 2. Create the Per-Agent Config

Do this before any executor operation. The normal flow is: collect config fields, write one `config.env`, run `agent-init`, then run read-only/dry-run checks. See `config-requirements.md` for the complete layered field table.

Pick `<agent-id>` as the first 6 lowercase hex characters of `AGENT_ADDRESS` without `0x`.

Example:

```text
AGENT_ADDRESS=0xBd0164eDaC67B701B3960551F86F336f5435C4e2
agent-id=bd0164
```

Create the runtime directory and config:

```bash
mkdir -p ~/.moss-hyper-agent/agents/<agent-id>
cp ~/.moss-hyper-agent/templates/env.testnet.example ~/.moss-hyper-agent/agents/<agent-id>/config.env
```

Edit only the small user-facing section first. For a normal Hyperliquid testnet setup, keep the remaining template defaults:

```text
NETWORK=testnet
AGENT_ADDRESS=0xAgentProxy
EXECUTOR_ADDRESS=0xExecutor
SIGNER_MODE=private_key
EXECUTOR_PRIVATE_KEY=
```

`SIGNER_MODE` has two modes: `dry_run` only generates calldata / reads state and never broadcasts; `private_key` allows signed sends after the user writes `EXECUTOR_PRIVATE_KEY` locally. The private key must derive `EXECUTOR_ADDRESS`; the CLI checks this before broadcasting.

Only change RPC/Core constants or automation switches when the operator explicitly needs them. The full layered field table is in `references/config-requirements.md`.

Minimum setup checklist:

- `AGENT_ADDRESS` is the Hyperliquid Agent proxy.
- `EXECUTOR_ADDRESS` is the intended trading/API wallet.
- `NETWORK`, `CHAIN_ID`, `EVM_RPC_URL`, and `HYPERCORE_API_URL` point to the same environment.
- `ACCEPT_TOKEN` and `CORE_DEPOSIT_WALLET` match the Agent contract getters.
- Use `dry_run` for read-only checks if desired; `private_key` can send only after the user writes the executor private key locally.
- Keep auto actions disabled during first setup unless the operator explicitly enables them.

## 3. Initialize Local Runtime (`agent-init`)

```bash
./scripts/executorctl.sh --agent 0xAgentProxy agent-init
```

`agent-init` is a local setup command. It does not send a transaction and does not authorize anything on chain. It creates/ensures:

```text
~/.moss-hyper-agent/agents/<agent-id>/
├── config.env
├── service.pid
├── service_state.json
├── operations.jsonl
├── nav_snapshots/
└── logs/
```

Run:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy service status
```

## 4. Verify Chain and HyperCore State

Read Agent contract state and HyperEVM idle USDC:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy agent-chain-state --json
```

Check at least:

- `agent_address` is the expected Agent proxy.
- `accept_token` matches `ACCEPT_TOKEN`.
- `evm_idle_usdc`, `accounted_evm_usdc`, `unaccounted_evm_usdc`, `tracked_core_usdc`, pending Core values, and `reserved_redeem_amount` are understood.
- `last_settled_day` and `last_settled_total_assets` match expectations.

Read HyperCore state:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy hyper-state
```

Check spot USDC, perp account value, withdrawable, positions, and recent ledger items.

## 5. Check Executor Permission on the Agent Contract

Most Agents should already have the intended executor set by the create/deploy flow. First check contract state through the frontend, chain reads, or `agent-chain-state` plus direct calls if needed. The expected state is:

```text
isExecutor(EXECUTOR_ADDRESS) == true
approvedTradingWallet(EXECUTOR_ADDRESS) == true
```

If either value is false, stop and ask the Agent owner to enable the executor. This is an owner action, not an executor CLI command:

```bash
cast send "$AGENT_ADDRESS" "setExecutor(address,bool)" "$EXECUTOR_ADDRESS" true \
  --rpc-url "$EVM_RPC_URL" --legacy --private-key "$OWNER_PRIVATE_KEY"
```

After owner action, re-check until both values are true before using any `--send` Executor command.

## 6. Authorize the Executor as the Agent's HyperCore Trading Wallet

This step is required before the executor can trade or send HyperCore/CoreWriter actions for the Agent on HyperCore. The executor signs an Agent contract transaction that calls CoreWriter `addApiWallet`, authorizing `EXECUTOR_ADDRESS` as the Agent's HyperCore API/trading wallet.

Use a dedicated executor/API wallet. Do not reuse a Hyperliquid address that is already an ordinary `user` account; Hyperliquid should report the executor as an `agent` for `AGENT_ADDRESS` after authorization.

Dry-run first:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy authorize-approved --name executor
```

Send after checking the Agent, executor address, and generated calldata:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy authorize-approved --name executor --send
```

Then verify on Hyperliquid info API / tooling:

```text
userRole(EXECUTOR_ADDRESS).role == agent
userRole(EXECUTOR_ADDRESS).data.user == AGENT_ADDRESS
extraAgents(AGENT_ADDRESS) contains EXECUTOR_ADDRESS
```

## 7. Activate the Agent HyperCore Address with External Funding

Fresh Agent addresses need activation on HyperCore before trading or reliable funding flows on both testnet and mainnet. Use an external funding account, such as an operator/owner wallet, to transfer a small amount to the Agent HyperCore address. This activation transfer is not sent by `executorctl.sh`.

Use native HyperCore transfer flows for activation, for example:

```text
external funding account -> usd_transfer(small_amount, AGENT_ADDRESS)
```

or spot transfer tooling, depending on the test plan.

Important:

- Native HyperCore transfers are not contract calls and are not executed by `executorctl.sh`.
- The funding account should be outside the Agent contract; it is used only to activate/fund the Agent HyperCore address.
- External activation/funding balances are not automatically reflected in contract accounting.
- If external HyperCore funding is used as test funds, owner-level `syncCoreAccounting(...)` may be required before contract-gated operations such as `withdraw-core`, because `tracked_core_usdc` is not increased by native HyperCore transfers.
- Observe HyperCore ledger / balances after transfer.
- If accounting must be repaired, `syncCoreAccounting(...)` is an owner-level manual action, not normal Executor automation.

## 8. Optional: Contract Deposit Path to Core

This path means:

```text
HyperEVM Agent contract USDC -> HyperCore spot account
```

Use this only after the Agent HyperCore address has already been activated by the external transfer in step 7 and where `CoreDepositWallet.deposit(...)` is supported for the target network. Mainnet is expected to use this normal contract-driven path after activation. On current testnet, HyperEVM-to-HyperCore funding is not reliable/available for real balance tests: do not assume a successful HyperEVM receipt means HyperCore credited the Agent. For testnet funding, use the external HyperCore transfer flow in step 7 and send USDC directly to the Agent HyperCore address.

Dry-run:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy deposit-core --amount <asset-units>
```

Send:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy deposit-core --amount <asset-units> --send
```

Before confirming:

1. Verify the HyperEVM transaction succeeded.
2. Verify HyperCore ledger or spot/perp balance delta.
3. Record observed evidence.

Only then:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy confirm-core-deposit --amount <asset-units> --send
```

## 9. Move Spot USDC to Perp or Back

This path stays inside HyperCore:

```text
HyperCore spot account <-> HyperCore perp account
```

Prefer `--amount-usdc` for `move-usdc`; the CLI converts human USDC to the action's 1e6 raw scale. Use `--amount-wei` only when an exact raw action is required.

Spot to perp means moving funds from the spot account into the perp/contract account:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy move-usdc --amount-usdc <usdc> --to-perp
./scripts/executorctl.sh --agent 0xAgentProxy move-usdc --amount-usdc <usdc> --to-perp --send
```

Perp to spot means moving funds from the perp/contract account back to the spot account:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy move-usdc --amount-usdc <usdc>
./scripts/executorctl.sh --agent 0xAgentProxy move-usdc --amount-usdc <usdc> --send
```

After sending, verify `hyper-state` and ledger items.

## 10. Withdraw Core Funds Back to the HyperEVM Agent Contract

This path means:

```text
HyperCore perp account -> HyperCore spot account -> HyperEVM Agent contract USDC
```

If funds are currently in the perp/contract account, first move them back to spot:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy move-usdc --amount-usdc <usdc>
./scripts/executorctl.sh --agent 0xAgentProxy move-usdc --amount-usdc <usdc> --send
```

Verify spot balance increased:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy hyper-state
```

Then request withdrawal from HyperCore spot back to the HyperEVM Agent contract:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy withdraw-core --amount-usdc <usdc>
./scripts/executorctl.sh --agent 0xAgentProxy withdraw-core --amount-usdc <usdc> --send
```

Do not confirm immediately. Before `confirm-withdrawal`, verify:

1. HyperCore withdrawal ledger / status shows completion.
2. HyperEVM USDC balance of the Agent contract increased.
3. The amount matches this withdrawal.
4. Evidence is recorded.

After HyperEVM-side USDC arrives, confirm accounting in the Agent contract:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy confirm-withdrawal --amount <asset-units> --send
```

`withdraw-core` initiates the HyperCore withdrawal. `confirm-withdrawal` only updates Agent contract accounting after funds are observed on HyperEVM; it is not the bridge action itself.

## 11. NAV Preview and Settlement

Run assisted NAV cycle first:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy nav-cycle --day <yyyymmdd>
```

This command:

1. Reads Agent contract accounting.
2. Reads HyperCore spot/perp state.
3. Builds a local snapshot under `nav_snapshots/`.
4. Computes accounted `settled_total_assets` and diagnostic `observed_gross_total_assets`.
5. Generates `settleDailyNav(...)` calldata.
6. Applies `MAX_NAV_CHANGE_BPS` safety check.

Review:

- raw, accounted, and unaccounted HyperEVM USDC;
- HyperCore spot USDC;
- HyperCore perp `accountValue`;
- pending Core deposits / withdrawals;
- reserved redeem;
- previous total assets and change bps;
- snapshot hash and generated calldata.

If either pending Core value is non-zero, `nav-cycle` stops before producing settlement calldata.
Verify both sides and confirm or repair accounting first.

Send only after review:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy nav-cycle --day <yyyymmdd> --send
```

Low-level settlement is available only when an externally reviewed snapshot already exists:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy nav-settle \
  --day <yyyymmdd> \
  --assets <accounted-total-assets> \
  --snapshot-hash <0xhash> \
  --send
```

## 12. Redeem Liquidity

If users have redeem demand and HyperEVM idle USDC is insufficient, prepare liquidity before the claim window. Use step 10 to bring funds back from HyperCore spot/perp to the HyperEVM Agent contract, then verify `agent-chain-state` before users or keepers call redeem.

## 13. Start the Watcher

Run one check:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy service run-once --json
```

Start watcher:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy service start --interval 300
```

Inspect:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy service status
./scripts/executorctl.sh --agent 0xAgentProxy service logs --lines 120
```

Stop:

```bash
./scripts/executorctl.sh --agent 0xAgentProxy service stop
```

## Normal First-Time Order

Use this order for a new Agent:

1. Install skill runtime.
2. Create and fill `config.env`.
3. Run `agent-init`.
4. Verify `agent-chain-state` and `hyper-state`.
5. Check executor permissions; if missing, ask the owner to run `setExecutor(EXECUTOR_ADDRESS, true)`, then re-check.
6. Executor dry-runs and sends `authorize-approved` to authorize its own address as the Agent HyperCore/API trading wallet.
7. Use an external funding account to transfer a small amount to the Agent HyperCore address for activation on both testnet and mainnet.
8. Verify HyperCore ledger/balances.
9. After activation: on testnet, continue using external HyperCore funding for real balance tests and owner-sync accounting if those externally funded balances must be withdrawn through the contract; on mainnet, if needed, run `deposit-core` and only then `confirm-core-deposit` after HyperCore evidence.
10. Move spot/perp balances as needed.
11. If funds must return to HyperEVM, run the withdrawal flow: perp -> spot if needed, `withdraw-core`, wait for HyperEVM evidence, then `confirm-withdrawal`.
12. Run `nav-cycle` without `--send`, review the snapshot, then run `nav-cycle --send` if safe.
13. Start watcher only after manual flows are understood.
