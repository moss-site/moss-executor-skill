from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from executor_backend.chain.client import AgentContractClient, TxResult
from executor_backend.hyper.client import HyperCoreClient
from executor_backend.models import NavSnapshot

SHARE_PRICE_PRECISION = 10**18


class NavService:
    def __init__(self, agent: AgentContractClient, hypercore: HyperCoreClient):
        self.agent = agent
        self.hypercore = hypercore

    def preview(
        self,
        agent_address: str,
        epoch_day: int,
        evm_idle_usdc: int,
        accounted_evm_usdc: int,
        reserved_redeem_amount: int,
        pending_core_withdrawals: int,
        previous_share_price: int = SHARE_PRICE_PRECISION,
        pending_core_deposits: int = 0,
    ) -> NavSnapshot:
        if min(
            evm_idle_usdc,
            accounted_evm_usdc,
            reserved_redeem_amount,
            pending_core_deposits,
            pending_core_withdrawals,
        ) < 0:
            raise ValueError("NAV accounting inputs cannot be negative")
        if pending_core_deposits != 0 or pending_core_withdrawals != 0:
            raise ValueError(
                "NAV settlement is blocked while Core bridge accounting is pending; "
                "verify HyperCore/HyperEVM state and confirm or repair accounting first"
            )
        if evm_idle_usdc < accounted_evm_usdc:
            raise ValueError(
                "raw HyperEVM USDC balance is below accountedEvmUsdc; "
                "restore the token shortfall before NAV settlement"
            )
        state = self.hypercore.fetch_state(agent_address)
        # Settlement uses protocol-accounted EVM assets. Raw balance and excess
        # transfers remain visible in the snapshot but cannot affect share price.
        settled_total_assets = (
            accounted_evm_usdc
            + state.spot_usdc
            + state.perp_account_value
        )
        if settled_total_assets < 0:
            raise ValueError("HyperCore losses exceed accounted assets; NAV cannot be negative")
        observed_gross_total_assets = (
            evm_idle_usdc
            + state.spot_usdc
            + state.perp_account_value
        )
        payload = {
            "agent_address": agent_address,
            "epoch_day": epoch_day,
            "settled_total_assets": settled_total_assets,
            "observed_gross_total_assets": observed_gross_total_assets,
            "evm_idle_usdc": evm_idle_usdc,
            "accounted_evm_usdc": accounted_evm_usdc,
            "unaccounted_evm_usdc": evm_idle_usdc - accounted_evm_usdc,
            "hypercore_spot_usdc": state.spot_usdc,
            "hypercore_perp_account_value": state.perp_account_value,
            "hypercore_perp_withdrawable": state.perp_withdrawable,
            "reserved_redeem_amount": reserved_redeem_amount,
            "pending_core_deposits": pending_core_deposits,
            "pending_core_withdrawals": pending_core_withdrawals,
            "positions": state.positions,
            "ledger_items": state.ledger,
        }
        serialized_payload = json.dumps(payload, sort_keys=True).encode()
        snapshot_hash = "0x" + hashlib.sha256(serialized_payload).hexdigest()
        return NavSnapshot(
            previous_share_price=previous_share_price,
            new_share_price=previous_share_price,
            snapshot_hash=snapshot_hash,
            **payload,
        )

    def settle(self, snapshot: NavSnapshot) -> TxResult:
        return self.agent.settle_daily_nav(
            snapshot.epoch_day,
            snapshot.settled_total_assets,
            snapshot.snapshot_hash,
        )

    @staticmethod
    def to_json(snapshot: NavSnapshot) -> str:
        return json.dumps(asdict(snapshot), sort_keys=True, indent=2)


def nav_change_bps(current_assets: int, previous_assets: int) -> int:
    if previous_assets == 0:
        return 0
    return abs(current_assets - previous_assets) * 10_000 // previous_assets
