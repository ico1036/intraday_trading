from intraday.strategies.multi import TurtleAtrCertificationFirstLockStrategy


def test_turtle_atr_certification_first_lock_strategy_smoke():
    s = TurtleAtrCertificationFirstLockStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
