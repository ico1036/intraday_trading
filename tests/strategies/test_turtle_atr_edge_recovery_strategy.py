from intraday.strategies.multi import TurtleAtrEdgeRecoveryStrategy


def test_turtle_atr_edge_recovery_strategy_smoke():
    s = TurtleAtrEdgeRecoveryStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
