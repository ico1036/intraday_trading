from intraday.strategies.multi import TurtleAtrFailClosedVerifiedStrategy


def test_turtle_atr_fail_closed_verified_strategy_smoke():
    s = TurtleAtrFailClosedVerifiedStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
