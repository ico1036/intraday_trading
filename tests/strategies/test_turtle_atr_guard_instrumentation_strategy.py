from intraday.strategies.multi import TurtleAtrGuardInstrumentationStrategy


def test_turtle_atr_guard_instrumentation_strategy_smoke():
    s = TurtleAtrGuardInstrumentationStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
