from __future__ import annotations

import unittest

from executor_backend.hyper.client import HyperCoreState, PerpAccountState
from executor_backend.services.reconciliation import ReconciliationService


class FakeHyperCoreClient:
    def __init__(self, state: HyperCoreState):
        self.state = state

    def fetch_state(self, agent_address: str) -> HyperCoreState:
        return self.state


class ReconciliationServiceTest(unittest.TestCase):
    def test_report_includes_xyz_in_observed_core_assets(self) -> None:
        state = HyperCoreState(
            spot_usdc=100_000,
            spot_usdc_available=100_000,
            perp_account_value=200_000,
            perp_withdrawable=150_000,
            positions=[],
            ledger=[],
            perp_accounts={
                "main": PerpAccountState(200_000, 150_000, [], 100),
                "xyz": PerpAccountState(300_000, 250_000, [], 101),
            },
        )

        report = ReconciliationService(FakeHyperCoreClient(state)).build_report(
            agent_address="0x0000000000000000000000000000000000000001",
            agent_evm_usdc=1_000_000,
            tracked_core_usdc=600_000,
            pending_core_deposits=0,
            pending_core_withdrawals=0,
        )

        self.assertEqual(report.hypercore_total_perp_account_value, 500_000)
        self.assertEqual(report.hypercore_total_observed, 600_000)
        self.assertEqual(report.hypercore_perp_accounts["xyz"]["account_value"], 300_000)
        self.assertEqual(report.diff, 0)
        self.assertEqual(report.status, "ok")


if __name__ == "__main__":
    unittest.main()
