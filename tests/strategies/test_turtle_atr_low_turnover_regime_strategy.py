from intraday.strategies.multi import TurtleAtrLowTurnoverRegimeStrategy


def test_turtle_atr_low_turnover_regime_strategy_smoke():
    s = TurtleAtrLowTurnoverRegimeStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
