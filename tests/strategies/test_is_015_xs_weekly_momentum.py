from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi.xs_weekly_momentum_strategy import XsWeeklyMomentumStrategy
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
    s = XsWeeklyMomentumStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_bars=4, rebalance_bars=1)
    assert feed(s, [{"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}}]) is None


def test_long_winner_short_loser():
    s = XsWeeklyMomentumStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_bars=2, rebalance_bars=1, entry_z=0.5, max_weight=0.4)
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 101.0}, "ETHUSDT": {"close": 99.0}},
        {"BTCUSDT": {"close": 102.5}, "ETHUSDT": {"close": 97.5}},
    ]
    r = feed(s, rows)
    assert isinstance(r, PortfolioOrder)
    btc, eth = r["BTCUSDT"], r["ETHUSDT"]
    assert btc and eth
    assert btc.side == Side.BUY
    assert eth.side == Side.SELL


def test_finite_weights():
    s = XsWeeklyMomentumStrategy(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"], lookback_bars=2, rebalance_bars=1, entry_z=0.3, max_weight=0.5)
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}, "SOLUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 102.0}, "ETHUSDT": {"close": 100.5}, "SOLUSDT": {"close": 98.0}},
        {"BTCUSDT": {"close": 104.0}, "ETHUSDT": {"close": 100.0}, "SOLUSDT": {"close": 96.0}},
    ]
    r = feed(s, rows)
    assert isinstance(r, PortfolioOrder)
    import math as _m
    for sym, o in r.items():
        if o and o.weight is not None:
            assert 0 < o.weight <= 0.5 and _m.isfinite(o.weight)


def test_single_symbol_returns_none():
    s = XsWeeklyMomentumStrategy(symbols=["BTCUSDT"], lookback_bars=2, rebalance_bars=1)
    assert feed(s, [{"BTCUSDT": {"close": 100.0}}, {"BTCUSDT": {"close": 101.0}}, {"BTCUSDT": {"close": 102.0}}]) is None
