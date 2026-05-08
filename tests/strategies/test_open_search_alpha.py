from __future__ import annotations

from datetime import datetime

from intraday.strategies.multi.open_search_alpha import OpenSearchAlpha
from intraday.strategy import MarketState, PortfolioOrder


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


def row(price: float, volume: float = 100.0) -> dict[str, float]:
    return {
        "open": price,
        "high": price * 1.001,
        "low": price * 0.999,
        "close": price,
        "volume": volume,
        "vwap": price,
    }


def test_open_search_alpha_emits_portfolio_order_for_trend():
    strategy = OpenSearchAlpha(
        symbols=["BTCUSDT", "ETHUSDT"],
        idea="trend_follow",
        fast=2,
        slow=4,
        lookback=4,
        rebalance_bars=1,
        entry_threshold=0.0001,
        max_weight=0.5,
    )

    result = None
    for idx in range(8):
        result = strategy.generate_order(
            state({
                "BTCUSDT": row(100 + idx),
                "ETHUSDT": row(100 - idx),
            })
        )

    assert isinstance(result, PortfolioOrder)
    assert any(order is not None for order in result.active_orders.values())


def test_open_search_alpha_supports_short_only_mode():
    strategy = OpenSearchAlpha(
        symbols=["BTCUSDT"],
        idea="trend_follow",
        fast=2,
        slow=4,
        lookback=4,
        rebalance_bars=1,
        entry_threshold=0.0001,
        side_mode="short_only",
    )

    result = None
    for idx in range(8):
        result = strategy.generate_order(state({"BTCUSDT": row(100 - idx)}))

    assert isinstance(result, PortfolioOrder)
    assert any(order is not None for order in result.active_orders.values())


def test_open_search_alpha_supports_constant_short_before_warmup():
    strategy = OpenSearchAlpha(
        symbols=["BTCUSDT"],
        idea="constant_short",
        rebalance_bars=1,
        side_mode="short_only",
    )

    result = strategy.generate_order(state({"BTCUSDT": row(100)}))

    assert isinstance(result, PortfolioOrder)
    assert any(order is not None for order in result.active_orders.values())
