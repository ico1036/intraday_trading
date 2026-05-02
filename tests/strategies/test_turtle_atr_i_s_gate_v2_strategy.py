from intraday.strategies.multi import TurtleAtrISGateV2Strategy


def test_turtle_atr_i_s_gate_v2_strategy_smoke():
    s = TurtleAtrISGateV2Strategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
