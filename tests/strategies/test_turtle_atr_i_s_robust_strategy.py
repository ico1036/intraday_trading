from intraday.strategies.multi import TurtleAtrISRobustStrategy


def test_turtle_atr_i_s_robust_strategy_smoke():
    s = TurtleAtrISRobustStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
