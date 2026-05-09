from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi.ts_donchian_weekly_strategy import TsDonchianWeeklyStrategy
from intraday.strategy import MarketState, PortfolioOrder, Side


def make_state(panel, positions=None):
    return MarketState(
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        mid_price=0.0, imbalance=0.0, spread=0.0, spread_bps=0.0,
        best_bid=0.0, best_ask=0.0, best_bid_qty=0.0, best_ask_qty=0.0,
        panel=panel, positions=positions,
    )


def feed(s, rows):
    last = None
    for r in rows: last = s.generate_order(make_state(r))
    return last


def test_warmup_returns_none():
    s = TsDonchianWeeklyStrategy(symbols=["BTCUSDT", "ETHUSDT"], channel_bars=4, rebalance_bars=1, hold_bars=10)
    rows = [{"BTCUSDT": {"high": 100, "low": 99, "close": 100}, "ETHUSDT": {"high": 100, "low": 99, "close": 100}}]
    assert feed(s, rows) is None


def test_long_breakout():
    s = TsDonchianWeeklyStrategy(symbols=["BTCUSDT", "ETHUSDT"], channel_bars=3, rebalance_bars=1, hold_bars=10, max_weight=0.4)
    rows = [
        {"BTCUSDT": {"high": 100, "low": 99, "close": 100}, "ETHUSDT": {"high": 100, "low": 99, "close": 100}},
        {"BTCUSDT": {"high": 101, "low": 100, "close": 100}, "ETHUSDT": {"high": 101, "low": 100, "close": 100}},
        {"BTCUSDT": {"high": 102, "low": 101, "close": 102}, "ETHUSDT": {"high": 102, "low": 101, "close": 102}},
    ]
    r = feed(s, rows)
    # BTC and ETH both made new highs → both LONG
    assert isinstance(r, PortfolioOrder)
    btc = r["BTCUSDT"]; assert btc and btc.side == Side.BUY


def test_finite_weights():
    s = TsDonchianWeeklyStrategy(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"], channel_bars=2, rebalance_bars=1, hold_bars=10, max_weight=0.3)
    rows = [
        {"BTCUSDT": {"high": 100, "low": 99, "close": 100}, "ETHUSDT": {"high": 100, "low": 99, "close": 100}, "SOLUSDT": {"high": 100, "low": 99, "close": 100}},
        {"BTCUSDT": {"high": 101, "low": 99, "close": 101}, "ETHUSDT": {"high": 100, "low": 98, "close": 98}, "SOLUSDT": {"high": 102, "low": 99, "close": 102}},
    ]
    r = feed(s, rows)
    if r is not None:
        import math as _m
        for sym, o in r.items():
            if o and o.weight is not None:
                assert 0 < o.weight <= 0.3 and _m.isfinite(o.weight)


def test_single_symbol_warmup():
    s = TsDonchianWeeklyStrategy(symbols=["BTCUSDT"], channel_bars=4, rebalance_bars=1, hold_bars=10)
    rows = [{"BTCUSDT": {"high": 100, "low": 99, "close": 100}}]
    assert feed(s, rows) is None
