from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from decimal import Decimal
from typing import Iterator

from executor_backend.config import load_config
from executor_backend.cli import (
    build_agent_client,
    usdc_asset_units,
    validate_manual_nav_settlement,
)
from executor_backend.hyper.client import HyperCoreClient
from executor_backend.models import OperationStatus, RedeemLiquidityPlan
from executor_backend.services.redeem import RedeemService


@contextmanager
def patched_env(values: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class SafetyRegressionTest(unittest.TestCase):
    def test_config_repr_redacts_sensitive_fields(self) -> None:
        with patched_env(
            {
                "EXECUTOR_PRIVATE_KEY": "0xdeadbeef",
                "TRADING_SERVICE_API_KEY": "trading-secret",
            }
        ):
            rendered = repr(load_config())

        self.assertNotIn("0xdeadbeef", rendered)
        self.assertNotIn("trading-secret", rendered)

    def test_redeem_liquidity_exposes_deleverage_delivery_failure(self) -> None:
        class FailingGateway:
            def request_deleverage(self, payload):
                self.payload = payload
                return {"status": "failed", "error": "connection refused"}

        gateway = FailingGateway()
        service = RedeemService(agent=None, trading=gateway, buffer_bps=100)
        plan = RedeemLiquidityPlan(
            agent_address="0x0000000000000000000000000000000000000001",
            confirmed_redeem_amount=1_000_000,
            agent_evm_idle=0,
            accounted_evm_idle=0,
            usable_evm_liquidity=0,
            pending_core_withdrawals=0,
            hypercore_free_usdc=0,
            buffer_amount=10_000,
            liquidity_needed=1_010_000,
            deleverage_needed=1_010_000,
        )

        result = service.prepare_liquidity(plan, "redeem-1", "2026-07-29T00:00:00Z")

        self.assertEqual(result["status"], OperationStatus.LIQUIDITY_PENDING)
        self.assertEqual(
            result["trading_result"],
            {"status": "failed", "error": "connection refused"},
        )
        self.assertEqual(gateway.payload.target_release_usdc, Decimal("1.01"))

    def test_redeem_liquidity_ignores_unaccounted_evm_donation(self) -> None:
        service = RedeemService(agent=None, trading=None, buffer_bps=0)

        plan = service.plan_liquidity(
            confirmed_redeem_amount=1_000_000,
            agent_evm_idle=2_000_000,
            accounted_evm_idle=100_000,
            pending_core_withdrawals=0,
            hypercore_free_usdc=900_000,
            agent_address="0x0000000000000000000000000000000000000001",
        )

        self.assertEqual(plan.usable_evm_liquidity, 100_000)
        self.assertEqual(plan.liquidity_needed, 900_000)

    def test_pending_core_withdrawal_is_not_reported_as_ready_evm_liquidity(self) -> None:
        service = RedeemService(agent=None, trading=None, buffer_bps=0)
        plan = service.plan_liquidity(
            confirmed_redeem_amount=1_000_000,
            agent_evm_idle=0,
            accounted_evm_idle=0,
            pending_core_withdrawals=1_000_000,
            hypercore_free_usdc=0,
            agent_address="0x0000000000000000000000000000000000000001",
        )

        result = service.prepare_liquidity(plan, "redeem-1", "2026-08-03T00:00:00Z")

        self.assertEqual(plan.liquidity_needed, 0)
        self.assertEqual(result["status"], OperationStatus.CORE_PENDING)

    def test_hypercore_decimal_parser_preserves_negative_sign(self) -> None:
        self.assertEqual(HyperCoreClient._decimal_to_usdc_units("-0.5"), -500_000)
        self.assertEqual(HyperCoreClient._decimal_to_usdc_units("-1.5"), -1_500_000)
        self.assertEqual(HyperCoreClient._decimal_to_usdc_units("1.2345678"), 1_234_567)
        self.assertEqual(HyperCoreClient._decimal_to_usdc_units("-0.0000001"), -1)

    def test_manual_nav_settlement_guard_cannot_be_bypassed_without_force(self) -> None:
        with self.assertRaisesRegex(ValueError, "Core bridge accounting is pending"):
            validate_manual_nav_settlement(100, 100, 1, 0, 2_000, force=True)
        with self.assertRaisesRegex(ValueError, "initial.*--force"):
            validate_manual_nav_settlement(100, 0, 0, 0, 2_000, force=False)
        with self.assertRaisesRegex(ValueError, "exceeds limit"):
            validate_manual_nav_settlement(200, 100, 0, 0, 2_000, force=False)

        self.assertEqual(
            validate_manual_nav_settlement(200, 100, 0, 0, 2_000, force=True),
            10_000,
        )

    def test_unknown_network_is_rejected(self) -> None:
        with patched_env({"NETWORK": "testent"}):
            with self.assertRaisesRegex(ValueError, "unsupported NETWORK"):
                load_config()

    def test_default_sqlite_database_is_separated_by_network(self) -> None:
        previous = os.environ.pop("DATABASE_URL", None)
        try:
            for network in ("testnet", "mainnet"):
                with self.subTest(network=network), patched_env({"NETWORK": network}):
                    self.assertEqual(
                        load_config().database_url,
                        f"sqlite:///executor-{network}.db",
                    )
        finally:
            if previous is not None:
                os.environ["DATABASE_URL"] = previous

    def test_auto_nav_is_disabled_by_default(self) -> None:
        previous = os.environ.pop("ENABLE_AUTO_NAV", None)
        try:
            self.assertFalse(load_config().auto_nav)
        finally:
            if previous is not None:
                os.environ["ENABLE_AUTO_NAV"] = previous

    def test_unknown_signer_mode_is_rejected(self) -> None:
        with patched_env({"SIGNER_MODE": "send_everything"}):
            with self.assertRaisesRegex(ValueError, "unsupported SIGNER_MODE"):
                load_config()

    def test_dry_run_signer_mode_blocks_send_even_with_key_and_mainnet_ack(self) -> None:
        with patched_env(
            {
                "NETWORK": "mainnet",
                "SIGNER_MODE": "dry_run",
                "ALLOW_MAINNET_SEND": "true",
                "EXECUTOR_PRIVATE_KEY": "0xdeadbeef",
            }
        ):
            with self.assertRaisesRegex(SystemExit, "SIGNER_MODE is not private_key"):
                build_agent_client(dry_run=False)

    def test_mainnet_send_requires_process_acknowledgement(self) -> None:
        with patched_env(
            {
                "NETWORK": "mainnet",
                "SIGNER_MODE": "private_key",
                "ALLOW_MAINNET_SEND": "false",
                "EXECUTOR_PRIVATE_KEY": "",
            }
        ):
            with self.assertRaisesRegex(SystemExit, "ALLOW_MAINNET_SEND=true"):
                build_agent_client(dry_run=False)

    def test_usdc_cli_amount_converts_exactly_to_asset_units(self) -> None:
        self.assertEqual(usdc_asset_units("1"), 1_000_000)
        self.assertEqual(usdc_asset_units("0.000001"), 1)
        with self.assertRaisesRegex(Exception, "at most 6 decimals"):
            usdc_asset_units("0.0000001")

    def test_hypercore_schema_mismatch_fails_closed(self) -> None:
        class InvalidResponseClient(HyperCoreClient):
            def post_info(self, payload):
                if payload["type"] == "clearinghouseState":
                    return []
                return {}

        client = InvalidResponseClient("https://example.invalid")
        with self.assertRaisesRegex(ValueError, "non-object"):
            client.fetch_state("0x0000000000000000000000000000000000000001")

    def test_hypercore_missing_account_value_fails_closed(self) -> None:
        class MissingAccountValueClient(HyperCoreClient):
            def clearinghouse_state(self, user):
                return {"marginSummary": {}, "assetPositions": []}

            def spot_clearinghouse_state(self, user):
                return {"balances": []}

            def user_non_funding_ledger_updates(self, user, start_time=None):
                return []

        client = MissingAccountValueClient("https://example.invalid")
        with self.assertRaisesRegex(ValueError, "marginSummary.accountValue"):
            client.fetch_state("0x0000000000000000000000000000000000000001")

    def test_hypercore_missing_spot_balances_fails_closed(self) -> None:
        class MissingBalancesClient(HyperCoreClient):
            def clearinghouse_state(self, user):
                return {
                    "marginSummary": {"accountValue": "0"},
                    "assetPositions": [],
                }

            def spot_clearinghouse_state(self, user):
                return {}

            def user_non_funding_ledger_updates(self, user, start_time=None):
                return []

        client = MissingBalancesClient("https://example.invalid")
        with self.assertRaisesRegex(ValueError, "missing balances"):
            client.fetch_state("0x0000000000000000000000000000000000000001")

    def test_hypercore_spot_available_subtracts_held_usdc(self) -> None:
        class SpotBalanceClient(HyperCoreClient):
            def clearinghouse_state(self, user):
                return {
                    "marginSummary": {"accountValue": "0"},
                    "withdrawable": "0",
                    "assetPositions": [],
                }

            def spot_clearinghouse_state(self, user):
                return {
                    "balances": [
                        {"coin": "USDC", "token": 0, "total": "2", "hold": "0.75"}
                    ]
                }

            def user_non_funding_ledger_updates(self, user, start_time=None):
                return []

        state = SpotBalanceClient("https://example.invalid").fetch_state(
            "0x0000000000000000000000000000000000000001"
        )

        self.assertEqual(state.spot_usdc, 2_000_000)
        self.assertEqual(state.spot_usdc_available, 1_250_000)

        with self.assertRaisesRegex(ValueError, "inconsistent"):
            HyperCoreClient._extract_spot_usdc(
                {"balances": [{"coin": "USDC", "total": "1", "hold": "2"}]}
            )


if __name__ == "__main__":
    unittest.main()
