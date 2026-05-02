from intraday.strategies.multi import TurtleAtrVerificationGateStrategy


def test_turtle_atr_verification_gate_strategy_smoke():
    s = TurtleAtrVerificationGateStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
