# HyperCore 提现被 `trackedCoreUsdc` 卡住：简化处置文档（可发客户）

适用场景：

- `withdraw-core` 失败，报错 `InsufficientTrackedCoreAssets`；
- 或本地预检提示 `tracked_core_usdc` 小于拟提现金额；
- 常见于「外部打入 HyperCore 资金 / 激活金 / 已实现盈利」尚未同步到合约 `trackedCoreUsdc`。

核心结论：

1. Executor 先核对 HyperCore 真实可提余额；
2. Owner 调一次 `syncCoreAccounting(...)` 同步 `trackedCoreUsdc`；
3. Executor 再执行 `withdraw-core`，到账后 `confirm-withdrawal`。

> 注意：`syncCoreAccounting` 是 Owner 权限，Executor 不能代替。

---

## 一次性快速执行（复制后改变量）

在 skill 根目录执行（有 `scripts/executorctl.sh` 的目录）：

```bash
# ====== 必填变量 ======
AGENT=0x48e1e329db93b070c21f06cdf46c6b927e757c50
CONFIG=~/.moss-hyper-agent/agents/<agent-id>/config.env
RPC_URL=https://rpc.hyperliquid.xyz/evm
OWNER_PRIVATE_KEY=0x...             # 仅 Owner 私钥可用

# 拟同步到合约的 trackedCoreUsdc（单位: asset units，1 USDC=1,000,000）
# 例：13.8 USDC => 13800000
NEW_TRACKED_CORE_USDC=<asset-units>

# 提现金额（两种表达，保持一致）
WITHDRAW_USDC=<usdc>                # 例：13.8
WITHDRAW_ASSET_UNITS=<asset-units>  # 例：13800000

# ====== 1) 取证：当前链上会计 + HyperCore 状态 ======
./scripts/executorctl.sh --config "$CONFIG" agent-chain-state --json | tee /tmp/agent_chain_state.json
./scripts/executorctl.sh --config "$CONFIG" hyper-state

# ====== 2) Owner 同步会计（保留 pending 两个值不变） ======
PENDING_CORE_DEPOSITS=$(python -c 'import json; print(json.load(open("/tmp/agent_chain_state.json"))["pending_core_deposits"])')
PENDING_CORE_WITHDRAWALS=$(python -c 'import json; print(json.load(open("/tmp/agent_chain_state.json"))["pending_core_withdrawals"])')

cast send "$AGENT" "syncCoreAccounting(uint256,uint256,uint256)" \
  "$NEW_TRACKED_CORE_USDC" "$PENDING_CORE_DEPOSITS" "$PENDING_CORE_WITHDRAWALS" \
  --private-key "$OWNER_PRIVATE_KEY" --rpc-url "$RPC_URL"

# 校验同步结果
cast call "$AGENT" "trackedCoreUsdc()(uint256)" --rpc-url "$RPC_URL"

# ====== 3) Executor 重试提现 ======
./scripts/executorctl.sh --config "$CONFIG" withdraw-core --amount-usdc "$WITHDRAW_USDC" --send

# ====== 4) 到账后再确认（必须先看到账） ======
./scripts/executorctl.sh --config "$CONFIG" confirm-withdrawal --amount "$WITHDRAW_ASSET_UNITS" --send
```

---

## 三个必须确认点（避免误操作）

1. `NEW_TRACKED_CORE_USDC` 单位是 `asset units`（1 USDC=1,000,000）。
2. `confirm-withdrawal --amount` 也是 `asset units`，不是 HyperCore `spot_send` wei。
3. `confirm-withdrawal` 之前必须看到：
   - HyperCore 提现 ledger 完成；
   - Agent 的 HyperEVM USDC 余额确实增加。

---

## 给客户/AI 助手的最短指令模板

把下面这段发给客户（或让客户喂给 AI）即可：

```text
我在 Hyper Agent 提现遇到 InsufficientTrackedCoreAssets。
请按以下流程执行并输出每一步结果：
1) 读取 agent-chain-state 与 hyper-state，确认 tracked_core_usdc 与真实可提余额差异；
2) 使用 Owner key 调 syncCoreAccounting(newTrackedCoreUsdc, pendingCoreDeposits, pendingCoreWithdrawals)；
3) 用 executor 执行 withdraw-core --send；
4) 仅在 HyperEVM USDC 到账后执行 confirm-withdrawal --send；
5) 返回每个 tx hash、关键状态字段前后对比、以及最终是否可 redeem。
```

---

## 常见问题

- 问：为什么 daily NAV 上报后还是提不出来？
  - 答：`settleDailyNav` 不会修改 `trackedCoreUsdc`，只能更新 NAV/份额定价。

- 问：Executor 能直接调 `syncCoreAccounting` 吗？
  - 答：不能。该函数是 Owner 权限。

