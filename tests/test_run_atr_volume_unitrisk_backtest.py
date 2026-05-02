from pathlib import Path
import importlib.util

import pandas as pd

from intraday.strategy import Order, Side, PortfolioOrder


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_atr_volume_unitrisk_backtest",
        Path(__file__).resolve().parent.parent / "scripts" / "run_atr_volume_unitrisk_backtest.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.CandleBacktestRunner


CandleBacktestRunner = _load_runner()


class _FixedSymbolStrategy:
    """Strategy that returns one deterministic order on first call."""

    def __init__(self, order: Order):
        self.symbols = ["BTCUSDT"]
        self.order = order
        self._called = 0

    def generate_order(self, state):
        self._called += 1
        if self._called == 1:
            return PortfolioOrder({"BTCUSDT": self.order})
        return PortfolioOrder({})


def test_margin_is_isolated_per_symbol_on_open():
    runner = CandleBacktestRunner(
        strategy=_FixedSymbolStrategy(Order(side=Side.BUY, quantity=20, order_type=None)),
        initial_capital=10000.0,
        position_size_pct=1.0,
        leverage=2,
        maker_fee_rate=0.0,
        taker_fee_rate=0.0,
        maintenance_margin_rate=0.004,
    )

    ts = pd.Timestamp("2026-01-01")
    runner._execute_order("BTCUSDT", Order(side=Side.BUY, quantity=20), 100.0, ts)

    pos = runner.positions["BTCUSDT"]
    assert pos["side"] == "LONG"
    assert pos["qty"] == 20
    # 20 * 100 = 2000 notional, leverage 2 -> margin 1000
    assert pos["margin"] == 1000.0
    assert runner.capital == 9000.0


def test_long_liquidates_when_mark_below_liq_price():
    runner = CandleBacktestRunner(
        strategy=_FixedSymbolStrategy(Order(side=Side.BUY, quantity=20)),
        initial_capital=10000.0,
        position_size_pct=1.0,
        leverage=2,
        taker_fee_rate=0.0,
        maker_fee_rate=0.0,
        maintenance_margin_rate=0.004,
    )

    ts = pd.Timestamp("2026-01-01")
    runner._execute_order("BTCUSDT", Order(side=Side.BUY, quantity=20), 1000.0, ts)
    liq = runner.positions["BTCUSDT"]["liquidation_price"]

    # Force liquidation trigger
    runner._liquidate_if_needed("BTCUSDT", liq, ts)

    assert "BTCUSDT" not in runner.positions
    # Expected capital is reserved margin + liquidation PnL (entry fee is zero)
    expected_capital = 10000 + (liq - 1000.0) * 20
    assert abs(runner.capital - expected_capital) < 1e-6
    assert any(entry["action"] == "LIQUIDATE" for entry in runner.trade_log)


def test_run_marks_liquidation_before_entry_and_keeps_equity_finite():
    # create synthetic 5m data and skip disk I/O by monkeypatching loader
    candle_data = pd.DataFrame(
        {
            "timestamp": [
                pd.Timestamp("2025-01-01 00:00:00"),
                pd.Timestamp("2025-01-01 00:05:00"),
                pd.Timestamp("2025-01-01 00:10:00"),
                pd.Timestamp("2025-01-01 00:15:00"),
            ],
            "open": [1000, 1000, 1000, 1000],
            "high": [1000, 1000, 1000, 1000],
            "low": [1000, 505, 505, 505],
            "close": [1000, 505, 505, 505],
            "volume": [10, 10, 10, 10],
            "symbol": ["BTCUSDT"] * 4,
        }
    )

    strategy = _FixedSymbolStrategy(
        Order(side=Side.BUY, quantity=20),
    )
    runner = CandleBacktestRunner(
        strategy=strategy,
        initial_capital=10000.0,
        position_size_pct=0.8,
        leverage=2,
        maker_fee_rate=0.0,
        taker_fee_rate=0.0,
        maintenance_margin_rate=0.004,
    )
    runner.load_candle_data = lambda *args, **kwargs: candle_data.copy()

    result = runner.run(data_paths={"BTCUSDT": "ignore"}, start_date="2025-01-01", end_date="2025-01-01")

    assert result["final_capital"] > 0
    assert any(
        entry["action"] in {"LIQUIDATE", "CLOSE_LONG", "CLOSE_SHORT"}
        for entry in result["trade_log"]
    )
    # liquidation-guardrail should prevent runaway equity
    assert result["final_capital"] < 100000
