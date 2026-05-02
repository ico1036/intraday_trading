from intraday.strategies.multi import TurtleAtrRegimeSwitchHurdleStrategy


def test_turtle_atr_regime_switch_hurdle_strategy_smoke():
    s = TurtleAtrRegimeSwitchHurdleStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
