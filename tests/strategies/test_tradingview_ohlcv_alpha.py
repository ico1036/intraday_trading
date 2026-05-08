from __future__ import annotations

from datetime import datetime

from intraday.strategies.multi.trading_view_ohlcv_alpha import TradingViewOhlcvAlpha
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


def row(price: float) -> dict[str, float]:
    return {
        "open": price,
        "high": price * 1.001,
        "low": price * 0.999,
        "close": price,
        "volume": 100.0,
        "vwap": price,
    }


def test_ema_vwap_formula_emits_portfolio_order():
    strategy = TradingViewOhlcvAlpha(
        symbols=["BTCUSDT", "ETHUSDT"],
        formula="ema_vwap",
        fast=2,
        slow=4,
        lookback=4,
        entry_threshold=0.0001,
        rebalance_bars=1,
        max_weight=0.5,
    )

    result = None
    for idx in range(8):
        result = strategy.generate_order(
            state({
                "BTCUSDT": row(100 + idx),
                "ETHUSDT": row(100 - idx * 0.5),
            })
        )

    assert isinstance(result, PortfolioOrder)
    assert any(order is not None for order in result.active_orders.values())


def test_legacy_family_param_still_maps_to_formula():
    strategy = TradingViewOhlcvAlpha(symbols=["BTCUSDT"], family="donchian_breakout")
    assert strategy.formula == "donchian_breakout"


def test_alpha_id_is_configurable():
    strategy = TradingViewOhlcvAlpha(symbols=["BTCUSDT"], alpha_id="tv_test")
    assert strategy.alpha_id == "tv_test"
