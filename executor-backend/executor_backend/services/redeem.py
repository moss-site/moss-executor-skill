from __future__ import annotations

from decimal import Decimal

from executor_backend.chain.client import AgentContractClient, TxResult
from executor_backend.models import DeleverageRequest, OperationStatus, RedeemLiquidityPlan
from executor_backend.services.trading_gateway import TradingServiceGateway


class RedeemService:
    def __init__(self, agent: AgentContractClient, trading: TradingServiceGateway, buffer_bps: int):
        self.agent = agent
        self.trading = trading
        self.buffer_bps = buffer_bps

    def plan_liquidity(
        self,
        confirmed_redeem_amount: int,
        agent_evm_idle: int,
        accounted_evm_idle: int,
        pending_core_withdrawals: int,
        hypercore_free_usdc: int,
        agent_address: str,
    ) -> RedeemLiquidityPlan:
        values = (
            confirmed_redeem_amount,
            agent_evm_idle,
            accounted_evm_idle,
            pending_core_withdrawals,
            hypercore_free_usdc,
        )
        if any(value < 0 for value in values):
            raise ValueError("redeem liquidity inputs cannot be negative")
        usable_evm_liquidity = min(agent_evm_idle, accounted_evm_idle)
        buffer_amount = (confirmed_redeem_amount * self.buffer_bps) // 10_000
        liquidity_needed = max(
            0,
            confirmed_redeem_amount
            + buffer_amount
            - usable_evm_liquidity
            - pending_core_withdrawals,
        )
        deleverage_needed = max(0, liquidity_needed - hypercore_free_usdc)
        return RedeemLiquidityPlan(
            agent_address=agent_address,
            confirmed_redeem_amount=confirmed_redeem_amount,
            agent_evm_idle=agent_evm_idle,
            accounted_evm_idle=accounted_evm_idle,
            usable_evm_liquidity=usable_evm_liquidity,
            pending_core_withdrawals=pending_core_withdrawals,
            hypercore_free_usdc=hypercore_free_usdc,
            buffer_amount=buffer_amount,
            liquidity_needed=liquidity_needed,
            deleverage_needed=deleverage_needed,
        )

    def prepare_liquidity(
        self,
        plan: RedeemLiquidityPlan,
        request_id: str,
        deadline: str,
    ) -> dict[str, object]:
        trading_result: dict[str, object] | None = None
        required_evm_liquidity = plan.confirmed_redeem_amount + plan.buffer_amount
        if plan.usable_evm_liquidity >= required_evm_liquidity:
            return {"status": OperationStatus.COMPLETED, "trading_result": trading_result}
        if plan.liquidity_needed == 0:
            return {"status": OperationStatus.CORE_PENDING, "trading_result": trading_result}
        if plan.deleverage_needed > 0:
            request = DeleverageRequest(
                agent_address=plan.agent_address,
                request_id=request_id,
                target_release_usdc=Decimal(plan.deleverage_needed) / Decimal(10**6),
                deadline=deadline,
            )
            trading_result = self.trading.request_deleverage(request)
            if trading_result.get("status") not in {"accepted", "completed"}:
                return {
                    "status": OperationStatus.LIQUIDITY_PENDING,
                    "trading_result": trading_result,
                }
        return {"status": OperationStatus.CORE_PENDING, "trading_result": trading_result}

    def request_core_withdrawal(self, amount_wei: int) -> TxResult:
        return self.agent.request_core_withdrawal(amount_wei)
