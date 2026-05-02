from intraday.strategies.multi import TurtleAtrISRecoveryStrategy


def test_turtle_atr_i_s_recovery_strategy_smoke():
    s = TurtleAtrISRecoveryStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
