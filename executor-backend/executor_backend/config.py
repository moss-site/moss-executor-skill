from __future__ import annotations

from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class NetworkConfig:
    name: str
    chain_id: int
    evm_rpc_url: str
    hypercore_api_url: str
    core_writer: str = "0x3333333333333333333333333333333333333333"


@dataclass(frozen=True)
class AgentConfig:
    agent_address: str
    executor_address: str
    accept_token: str
    core_deposit_wallet: str
    usdc_token_index: int | None
    spot_destination_dex: int | None
    core_usdc_wei_per_asset_unit: int | None


@dataclass(frozen=True)
class SignerConfig:
    mode: str
    executor_private_key: str | None = field(repr=False)
    gas_limit: int | None


@dataclass(frozen=True)
class TradingServiceConfig:
    base_url: str
    api_key: str | None = field(repr=False)
    deleverage_endpoint: str = "/deleverage"
    timeout_seconds: int = 3600


@dataclass(frozen=True)
class AppConfig:
    network: NetworkConfig
    agent: AgentConfig
    signer: SignerConfig
    trading_service: TradingServiceConfig
    database_url: str
    auto_nav: bool
    auto_reconcile: bool
    auto_core_withdraw: bool
    max_nav_change_bps: int
    redeem_liquidity_buffer_bps: int
    nav_perp_dexes: tuple[str, ...]


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _optional_int(name: str) -> int | None:
    value = os.getenv(name)
    return None if value in {None, ""} else int(value)


def _nav_perp_dexes() -> tuple[str, ...]:
    values = tuple(
        value.strip()
        for value in os.getenv("NAV_PERP_DEXS", "main,xyz").split(",")
        if value.strip()
    )
    if not values or "main" not in values:
        raise ValueError("NAV_PERP_DEXS must include main")
    if len(values) != len(set(values)):
        raise ValueError("NAV_PERP_DEXS cannot contain duplicate dex names")
    return values


def load_config() -> AppConfig:
    network_name = os.getenv("NETWORK", "testnet")
    if network_name == "testnet":
        default_chain_id = 998
        default_evm_rpc = "https://rpc.hyperliquid-testnet.xyz/evm"
        default_hyper_api = "https://api.hyperliquid-testnet.xyz"
    elif network_name == "sepolia":
        default_chain_id = 11155111
        default_evm_rpc = "https://ethereum-sepolia-rpc.publicnode.com"
        default_hyper_api = ""
    elif network_name == "mainnet":
        default_chain_id = 999
        default_evm_rpc = "https://rpc.hyperliquid.xyz/evm"
        default_hyper_api = "https://api.hyperliquid.xyz"
    else:
        raise ValueError(
            f"unsupported NETWORK={network_name!r}; expected testnet, mainnet, or sepolia"
        )
    private_key = os.getenv("EXECUTOR_PRIVATE_KEY") or None
    signer_mode = os.getenv("SIGNER_MODE", "private_key" if private_key else "dry_run")
    if signer_mode not in {"dry_run", "private_key"}:
        raise ValueError(
            f"unsupported SIGNER_MODE={signer_mode!r}; expected dry_run or private_key"
        )
    return AppConfig(
        network=NetworkConfig(
            name=network_name,
            chain_id=int(os.getenv("CHAIN_ID", str(default_chain_id))),
            evm_rpc_url=os.getenv("EVM_RPC_URL", default_evm_rpc),
            hypercore_api_url=os.getenv("HYPERCORE_API_URL", default_hyper_api),
        ),
        agent=AgentConfig(
            agent_address=os.getenv("AGENT_ADDRESS", ""),
            executor_address=os.getenv("EXECUTOR_ADDRESS", ""),
            accept_token=os.getenv("ACCEPT_TOKEN", ""),
            core_deposit_wallet=os.getenv("CORE_DEPOSIT_WALLET", ""),
            usdc_token_index=_optional_int("USDC_TOKEN_INDEX"),
            spot_destination_dex=_optional_int("USDC_SPOT_DESTINATION_DEX"),
            core_usdc_wei_per_asset_unit=_optional_int("CORE_USDC_WEI_PER_ASSET_UNIT"),
        ),
        signer=SignerConfig(
            mode=signer_mode,
            executor_private_key=private_key,
            gas_limit=_optional_int("EXECUTOR_GAS_LIMIT"),
        ),
        trading_service=TradingServiceConfig(
            base_url=os.getenv("TRADING_SERVICE_URL", "http://localhost:9000"),
            api_key=os.getenv("TRADING_SERVICE_API_KEY"),
            deleverage_endpoint=os.getenv("TRADING_SERVICE_DELEVERAGE_ENDPOINT", "/deleverage"),
            timeout_seconds=int(os.getenv("DELEVERAGE_REQUEST_TIMEOUT_SECONDS", "3600")),
        ),
        database_url=os.getenv("DATABASE_URL", f"sqlite:///executor-{network_name}.db"),
        auto_nav=_bool("ENABLE_AUTO_NAV", False),
        auto_reconcile=_bool("ENABLE_AUTO_RECONCILE", True),
        auto_core_withdraw=_bool("ENABLE_AUTO_CORE_WITHDRAW", False),
        max_nav_change_bps=int(os.getenv("MAX_NAV_CHANGE_BPS", "2000")),
        redeem_liquidity_buffer_bps=int(os.getenv("REDEEM_LIQUIDITY_BUFFER_BPS", "100")),
        nav_perp_dexes=_nav_perp_dexes(),
    )
