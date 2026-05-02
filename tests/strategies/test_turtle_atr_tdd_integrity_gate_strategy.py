from intraday.strategies.multi import TurtleAtrTddIntegrityGateStrategy


def test_turtle_atr_tdd_integrity_gate_strategy_smoke():
    s = TurtleAtrTddIntegrityGateStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
