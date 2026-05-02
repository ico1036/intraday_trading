from intraday.strategies.multi import TurtleAtrStageGateStrategy


def test_turtle_atr_stage_gate_strategy_smoke():
    s = TurtleAtrStageGateStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
