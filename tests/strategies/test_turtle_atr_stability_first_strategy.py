from intraday.strategies.multi import TurtleAtrStabilityFirstStrategy


def test_turtle_atr_stability_first_strategy_smoke():
    s = TurtleAtrStabilityFirstStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
