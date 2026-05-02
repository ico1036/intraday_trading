from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi._alpha_template import AlphaTemplateStrategy
from intraday.strategy import MarketState, PortfolioOrder, Side


def make_state(
    panel: dict[str, dict[str, float]],
    positions: dict[str, dict] | None = None,
) -> MarketState:
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


def feed(strategy: AlphaTemplateStrategy, closes: list[dict[str, float]]):
    result = None
    for row in closes:
        result = strategy.generate_order(
            make_state({symbol: {"close": close} for symbol, close in row.items()})
        )
    return result


def test_single_symbol_is_one_symbol_portfolio():
    strategy = AlphaTemplateStrategy(
        symbols=["BTCUSDT"],
        lookback_bars=2,
        rebalance_bars=1,
        entry_threshold=0.001,
        max_weight=0.5,
    )

    result = feed(
        strategy,
        [
            {"BTCUSDT": 100.0},
            {"BTCUSDT": 100.2},
            {"BTCUSDT": 100.5},
        ],
    )

    assert isinstance(result, PortfolioOrder)
    order = result["BTCUSDT"]
    assert order is not None
    assert order.side == Side.BUY
    assert order.weight == 0.5


def test_multiple_symbols_use_the_same_template_contract():
    strategy = AlphaTemplateStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        rebalance_bars=1,
        entry_threshold=0.001,
        max_weight=0.5,
    )

    result = feed(
        strategy,
        [
            {"BTCUSDT": 100.0, "ETHUSDT": 100.0},
            {"BTCUSDT": 100.2, "ETHUSDT": 99.8},
            {"BTCUSDT": 100.5, "ETHUSDT": 99.5},
        ],
    )

    assert isinstance(result, PortfolioOrder)
    btc = result["BTCUSDT"]
    eth = result["ETHUSDT"]
    assert btc is not None
    assert eth is not None
    assert btc.side == Side.BUY
    assert eth.side == Side.SELL
    assert btc.weight == 0.5
    assert eth.weight == 0.5


def test_neutral_signal_closes_existing_single_symbol_position():
    strategy = AlphaTemplateStrategy(
        symbols=["BTCUSDT"],
        lookback_bars=2,
        rebalance_bars=1,
        entry_threshold=0.01,
        exit_threshold=0.001,
        max_weight=0.5,
    )

    feed(
        strategy,
        [
            {"BTCUSDT": 100.0},
            {"BTCUSDT": 100.0},
        ],
    )
    result = strategy.generate_order(
        make_state(
            {"BTCUSDT": {"close": 100.0}},
            positions={"BTCUSDT": {"side": "LONG", "qty": 1.0, "entry_price": 100.0}},
        )
    )

    assert isinstance(result, PortfolioOrder)
    order = result["BTCUSDT"]
    assert order is not None
    assert order.side == Side.SELL
    assert order.quantity == 0.0
    assert order.weight is None
