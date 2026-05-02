from intraday.strategies.multi import TurtleAtrSingleBranchRecoveryStrategy


def test_turtle_atr_single_branch_recovery_strategy_smoke():
    s = TurtleAtrSingleBranchRecoveryStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
