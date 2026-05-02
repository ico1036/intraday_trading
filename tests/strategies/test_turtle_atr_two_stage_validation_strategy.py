from intraday.strategies.multi import TurtleAtrTwoStageValidationStrategy


def test_turtle_atr_two_stage_validation_strategy_smoke():
    s = TurtleAtrTwoStageValidationStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
