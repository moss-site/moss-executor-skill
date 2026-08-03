from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from executor_backend.chain.rpc import JsonRpcClient


class SigningUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class TransactionRequest:
    to: str
    data: str
    value: int = 0
    gas_limit: int | None = None


class ExecutorSigner:
    def __init__(self, address: str, private_key: str | None = None):
        self.address = address
        self.private_key = private_key

    @classmethod
    def from_private_key(cls, private_key: str) -> "ExecutorSigner":
        try:
            from eth_account import Account  # type: ignore
            from eth_utils import to_checksum_address  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise SigningUnavailable(
                "eth-account is required for EXECUTOR_PRIVATE_KEY signing; install executor-backend dependencies"
            ) from exc
        account = Account.from_key(private_key)
        return cls(address=account.address, private_key=private_key)

    def sign_transaction(self, rpc: JsonRpcClient, chain_id: int, tx: TransactionRequest) -> str:
        if not self.private_key:
            raise SigningUnavailable("EXECUTOR_PRIVATE_KEY is not configured")
        try:
            from eth_account import Account  # type: ignore
            from eth_utils import to_checksum_address  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise SigningUnavailable(
                "eth-account is required for EXECUTOR_PRIVATE_KEY signing; install executor-backend dependencies"
            ) from exc

        nonce = rpc.get_transaction_count(self.address)
        gas_price = rpc.gas_price()
        unsigned: dict[str, Any] = {
            "chainId": chain_id,
            "nonce": nonce,
            "to": to_checksum_address(tx.to),
            "value": tx.value,
            "data": tx.data,
            "gasPrice": gas_price,
        }
        if tx.gas_limit is not None:
            unsigned["gas"] = tx.gas_limit
        else:
            estimate_tx = {
                "from": self.address,
                "to": tx.to,
                "value": tx.value,
                "data": tx.data,
            }
            unsigned["gas"] = int(rpc.estimate_gas(estimate_tx) * 1.2)
        signed = Account.sign_transaction(unsigned, self.private_key)
        raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
        if raw is None:
            raise SigningUnavailable("eth-account returned no raw transaction")
        return "0x" + bytes(raw).hex()
