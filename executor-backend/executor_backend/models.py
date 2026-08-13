from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any


class OperationStatus(StrEnum):
    CREATED = "created"
    VALIDATED = "validated"
    WAITING_SIGNATURE = "waiting_signature"
    SUBMITTED = "submitted"
    EVM_CONFIRMED = "evm_confirmed"
    CORE_PENDING = "core_pending"
    CORE_CONFIRMED = "core_confirmed"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    LIQUIDITY_PENDING = "liquidity_pending"


@dataclass(frozen=True)
class Operation:
    operation_id: str
    agent_address: str
    action_type: str
    status: OperationStatus
    params: dict[str, Any] = field(default_factory=dict)
    tx_hash: str | None = None
    core_status: str | None = None
    error_reason: str | None = None


@dataclass(frozen=True)
class NavSnapshot:
    agent_address: str
    epoch_day: int
    settled_total_assets: int
    observed_gross_total_assets: int
    previous_share_price: int
    new_share_price: int
    evm_idle_usdc: int
    accounted_evm_usdc: int
    unaccounted_evm_usdc: int
    hypercore_spot_usdc: int
    hypercore_perp_account_value: int
    hypercore_perp_withdrawable: int
    hypercore_total_perp_account_value: int
    hypercore_perp_accounts: dict[str, Any]
    reserved_redeem_amount: int
    pending_core_deposits: int
    pending_core_withdrawals: int
    positions: list[dict[str, Any]]
    ledger_items: list[dict[str, Any]]
    snapshot_hash: str


@dataclass(frozen=True)
class RedeemLiquidityPlan:
    agent_address: str
    confirmed_redeem_amount: int
    agent_evm_idle: int
    accounted_evm_idle: int
    usable_evm_liquidity: int
    pending_core_withdrawals: int
    hypercore_free_usdc: int
    buffer_amount: int
    liquidity_needed: int
    deleverage_needed: int


@dataclass(frozen=True)
class DeleverageRequest:
    agent_address: str
    request_id: str
    target_release_usdc: Decimal
    deadline: str
    mode: str = "reduce_only"
    max_slippage_bps: int = 50
    reason: str = "redeem_liquidity"
