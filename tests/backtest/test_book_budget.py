"""The gross budget covers the whole book, and weight events are never NaN targets."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import pandas as pd
import pytest

from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner
from intraday.candle_builder import Candle, CandleType
from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class _BarLoader:
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


def _bars(prices: list[float], start: datetime, skip_first: int = 0) -> pd.DataFrame:
    ts = [start + timedelta(days=i) for i in range(skip_first, len(prices) + skip_first)]
    return pd.DataFrame({"timestamp": ts, "open": prices, "high": prices, "low": prices, "close": prices,
                         "volume": 10.0, "quote_volume": 1e6})


def _buy(weight: float) -> Order:
    return Order(side=Side.BUY, quantity=0.0, weight=weight, order_type=OrderType.MARKET)


def _close_long() -> Order:
    return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)


class _Script:
    """Batch-aware strategy that emits a scripted PortfolioOrder per day."""
    BATCH_HOOK = True

    def __init__(self, symbols, script: dict[int, dict[str, Order]], **_):
        self.symbols = symbols
        self.script = script
        self.day = 0

    def generate_order(self, state: MarketState):
        orders = self.script.get(self.day)
        self.day += 1
        return PortfolioOrder(orders=orders) if orders else None


def _runner(strategy, loaders, **kw):
    base = dict(bar_type=CandleType.TIME, bar_size=86400, initial_capital=10000.0, position_size_pct=1.0,
                maker_fee_rate=0.0, taker_fee_rate=0.0, fixed_aum_sizing=True)
    base.update(kw)
    return PortfolioTickBacktestRunner(strategy=strategy, data_loaders=loaders, **base)


START = datetime(2025, 1, 1)


def _flat_loaders(n: int = 4) -> dict:
    return {"AAA": _BarLoader(_bars([100.0] * n, START)), "BBB": _BarLoader(_bars([50.0] * n, START))}


def test_adding_a_position_over_the_budget_is_rejected_even_when_the_order_is_small():
    # day 0: long AAA 0.6 (fills day 1). day 1: order only BBB 0.6 while AAA is still held.
    strat = _Script(["AAA", "BBB"], {0: {"AAA": _buy(0.6)}, 1: {"BBB": _buy(0.6)}})
    with pytest.raises(ValueError, match="untouched positions 0.6"):
        _runner(strat, _flat_loaders()).run()


def test_re_emitting_the_whole_book_at_the_budget_passes():
    strat = _Script(["AAA", "BBB"], {0: {"AAA": _buy(0.6)}, 1: {"AAA": _buy(0.6), "BBB": _buy(0.4)}})
    r = _runner(strat, _flat_loaders())
    r.run()
    assert {t["symbol"] for t in r._trade_log if t["action"] == "OPEN_LONG"} == {"AAA", "BBB"}


def test_closing_one_leg_and_opening_another_in_one_order_passes():
    strat = _Script(["AAA", "BBB"], {0: {"AAA": _buy(0.6)}, 1: {"AAA": _close_long(), "BBB": _buy(0.6)}})
    r = _runner(strat, _flat_loaders())
    r.run()
    actions = [(t["symbol"], t["action"]) for t in r._trade_log]
    assert ("AAA", "CLOSE_LONG") in actions and ("BBB", "OPEN_LONG") in actions


def test_a_book_that_drifted_over_budget_may_be_reduced_but_not_grown():
    # AAA doubles after the fill: the held weight is 2.0 against a budget of 1.
    loaders = {"AAA": _BarLoader(_bars([100.0, 100.0, 200.0, 200.0], START)),
               "BBB": _BarLoader(_bars([50.0] * 4, START))}
    grow = _Script(["AAA", "BBB"], {0: {"AAA": _buy(1.0)}, 2: {"BBB": _buy(0.05)}})
    with pytest.raises(ValueError, match="budget 1.000000"):
        _runner(grow, loaders).run()
    reduce = _Script(["AAA", "BBB"], {0: {"AAA": _buy(1.0)}, 2: {"AAA": _buy(0.9), "BBB": _buy(0.1)}})
    r = _runner(reduce, loaders)
    r.run()
    assert any(t["symbol"] == "BBB" and t["action"] == "OPEN_LONG" for t in r._trade_log)


def test_invalid_weight_raises_on_the_decision_bar_instead_of_logging_nan():
    # a zero weight passes the budget but is not a valid order weight
    strat = _Script(["AAA", "BBB"], {0: {"AAA": _buy(0.5), "BBB": _buy(0.0)}})
    r = _runner(strat, _flat_loaders())
    with pytest.raises(ValueError, match="Invalid order weight"):
        r.run()
    # the valid leg was logged before the bad one raised; nothing NaN, nothing for BBB
    assert [e["symbol"] for e in r._weight_events] == ["AAA"]
    assert all(not math.isnan(e["target_weight"]) for e in r._weight_events)


def test_order_ahead_of_first_bar_logs_its_weight_and_fills_on_that_bar():
    loaders = {"AAA": _BarLoader(_bars([100.0] * 4, START)),
               "ZZZ": _BarLoader(_bars([10.0] * 3, START, skip_first=1))}
    strat = _Script(["AAA", "ZZZ"], {0: {"AAA": _buy(0.5), "ZZZ": _buy(0.2)}})
    r = _runner(strat, loaders)
    r.run()
    zzz = [e for e in r._weight_events if e["symbol"] == "ZZZ"]
    assert len(zzz) == 1 and zzz[0]["target_weight"] == pytest.approx(0.2) and math.isnan(zzz[0]["target_qty"])
    assert all(not math.isnan(e["target_weight"]) for e in r._weight_events)
    fills = {t["symbol"]: t["timestamp"] for t in r._trade_log if t["action"] == "OPEN_LONG"}
    assert fills == {"AAA": START + timedelta(days=1), "ZZZ": START + timedelta(days=1)}
