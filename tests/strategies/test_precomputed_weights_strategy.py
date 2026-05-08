from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from intraday.strategies.multi.precomputed_weights_strategy import (
    PrecomputedWeightsStrategy,
)
from intraday.strategy import MarketState, PortfolioOrder, Side


SYMBOLS = ["BTCUSDT", "ETHUSDT"]


def _state(
    ts: datetime,
    positions: dict[str, dict] | None = None,
) -> MarketState:
    return MarketState(
        timestamp=ts,
        mid_price=0.0,
        imbalance=0.0,
        spread=0.0,
        spread_bps=0.0,
        best_bid=0.0,
        best_ask=0.0,
        best_bid_qty=0.0,
        best_ask_qty=0.0,
        panel={s: {"close": 100.0} for s in SYMBOLS},
        positions=positions,
    )


def _write_schedule(tmp_path: Path, rows: list[dict]) -> Path:
    df = pd.DataFrame(rows)
    p = tmp_path / "combined_weights.parquet"
    df.to_parquet(p)
    return p


def test_emits_long_and_short_orders_at_scheduled_timestamp(tmp_path: Path):
    ts = datetime(2026, 3, 4, 0, 0)
    path = _write_schedule(
        tmp_path,
        [
            {"timestamp": ts, "symbol": "BTCUSDT", "target_weight": 0.3},
            {"timestamp": ts, "symbol": "ETHUSDT", "target_weight": -0.2},
        ],
    )

    strat = PrecomputedWeightsStrategy(symbols=SYMBOLS, weights_path=str(path))
    order = strat.generate_order(_state(ts))

    assert isinstance(order, PortfolioOrder)
    btc = order["BTCUSDT"]
    eth = order["ETHUSDT"]
    assert btc is not None and btc.side == Side.BUY and btc.weight == pytest.approx(0.3)
    assert eth is not None and eth.side == Side.SELL and eth.weight == pytest.approx(0.2)


def test_returns_none_when_timestamp_not_in_schedule(tmp_path: Path):
    scheduled_ts = datetime(2026, 3, 4, 0, 0)
    other_ts = datetime(2026, 3, 4, 1, 0)
    path = _write_schedule(
        tmp_path,
        [{"timestamp": scheduled_ts, "symbol": "BTCUSDT", "target_weight": 0.5}],
    )
    strat = PrecomputedWeightsStrategy(symbols=SYMBOLS, weights_path=str(path))

    assert strat.generate_order(_state(other_ts)) is None


def test_zero_weight_closes_existing_position(tmp_path: Path):
    ts = datetime(2026, 3, 4, 0, 0)
    path = _write_schedule(
        tmp_path,
        [{"timestamp": ts, "symbol": "BTCUSDT", "target_weight": 0.0}],
    )
    strat = PrecomputedWeightsStrategy(symbols=SYMBOLS, weights_path=str(path))

    order = strat.generate_order(
        _state(
            ts,
            positions={"BTCUSDT": {"side": "LONG", "qty": 1.0, "entry_price": 100.0}},
        )
    )

    assert isinstance(order, PortfolioOrder)
    btc = order["BTCUSDT"]
    assert btc is not None
    assert btc.side == Side.SELL
    assert btc.quantity == 0.0
    assert btc.weight is None


def test_zero_weight_with_no_position_emits_no_order(tmp_path: Path):
    ts = datetime(2026, 3, 4, 0, 0)
    path = _write_schedule(
        tmp_path,
        [{"timestamp": ts, "symbol": "BTCUSDT", "target_weight": 0.0}],
    )
    strat = PrecomputedWeightsStrategy(symbols=SYMBOLS, weights_path=str(path))

    assert strat.generate_order(_state(ts)) is None


def test_rejects_symbol_outside_universe(tmp_path: Path):
    ts = datetime(2026, 3, 4, 0, 0)
    path = _write_schedule(
        tmp_path,
        [{"timestamp": ts, "symbol": "DOGEUSDT", "target_weight": 0.5}],
    )
    with pytest.raises(ValueError, match="outside run universe"):
        PrecomputedWeightsStrategy(symbols=SYMBOLS, weights_path=str(path))


def test_missing_columns_rejected(tmp_path: Path):
    p = tmp_path / "bad.parquet"
    pd.DataFrame({"timestamp": [datetime(2026, 3, 4)], "symbol": ["BTCUSDT"]}).to_parquet(p)
    with pytest.raises(ValueError, match="missing columns"):
        PrecomputedWeightsStrategy(symbols=SYMBOLS, weights_path=str(p))


def test_clamps_magnitude_to_one(tmp_path: Path):
    ts = datetime(2026, 3, 4, 0, 0)
    path = _write_schedule(
        tmp_path,
        [{"timestamp": ts, "symbol": "BTCUSDT", "target_weight": 1.7}],
    )
    strat = PrecomputedWeightsStrategy(symbols=SYMBOLS, weights_path=str(path))
    order = strat.generate_order(_state(ts))
    assert order["BTCUSDT"].weight == pytest.approx(1.0)
