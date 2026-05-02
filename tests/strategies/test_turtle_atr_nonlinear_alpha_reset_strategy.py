from intraday.strategies.multi import TurtleAtrNonlinearAlphaResetStrategy


def test_turtle_atr_nonlinear_alpha_reset_strategy_smoke():
    s = TurtleAtrNonlinearAlphaResetStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
