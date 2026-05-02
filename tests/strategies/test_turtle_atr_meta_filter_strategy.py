from intraday.strategies.multi import TurtleAtrMetaFilterStrategy


def test_turtle_atr_meta_filter_strategy_smoke():
    s = TurtleAtrMetaFilterStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
