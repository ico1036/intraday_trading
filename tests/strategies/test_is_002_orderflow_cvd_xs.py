from __future__ import annotations

from datetime import datetime, timezone

from intraday.strategies.multi.orderflow_cvd_xs_strategy import OrderflowCvdXsStrategy
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


def feed(strategy: OrderflowCvdXsStrategy, rows: list[dict[str, dict[str, float]]]):
    last = None
    for panel in rows:
        last = strategy.generate_order(make_state(panel))
    return last


def test_warmup_returns_none():
    strategy = OrderflowCvdXsStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=4,
    )
    result = feed(
        strategy,
        [
            {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.5},
             "ETHUSDT": {"volume": 10.0, "volume_imbalance": -0.5}},
            {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.5},
             "ETHUSDT": {"volume": 10.0, "volume_imbalance": -0.5}},
        ],
    )
    assert result is None


def test_long_top_short_bottom_after_warmup():
    strategy = OrderflowCvdXsStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=3,
        entry_z=0.5,
        exit_z=0.1,
        max_weight=0.4,
    )
    rows = [
        {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.8},
         "ETHUSDT": {"volume": 10.0, "volume_imbalance": -0.8}}
    ] * 4
    result = feed(strategy, rows)

    assert isinstance(result, PortfolioOrder)
    btc = result["BTCUSDT"]
    eth = result["ETHUSDT"]
    assert btc is not None and eth is not None
    assert btc.side == Side.BUY
    assert eth.side == Side.SELL
    assert btc.weight == 0.4
    assert eth.weight == 0.4


def test_single_symbol_returns_none_no_xs_signal():
    strategy = OrderflowCvdXsStrategy(symbols=["BTCUSDT"], lookback_bars=2)
    result = feed(
        strategy,
        [
            {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.5}},
            {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.5}},
            {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.5}},
        ],
    )
    assert result is None


def test_neutral_z_closes_long_position():
    strategy = OrderflowCvdXsStrategy(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        lookback_bars=2,
        entry_z=2.0,
        exit_z=0.5,
        max_weight=0.3,
    )
    rows = [
        {"BTCUSDT": {"volume": 10.0, "volume_imbalance": 0.30},
         "ETHUSDT": {"volume": 10.0, "volume_imbalance": -0.50},
         "SOLUSDT": {"volume": 10.0, "volume_imbalance": 0.50}}
    ] * 3
    for panel in rows[:-1]:
        strategy.generate_order(make_state(panel))
    result = strategy.generate_order(
        make_state(
            rows[-1],
            positions={"BTCUSDT": {"side": "LONG", "qty": 1.0, "entry_price": 100.0}},
        )
    )

    assert isinstance(result, PortfolioOrder)
    btc = result["BTCUSDT"]
    assert btc is not None
    assert btc.side == Side.SELL
    assert btc.quantity == 0.0
    assert btc.weight is None


def test_zero_volume_skipped():
    strategy = OrderflowCvdXsStrategy(
        symbols=["BTCUSDT", "ETHUSDT"],
        lookback_bars=2,
        entry_z=0.5,
    )
    result = feed(
        strategy,
        [
            {"BTCUSDT": {"volume": 0.0, "volume_imbalance": 0.5},
             "ETHUSDT": {"volume": 0.0, "volume_imbalance": -0.5}},
            {"BTCUSDT": {"volume": 0.0, "volume_imbalance": 0.5},
             "ETHUSDT": {"volume": 0.0, "volume_imbalance": -0.5}},
            {"BTCUSDT": {"volume": 0.0, "volume_imbalance": 0.5},
             "ETHUSDT": {"volume": 0.0, "volume_imbalance": -0.5}},
        ],
    )
    assert result is None
