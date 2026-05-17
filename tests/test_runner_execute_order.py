"""Direct tests of PortfolioTickBacktestRunner._execute_order.

The runner historically only supported binary entry/exit per symbol:
opening a new position when none existed, or flipping direction. It
silently no-op'd same-side weight changes — so weight-based strategies
that emit different ``per_leg`` values daily lost all daily-rebalance
information after the first entry.

These tests pin the corrected behavior:
  - weight-based BUY/SELL re-target the symbol's notional every call
  - close-marker orders (``weight=None``, ``quantity=0``) close fully
  - direction flips realize PnL on the old leg before opening the new
"""
from __future__ import annotations

from datetime import datetime

import pytest

from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner
from intraday.candle_builder import CandleType
from intraday.strategy import Order, OrderType, PortfolioOrder, Side


class _DummyLoader:
    def iter_bars(self, *args, **kwargs):
        return iter([])

    def estimate_total_rows(self, *args, **kwargs):
        return 0


class _DummyStrategy:
    symbols: list = []


def _runner(symbols=("BTCUSDT",), capital: float = 10_000.0) -> PortfolioTickBacktestRunner:
    runner = PortfolioTickBacktestRunner(
        strategy=_DummyStrategy(),
        data_loaders={s: _DummyLoader() for s in symbols},
        bar_type=CandleType.TIME,
        bar_size=60.0,
        initial_capital=capital,
        position_size_pct=1.0,
        maker_fee_rate=0.0,
        taker_fee_rate=0.0,
        leverage=1,
    )
    # _execute_order reads from _latest_prices; we need at least an entry.
    for s in symbols:
        runner._latest_prices[s] = 100.0
    return runner


def _buy(weight: float) -> Order:
    return Order(side=Side.BUY, quantity=0.0, weight=weight, order_type=OrderType.MARKET)


def _sell(weight: float) -> Order:
    return Order(side=Side.SELL, quantity=0.0, weight=weight, order_type=OrderType.MARKET)


def _close_long() -> Order:
    # Strategy's _close_order(LONG) → weight=None, qty=0, side=SELL
    return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)


def _close_short() -> Order:
    return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)


# --- baseline: existing supported cases must keep working ---------------------


def test_open_long_from_empty():
    r = _runner()
    r._execute_order("BTCUSDT", _buy(0.02), price=100.0, timestamp=datetime(2024, 1, 1))
    assert r._position.has("BTCUSDT")
    assert r._position.get_side("BTCUSDT") == "LONG"
    # qty = capital × pct × weight × lev / price = 10000 × 1 × 0.02 × 1 / 100 = 2
    assert r._position.get_qty("BTCUSDT") == pytest.approx(2.0)


def test_open_short_from_empty():
    r = _runner()
    r._execute_order("BTCUSDT", _sell(0.03), price=100.0, timestamp=datetime(2024, 1, 1))
    assert r._position.has("BTCUSDT")
    assert r._position.get_side("BTCUSDT") == "SHORT"
    assert r._position.get_qty("BTCUSDT") == pytest.approx(3.0)


def test_long_to_short_flip_closes_and_opens():
    r = _runner()
    # 1) open LONG qty=2
    r._execute_order("BTCUSDT", _buy(0.02), 100.0, datetime(2024, 1, 1))
    # 2) flip to SHORT qty=3 — same-symbol SELL while LONG
    r._execute_order("BTCUSDT", _sell(0.03), 100.0, datetime(2024, 1, 2))
    assert r._position.get_side("BTCUSDT") == "SHORT"
    assert r._position.get_qty("BTCUSDT") == pytest.approx(3.0)
    actions = [t["action"] for t in r._trade_log]
    assert actions == ["OPEN_LONG", "CLOSE_LONG", "OPEN_SHORT"]


def test_short_to_long_flip_closes_and_opens():
    r = _runner()
    r._execute_order("BTCUSDT", _sell(0.02), 100.0, datetime(2024, 1, 1))
    r._execute_order("BTCUSDT", _buy(0.03), 100.0, datetime(2024, 1, 2))
    assert r._position.get_side("BTCUSDT") == "LONG"
    assert r._position.get_qty("BTCUSDT") == pytest.approx(3.0)


# --- close marker (qty=0, weight=None) -------------------------------------


def test_close_long_marker_closes_full_position():
    r = _runner()
    r._execute_order("BTCUSDT", _buy(0.02), 100.0, datetime(2024, 1, 1))
    r._execute_order("BTCUSDT", _close_long(), 100.0, datetime(2024, 1, 2))
    assert not r._position.has("BTCUSDT")


