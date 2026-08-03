from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib import request
import json


class RpcError(RuntimeError):
    pass


def _quantity(value: int) -> str:
    return hex(value)


@dataclass(frozen=True)
class JsonRpcClient:
    url: str

    def call(self, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        req = request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=30) as response:
            body = json.loads(response.read().decode())
        if "error" in body:
            raise RpcError(str(body["error"]))
        return body.get("result")

    def eth_call(self, to: str, data: str, block: str = "latest") -> str:
        return self.call("eth_call", [{"to": to, "data": data}, block])

    def send_raw_transaction(self, raw_tx: str) -> str:
        return self.call("eth_sendRawTransaction", [raw_tx])

    def get_transaction_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        return self.call("eth_getTransactionReceipt", [tx_hash])

    def get_transaction_count(self, address: str, block: str = "pending") -> int:
        return int(self.call("eth_getTransactionCount", [address, block]), 16)

    def gas_price(self) -> int:
        return int(self.call("eth_gasPrice", []), 16)

    def estimate_gas(self, tx: dict[str, Any]) -> int:
        rpc_tx = {k: (_quantity(v) if isinstance(v, int) else v) for k, v in tx.items()}
        return int(self.call("eth_estimateGas", [rpc_tx]), 16)
