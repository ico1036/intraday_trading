from intraday.strategies.multi import TurtleAtrDualHorizonBreakStrategy


def test_turtle_atr_dual_horizon_break_strategy_smoke():
    s = TurtleAtrDualHorizonBreakStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
