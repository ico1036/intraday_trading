from intraday.strategies.multi import TurtleAtrCorrelationCappedRegimeStrategy


def test_turtle_atr_correlation_capped_regime_strategy_smoke():
    s = TurtleAtrCorrelationCappedRegimeStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
