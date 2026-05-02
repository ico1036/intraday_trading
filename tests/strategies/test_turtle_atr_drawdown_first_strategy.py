from intraday.strategies.multi import TurtleAtrDrawdownFirstStrategy


def test_turtle_atr_drawdown_first_strategy_smoke():
    s = TurtleAtrDrawdownFirstStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
