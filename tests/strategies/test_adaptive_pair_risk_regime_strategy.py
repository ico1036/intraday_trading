from intraday.strategies.multi import AdaptivePairRiskRegimeStrategy


def test_adaptive_pair_risk_regime_strategy_smoke():
    s = AdaptivePairRiskRegimeStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
