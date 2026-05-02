from intraday.strategies.multi import TurtleAtrResearchLockStrategy


def test_turtle_atr_research_lock_strategy_smoke():
    s = TurtleAtrResearchLockStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
