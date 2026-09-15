"""Read-only /info transport. Never import this for transaction broadcast."""
from email.utils import parsedate_to_datetime
import json
import logging
import random
import time
from urllib import request
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)


class HyperReadError(RuntimeError):
    def __init__(self, status=None, retry_after=0):
        self.status = status
        self.retry_after = retry_after
        super().__init__('[INFO_RETRY_EXHAUSTED] ' + (f'HyperCore /info HTTP {status}' if status else 'HyperCore /info transport unavailable'))


def _retry_after(value):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return 0.0


def read_json(url, payload, *, attempts=4, budget=45):
    deadline = time.monotonic() + budget
    for attempt in range(attempts):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise HyperReadError()
        req = request.Request(url, data=json.dumps(payload).encode(),
                              headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with request.urlopen(req, timeout=min(10, remaining)) as response:
                return json.loads(response.read().decode())
        except HTTPError as exc:
            error = HyperReadError(exc.code, _retry_after(exc.headers.get('Retry-After')))
            logger.warning('HyperCore /info status=%s cf_ray=%s retry_after=%s', exc.code,
                           str(exc.headers.get('CF-Ray', ''))[:100], error.retry_after)
            exc.close()
            if exc.code not in {408, 429, 500, 502, 503, 504}:
                raise error from None
        except (URLError, TimeoutError, ConnectionError):
            error = HyperReadError()
        if attempt + 1 == attempts:
            raise error from None
        delay = max(error.retry_after, random.uniform(1, min(20, 2 ** (attempt + 1))))
        if delay >= deadline - time.monotonic():
            raise error from None
        time.sleep(delay)
    raise HyperReadError()
