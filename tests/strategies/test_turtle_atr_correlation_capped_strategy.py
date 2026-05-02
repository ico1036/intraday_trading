from intraday.strategies.multi import TurtleAtrCorrelationCappedStrategy


def test_turtle_atr_correlation_capped_strategy_smoke():
    s = TurtleAtrCorrelationCappedStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
