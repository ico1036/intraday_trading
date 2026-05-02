from intraday.strategies.multi import AdaptiveTurtleAtrUnitPortfolioStrategyV2


def test_adaptive_turtle_atr_unit_portfolio_strategy_v2_smoke():
    s = AdaptiveTurtleAtrUnitPortfolioStrategyV2(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
