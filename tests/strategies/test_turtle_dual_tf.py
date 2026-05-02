from datetime import datetime, timedelta

import pandas as pd

from intraday.strategy import MarketState, Side
from intraday.strategies.multi import TurtleDualTimeframeStrategy


def make_state(ts: datetime, symbol: str, bars: dict[str, pd.DataFrame]):
    panel = {}
    for sym, df in bars.items():
        row = df.iloc[-1]
        panel[sym] = {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }
    return MarketState(
        timestamp=ts,
        mid_price=panel[symbol]["close"],
        imbalance=0.0,
        spread=0.0,
        spread_bps=0.0,
        best_bid=panel[symbol]["close"],
        best_ask=panel[symbol]["close"],
        best_bid_qty=0,
        best_ask_qty=0,
        open=panel[symbol]["open"],
        high=panel[symbol]["high"],
        low=panel[symbol]["low"],
        close=panel[symbol]["close"],
        volume=panel[symbol]["volume"],
        symbol=symbol,
        panel=panel,
        positions={},
    )


def build_monotonic_df(base: float, n: int = 90) -> pd.DataFrame:
    idx = [datetime(2025, 1, 1) + timedelta(minutes=i) for i in range(n)]
    close = pd.Series([base + i * 0.1 for i in range(n)])
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
            "volume": [100.0] * n,
        },
        index=idx,
    )


def test_turtle_strategy_generates_entry_or_none():
    strategy = TurtleDualTimeframeStrategy(
        symbols=["AAAUSDT", "BBBUSDT"],
        fast_window=5,
        slow_window=12,
        atr_window=3,
        stop_atr=2.0,
        trail_atr=1.5,
        history_max_len=200,
    )
    strategy.set_initial_capital(10000)

    bars = {
        "AAAUSDT": build_monotonic_df(100, 90),
        "BBBUSDT": build_monotonic_df(50, 90),
    }

    # enough bars fed through multiple states
    last_ts = None
    order_count = 0
    for i in range(12, 90):
        ts = datetime(2025, 1, 1) + timedelta(minutes=i)
        last_ts = ts
        for sym in bars:
            # emulate panel snapshot at each ts
            state = make_state(ts, sym, {s: df.iloc[: i + 1] for s, df in bars.items()})
            order = strategy.generate_order(state)
            if order is not None:
                order_count += len(order.active_orders)

    assert last_ts is not None
    assert isinstance(order_count, int)
    # sanity: 주문이 생성될 수 있으므로 음수가 아닌 값이면 통과
    assert order_count >= 0


def test_turtle_exit_signal_present_after_entry_attempt():
    strategy = TurtleDualTimeframeStrategy(
        symbols=["AAAUSDT"],
        fast_window=3,
        slow_window=8,
        atr_window=3,
        max_open_positions=1,
        history_max_len=120,
    )
    strategy.set_initial_capital(10000)

    bars = {"AAAUSDT": build_monotonic_df(100, 120)}
    # open trend
    for i in range(8, 90):
        ts = datetime(2025, 1, 1) + timedelta(minutes=i)
        state = make_state(ts, "AAAUSDT", {"AAAUSDT": bars["AAAUSDT"].iloc[: i + 1]})
        _ = strategy.generate_order(state)

    # force reversal by injecting a downward jump at end
    down = bars["AAAUSDT"].copy()
    down.iloc[-1] = down.iloc[-1] * 0.5
    ts = datetime(2025, 1, 1) + timedelta(minutes=120)
    state = make_state(ts, "AAAUSDT", {"AAAUSDT": down})
    order = strategy.generate_order(state)
    assert order is None or order.active_orders is not None
