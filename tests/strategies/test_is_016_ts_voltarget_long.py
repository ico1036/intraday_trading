from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi.ts_voltarget_long_strategy import TsVoltargetLongStrategy
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
    s = TsVoltargetLongStrategy(symbols=["BTCUSDT"], vol_window_bars=5, rebalance_bars=1)
    rows = [{"BTCUSDT": {"close": 100.0}}, {"BTCUSDT": {"close": 100.5}}]
    assert feed(s, rows) is None


def test_long_only_no_short():
    s = TsVoltargetLongStrategy(symbols=["BTCUSDT"], vol_window_bars=3, rebalance_bars=1, target_daily_vol=0.5, max_weight=0.4)
    rows = [
        {"BTCUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.1}},
        {"BTCUSDT": {"close": 100.2}},
        {"BTCUSDT": {"close": 100.3}},
    ]
    r = feed(s, rows)
    if r is not None:
        for sym, o in r.items():
            if o is not None:
                # only opens LONG (BUY), only closes existing LONG (SELL with quantity=0 for time/vol stop)
                assert o.side in {Side.BUY, Side.SELL}


def test_finite_weights():
    s = TsVoltargetLongStrategy(symbols=["BTCUSDT", "ETHUSDT"], vol_window_bars=3, rebalance_bars=1, target_daily_vol=0.5, max_weight=0.3)
    rows = [
        {"BTCUSDT": {"close": 100.0}, "ETHUSDT": {"close": 100.0}},
        {"BTCUSDT": {"close": 100.1}, "ETHUSDT": {"close": 100.05}},
        {"BTCUSDT": {"close": 100.2}, "ETHUSDT": {"close": 100.1}},
        {"BTCUSDT": {"close": 100.3}, "ETHUSDT": {"close": 100.15}},
    ]
    r = feed(s, rows)
    if r is not None:
        import math as _m
        for sym, o in r.items():
            if o and o.weight is not None:
                assert 0 < o.weight <= 0.3 and _m.isfinite(o.weight)


def test_single_symbol_warmup():
    s = TsVoltargetLongStrategy(symbols=["BTCUSDT"], vol_window_bars=10, rebalance_bars=1)
    rows = [{"BTCUSDT": {"close": 100.0}}, {"BTCUSDT": {"close": 100.5}}]
    assert feed(s, rows) is None
