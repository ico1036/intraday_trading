from intraday.strategies.multi import TurtleAtrStagnationBreakerStrategy


def test_turtle_atr_stagnation_breaker_strategy_smoke():
    s = TurtleAtrStagnationBreakerStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
