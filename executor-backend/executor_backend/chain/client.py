from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from executor_backend.chain.abi import calldata, decode_address, decode_uint, encode_uint, selector
from executor_backend.chain.rpc import JsonRpcClient
from executor_backend.chain.signer import ExecutorSigner, TransactionRequest

CORE_WRITER = "0x3333333333333333333333333333333333333333"
ENCODING_VERSION = 1
ACTION_SPOT_SEND = 6
ACTION_USD_CLASS_TRANSFER = 7
ACTION_ADD_API_WALLET = 9
CONFIRM_CORE_DEPOSIT_SELECTOR = "0x7e128bca"
CONFIRM_CORE_WITHDRAWAL_SELECTOR = "0x441e5ac0"


@dataclass(frozen=True)
class AgentChainState:
    agent_address: str
    accept_token: str
    evm_idle_usdc: int
    accounted_evm_usdc: int
    unaccounted_evm_usdc: int
    tracked_core_usdc: int
    pending_core_deposits: int
    pending_core_withdrawals: int
    reserved_redeem_amount: int
    pending_mint_assets: int
    max_trading_bps: int
    last_settled_day: int
    last_settled_total_assets: int
    last_settled_share_price: int
    initial_share_price: int
    total_supply: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TxResult:
    tx_hash: str | None
    status: str = "submitted"
    calldata: str | None = None
    dry_run: bool = False


