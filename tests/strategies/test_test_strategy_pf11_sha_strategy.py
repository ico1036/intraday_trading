from intraday.strategies.multi import TestStrategyPf11ShaStrategy


def test_test_strategy_pf11_sha_strategy_smoke():
    s = TestStrategyPf11ShaStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
