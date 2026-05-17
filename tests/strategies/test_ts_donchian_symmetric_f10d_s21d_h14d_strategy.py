from __future__ import annotations

from intraday.strategies.multi.ts_donchian_symmetric_f10d_s21d_h14d_strategy import TsDonchianSymmetricF10dS21dH14dStrategy


def test_instantiate_and_run_smoke():
    s = TsDonchianSymmetricF10dS21dH14dStrategy(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    # No data yet — generate_order must be safe.
    class _S:
        timestamp = None
        panel = None
        positions = {}
    assert s.generate_order(_S()) is None or hasattr(s.generate_order(_S()), "orders") or s.generate_order(_S()) is None
