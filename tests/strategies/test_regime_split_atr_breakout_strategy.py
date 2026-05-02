from intraday.strategies.multi import RegimeSplitAtrBreakoutStrategy


def test_regime_split_atr_breakout_strategy_smoke():
    s = RegimeSplitAtrBreakoutStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
