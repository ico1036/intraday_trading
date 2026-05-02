from intraday.strategies.multi import TurtleAtrSingleGateRecoveryStrategy


def test_turtle_atr_single_gate_recovery_strategy_smoke():
    s = TurtleAtrSingleGateRecoveryStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
