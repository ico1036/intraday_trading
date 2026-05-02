"""Tests for VPINTop5RebalanceStrategy."""

from __future__ import annotations

from datetime import datetime, timedelta

from intraday.strategy import MarketState, Side, PortfolioOrder
from intraday.strategies.tick.vpin_top5_rebalance import VPINTop5RebalanceStrategy


def make_state(timestamp: datetime, panel: dict | None = None, positions: dict | None = None):
    return MarketState(
        timestamp=timestamp,
        mid_price=50000.0,
        imbalance=0.0,
        spread=0.0,
        spread_bps=0.0,
        best_bid=50000.0,
        best_ask=50000.0,
        best_bid_qty=10,
        best_ask_qty=10,
        position_side=None,
        position_qty=0.0,
        open=50000.0,
        high=50000.0,
        low=49900.0,
        close=50000.0,
        volume=1200,
        vwap=50000.0,
        symbol="BTCUSDT",
        panel=panel,
        positions=positions,
    )


def test_none_without_panel():
    s = VPINTop5RebalanceStrategy()
    state = make_state(datetime(2026, 2, 15, 0, 0), panel=None)

    assert s.generate_order(state) is None


def test_rebalance_selects_top_vpin_symbols():
    s = VPINTop5RebalanceStrategy(top_n=3, rebalance_minutes=60, vpin_lookback=2)

    base_time = datetime(2026, 2, 15, 0, 0)

    # 두 바에 걸쳐 히스토리 구축
    panel1 = {
        "BTCUSDT": {"volume_imbalance": 0.2},
        "ETHUSDT": {"volume_imbalance": 0.6},
        "SOLUSDT": {"volume_imbalance": 0.9},
        "BNBUSDT": {"volume_imbalance": 0.5},
        "DOGEUSDT": {"volume_imbalance": 0.1},
        "ADAUSDT": {"volume_imbalance": 0.4},
    }
    panel2 = {
        "BTCUSDT": {"volume_imbalance": 0.4},
        "ETHUSDT": {"volume_imbalance": 0.8},
        "SOLUSDT": {"volume_imbalance": 0.6},
        "BNBUSDT": {"volume_imbalance": 0.7},
        "DOGEUSDT": {"volume_imbalance": 0.2},
        "ADAUSDT": {"volume_imbalance": 0.5},
    }

    s.generate_order(make_state(base_time, panel=panel1))
    result = s.generate_order(make_state(base_time + timedelta(minutes=1), panel=panel2))

    # 첫 리밸런싱 후 top-3 선택: SOL(0.75), ETH(0.7), BNB(0.6)
    assert result is not None
    assert isinstance(result, PortfolioOrder)
    orders = result.active_orders
    assert set(orders.keys()) == {"SOLUSDT", "ETHUSDT", "BNBUSDT"}

    for o in orders.values():
        assert o is not None
        assert o.side == Side.BUY

    # equal-weight
    assert abs(orders["SOLUSDT"].weight - (1.0 / 3)) < 1e-9
    assert abs(orders["ETHUSDT"].weight - (1.0 / 3)) < 1e-9
    assert abs(orders["BNBUSDT"].weight - (1.0 / 3)) < 1e-9


def test_rebalance_interval_enforced():
    s = VPINTop5RebalanceStrategy(top_n=2, rebalance_minutes=60, vpin_lookback=1)
    t0 = datetime(2026, 2, 15, 0, 0)

    panel_a = {
        "BTCUSDT": {"volume_imbalance": 0.9},
        "ETHUSDT": {"volume_imbalance": 0.8},
    }
    panel_b = {
        "BTCUSDT": {"volume_imbalance": 0.9},
        "ETHUSDT": {"volume_imbalance": 0.8},
    }

    s.generate_order(make_state(t0, panel=panel_a))
    first = s.generate_order(make_state(t0 + timedelta(minutes=30), panel=panel_b))
    assert first is None


def test_close_non_selected_positions_on_rebalance_change():
    s = VPINTop5RebalanceStrategy(top_n=1, rebalance_minutes=60, vpin_lookback=1)

    t0 = datetime(2026, 2, 15, 0, 0)

    # 1시간 뒤 첫 리밸런스: ETH top1
    state1 = make_state(t0, panel={
        "BTCUSDT": {"volume_imbalance": 0.1},
        "ETHUSDT": {"volume_imbalance": 0.9},
    })
    s.generate_order(state1)
    result1 = s.generate_order(make_state(t0 + timedelta(minutes=1), panel={
        "BTCUSDT": {"volume_imbalance": 0.2},
        "ETHUSDT": {"volume_imbalance": 0.95},
    }))
    assert result1 is None

    # 60분 뒤 BTC 상승해서 top1이 BTC로 바뀜
    t1 = t0 + timedelta(minutes=61)
    result2 = s.generate_order(make_state(t1, panel={
        "BTCUSDT": {"volume_imbalance": 0.99},
        "ETHUSDT": {"volume_imbalance": 0.1},
        "SOLUSDT": {"volume_imbalance": 0.2},
    }, positions={
        "ETHUSDT": {"side": "LONG", "qty": 0.01, "entry_price": 50000}
    }))

    assert result2 is not None
    assert isinstance(result2, PortfolioOrder)
    orders = result2.active_orders
    # BTC 진입 + ETH 청산
    assert "BTCUSDT" in orders
    assert "ETHUSDT" in orders
    assert orders["BTCUSDT"].side == Side.BUY
    assert orders["ETHUSDT"].side == Side.SELL
