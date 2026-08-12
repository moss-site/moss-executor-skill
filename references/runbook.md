# Executor Runbook

In an installed skill, run commands from the skill root with `./scripts/executorctl.sh --agent 0xAgent ...`. In the protocol repo, the same CLI remains available through `PYTHONPATH=. python -m executor_backend.cli ...`.

## Initialize

```bash
./scripts/executorctl.sh --agent 0xAgent agent-init
./scripts/executorctl.sh --agent 0xAgent service status
```

## Daemon

```bash
./scripts/executorctl.sh --agent 0xAgent service run-once --json
./scripts/executorctl.sh --agent 0xAgent service start --interval 300
./scripts/executorctl.sh --agent 0xAgent service logs --lines 120
./scripts/executorctl.sh --agent 0xAgent service stop
```

## Agent State

Read HyperCore state:

```bash
./scripts/executorctl.sh --agent 0xAgent hyper-state
```

Read Agent contract accounting and HyperEVM idle USDC:

```bash
./scripts/executorctl.sh --agent 0xAgent agent-chain-state --json
```

## NAV

Manual preview when values are supplied externally:

```bash
./scripts/executorctl.sh --agent 0xAgent nav-preview \
  --day <yyyymmdd> \
  --evm-idle-usdc <asset-units> \
  --accounted-evm-usdc <asset-units> \
  --reserved-redeem <asset-units> \
  --pending-core-deposits <asset-units> \
  --pending-core-withdrawals <asset-units>
```

NAV settlement input is the Agent's accounted total assets. Use `accountedEvmUsdc()`
rather than raw HyperEVM token balance, then include observed HyperCore spot/perp USDC,
pending Core deposits, and pending Core withdrawals. Raw and unaccounted EVM values are
diagnostic only. Do not subtract `pendingMintAssets` or `reservedRedeemAmount` in the executor layer;
`HyperAgent.settleDailyNav(...)` subtracts those internally when computing active
share price. Do not confirm a deposit until HyperCore ledger/spot proves it
arrived.

Assisted cycle: read Agent contract accounting including pending Core deposits, read HyperCore state, write a local snapshot, and return the exact `settleDailyNav` calldata without sending:

```bash
./scripts/executorctl.sh --agent 0xAgent nav-cycle --day <yyyymmdd>
```

Send only after reviewing the cycle output, snapshot hash, HyperCore state, and NAV change guard:

```bash
./scripts/executorctl.sh --agent 0xAgent nav-cycle --day <yyyymmdd> --send
```

After a successful manual cycle, offer automatic daily NAV. Set `ENABLE_AUTO_NAV=true` in the per-Agent `config.env`, restart the service, and verify `service status`. The daemon attempts at most one settlement per UTC day. All NAV checks still apply; mainnet also requires `ALLOW_MAINNET_SEND=true` in the environment of `service start`.

Low-level settle remains available when an externally reviewed snapshot is already prepared:

```bash
./scripts/executorctl.sh --agent 0xAgent nav-settle \
  --day <yyyymmdd> \
  --assets <accounted-total-assets> \
  --snapshot-hash <hash> \
  --send
```

## Executor Key Rotation / Leak Response

Use this runbook when the executor private key may be exposed or the operator wants to rotate the executor/trading wallet.

### Goals

- Move Agent contract executor authority to a new wallet.
- Authorize the new wallet as the Agent's HyperCore API wallet.
- Stop using the old wallet immediately.
- Verify whether the old HyperCore API wallet is still present before declaring the incident closed.

### Safe sequence

1. Generate a fresh wallet that has never been used on Hyperliquid. Confirm:

```bash
# Hyperliquid info API: userRole(newWallet) should be {"role":"missing"}
```

2. Fund the new wallet with enough HyperEVM gas for executor transactions.
3. Owner enables the new executor on the Agent contract:

```bash
cast send "$AGENT_ADDRESS" "setExecutor(address,bool)" "$NEW_EXECUTOR" true \
  --rpc-url "$EVM_RPC_URL" --legacy --private-key "$OWNER_PRIVATE_KEY"
```

4. Update local executor config to the new address/private key. Do not print the private key.
5. New executor authorizes itself through the Agent/CoreWriter path. Use a short name such as `bot`:

```bash
./scripts/executorctl.sh --agent 0xAgent authorize-approved --name bot --send
```

6. Verify the new wallet:

```text
isExecutor(new) == true
approvedTradingWallet(new) == true
userRole(new).role == agent
userRole(new).data.user == Agent
extraAgents(Agent) contains new
```

7. Owner disables the old executor on the Agent contract:

```bash
cast send "$AGENT_ADDRESS" "setExecutor(address,bool)" "$OLD_EXECUTOR" false \
  --rpc-url "$EVM_RPC_URL" --legacy --private-key "$OWNER_PRIVATE_KEY"
```

8. Verify the old contract permissions are gone:

```text
isExecutor(old) == false
approvedTradingWallet(old) == false
```

### Important HyperCore API wallet caveat

Contract `setExecutor(old, false)` only removes Agent-contract permissions. It does not automatically revoke the old wallet from Hyperliquid `extraAgents`.

Current CoreWriter integration has an `addApiWallet` action, but no confirmed `removeApiWallet` action in this backend. Do not assume that calling `authorize-approved --name <old-name>` with a new wallet removes the old wallet. On testnet, a successful same-name CoreWriter transaction did not remove the previous `extraAgents` entry.

Therefore, after any suspected key leak:

