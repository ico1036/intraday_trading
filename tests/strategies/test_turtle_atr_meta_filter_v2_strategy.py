from intraday.strategies.multi import TurtleAtrMetaFilterV2Strategy


def test_turtle_atr_meta_filter_v2_strategy_smoke():
    s = TurtleAtrMetaFilterV2Strategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
