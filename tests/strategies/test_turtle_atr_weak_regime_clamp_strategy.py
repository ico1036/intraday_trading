from intraday.strategies.multi import TurtleAtrWeakRegimeClampStrategy


def test_turtle_atr_weak_regime_clamp_strategy_smoke():
    s = TurtleAtrWeakRegimeClampStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
