from intraday.strategies.multi import TurtleAtrParityCertifiedStrategy


def test_turtle_atr_parity_certified_strategy_smoke():
    s = TurtleAtrParityCertifiedStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
