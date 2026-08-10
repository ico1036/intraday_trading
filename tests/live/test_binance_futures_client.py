from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlencode

from intraday.live.binance_futures import BinanceFuturesClient


class _Response:
    ok = True
    status_code = 200
    text = ""

    def json(self):
        return []


class _Session:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def request(self, method, url, params, timeout):
        self.calls.append((method, url, params, timeout))
        return _Response()


def test_signed_request_uses_hmac_and_api_key(monkeypatch):
    session = _Session()
    monkeypatch.setattr("intraday.live.binance_futures.time.time", lambda: 1234.5)
    client = BinanceFuturesClient(
        "key", "secret", base_url="https://example.test", session=session
    )

    client.balances()

    method, url, params, timeout = session.calls[0]
    assert method == "GET"
    assert url == "https://example.test/fapi/v3/balance"
    assert session.headers["X-MBX-APIKEY"] == "key"
    unsigned = {"recvWindow": 5000, "timestamp": 1234500}
    expected = hmac.new(
        b"secret", urlencode(unsigned).encode(), hashlib.sha256
    ).hexdigest()
    assert params["signature"] == expected
