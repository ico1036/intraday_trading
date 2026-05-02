from intraday.strategies.multi import TurtleAtrExecutionRegimeSwitchStrategy


def test_turtle_atr_execution_regime_switch_strategy_smoke():
    s = TurtleAtrExecutionRegimeSwitchStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
