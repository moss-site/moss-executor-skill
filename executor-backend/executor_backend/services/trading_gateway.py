from __future__ import annotations

from dataclasses import asdict
from typing import Any
from urllib import request
import json

from executor_backend.config import TradingServiceConfig
from executor_backend.models import DeleverageRequest


class TradingServiceGateway:
    """HTTP boundary to the independent Layer 3 trading service."""

    def __init__(self, config: TradingServiceConfig):
        self.config = config

    def request_deleverage(self, payload: DeleverageRequest) -> dict[str, Any]:
        body = json.dumps(asdict(payload), default=str).encode()
        url = self.config.base_url.rstrip("/") + self.config.deleverage_endpoint
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        req = request.Request(url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode())
        except Exception as exc:  # network errors should move redeem flow to liquidity_pending
            return {"status": "failed", "error": str(exc)}
