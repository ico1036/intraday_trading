from intraday.strategies.multi import TurtleAtrIsGuardSelectiveParticipationStrategy


def test_turtle_atr_is_guard_selective_participation_strategy_smoke():
    s = TurtleAtrIsGuardSelectiveParticipationStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
