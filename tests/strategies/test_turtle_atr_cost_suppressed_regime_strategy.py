from intraday.strategies.multi import TurtleAtrCostSuppressedRegimeStrategy


def test_turtle_atr_cost_suppressed_regime_strategy_smoke():
    s = TurtleAtrCostSuppressedRegimeStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
