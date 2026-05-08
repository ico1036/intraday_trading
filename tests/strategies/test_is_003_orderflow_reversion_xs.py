from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi.orderflow_reversion_xs_strategy import (
    OrderflowReversionXsStrategy,
)
from intraday.strategy import MarketState, PortfolioOrder, Side


def make_state(panel, positions=None):
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


def test_sign_is_reversed_high_z_goes_short():
    strategy = OrderflowReversionXsStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=3,
        rebalance_bars=1,
        entry_z=0.5,
        exit_z=0.1,
        max_weight=0.4,
    )
    rows = [
        {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.8},
         "ETHUSDT": {"volume": 10.0, "volume_imbalance": -0.8}}
    ] * 4
    last = None
    for r in rows:
        last = strategy.generate_order(make_state(r))

    assert isinstance(last, PortfolioOrder)
    btc = last["BTCUSDT"]
    eth = last["ETHUSDT"]
    assert btc.side == Side.SELL  # positive CVD → short under reversion
    assert eth.side == Side.BUY   # negative CVD → long under reversion


def test_rebalance_bars_skips_intermediate_signals():
    strategy = OrderflowReversionXsStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        rebalance_bars=3,
        entry_z=0.5,
        max_weight=0.4,
    )
    rows = [
        {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.8},
         "ETHUSDT": {"volume": 10.0, "volume_imbalance": -0.8}}
    ] * 2
    for r in rows:
        result = strategy.generate_order(make_state(r))
    assert result is None


def test_warmup_returns_none():
    strategy = OrderflowReversionXsStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=4,
        rebalance_bars=1,
    )
    result = strategy.generate_order(
        make_state(
            {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.5},
             "ETHUSDT": {"volume": 10.0, "volume_imbalance": -0.5}}
        )
    )
    assert result is None
