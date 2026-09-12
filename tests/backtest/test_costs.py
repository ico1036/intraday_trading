"""Funding settlement and slippage in the portfolio bar runner."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from intraday.backtest.costs import SlippageState, half_spread_bps, slippage_bps
from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner
from intraday.candle_builder import Candle, CandleType
from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


def test_half_spread_tiers():
    assert half_spread_bps(None) == 6.0
    assert half_spread_bps(6e7) == 0.5
    assert half_spread_bps(2e7) == 1.5
    assert half_spread_bps(6e6) == 3.0
    assert half_spread_bps(2e6) == 6.0
    assert half_spread_bps(5e5) == 12.0


def test_slippage_bps_unknown_adv_has_no_impact():
    st = SlippageState()
    for _ in range(5):
        st.push(1e6, 100.0)
    assert slippage_bps("adv_tier", st, 1000.0) == 6.0
    assert slippage_bps(None, st, 1000.0) == 0.0


def test_slippage_bps_adds_sqrt_impact():
    st = SlippageState()
    for _ in range(30):
        st.push(2e6, 100.0)          # ADV 2M -> 6 bps tier; flat closes -> vol 0
    assert slippage_bps("adv_tier", st, 20000.0) == pytest.approx(6.0)
    st2 = SlippageState()
    px = 100.0
    for i in range(30):
        px *= 1.02 if i % 2 else 0.98
        st2.push(2e6, px)
    vol = st2.vol()
    assert vol > 0
    expect = 6.0 + 0.5 * vol * np.sqrt(20000.0 / 2e6) * 1e4
    assert slippage_bps("adv_tier", st2, 20000.0) == pytest.approx(expect)


class _BarLoader:
    """Minimal bar loader: yields Candle objects from a dataframe."""

    def __init__(self, df: pd.DataFrame):
        self.df = df

    def to_dataframe(self, start_time=None, end_time=None):
        return self.df

    def estimate_total_rows(self, start_time=None, end_time=None):
        return len(self.df)

    def iter_bars(self, start_time=None, end_time=None):
        for r in self.df.itertuples():
            yield Candle(timestamp=r.timestamp, open=r.open, high=r.high, low=r.low,
                         close=r.close, volume=r.volume, quote_volume=r.quote_volume)


class _HoldLong:
    """Go long BTC with weight 1.0 on the first bar and hold."""

    def __init__(self, symbols, **_):
        self.symbols = symbols
        self._done = False

    def generate_order(self, state: MarketState):
        if self._done:
            return None
        self._done = True
        return PortfolioOrder(orders={
            "BTCUSDT": Order(side=Side.BUY, quantity=0.0, weight=1.0, order_type=OrderType.MARKET)
        })


def _bars(n: int, start: datetime, price: float = 100.0) -> pd.DataFrame:
    ts = [start + timedelta(days=i) for i in range(n)]
    return pd.DataFrame({
        "timestamp": ts, "open": price, "high": price, "low": price, "close": price,
        "volume": 10.0, "quote_volume": 1e6,
    })


def _run(funding=None, slippage=None):
    start = datetime(2025, 1, 1)
    loaders = {"BTCUSDT": _BarLoader(_bars(5, start))}
    runner = PortfolioTickBacktestRunner(
        strategy=_HoldLong(["BTCUSDT"]),
        data_loaders=loaders,
        bar_type=CandleType.TIME,
        bar_size=86400,
        initial_capital=10000.0,
        position_size_pct=1.0,
        maker_fee_rate=0.0,
        taker_fee_rate=0.0,
        fixed_aum_sizing=True,
        funding_rates=funding,
        slippage_model=slippage,
    )
    runner.run()
    return runner


def test_funding_charges_long_the_days_settlements():
    # Three 8h settlements a day at +1bp each from day 2 on; long pays.
    ts = []
    for d in range(1, 5):
        for h in (0, 8, 16):
            ts.append(datetime(2025, 1, 1) + timedelta(days=d, hours=h))
    ts_ns = np.array([pd.Timestamp(t).value for t in ts], dtype=np.int64)
    rates = np.full(len(ts), 1e-4)
    r = _run(funding={"BTCUSDT": (ts_ns, rates)})
    # Order placed at bar 1, filled at bar 2 open (day index 1). Position held
    # over days 1..4 -> 4 days x 3 settlements x 1bp on 10,000 notional = 12 USD.
    assert r._funding_total == pytest.approx(-12.0, rel=1e-6)
    log = pd.DataFrame(r._funding_log)
    assert log["settlements"].tolist() == [3, 3, 3, 3]
    assert (log["side"] == "LONG").all()
    # No funding -> capital unchanged (flat price, zero fees).
    assert _run()._capital == pytest.approx(10000.0)
    assert r._capital == pytest.approx(10000.0 - 12.0)


def test_funding_short_receives_positive_rate():
    class _HoldShort(_HoldLong):
        def generate_order(self, state):
            if self._done:
                return None
            self._done = True
            return PortfolioOrder(orders={
                "BTCUSDT": Order(side=Side.SELL, quantity=0.0, weight=1.0, order_type=OrderType.MARKET)
            })
    start = datetime(2025, 1, 1)
    ts_ns = np.array([pd.Timestamp(start + timedelta(days=2, hours=8)).value], dtype=np.int64)
    runner = PortfolioTickBacktestRunner(
        strategy=_HoldShort(["BTCUSDT"]), data_loaders={"BTCUSDT": _BarLoader(_bars(5, start))},
        bar_type=CandleType.TIME, bar_size=86400, initial_capital=10000.0,
        position_size_pct=1.0, maker_fee_rate=0.0, taker_fee_rate=0.0, fixed_aum_sizing=True,
        funding_rates={"BTCUSDT": (ts_ns, np.array([5e-4]))},
    )
    runner.run()
    assert runner._funding_total == pytest.approx(10000.0 * 5e-4)


def test_slippage_moves_fill_against_the_trade():
    r = _run(slippage="adv_tier")
    trades = pd.DataFrame(r._trade_log)
    opened = trades[trades["action"] == "OPEN_LONG"].iloc[0]
    # Fewer than 10 bars known -> 6 bps half-spread, no impact. Buy fills above.
    assert opened["price"] == pytest.approx(100.0 * (1 + 6 / 1e4))
    assert opened["slippage"] == pytest.approx(100.0 * 6 / 1e4 * opened["quantity"])
    final = trades[trades["action"] == "CLOSE_FINAL"].iloc[0]
    assert final["price"] == pytest.approx(100.0 * (1 - 6 / 1e4))
    assert r._slippage_total == pytest.approx(opened["slippage"] + final["slippage"])
    # Without a model the trade log keeps the legacy schema.
    assert "slippage" not in pd.DataFrame(_run()._trade_log).columns


def test_save_report_writes_costs(tmp_path):
    r = _run(slippage="adv_tier")
    r.save_report(tmp_path)
    import json
    m = json.loads((tmp_path / "metrics.json").read_text())
    assert m["costs"]["slippage_model"] == "adv_tier"
    assert m["costs"]["funding_applied"] is False
    assert m["costs"]["slippage"] == pytest.approx(r._slippage_total)
    assert (tmp_path / "funding.parquet").exists()
