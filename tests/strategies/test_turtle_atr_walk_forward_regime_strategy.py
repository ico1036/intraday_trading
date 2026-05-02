from intraday.strategies.multi import TurtleAtrWalkForwardRegimeStrategy


def test_turtle_atr_walk_forward_regime_strategy_smoke():
    s = TurtleAtrWalkForwardRegimeStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
