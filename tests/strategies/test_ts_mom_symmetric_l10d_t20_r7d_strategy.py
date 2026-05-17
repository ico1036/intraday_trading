from __future__ import annotations

from intraday.strategies.multi.ts_mom_symmetric_l10d_t20_r7d_strategy import TsMomSymmetricL10dT20R7dStrategy


def test_instantiate_and_run_smoke():
    s = TsMomSymmetricL10dT20R7dStrategy(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    # No data yet — generate_order must be safe.
    class _S:
        timestamp = None
        panel = None
        positions = {}
    assert s.generate_order(_S()) is None or hasattr(s.generate_order(_S()), "orders") or s.generate_order(_S()) is None
