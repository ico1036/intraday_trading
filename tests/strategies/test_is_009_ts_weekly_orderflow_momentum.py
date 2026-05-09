from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi.ts_weekly_orderflow_momentum_strategy import (
    TsWeeklyOrderflowMomentumStrategy,
)
from intraday.strategy import MarketState, PortfolioOrder, Side


def make_state(panel, positions=None) -> MarketState:
    return MarketState(
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        mid_price=0.0,
        imbalance=0.0,
        spread=0.0,
        spread_bps=0.0,
        best_bid=0.0,
        best_ask=0.0,
        best_bid_qty=0.0,
        best_ask_qty=0.0,
        panel=panel,
        positions=positions,
    )


def feed(strategy, rows):
    last = None
    for panel in rows:
        last = strategy.generate_order(make_state(panel))
    return last


def test_warmup_returns_none():
    strategy = TsWeeklyOrderflowMomentumStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        history_window=3,
        rebalance_bars=1,
    )
    assert (
        feed(
            strategy,
            [
                {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.5},
                 "ETHUSDT": {"volume": 10.0, "volume_imbalance": -0.5}},
            ],
        )
        is None
    )


def test_long_when_strong_buy_flow():
    strategy = TsWeeklyOrderflowMomentumStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        history_window=3,
        rebalance_bars=1,
        entry_z=1.0,
        max_weight=0.4,
    )
    # Build small history with neutral flow then a big positive flow on BTC
    rows = [
        {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.05},
         "ETHUSDT": {"volume": 10.0, "volume_imbalance": 0.0}},
        {"BTCUSDT": {"volume": 10.0, "volume_imbalance": -0.05},
         "ETHUSDT": {"volume": 10.0, "volume_imbalance": 0.0}},
        {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.0},
         "ETHUSDT": {"volume": 10.0, "volume_imbalance": 0.0}},
        {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.0},
         "ETHUSDT": {"volume": 10.0, "volume_imbalance": 0.0}},
        {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.95},
         "ETHUSDT": {"volume": 10.0, "volume_imbalance": 0.0}},
    ]
    result = feed(strategy, rows)
    assert isinstance(result, PortfolioOrder)
    btc = result["BTCUSDT"]
    assert btc is not None and btc.side == Side.BUY


def test_skips_zero_volume_bars():
    strategy = TsWeeklyOrderflowMomentumStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        history_window=3,
        rebalance_bars=1,
    )
    rows = [
        {"BTCUSDT": {"volume": 0.0, "volume_imbalance": 0.5},
         "ETHUSDT": {"volume": 0.0, "volume_imbalance": -0.5}},
        {"BTCUSDT": {"volume": 0.0, "volume_imbalance": 0.5},
         "ETHUSDT": {"volume": 0.0, "volume_imbalance": -0.5}},
    ]
    assert feed(strategy, rows) is None


def test_single_symbol_warmup_none():
    strategy = TsWeeklyOrderflowMomentumStrategy(
        symbols=["BTCUSDT"],
        lookback_bars=2,
        history_window=3,
        rebalance_bars=1,
    )
    rows = [
        {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.1}},
        {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.1}},
    ]
    assert feed(strategy, rows) is None
