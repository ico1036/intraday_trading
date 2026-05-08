from __future__ import annotations

from datetime import datetime

from intraday.strategies.multi.physics_oscillator_reversion import PhysicsOscillatorReversion
from intraday.strategy import MarketState, PortfolioOrder, Side


def state(panel: dict[str, dict[str, float]]) -> MarketState:
    return MarketState(
        timestamp=datetime(2026, 1, 1),
        mid_price=0.0,
        imbalance=0.0,
        spread=0.0,
        spread_bps=0.0,
        best_bid=0.0,
        best_ask=0.0,
        best_bid_qty=0.0,
        best_ask_qty=0.0,
        panel=panel,
    )


def row(price: float) -> dict[str, float]:
    return {
        "open": price,
        "high": price * 1.001,
        "low": price * 0.999,
        "close": price,
        "volume": 100.0,
        "vwap": price,
    }


def test_physics_reversion_longs_low_oscillator_and_shorts_high_oscillator():
    strategy = PhysicsOscillatorReversion(
        symbols=["BTCUSDT", "ETHUSDT"],
        equilibrium_window=8,
        stiffness_window=8,
        vol_window=8,
        rebalance_bars=1,
        entry_threshold=0.05,
        max_weight=0.4,
        top_k=1,
    )

    result = None
    for idx in range(30):
        btc = 100.0 + 0.05 * idx
        eth = 100.0 - 0.05 * idx
        if idx >= 20:
            btc -= (idx - 19) * 1.8
            eth += (idx - 19) * 1.8
        result = strategy.generate_order(state({"BTCUSDT": row(btc), "ETHUSDT": row(eth)}))

    assert isinstance(result, PortfolioOrder)
    orders = result.active_orders
    assert orders["BTCUSDT"] is not None
    assert orders["BTCUSDT"].side == Side.BUY
    assert orders["ETHUSDT"] is not None
    assert orders["ETHUSDT"].side == Side.SELL


def test_physics_reversion_supports_single_symbol():
    strategy = PhysicsOscillatorReversion(
        symbols=["BTCUSDT"],
        equilibrium_window=8,
        stiffness_window=8,
        vol_window=8,
        rebalance_bars=1,
        entry_threshold=0.05,
    )

    result = None
    for idx in range(30):
        price = 100.0 + 0.1 * idx
        if idx >= 20:
            price -= (idx - 19) * 1.5
        result = strategy.generate_order(state({"BTCUSDT": row(price)}))

    assert isinstance(result, PortfolioOrder)
    assert any(order is not None for order in result.active_orders.values())