class AgentContractClient:
    """Agent ABI boundary for Layer 2.

    Executor actions are routed through the contract's controlled execute(...) entrypoint.
    Owner-level methods are intentionally not included.
    """

    def __init__(
        self,
        agent_address: str,
        rpc: JsonRpcClient | None = None,
        signer: ExecutorSigner | None = None,
        chain_id: int | None = None,
        dry_run: bool = True,
        gas_limit: int | None = None,
        core_deposit_wallet: str = "",
        spot_destination_dex: int | None = None,
        usdc_token_index: int | None = None,
        core_usdc_wei_per_asset_unit: int | None = None,
    ):
        self.agent_address = agent_address
        self.rpc = rpc
        self.signer = signer
        self.chain_id = chain_id
        self.dry_run = dry_run
        self.gas_limit = gas_limit
        self.core_deposit_wallet = core_deposit_wallet
        self.spot_destination_dex = spot_destination_dex
        self.usdc_token_index = usdc_token_index
        self.core_usdc_wei_per_asset_unit = core_usdc_wei_per_asset_unit

    def read_config(self) -> dict[str, Any]:
        return {"agent": self.agent_address}

    def read_runtime_config(self) -> dict[str, Any]:
        """Read Agent/Core constants from the Agent contract."""
        if self.rpc is None:
            raise ValueError("EVM_RPC_URL/RPC client is required to read Agent runtime config")
        return {
            "accept_token": self._read_address(self.agent_address, "acceptToken()"),
            "core_deposit_wallet": self._read_address(self.agent_address, "coreDepositWallet()"),
            "usdc_token_index": self._read_uint(self.agent_address, "usdcTokenIndex()"),
            "spot_destination_dex": self._read_uint(self.agent_address, "spotDestinationDex()"),
            "core_usdc_wei_per_asset_unit": self._read_uint(
                self.agent_address, "coreUsdcWeiPerAssetUnit()"
            ),
        }

    def resolve_runtime_config(self) -> dict[str, Any]:
        """Fill missing local config from chain and return the resolved values."""
        chain_cfg = self.read_runtime_config()
        if self.core_deposit_wallet:
            if self.core_deposit_wallet.lower() != chain_cfg["core_deposit_wallet"].lower():
                raise ValueError(
                    "CORE_DEPOSIT_WALLET does not match Agent coreDepositWallet()"
                )
        else:
            self.core_deposit_wallet = chain_cfg["core_deposit_wallet"]
        if self.usdc_token_index is not None and self.usdc_token_index != chain_cfg["usdc_token_index"]:
            raise ValueError("USDC_TOKEN_INDEX does not match Agent usdcTokenIndex()")
        if self.usdc_token_index is None:
            self.usdc_token_index = chain_cfg["usdc_token_index"]
        if (
            self.spot_destination_dex is not None
            and self.spot_destination_dex != chain_cfg["spot_destination_dex"]
        ):
            raise ValueError("USDC_SPOT_DESTINATION_DEX does not match Agent spotDestinationDex()")
        if self.spot_destination_dex is None:
            self.spot_destination_dex = chain_cfg["spot_destination_dex"]
        if (
            self.core_usdc_wei_per_asset_unit is not None
            and self.core_usdc_wei_per_asset_unit != chain_cfg["core_usdc_wei_per_asset_unit"]
        ):
            raise ValueError(
                "CORE_USDC_WEI_PER_ASSET_UNIT does not match Agent coreUsdcWeiPerAssetUnit()"
            )
        if self.core_usdc_wei_per_asset_unit is None:
            self.core_usdc_wei_per_asset_unit = chain_cfg["core_usdc_wei_per_asset_unit"]
        return {
            **chain_cfg,
            "core_deposit_wallet": self.core_deposit_wallet,
            "usdc_token_index": self.usdc_token_index,
            "spot_destination_dex": self.spot_destination_dex,
            "core_usdc_wei_per_asset_unit": self.core_usdc_wei_per_asset_unit,
        }

    def read_chain_state(self) -> AgentChainState:
        if self.rpc is None:
            raise ValueError("EVM_RPC_URL/RPC client is required to read Agent chain state")
        accept_token = self._read_address(self.agent_address, "acceptToken()")
        return AgentChainState(
            agent_address=self.agent_address,
            accept_token=accept_token,
            evm_idle_usdc=self._read_uint(accept_token, "balanceOf(address)", self.agent_address),
            accounted_evm_usdc=self._read_uint(self.agent_address, "accountedEvmUsdc()"),
            unaccounted_evm_usdc=self._read_uint(
                self.agent_address, "unaccountedAcceptTokenAssets()"
            ),
            tracked_core_usdc=self._read_uint(self.agent_address, "trackedCoreUsdc()"),
            pending_core_deposits=self._read_uint(self.agent_address, "pendingCoreDeposits()"),
            pending_core_withdrawals=self._read_uint(self.agent_address, "pendingCoreWithdrawals()"),
            reserved_redeem_amount=self._read_uint(self.agent_address, "reservedRedeemAmount()"),
            pending_mint_assets=self._read_uint(self.agent_address, "pendingMintAssets()"),
            max_trading_bps=self._read_uint(self.agent_address, "maxTradingBps()"),
            last_settled_day=self._read_uint(self.agent_address, "lastSettledDay()"),
            last_settled_total_assets=self._read_uint(self.agent_address, "lastSettledTotalAssets()"),
            last_settled_share_price=self._read_uint(self.agent_address, "lastSettledSharePrice()"),
            initial_share_price=self._read_uint(self.agent_address, "initialSharePrice()"),
            total_supply=self._read_uint(self.agent_address, "totalSupply()"),
        )

    def execute(self, target: str, value: int, inner_calldata: str) -> TxResult:
        data = calldata(
            "execute(address,uint256,bytes,bytes32,string)",
            [
                ("address", target),
                ("uint256", value),
                ("bytes", inner_calldata),
                ("bytes32", "0x" + "00" * 32),
                ("string", ""),
            ],
        )
        return self._send_executor_tx(data)

    def core_deposit_preflight(self, amount: int) -> dict[str, int]:
        """Mirror the Agent's Core deposit limits before building or sending a transaction."""
        state = self.read_chain_state()
        total_managed_assets = state.last_settled_total_assets or (
            state.accounted_evm_usdc
            + state.tracked_core_usdc
            + state.pending_core_deposits
            + state.pending_core_withdrawals
        )
        max_core_exposure = total_managed_assets * state.max_trading_bps // 10_000
        current_core_exposure = (
            state.tracked_core_usdc
            + state.pending_core_deposits
            + state.pending_core_withdrawals
        )
        trading_capacity = max(0, max_core_exposure - current_core_exposure)
        protected_assets = state.pending_mint_assets + state.reserved_redeem_amount
        unreserved_evm_assets = max(0, state.accounted_evm_usdc - protected_assets)
        deposit_capacity = min(
            state.evm_idle_usdc,
            state.accounted_evm_usdc,
            unreserved_evm_assets,
            trading_capacity,
        )
        checks = {
            "amount": amount,
            "max_trading_bps": state.max_trading_bps,
            "total_managed_assets": total_managed_assets,
            "max_core_exposure": max_core_exposure,
            "current_core_exposure": current_core_exposure,
            "trading_capacity": trading_capacity,
            "protected_evm_assets": protected_assets,
            "unreserved_evm_assets": unreserved_evm_assets,
            "deposit_capacity": deposit_capacity,
        }
        if amount > deposit_capacity:
            raise ValueError(
                "Core deposit preflight failed: requested "
                f"{amount} asset units, available {deposit_capacity}; "
                f"maxTradingBps={state.max_trading_bps} permits total Core exposure "
                f"{max_core_exposure}, currently {current_core_exposure}. "
                "Reduce the amount and re-check pending/protected assets."
            )
        return checks

    def deposit_usdc_to_core(self, amount: int, *, preflight: bool = True) -> TxResult:
        self.resolve_runtime_config()
        if preflight:
            self.core_deposit_preflight(amount)
        if not self.core_deposit_wallet:
            raise ValueError("CORE_DEPOSIT_WALLET is required")
        inner = calldata(
            "deposit(uint256,uint32)",
            [("uint256", amount), ("uint32", self.spot_destination_dex)],
        )
        return self.execute(self.core_deposit_wallet, 0, inner)

    def confirm_core_deposit(self, amount: int) -> TxResult:
        inner = CONFIRM_CORE_DEPOSIT_SELECTOR + encode_uint(amount)
        return self.execute(self.agent_address, 0, inner)

    def move_usdc_class(self, amount_wei: int, to_perp: bool) -> TxResult:
        raw = self._raw_action(
            ACTION_USD_CLASS_TRANSFER,
            calldata("x(uint64,bool)", [("uint64", amount_wei), ("bool", to_perp)])[10:],
        )
        return self.execute(CORE_WRITER, 0, self._send_raw_action_calldata(raw))

    def request_core_withdrawal(self, amount_wei: int) -> TxResult:
        self.resolve_runtime_config()
        destination = self._core_system_address(self.usdc_token_index)
        raw = self._raw_action(
            ACTION_SPOT_SEND,
            calldata(
                "x(address,uint64,uint64)",
                [("address", destination), ("uint64", self.usdc_token_index), ("uint64", amount_wei)],
            )[10:],
        )
        return self.execute(CORE_WRITER, 0, self._send_raw_action_calldata(raw))

    def confirm_core_withdrawal(self, amount: int) -> TxResult:
        inner = CONFIRM_CORE_WITHDRAWAL_SELECTOR + encode_uint(amount)
        return self.execute(self.agent_address, 0, inner)

    def settle_daily_nav(self, day: int, accounted_assets: int, snapshot_hash: str) -> TxResult:
        data = calldata(
            "settleDailyNav(uint64,uint256,bytes32)",
            [("uint64", day), ("uint256", accounted_assets), ("bytes32", snapshot_hash)],
        )
        return self._send_executor_tx(data)

    def authorize_approved_wallet(self, wallet: str, name: str) -> TxResult:
        raw = self._raw_action(
            ACTION_ADD_API_WALLET,
            calldata("x(address,string)", [("address", wallet), ("string", name)])[10:],
        )
        return self.execute(CORE_WRITER, 0, self._send_raw_action_calldata(raw))


    def _read_uint(self, target: str, signature: str, *args: object) -> int:
        if self.rpc is None:
            raise ValueError("RPC client is required")
        data = selector(signature)
        if args:
            # The only argumented read currently needed is ERC20 balanceOf(address).
            data = calldata(signature, [("address", args[0])])
        return decode_uint(self.rpc.eth_call(target, data))

    def _read_address(self, target: str, signature: str) -> str:
        if self.rpc is None:
            raise ValueError("RPC client is required")
        return decode_address(self.rpc.eth_call(target, selector(signature)))

    def _send_executor_tx(self, data: str) -> TxResult:
        if self.dry_run or self.rpc is None or self.signer is None or self.chain_id is None:
            return TxResult(tx_hash=None, status="dry_run", calldata=data, dry_run=True)
        raw_tx = self.signer.sign_transaction(
            self.rpc,
            self.chain_id,
            TransactionRequest(to=self.agent_address, data=data, gas_limit=self.gas_limit),
        )
        tx_hash = self.rpc.send_raw_transaction(raw_tx)
        return TxResult(tx_hash=tx_hash, calldata=data, dry_run=False)

    @staticmethod
    def _send_raw_action_calldata(raw_action: str) -> str:
        return calldata("sendRawAction(bytes)", [("bytes", raw_action)])

    @staticmethod
    def _raw_action(action_id: int, encoded_action: str) -> str:
        prefix = bytes([ENCODING_VERSION]) + action_id.to_bytes(3, "big")
        return "0x" + prefix.hex() + encoded_action

    @staticmethod
    def _core_system_address(token_index: int) -> str:
        value = (0x20 << 152) | token_index
        return "0x" + value.to_bytes(20, "big").hex()
