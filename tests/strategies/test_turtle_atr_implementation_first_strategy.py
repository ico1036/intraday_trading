from intraday.strategies.multi import TurtleAtrImplementationFirstStrategy


def test_turtle_atr_implementation_first_strategy_smoke():
    s = TurtleAtrImplementationFirstStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
