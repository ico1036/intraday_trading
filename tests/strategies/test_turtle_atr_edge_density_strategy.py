from intraday.strategies.multi import TurtleAtrEdgeDensityStrategy


def test_turtle_atr_edge_density_strategy_smoke():
    s = TurtleAtrEdgeDensityStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
