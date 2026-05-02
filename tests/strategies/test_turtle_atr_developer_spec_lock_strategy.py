from intraday.strategies.multi import TurtleAtrDeveloperSpecLockStrategy


def test_turtle_atr_developer_spec_lock_strategy_smoke():
    s = TurtleAtrDeveloperSpecLockStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