def test_close_short_marker_closes_full_position():
    r = _runner()
    r._execute_order("BTCUSDT", _sell(0.02), 100.0, datetime(2024, 1, 1))
    r._execute_order("BTCUSDT", _close_short(), 100.0, datetime(2024, 1, 2))
    assert not r._position.has("BTCUSDT")


def test_close_marker_no_position_is_noop():
    r = _runner()
    r._execute_order("BTCUSDT", _close_long(), 100.0, datetime(2024, 1, 1))
    assert not r._position.has("BTCUSDT")
    assert r._trade_log == []


# --- NEW BEHAVIOR: same-side resize via weight (the bug) -------------------


def test_resize_long_with_larger_weight_increases_qty():
    """Initial LONG qty=2 at weight 0.02. New BUY weight 0.05 → target qty=5.
    Old behavior: silent no-op, position stays at 2 (BUG).
    Fix: position resizes to 5."""
    r = _runner()
    r._execute_order("BTCUSDT", _buy(0.02), 100.0, datetime(2024, 1, 1))
    assert r._position.get_qty("BTCUSDT") == pytest.approx(2.0)
    r._execute_order("BTCUSDT", _buy(0.05), 100.0, datetime(2024, 1, 2))
    assert r._position.get_qty("BTCUSDT") == pytest.approx(5.0)


def test_resize_long_with_smaller_weight_decreases_qty():
    r = _runner()
    r._execute_order("BTCUSDT", _buy(0.05), 100.0, datetime(2024, 1, 1))
    assert r._position.get_qty("BTCUSDT") == pytest.approx(5.0)
    r._execute_order("BTCUSDT", _buy(0.02), 100.0, datetime(2024, 1, 2))
    assert r._position.get_qty("BTCUSDT") == pytest.approx(2.0)


def test_resize_short_with_larger_weight_increases_qty():
    r = _runner()
    r._execute_order("BTCUSDT", _sell(0.02), 100.0, datetime(2024, 1, 1))
    assert r._position.get_qty("BTCUSDT") == pytest.approx(2.0)
    r._execute_order("BTCUSDT", _sell(0.05), 100.0, datetime(2024, 1, 2))
    assert r._position.get_side("BTCUSDT") == "SHORT"
    assert r._position.get_qty("BTCUSDT") == pytest.approx(5.0)


def test_resize_short_with_smaller_weight_decreases_qty():
    r = _runner()
    r._execute_order("BTCUSDT", _sell(0.05), 100.0, datetime(2024, 1, 1))
    r._execute_order("BTCUSDT", _sell(0.02), 100.0, datetime(2024, 1, 2))
    assert r._position.get_side("BTCUSDT") == "SHORT"
    assert r._position.get_qty("BTCUSDT") == pytest.approx(2.0)


def test_resize_long_at_same_weight_keeps_position():
    """Same target → no behavior change required, but must not crash and
    must leave a usable position."""
    r = _runner()
    r._execute_order("BTCUSDT", _buy(0.03), 100.0, datetime(2024, 1, 1))
    qty_before = r._position.get_qty("BTCUSDT")
    r._execute_order("BTCUSDT", _buy(0.03), 100.0, datetime(2024, 1, 2))
    assert r._position.has("BTCUSDT")
    assert r._position.get_side("BTCUSDT") == "LONG"
    # qty should equal target (whether or not we churn close/reopen)
    assert r._position.get_qty("BTCUSDT") == pytest.approx(qty_before)


# --- realized PnL accounting on resize -------------------------------------


def test_resize_long_realizes_pnl_proportional_to_price_move():
    """Open LONG qty=2 at $100. Then resize at $110 to weight=0.02.

    Under delta execution:
      - target_qty computed from pre-trade capital: 10000 × 0.02 / 110 = 1.8181
      - delta = 1.8181 - 2.0 = -0.1818  (partial close that qty)
      - PnL on closed 0.1818 @ price 110 from entry 100 = $1.818 banked
      - Remaining qty = 1.8181
    """
    r = _runner()
    r._execute_order("BTCUSDT", _buy(0.02), 100.0, datetime(2024, 1, 1))
    cap_before = r._capital
    assert r._position.get_qty("BTCUSDT") == pytest.approx(2.0)
    r._execute_order("BTCUSDT", _buy(0.02), 110.0, datetime(2024, 1, 2))
    # Partial PnL realized into capital (positive but smaller than full-close PnL)
    expected_pnl = (110.0 - 100.0) * (2.0 - 10000 * 0.02 / 110.0)
    assert r._capital == pytest.approx(cap_before + expected_pnl, rel=1e-6)
    # Position resized to target qty derived from pre-trade capital
    assert r._position.get_qty("BTCUSDT") == pytest.approx(10000 * 0.02 / 110.0)
