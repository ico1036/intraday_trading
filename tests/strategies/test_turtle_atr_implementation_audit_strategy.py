from intraday.strategies.multi import TurtleAtrImplementationAuditStrategy


def test_turtle_atr_implementation_audit_strategy_smoke():
    s = TurtleAtrImplementationAuditStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
