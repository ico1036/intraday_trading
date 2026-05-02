from intraday.strategies.multi import TurtleAtrExecutionParityGatedStrategy


def test_turtle_atr_execution_parity_gated_strategy_smoke():
    s = TurtleAtrExecutionParityGatedStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
