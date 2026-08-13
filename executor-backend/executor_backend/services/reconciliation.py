from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any

from executor_backend.hyper.client import HyperCoreClient


@dataclass(frozen=True)
class ReconciliationReport:
    agent_address: str
    agent_evm_usdc: int
    tracked_core_usdc: int
    pending_core_deposits: int
    pending_core_withdrawals: int
    hypercore_spot_usdc: int
    hypercore_perp_account_value: int
    hypercore_perp_withdrawable: int
    hypercore_total_perp_account_value: int
    hypercore_perp_accounts: dict[str, Any]
    hypercore_total_observed: int
    accounting_total: int
    diff: int
    positions_count: int
    ledger_items_count: int
    status: str
    suggested_action: str


class ReconciliationService:
    def __init__(self, hypercore: HyperCoreClient):
        self.hypercore = hypercore

    def build_report(
        self,
        agent_address: str,
        agent_evm_usdc: int,
        tracked_core_usdc: int,
        pending_core_deposits: int,
        pending_core_withdrawals: int,
    ) -> ReconciliationReport:
        state = self.hypercore.fetch_state(agent_address)
        observed = state.spot_usdc + state.total_perp_account_value
        accounting = tracked_core_usdc + pending_core_deposits + pending_core_withdrawals
        diff = observed - accounting
        if diff == 0:
            status = "ok"
            action = "none"
        elif diff > 0:
            status = "untracked_external_core_balance"
            action = "verify HyperCore ledger; if expected, owner can syncCoreAccounting to include external deposits or activation funds"
        else:
            status = "needs_manual_review"
            action = "observed HyperCore balance is below contract accounting; pause new funding and review ledger before owner syncCoreAccounting"
        return ReconciliationReport(
            agent_address=agent_address,
            agent_evm_usdc=agent_evm_usdc,
            tracked_core_usdc=tracked_core_usdc,
            pending_core_deposits=pending_core_deposits,
            pending_core_withdrawals=pending_core_withdrawals,
            hypercore_spot_usdc=state.spot_usdc,
            hypercore_perp_account_value=state.perp_account_value,
            hypercore_perp_withdrawable=state.perp_withdrawable,
            hypercore_total_perp_account_value=state.total_perp_account_value,
            hypercore_perp_accounts={
                dex: asdict(account) for dex, account in state.perp_accounts.items()
            },
            hypercore_total_observed=observed,
            accounting_total=accounting,
            diff=diff,
            positions_count=len(state.all_positions),
            ledger_items_count=len(state.ledger),
            status=status,
            suggested_action=action,
        )

    @staticmethod
    def to_json(report: ReconciliationReport) -> str:
        return json.dumps(asdict(report), sort_keys=True, indent=2)