- Treat the old wallet as still capable of HyperCore trading until `extraAgents(Agent)` and `userRole(old)` prove otherwise.
- Pause external trading services that still know the old private key.
- Move execution to the new wallet and update all services/configs.
- Reduce risk by closing risky positions or moving funds if the old API wallet cannot be revoked promptly.
- Keep checking Hyperliquid docs/support for the supported revoke/expire path and add it to executor-backend before relying on full revocation.

A rotation is only fully closed when both are true:

```text
Agent contract: old executor disabled
Hyperliquid: old wallet no longer has agent role / no longer appears in active extraAgents
```

## Executor Authorization

Authorize the collapsed-role Executor/trading wallet after Owner has set Executor and auto-approved it on Agent:

```bash
./scripts/executorctl.sh --agent 0xAgent authorize-approved --name executor
./scripts/executorctl.sh --agent 0xAgent authorize-approved --name executor --send
```

Use `--wallet <address>` only when Owner has explicitly approved a separate trading wallet.

## Core Deposit

Fresh Agents must be activated on HyperCore before relying on contract-driven deposit flows. The external funder sends `usd_transfer(2.0, Agent)`: about 1 USDC may be consumed by activation, and the remaining approximately 1 USDC stays as the HyperCore withdrawal/dynamic-fee buffer. This is not HyperEVM gas. Testnet real funding uses native `usd_transfer` / `spot_transfer`; mainnet keeps `CoreDepositWallet.deposit(...)` as the production contract path.

Default `maxTradingBps=5000` limits cumulative Core exposure to 50% of `totalManagedAssets()`. `deposit-core` preflights `trackedCoreUsdc + pendingCoreDeposits + pendingCoreWithdrawals + amount` against that limit and checks unreserved EVM liquidity. Reduce the amount if the local check fails; do not try to bypass it because the contract will reject the same out-of-scope call.

Dry-run first:

```bash
./scripts/executorctl.sh --agent 0xAgent deposit-core --amount <asset-units>
```

Send after checking Agent HyperEVM USDC balance and trading limit:

```bash
./scripts/executorctl.sh --agent 0xAgent deposit-core --amount <asset-units> --send
```

Before confirming:

- verify HyperEVM receipt;
- verify HyperCore ledger or spot/perp balance delta;
- record the ledger hash or observed balance.

```bash
./scripts/executorctl.sh --agent 0xAgent confirm-core-deposit --amount <asset-units> --send
```

## Spot / Perp Move

Move USDC from spot to perp:

```bash
./scripts/executorctl.sh --agent 0xAgent move-usdc --amount-usdc <usdc> --to-perp
./scripts/executorctl.sh --agent 0xAgent move-usdc --amount-usdc <usdc> --to-perp --send
```

Move USDC from perp back to spot:

```bash
./scripts/executorctl.sh --agent 0xAgent move-usdc --amount-usdc <usdc>
./scripts/executorctl.sh --agent 0xAgent move-usdc --amount-usdc <usdc> --send
```

## Core Withdrawal

Dry-run first:

```bash
./scripts/executorctl.sh --agent 0xAgent withdraw-core --amount-usdc <usdc>
```

Send after checking HyperCore spot balance and leaving fee buffer:

```bash
./scripts/executorctl.sh --agent 0xAgent withdraw-core --amount-usdc <usdc> --send
```

Before confirming:

- verify HyperCore `spotTransfer` ledger;
- verify Agent HyperEVM USDC balance increased.

```bash
./scripts/executorctl.sh --agent 0xAgent confirm-withdrawal --amount <asset-units> --send
```

## Reconcile

Use `agent-chain-state --json` to source the contract values, then run:

```bash
./scripts/executorctl.sh --agent 0xAgent reconcile \
  --agent-evm-usdc <asset-units> \
  --tracked-core-usdc <asset-units> \
  --pending-core-deposits <asset-units> \
  --pending-core-withdrawals <asset-units>
```

Positive diff means external HyperCore balance, such as activation funds or `spot_transfer`; Owner decides whether to call `syncCoreAccounting`. Negative diff means manual review.

Do not collect or review a NAV snapshot while explicit Core deposits, withdrawals, or spot/perp
class transfers are running. HyperCore spot and perp state come from separate API requests.

## Redeem Liquidity

Plan liquidity before large redemptions. This talks to Layer3 deleverage service when needed; it does not place HyperCore orders directly.
Only arrived, accounted HyperEVM liquidity can produce `completed`; a plan still relying on
`pending-core-withdrawals` remains `core_pending` until the funds are observed on HyperEVM.

```bash
./scripts/executorctl.sh --agent 0xAgent prepare-redeem-liquidity \
  --confirmed-redeem-amount <asset-units> \
  --agent-evm-idle <asset-units> \
  --accounted-evm-idle <asset-units> \
  --pending-core-withdrawals <asset-units> \
  --hypercore-free-usdc <asset-units> \
  --request-id <id> \
  --deadline <iso8601>
```


## Periodic Assisted Loop

The service loop is a watcher/scheduler. It writes `last_seen.json`, `service_state.json`, and `operations.jsonl`; it suggests NAV and reconcile commands but does not bypass evidence checks.

```bash
./scripts/executorctl.sh --agent 0xAgent service start --interval 300
./scripts/executorctl.sh --agent 0xAgent service logs --lines 120
./scripts/executorctl.sh --agent 0xAgent service stop
```

For each cycle, use:

```bash
./scripts/executorctl.sh --agent 0xAgent service run-once --json
./scripts/executorctl.sh --agent 0xAgent nav-cycle
```

Only use `--send` after reviewing the generated snapshot and suggested action.
