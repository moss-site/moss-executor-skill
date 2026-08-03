from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DecimalException, ROUND_FLOOR
from typing import Any
from urllib import request
import json


@dataclass(frozen=True)
class HyperCoreState:
    spot_usdc: int
    spot_usdc_available: int
    perp_account_value: int
    perp_withdrawable: int
    positions: list[dict[str, Any]]
    ledger: list[dict[str, Any]]


class HyperCoreClient:
    """Read-only HyperCore API boundary used by Layer 2.

    Trading calls belong in Layer 3 and must not be added here.
    """

    def __init__(self, api_url: str):
        self.api_url = api_url.rstrip("/")

    def post_info(self, payload: dict[str, Any]) -> dict[str, Any] | list[Any]:
        req = request.Request(
            self.api_url + "/info",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())

    def clearinghouse_state(self, user: str) -> dict[str, Any]:
        data = self.post_info({"type": "clearinghouseState", "user": user})
        if not isinstance(data, dict):
            raise ValueError("HyperCore clearinghouseState returned a non-object response")
        return data

    def spot_clearinghouse_state(self, user: str) -> dict[str, Any]:
        data = self.post_info({"type": "spotClearinghouseState", "user": user})
        if not isinstance(data, dict):
            raise ValueError("HyperCore spotClearinghouseState returned a non-object response")
        return data

    def user_non_funding_ledger_updates(
        self, user: str, start_time: int | None = None
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"type": "userNonFundingLedgerUpdates", "user": user}
        if start_time is not None:
            payload["startTime"] = start_time
        data = self.post_info(payload)
        if not isinstance(data, list):
            raise ValueError("HyperCore userNonFundingLedgerUpdates returned a non-list response")
        return data

    def fetch_state(self, master_account: str) -> HyperCoreState:
        clearing = self.clearinghouse_state(master_account)
        spot = self.spot_clearinghouse_state(master_account)
        ledger = self.user_non_funding_ledger_updates(master_account)
        margin_summary = clearing.get("marginSummary")
        if not isinstance(margin_summary, dict) or "accountValue" not in margin_summary:
            raise ValueError("HyperCore clearinghouseState is missing marginSummary.accountValue")
        positions = clearing.get("assetPositions", [])
        if not isinstance(positions, list):
            raise ValueError("HyperCore clearinghouseState.assetPositions must be a list")
        if "balances" not in spot:
            raise ValueError("HyperCore spotClearinghouseState is missing balances")
        balances = spot["balances"]
        if not isinstance(balances, list):
            raise ValueError("HyperCore spotClearinghouseState.balances must be a list")
        spot_usdc, spot_usdc_available = self._extract_spot_usdc(spot)
        return HyperCoreState(
            spot_usdc=spot_usdc,
            spot_usdc_available=spot_usdc_available,
            perp_account_value=self._decimal_to_usdc_units(margin_summary.get("accountValue", "0")),
            perp_withdrawable=self._decimal_to_usdc_units(clearing.get("withdrawable", "0")),
            positions=positions,
            ledger=ledger,
        )

    def is_wallet_authorized(self, master_account: str, trading_wallet: str) -> bool:
        # HyperCore does not expose a stable authorization read in this skeleton. Keep this as a
        # boundary method so we can wire the exact endpoint once finalized.
        return bool(master_account and trading_wallet)

    @staticmethod
    def _extract_spot_usdc(state: dict[str, Any]) -> tuple[int, int]:
        balances = state.get("balances", [])
        if not isinstance(balances, list):
            raise ValueError("HyperCore spot balances must be a list")
        for balance in balances:
            if not isinstance(balance, dict):
                raise ValueError("HyperCore spot balance entry must be an object")
            coin = str(balance.get("coin", "")).upper()
            token = str(balance.get("token", "")).upper()
            if coin == "USDC" or token == "USDC" or token == "0":
                if "total" not in balance or "hold" not in balance:
                    raise ValueError("HyperCore USDC spot balance is missing total or hold")
                total = HyperCoreClient._decimal_to_usdc_units(balance["total"])
                hold = HyperCoreClient._decimal_to_usdc_units(balance["hold"])
                if total < 0 or hold < 0 or hold > total:
                    raise ValueError("HyperCore USDC spot total/hold values are inconsistent")
                return total, total - hold
        return 0, 0

    @staticmethod
    def _decimal_to_usdc_units(value: Any) -> int:
        try:
            decimal_value = Decimal(str(value))
            if not decimal_value.is_finite():
                raise ValueError("value must be finite")
            scaled = decimal_value * Decimal(10**6)
            return int(scaled.to_integral_value(rounding=ROUND_FLOOR))
        except (DecimalException, OverflowError, ValueError) as exc:
            raise ValueError(f"invalid HyperCore decimal value: {value!r}") from exc
