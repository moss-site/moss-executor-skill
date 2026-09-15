from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, DecimalException, ROUND_FLOOR
from typing import Any
from .http import read_json


@dataclass(frozen=True)
class PerpAccountState:
    account_value: int
    withdrawable: int
    positions: list[dict[str, Any]]
    time: int | None


@dataclass(frozen=True)
class HyperCoreState:
    spot_usdc: int
    spot_usdc_available: int
    perp_account_value: int
    perp_withdrawable: int
    positions: list[dict[str, Any]]
    ledger: list[dict[str, Any]]
    perp_accounts: dict[str, PerpAccountState] = field(default_factory=dict)
    ledger_included: bool = True

    @property
    def total_perp_account_value(self) -> int:
        if not self.perp_accounts:
            return self.perp_account_value
        return sum(account.account_value for account in self.perp_accounts.values())

    @property
    def all_positions(self) -> list[dict[str, Any]]:
        if not self.perp_accounts:
            return self.positions
        return [
            {**position, "dex": dex}
            for dex, account in self.perp_accounts.items()
            for position in account.positions
        ]


class HyperCoreClient:
    """Read-only HyperCore API boundary used by Layer 2.

    Trading calls belong in Layer 3 and must not be added here.
    """

    def __init__(self, api_url: str, perp_dexes: tuple[str, ...] = ("main",)):
        self.api_url = api_url.rstrip("/")
        from urllib.parse import urlsplit
        parsed = urlsplit(self.api_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.query or parsed.fragment
                or parsed.path.endswith(("/info", "/hypercore"))):
            raise ValueError("HyperCore read URL must be the native /info base URL")
        if not perp_dexes or "main" not in perp_dexes:
            raise ValueError("perp_dexes must include main")
        self.perp_dexes = perp_dexes

    def post_info(self, payload: dict[str, Any]) -> dict[str, Any] | list[Any]:
        return read_json(self.api_url + "/info", payload)

    def clearinghouse_state(self, user: str, dex: str = "main") -> dict[str, Any]:
        payload = {"type": "clearinghouseState", "user": user}
        if dex != "main":
            payload["dex"] = dex
        data = self.post_info(payload)
        if not isinstance(data, dict):
            raise ValueError(
                f"HyperCore clearinghouseState[{dex}] returned a non-object response"
            )
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

    def fetch_state(self, master_account: str, *, include_ledger: bool = True) -> HyperCoreState:
        clearings = {"main": self.clearinghouse_state(master_account)}
        clearings.update(
            {
                dex: self.clearinghouse_state(master_account, dex)
                for dex in self.perp_dexes
                if dex != "main"
            }
        )
        clearing = clearings["main"]
        spot = self.spot_clearinghouse_state(master_account)
        ledger = self.user_non_funding_ledger_updates(master_account) if include_ledger else []
        perp_accounts = {
            dex: self._extract_perp_account(dex, dex_clearing)
            for dex, dex_clearing in clearings.items()
        }
        main_perp = perp_accounts["main"]
        if "balances" not in spot:
            raise ValueError("HyperCore spotClearinghouseState is missing balances")
        balances = spot["balances"]
        if not isinstance(balances, list):
            raise ValueError("HyperCore spotClearinghouseState.balances must be a list")
        spot_usdc, spot_usdc_available = self._extract_spot_usdc(spot)
        return HyperCoreState(
            spot_usdc=spot_usdc,
            spot_usdc_available=spot_usdc_available,
            perp_account_value=main_perp.account_value,
            perp_withdrawable=main_perp.withdrawable,
            positions=main_perp.positions,
            ledger=ledger,
            ledger_included=include_ledger,
            perp_accounts=perp_accounts,
        )

    @classmethod
    def _extract_perp_account(cls, dex: str, clearing: dict[str, Any]) -> PerpAccountState:
        margin_summary = clearing.get("marginSummary")
        if not isinstance(margin_summary, dict) or "accountValue" not in margin_summary:
            raise ValueError(
                f"HyperCore clearinghouseState[{dex}] is missing marginSummary.accountValue"
            )
        positions = clearing.get("assetPositions", [])
        if not isinstance(positions, list):
            raise ValueError(
                f"HyperCore clearinghouseState[{dex}].assetPositions must be a list"
            )
        time = clearing.get("time")
        if time is not None and (not isinstance(time, int) or isinstance(time, bool)):
            raise ValueError(f"HyperCore clearinghouseState[{dex}].time must be an integer")
        return PerpAccountState(
            account_value=cls._decimal_to_usdc_units(margin_summary["accountValue"]),
            withdrawable=cls._decimal_to_usdc_units(clearing.get("withdrawable", "0")),
            positions=positions,
            time=time,
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
