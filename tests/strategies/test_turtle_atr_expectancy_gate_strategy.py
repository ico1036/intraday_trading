from intraday.strategies.multi import TurtleAtrExpectancyGateStrategy


def test_turtle_atr_expectancy_gate_strategy_smoke():
    s = TurtleAtrExpectancyGateStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
