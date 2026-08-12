from __future__ import annotations

import unittest

from executor_backend.chain.abi import calldata
from executor_backend.chain.client import CORE_WRITER, AgentContractClient
from executor_backend.hyper.client import HyperCoreState
from executor_backend.services.nav import NavService, nav_change_bps


class FakeHyperCoreClient:
    def __init__(self, state: HyperCoreState):
        self.state = state

    def fetch_state(self, agent_address: str) -> HyperCoreState:
        return self.state


class FakeRpcClient:
    def __init__(self, responses: dict[str, str]):
        self.responses = responses

    def eth_call(self, target: str, data: str) -> str:
        return self.responses[data]


class FakeAgentClient:
    def settle_daily_nav(self, day: int, accounted_assets: int, snapshot_hash: str):
        self.settle_args = (day, accounted_assets, snapshot_hash)
        return self.settle_args


class NavServiceTest(unittest.TestCase):
    def test_execute_uses_fat723_reasoning_signature_with_empty_defaults(self) -> None:
        client = AgentContractClient(
            agent_address="0x0000000000000000000000000000000000000001",
            dry_run=True,
        )

        tx = client.execute(CORE_WRITER, 0, "0x1234")

        self.assertTrue(tx.dry_run)
        self.assertIsNotNone(tx.calldata)
        self.assertTrue(tx.calldata.startswith("0x9bd11128"))
        self.assertFalse(tx.calldata.startswith("0xb61d27f6"))
        self.assertIn("0" * 64, tx.calldata)

    def test_runtime_config_can_be_resolved_from_agent_contract(self) -> None:
        client = AgentContractClient(
            agent_address="0x0000000000000000000000000000000000000001",
            rpc=FakeRpcClient(
                {
                    "0x5510f804": "0x" + "0" * 24 + "2b3370ee501b4a559b57d449569354196457d8ab",
                    "0xf3be0518": "0x" + "0" * 24 + "0b80659a4076e9e93c7dbe0f10675a16a3e5c206",
                    "0x15dc074d": "0x" + "0" * 63 + "0",
                    "0x98ab67cb": "0x" + "0" * 56 + "ffffffff",
                    "0xdcc410ef": "0x" + "0" * 62 + "64",
                }
            ),
            dry_run=True,
        )

        cfg = client.resolve_runtime_config()

        self.assertEqual(cfg["core_deposit_wallet"], "0x0b80659a4076e9e93c7dbe0f10675a16a3e5c206")
        self.assertEqual(cfg["usdc_token_index"], 0)
        self.assertEqual(cfg["spot_destination_dex"], 4294967295)
        self.assertEqual(cfg["core_usdc_wei_per_asset_unit"], 100)

    def test_preview_uses_accounted_assets_without_subtracting_reserved_redeem(self) -> None:
        service = NavService(
            agent=None,
            hypercore=FakeHyperCoreClient(
                HyperCoreState(
                    spot_usdc=200_000,
                    spot_usdc_available=200_000,
                    perp_account_value=300_000,
                    perp_withdrawable=250_000,
                    positions=[],
                    ledger=[],
                )
            ),
        )

        snapshot = service.preview(
            agent_address="0x0000000000000000000000000000000000000001",
            epoch_day=20260715,
            evm_idle_usdc=1_000_000,
            accounted_evm_usdc=900_000,
            reserved_redeem_amount=400_000,
            pending_core_withdrawals=0,
            pending_core_deposits=0,
        )

        self.assertEqual(snapshot.settled_total_assets, 1_400_000)
        self.assertEqual(snapshot.observed_gross_total_assets, 1_500_000)
        self.assertEqual(snapshot.unaccounted_evm_usdc, 100_000)
        self.assertEqual(snapshot.hypercore_perp_account_value, 300_000)
        self.assertEqual(snapshot.hypercore_perp_withdrawable, 250_000)
        self.assertEqual(snapshot.reserved_redeem_amount, 400_000)
        self.assertEqual(snapshot.pending_core_deposits, 0)
        self.assertEqual(snapshot.pending_core_withdrawals, 0)

    def test_preview_rejects_pending_core_bridge_accounting(self) -> None:
        service = NavService(
            agent=None,
            hypercore=FakeHyperCoreClient(
                HyperCoreState(
                    spot_usdc=200_000,
                    spot_usdc_available=200_000,
                    perp_account_value=300_000,
                    perp_withdrawable=250_000,
                    positions=[],
                    ledger=[],
                )
            ),
        )

        for pending_deposits, pending_withdrawals in ((1, 0), (0, 1)):
            with self.subTest(
                pending_deposits=pending_deposits,
                pending_withdrawals=pending_withdrawals,
            ):
                with self.assertRaisesRegex(ValueError, "Core bridge accounting is pending"):
                    service.preview(
                        agent_address="0x0000000000000000000000000000000000000001",
                        epoch_day=20260731,
                        evm_idle_usdc=1_000_000,
                        accounted_evm_usdc=1_000_000,
                        reserved_redeem_amount=0,
                        pending_core_withdrawals=pending_withdrawals,
                        pending_core_deposits=pending_deposits,
                    )

    def test_donation_does_not_change_settlement_or_nav_guard(self) -> None:
        service = NavService(
            agent=None,
            hypercore=FakeHyperCoreClient(
                HyperCoreState(
                    spot_usdc=0,
                    spot_usdc_available=0,
                    perp_account_value=0,
                    perp_withdrawable=0,
                    positions=[],
                    ledger=[],
                )
            ),
        )

        snapshot = service.preview(
            agent_address="0x0000000000000000000000000000000000000001",
            epoch_day=20260731,
            evm_idle_usdc=1_000_100,
            accounted_evm_usdc=100,
            reserved_redeem_amount=0,
            pending_core_withdrawals=0,
        )

        self.assertEqual(snapshot.settled_total_assets, 100)
        self.assertEqual(snapshot.observed_gross_total_assets, 1_000_100)
        self.assertEqual(snapshot.unaccounted_evm_usdc, 1_000_000)
        self.assertEqual(nav_change_bps(snapshot.settled_total_assets, 100), 0)

    def test_preview_rejects_evm_token_shortfall(self) -> None:
        service = NavService(
            agent=None,
            hypercore=FakeHyperCoreClient(
                HyperCoreState(
                    spot_usdc=0,
                    spot_usdc_available=0,
                    perp_account_value=0,
                    perp_withdrawable=0,
                    positions=[],
                    ledger=[],
                )
            ),
        )

        with self.assertRaisesRegex(ValueError, "below accountedEvmUsdc"):
            service.preview(
                agent_address="0x0000000000000000000000000000000000000001",
                epoch_day=20260731,
                evm_idle_usdc=99,
                accounted_evm_usdc=100,
                reserved_redeem_amount=0,
                pending_core_withdrawals=0,
            )

    def test_preview_rejects_negative_total_nav(self) -> None:
        service = NavService(
            agent=None,
            hypercore=FakeHyperCoreClient(
                HyperCoreState(
                    spot_usdc=0,
                    spot_usdc_available=0,
                    perp_account_value=-101,
                    perp_withdrawable=0,
                    positions=[],
                    ledger=[],
                )
            ),
        )

        with self.assertRaisesRegex(ValueError, "NAV cannot be negative"):
            service.preview(
                agent_address="0x0000000000000000000000000000000000000001",
                epoch_day=20260731,
                evm_idle_usdc=100,
                accounted_evm_usdc=100,
                reserved_redeem_amount=0,
                pending_core_withdrawals=0,
            )

    def test_settle_uses_accounted_total_assets(self) -> None:
        agent = FakeAgentClient()
        service = NavService(
            agent=agent,
            hypercore=FakeHyperCoreClient(
                HyperCoreState(
                    spot_usdc=0,
                    spot_usdc_available=0,
                    perp_account_value=0,
                    perp_withdrawable=0,
                    positions=[],
                    ledger=[],
                )
            ),
        )
        snapshot = service.preview(
            agent_address="0x0000000000000000000000000000000000000001",
            epoch_day=20260731,
            evm_idle_usdc=1_000_100,
            accounted_evm_usdc=100,
            reserved_redeem_amount=0,
            pending_core_withdrawals=0,
        )

        service.settle(snapshot)

        self.assertEqual(agent.settle_args, (20260731, 100, snapshot.snapshot_hash))

    def test_chain_state_reads_accounted_and_unaccounted_evm_balances(self) -> None:
        agent_address = "0x0000000000000000000000000000000000000001"
        token_address = "0x0000000000000000000000000000000000000002"

        def encoded(value: int) -> str:
            return "0x" + value.to_bytes(32, "big").hex()

        responses = {
            "0x5510f804": "0x" + "0" * 24 + token_address[2:],
            calldata("balanceOf(address)", [("address", agent_address)]): encoded(1_000_100),
            "0x2424d721": encoded(100),
            "0x7dbb6d8b": encoded(1_000_000),
            "0x25f25635": encoded(20),
            "0x0aa64d3d": encoded(30),
            "0xf31f268a": encoded(40),
            "0xef273a78": encoded(50),
            "0xb66a4d98": encoded(10),
            "0xdce77bdb": encoded(5_000),
            "0x80bc7175": encoded(20260730),
            "0xf490dd72": encoded(90),
            "0x6bddd479": encoded(1_000_000),
            "0x5f3e364a": encoded(1_000_000),
            "0x18160ddd": encoded(60),
        }
        client = AgentContractClient(agent_address=agent_address, rpc=FakeRpcClient(responses))

        state = client.read_chain_state()

        self.assertEqual(state.evm_idle_usdc, 1_000_100)
        self.assertEqual(state.accounted_evm_usdc, 100)
        self.assertEqual(state.unaccounted_evm_usdc, 1_000_000)
        self.assertEqual(state.pending_mint_assets, 10)
        self.assertEqual(state.max_trading_bps, 5_000)

    def test_core_deposit_preflight_mirrors_contract_trading_limit(self) -> None:
        agent_address = "0x0000000000000000000000000000000000000001"
        token_address = "0x0000000000000000000000000000000000000002"

        def encoded(value: int) -> str:
            return "0x" + value.to_bytes(32, "big").hex()

        responses = {
            "0x5510f804": "0x" + "0" * 24 + token_address[2:],
            calldata("balanceOf(address)", [("address", agent_address)]): encoded(700_000),
            "0x2424d721": encoded(700_000),
            "0x7dbb6d8b": encoded(0),
            "0x25f25635": encoded(200_000),
            "0x0aa64d3d": encoded(50_000),
            "0xf31f268a": encoded(0),
            "0xef273a78": encoded(0),
            "0xb66a4d98": encoded(0),
            "0xdce77bdb": encoded(5_000),
            "0x80bc7175": encoded(20260805),
            "0xf490dd72": encoded(1_000_000),
            "0x6bddd479": encoded(1_000_000),
            "0x5f3e364a": encoded(1_000_000),
            "0x18160ddd": encoded(1),
        }
        client = AgentContractClient(agent_address=agent_address, rpc=FakeRpcClient(responses))

        checks = client.core_deposit_preflight(250_000)

        self.assertEqual(checks["max_core_exposure"], 500_000)
        self.assertEqual(checks["current_core_exposure"], 250_000)
        self.assertEqual(checks["deposit_capacity"], 250_000)
        with self.assertRaisesRegex(ValueError, "maxTradingBps=5000"):
            client.core_deposit_preflight(250_001)

    def test_settle_calldata_encodes_accounted_assets(self) -> None:
        client = AgentContractClient(
            agent_address="0x0000000000000000000000000000000000000001",
            dry_run=True,
        )

        tx = client.settle_daily_nav(20260731, 100, "0x" + "11" * 32)

        self.assertIsNotNone(tx.calldata)
        self.assertEqual(int(tx.calldata[10 + 64 : 10 + 128], 16), 100)


if __name__ == "__main__":
    unittest.main()
