from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from executor_backend.chain.abi import keccak256
from executor_backend.chain.rpc import JsonRpcClient


@dataclass(frozen=True)
class LogEvent:
    address: str
    block_number: int
    tx_hash: str
    log_index: int
    topics: list[str]
    data: str


def event_topic(signature: str) -> str:
    return "0x" + keccak256(signature.encode()).hex()


class AgentEventIndexer:
    def __init__(self, rpc: JsonRpcClient, agent_address: str, max_block_range: int = 1000):
        self.rpc = rpc
        self.agent_address = agent_address
        self.max_block_range = max_block_range

    def get_logs(self, from_block: int, to_block: int | str = "latest", topics: list[str] | None = None) -> list[LogEvent]:
        if not isinstance(to_block, int):
            return self._get_logs_chunk(from_block, to_block, topics)

        logs: list[LogEvent] = []
        start = from_block
        while start <= to_block:
            end = min(start + self.max_block_range - 1, to_block)
            logs.extend(self._get_logs_chunk(start, end, topics))
            start = end + 1
        return logs

    def _get_logs_chunk(self, from_block: int, to_block: int | str, topics: list[str] | None = None) -> list[LogEvent]:
        params: dict[str, Any] = {
            "address": self.agent_address,
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block) if isinstance(to_block, int) else to_block,
        }
        if topics:
            params["topics"] = topics
        raw_logs = self.rpc.call("eth_getLogs", [params])
        return [self._parse_log(log) for log in raw_logs]

    @staticmethod
    def _parse_log(log: dict[str, Any]) -> LogEvent:
        return LogEvent(
            address=log["address"],
            block_number=int(log["blockNumber"], 16),
            tx_hash=log["transactionHash"],
            log_index=int(log["logIndex"], 16),
            topics=list(log.get("topics", [])),
            data=log.get("data", "0x"),
        )
