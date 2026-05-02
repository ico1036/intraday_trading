from intraday.strategies.multi import TurtleAtrAssertionFirstStrategy


def test_turtle_atr_assertion_first_strategy_smoke():
    s = TurtleAtrAssertionFirstStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
