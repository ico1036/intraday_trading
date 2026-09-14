"""Batched timestamp loop: fills next open for every symbol, one mark per timestamp."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner
from intraday.strategies.multi.precomputed_weights_strategy import PrecomputedWeightsStrategy
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


def _bars(n: int, start: datetime, price: float, skip_first: int = 0) -> pd.DataFrame:
    ts = [start + timedelta(days=i) for i in range(skip_first, n)]
    return pd.DataFrame({"timestamp": ts, "open": price, "high": price, "low": price, "close": price,
                         "volume": 10.0, "quote_volume": 1e6})


class _EqualWeightBatch:
    """Batch-aware: on the first complete panel, go long every symbol equally."""
    BATCH_HOOK = True

    def __init__(self, symbols, **_):
        self.symbols = symbols
        self.calls: list[MarketState] = []

    def generate_order(self, state: MarketState):
        # The panel is a live view, so snapshot what matters at call time.
        self.calls.append((state.batch, state.symbol, sorted(state.panel), state.panel["BBB"]["timestamp"] if "BBB" in state.panel else None, state.next_timestamp))
        if len(self.calls) != 1:
            return None
        w = 1.0 / len(self.symbols)
        return PortfolioOrder(orders={s: Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                                      for s in self.symbols})


def _runner(strategy, loaders, **kw):
    return PortfolioTickBacktestRunner(strategy=strategy, data_loaders=loaders, bar_type=CandleType.TIME,
                                       bar_size=86400, initial_capital=10000.0, position_size_pct=1.0,
                                       maker_fee_rate=0.0, taker_fee_rate=0.0, fixed_aum_sizing=True, **kw)


def test_every_symbol_fills_at_the_next_open_including_the_first_processed():
    start = datetime(2025, 1, 1)
    # ZZZ starts a day late so it has the fewest bars and would have been the
    # legacy loop's "first symbol" from day 2 on.
    loaders = {"AAA": _BarLoader(_bars(5, start, 100.0)), "MMM": _BarLoader(_bars(5, start, 50.0)),
               "ZZZ": _BarLoader(_bars(5, start, 10.0, skip_first=1))}
    strat = _EqualWeightBatch(["AAA", "MMM", "ZZZ"])
    r = _runner(strat, loaders)
    r.run()
    opens = {t["symbol"]: t["timestamp"] for t in r._trade_log if t["action"] == "OPEN_LONG"}
    # decision on day 1 (first complete panel) -> every symbol fills on day 2 open
    assert opens == {"AAA": start + timedelta(days=1), "MMM": start + timedelta(days=1), "ZZZ": start + timedelta(days=1)}


def test_strategy_called_once_per_timestamp_with_complete_panel_and_next_timestamp():
    start = datetime(2025, 1, 1)
    loaders = {"AAA": _BarLoader(_bars(3, start, 100.0)), "BBB": _BarLoader(_bars(3, start, 50.0))}
    strat = _EqualWeightBatch(["AAA", "BBB"])
    r = _runner(strat, loaders)
    r.run()
    assert len(strat.calls) == 3
    batch, symbol, panel_keys, bbb_ts, next_ts = strat.calls[0]
    assert batch is True and symbol is None
    assert panel_keys == ["AAA", "BBB"] and bbb_ts == start
    assert next_ts == start + timedelta(days=1)


def test_one_equity_mark_per_timestamp():
    start = datetime(2025, 1, 1)
    loaders = {s: _BarLoader(_bars(4, start, 100.0)) for s in ("AAA", "BBB", "CCC")}
    r = _runner(_EqualWeightBatch(["AAA", "BBB", "CCC"]), loaders)
    r.run()
    # 4 timestamps + the final close-out point
    assert len(r._equity_points) == 5
    assert [t for t in r._equity_timestamps[:4]] == [start + timedelta(days=i) for i in range(4)]


def test_legacy_strategy_still_uses_the_per_symbol_loop():
    class _Legacy:
        def __init__(self, symbols, **_):
            self.symbols = symbols
            self.seen_symbols: list = []

        def generate_order(self, state):
            self.seen_symbols.append(state.symbol)
            return None
    start = datetime(2025, 1, 1)
    loaders = {s: _BarLoader(_bars(2, start, 100.0)) for s in ("AAA", "BBB")}
    strat = _Legacy(["AAA", "BBB"])
    _runner(strat, loaders).run()
    assert strat.seen_symbols == ["AAA", "BBB", "AAA", "BBB"]


def test_xs_volume_rank_batch_matches_legacy_book_except_first_symbol_timing():
    from intraday.strategies.multi.xs_volume_rank_strategy import XsVolumeRankStrategy
    start = datetime(2025, 1, 1)
    frames = {}
    for i, s in enumerate(("AAA", "BBB", "CCC", "DDD")):
        df = _bars(4, start, 10.0 * (i + 1)); df["quote_volume"] = [1e6 * (i + 1)] * 4; frames[s] = _BarLoader(df)
    strat = XsVolumeRankStrategy(list(frames), reverse=True, max_weight=0.5)
    r = _runner(strat, frames)
    r.run()
    day2 = start + timedelta(days=1)
    fills = {(t["symbol"], t["action"]): t["timestamp"] for t in r._trade_log if t["action"].startswith("OPEN")}
    # reverse: long the low-volume half (AAA, BBB), short the high-volume half (CCC, DDD); all fill on day 2
    assert fills == {("AAA", "OPEN_LONG"): day2, ("BBB", "OPEN_LONG"): day2, ("CCC", "OPEN_SHORT"): day2, ("DDD", "OPEN_SHORT"): day2}


def test_precomputed_replay_fills_the_day_after_the_member_decision(tmp_path):
    """A member's weight event is stamped with its decision bar and fills at
    the next open. Replaying that event through PrecomputedWeightsStrategy
    must fill on the same day, not a day earlier (that would be look-ahead)."""
    start = datetime(2025, 1, 1)
    decision = start + timedelta(days=1)
    path = tmp_path / "w.parquet"
    pd.DataFrame({"timestamp": [decision, decision], "symbol": ["AAA", "BBB"],
                  "target_weight": [0.5, -0.5]}).to_parquet(path)
    loaders = {s: _BarLoader(_bars(4, start, 100.0)) for s in ("AAA", "BBB")}
    r = _runner(PrecomputedWeightsStrategy(["AAA", "BBB"], weights_path=str(path)), loaders)
    r.run()
    opens = {t["symbol"]: t["timestamp"] for t in r._trade_log if t["action"].startswith("OPEN")}
    assert opens == {"AAA": decision + timedelta(days=1), "BBB": decision + timedelta(days=1)}
    events = {(e["symbol"], e["timestamp"]) for e in r._weight_events}
    assert events == {("AAA", decision), ("BBB", decision)}
